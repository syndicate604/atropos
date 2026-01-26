"""
SecureCodeReviewEnv - HYDRA Secure Code Review Atropos Environment

This environment trains models to generate security patches by:
1. Presenting vulnerable code + task metadata
2. Generating patch candidates (unified diff format)
3. Scoring patches using the verification harness (exploit, tests, scanner)

Based on the GSM8K environment pattern with harness-based scoring.
"""

import asyncio
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from atroposlib.envs.base import (
    APIServerConfig,
    BaseEnv,
    BaseEnvConfig,
    ScoredDataGroup,
)
from atroposlib.type_definitions import Item  # noqa: F401 - used by BaseEnv

# Add harness to path for imports
HYDRA_DIR = Path(__file__).parent
sys.path.insert(0, str(HYDRA_DIR))

from harness.runner import HarnessRunner, TaskResult


# System prompt for secure code review
SYSTEM_PROMPT = """You are an expert security engineer specializing in secure code review and vulnerability remediation.

Your task is to analyze vulnerable code and produce a unified diff patch that:
1. Fixes the security vulnerability
2. Maintains all existing functionality
3. Passes regression tests
4. Produces clean static analysis results

CRITICAL OUTPUT FORMAT REQUIREMENTS:
- Output ONLY a unified diff patch, nothing else
- The patch MUST apply with `patch -p1`
- File paths MUST start with a/ and b/ prefixes: `--- a/workspace/app.py` and `+++ b/workspace/app.py`
- Include proper @@ hunk headers with line numbers
- Context lines (unchanged) must start with a single space
- Removed lines start with -
- Added lines start with +

EXAMPLE - SQL Injection Fix:
```diff
--- a/workspace/app.py
+++ b/workspace/app.py
@@ -15,7 +15,8 @@ def get_user(user_id):
     """Fetch user by ID."""
     conn = get_db()
-    # VULNERABLE: String concatenation allows SQL injection
-    sql = f"SELECT * FROM users WHERE id = '{user_id}'"
+    # FIXED: Parameterized query prevents SQL injection
+    sql = "SELECT * FROM users WHERE id = ?"
+    cursor = conn.execute(sql, (user_id,))
-    cursor = conn.execute(sql)
     return cursor.fetchone()
```

Generate ONLY the diff, no explanations before or after."""


class SCRTask(TypedDict):
    """Type for a secure code review task."""
    task_id: str
    code: str
    metadata: Dict[str, Any]
    cwe: str
    description: str


class SecureCodeReviewEnv(BaseEnv):
    """
    HYDRA Secure Code Review Environment for Atropos.

    Generates patch candidates and scores them using the verification harness.
    """

    name = "secure_code_review"

    def __init__(
        self,
        config: BaseEnvConfig,
        server_configs: List[APIServerConfig],
        slurm: bool = True,
        testing: bool = False,
    ):
        super().__init__(config, server_configs, slurm, testing)
        self.tasks: List[SCRTask] = []
        self.task_iter = 0
        self.harness: Optional[HarnessRunner] = None

        # Metrics for wandb
        self.pass_rate_buffer: List[float] = []
        self.failure_reasons: Dict[str, int] = {}

    @classmethod
    def config_init(cls) -> Tuple[BaseEnvConfig, List[APIServerConfig]]:
        """Default configuration for the environment."""
        env_config = BaseEnvConfig(
            tokenizer_name="Qwen/Qwen2.5-7B-Instruct",
            group_size=4,
            use_wandb=True,
            rollout_server_url="http://localhost:8000",
            total_steps=100,
            batch_size=4,
            steps_per_eval=25,
            max_token_length=2048,
            wandb_name="secure_code_review",
        )
        server_configs = [
            APIServerConfig(
                model_name="Qwen/Qwen2.5-7B-Instruct",
                base_url="http://localhost:9001/v1",
                api_key="x",
                num_requests_for_eval=32,
            ),
        ]
        return env_config, server_configs

    async def setup(self):
        """Load tasks from the tasks directory."""
        tasks_dir = HYDRA_DIR / "tasks"

        if not tasks_dir.exists():
            raise FileNotFoundError(f"Tasks directory not found: {tasks_dir}")

        # Initialize harness runner
        self.harness = HarnessRunner(
            tasks_dir=tasks_dir,
            image="hydra-harness:latest"
        )

        # Load all tasks
        self.tasks = []
        for task_dir in sorted(tasks_dir.iterdir()):
            if not task_dir.is_dir():
                continue

            task_json = task_dir / "task.json"
            if not task_json.exists():
                continue

            # Load task metadata
            with open(task_json) as f:
                task_meta = json.load(f)

            # Load vulnerable code from metadata or default to workspace/app.py
            vuln_file = task_meta.get("files", {}).get("vulnerable", "workspace/app.py")
            code_file = task_dir / vuln_file

            if code_file.exists():
                code = code_file.read_text()
            else:
                print(f"Warning: No code file found for task {task_dir.name}")
                continue

            task = SCRTask(
                task_id=task_meta["id"],
                code=code,
                metadata=task_meta.get("metadata", {}),
                cwe=task_meta.get("cwe", "Unknown"),
                description=task_meta.get("metadata", {}).get("description", "")
            )
            self.tasks.append(task)

        if not self.tasks:
            raise ValueError("No valid tasks found in tasks directory")

        print(f"Loaded {len(self.tasks)} tasks: {[t['task_id'] for t in self.tasks]}")
        self.task_iter = 0

    async def get_next_item(self) -> SCRTask:
        """Get the next task for training."""
        task = self.tasks[self.task_iter % len(self.tasks)]
        self.task_iter += 1
        return task

    def _build_user_prompt(self, task: SCRTask) -> str:
        """Build the user prompt for a task."""
        return f"""## Vulnerability Information
- CWE: {task['cwe']}
- Description: {task['description']}
- Language: {task['metadata'].get('language', 'python')}
- Framework: {task['metadata'].get('framework', 'unknown')}

## Vulnerable Code
```python
{task['code']}
```

## Requirements
1. Fix the security vulnerability described above
2. Maintain all existing functionality
3. The patch must pass regression tests
4. The code must be clean of security scanner findings

Generate a unified diff patch to fix this vulnerability:"""

    def _normalize_diff_headers(self, diff_text: str) -> str:
        """
        Normalize diff headers to ensure `patch -p1` compatibility.

        Converts:
        - `--- workspace/app.py` → `--- a/workspace/app.py`
        - `+++ workspace/app.py` → `+++ b/workspace/app.py`

        This fixes the most common formatting issue from small models.
        """
        lines = diff_text.split('\n')
        normalized = []

        for line in lines:
            # Fix --- header (missing a/ prefix)
            if line.startswith('--- ') and not line.startswith('--- a/'):
                # Extract path after "--- "
                path = line[4:].strip()
                # Skip timestamps if present (e.g., "--- file.py\t2024-01-01")
                if '\t' in path:
                    path = path.split('\t')[0]
                # Add a/ prefix if not present
                if not path.startswith('a/'):
                    line = f'--- a/{path}'
            # Fix +++ header (missing b/ prefix)
            elif line.startswith('+++ ') and not line.startswith('+++ b/'):
                path = line[4:].strip()
                if '\t' in path:
                    path = path.split('\t')[0]
                if not path.startswith('b/'):
                    line = f'+++ b/{path}'

            normalized.append(line)

        return '\n'.join(normalized)

    def _extract_diff_from_response(self, response: str) -> Optional[str]:
        """Extract a unified diff from the model response and normalize headers."""
        # Try to find diff in code block first (most reliable)
        diff_pattern = r'```(?:diff)?\s*\n(.*?)```'
        matches = re.findall(diff_pattern, response, re.DOTALL)

        if matches:
            diff_text = matches[0].strip()
            # Validate it looks like a diff
            if any(line.startswith(('---', '+++', 'diff ')) for line in diff_text.split('\n')[:5]):
                return self._normalize_diff_headers(diff_text)

        # Try to find raw diff without code blocks
        lines = response.split('\n')
        diff_start = None
        for i, line in enumerate(lines):
            if line.startswith(('--- ', 'diff --git')):
                diff_start = i
                break

        if diff_start is None:
            return None

        # Extract diff lines starting from diff_start
        diff_lines = []
        collecting = True

        for line in lines[diff_start:]:
            # Always include lines that look like diff content
            if line.startswith(('+', '-', '@', ' ', '\\', 'diff', '---', '+++')):
                diff_lines.append(line)
                collecting = True
            elif not line.strip():
                # Allow blank lines within the diff
                if collecting:
                    diff_lines.append(line)
            else:
                # Non-diff, non-blank line - stop collecting
                # But only if we've collected something meaningful
                if len(diff_lines) > 2:  # At least --- and +++ lines
                    break
                # Otherwise keep going in case we haven't found the real diff yet
                collecting = False

        diff_text = '\n'.join(diff_lines).strip()

        # Validate we got something that looks like a diff
        if diff_text and any(line.startswith('---') for line in diff_text.split('\n')[:5]):
            return self._normalize_diff_headers(diff_text)

        return None

    # Graded scoring by failure reason to create variance even when all patches fail
    # Higher (less negative) = closer to success
    FAILURE_SCORES = {
        # Format/application failures (worst)
        "invalid_patch_format": -1.0,
        "patch_apply_failure": -0.9,
        # Scanner still finds issues (applied but not properly fixed)
        "scanner_findings": -0.6,
        # Broke functionality (security fix worked but side effects)
        "regression_test_failure": -0.4,
        # Almost there - applied, tests pass, but exploit still works
        "patch_ineffective": -0.2,
        # Unknown failure
        "unknown": -0.8,
    }

    async def _score_single_patch(
        self,
        task_id: str,
        diff_text: Optional[str]
    ) -> Tuple[float, str, str]:
        """
        Score a single patch using the harness.

        Returns: (score, failure_reason, patch_error)

        Scoring is graded by failure reason to create variance:
        - +1.0: passed (all checks pass)
        - -0.2: patch_ineffective (almost there)
        - -0.4: regression_test_failure (fix worked but broke tests)
        - -0.6: scanner_findings (applied but incomplete fix)
        - -0.9: patch_apply_failure (couldn't apply)
        - -1.0: invalid_patch_format (no valid diff)
        """
        if diff_text is None:
            return self.FAILURE_SCORES["invalid_patch_format"], "invalid_patch_format", "Could not extract diff from response"

        # Write diff to temp file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.diff',
            delete=False
        ) as f:
            f.write(diff_text)
            temp_patch_file = Path(f.name)

        try:
            # Run harness in thread to avoid blocking
            loop = asyncio.get_running_loop()
            result: TaskResult = await loop.run_in_executor(
                None,
                lambda: self.harness.run_task(
                    task_id=task_id,
                    patch_file=temp_patch_file
                )
            )

            if result.passed:
                return 1.0, "", ""
            else:
                failure_reason = result.failure_reason or "unknown"
                score = self.FAILURE_SCORES.get(failure_reason, -0.8)
                return score, failure_reason, result.patch_error

        finally:
            # Cleanup temp file
            if temp_patch_file.exists():
                temp_patch_file.unlink()

    async def collect_trajectories(
        self, item: SCRTask
    ) -> Tuple[ScoredDataGroup, List[Item]]:
        """
        Generate patch candidates and score them.

        This is the main training loop method that:
        1. Generates multiple patch candidates using the model
        2. Scores each patch using the verification harness
        3. Returns tokens/masks/scores for GRPO training
        """
        user_message = {"role": "user", "content": self._build_user_prompt(item)}

        async with self.server.managed_server(tokenizer=self.tokenizer) as managed:
            chat_completions = await managed.chat_completion(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    user_message
                ],
                n=self.config.group_size,
                max_tokens=self.config.max_token_length,
                temperature=1.0,
            )

            state = managed.get_state()
            nodes = state["nodes"]

        # Build items to score
        to_score = []
        for i, choice in enumerate(chat_completions.choices):
            response_content = choice.message.content
            diff_text = self._extract_diff_from_response(response_content)

            to_score.append({
                "task_id": item["task_id"],
                "messages": (
                    {"role": "system", "content": SYSTEM_PROMPT},
                    user_message,
                    {"role": "assistant", "content": response_content},
                ),
                "diff_text": diff_text,
                "tokens": nodes[i].tokens,
                "masks": nodes[i].masked_tokens,
                "logprobs": nodes[i].logprobs,
                "finish_reason": choice.finish_reason,
            })

        # Score all patches
        scored_data = await self.score(to_score)

        return scored_data, []  # No backlog items

    async def score(
        self, rollout_group_data: List[Dict]
    ) -> Optional[ScoredDataGroup]:
        """
        Score patches using the verification harness.

        Returns ScoredDataGroup with tokens, masks, and scores.
        """
        if not rollout_group_data:
            return None

        # Initialize as dict literal (ScoredDataGroup is a TypedDict)
        scores: ScoredDataGroup = {
            "tokens": [],
            "masks": [],
            "scores": [],
            "inference_logprobs": [],
            "ref_logprobs": None,
            "advantages": None,
            "messages": None,
            "generation_params": None,
            "group_overrides": {},
            "overrides": None,
            "images": None,
        }

        # Score each patch (could parallelize later with semaphore)
        group_scores = []  # For debug logging
        for item in rollout_group_data:
            score_value, failure_reason, patch_error = await self._score_single_patch(
                task_id=item["task_id"],
                diff_text=item["diff_text"]
            )
            group_scores.append((score_value, failure_reason))

            # Track metrics
            if score_value > 0:
                self.pass_rate_buffer.append(1.0)
            else:
                self.pass_rate_buffer.append(0.0)
                self.failure_reasons[failure_reason] = self.failure_reasons.get(failure_reason, 0) + 1

        # Debug: log group scores
        print(f"[SCR] Group scores: {group_scores}")

            # Filter out very short completions
            masks = item["masks"]
            if len([m for m in masks if m != -100]) < 10:
                continue

            scores["tokens"].append(item["tokens"])
            scores["masks"].append(masks)
            scores["inference_logprobs"].append(item["logprobs"])
            scores["scores"].append(score_value)

        # Need at least 2 items with different scores for GRPO
        if len(scores["tokens"]) < 2:
            return None

        # If all scores are the same, can't learn from this
        if all(s == scores["scores"][0] for s in scores["scores"]):
            return None

        return scores

    async def wandb_log(self, wandb_metrics: Optional[Dict] = None):
        """Log metrics to wandb."""
        if wandb_metrics is None:
            wandb_metrics = {}

        # Calculate pass rate
        if self.pass_rate_buffer:
            wandb_metrics["train/pass_rate"] = sum(self.pass_rate_buffer) / len(self.pass_rate_buffer)
            self.pass_rate_buffer = []

        # Log failure reasons
        if self.failure_reasons:
            total = sum(self.failure_reasons.values())
            for reason, count in self.failure_reasons.items():
                wandb_metrics[f"train/failure_{reason}"] = count / total
            self.failure_reasons = {}

        await super().wandb_log(wandb_metrics)

    async def evaluate(self, *args, **kwargs):
        """
        Evaluate the model on all tasks.

        Uses temperature=0 for deterministic evaluation.
        """
        import time
        start_time = time.time()

        eval_results = []

        for task in self.tasks:
            user_prompt = self._build_user_prompt(task)

            async with self.server.managed_server(tokenizer=self.tokenizer) as managed:
                completion = await managed.chat_completion(
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    n=1,
                    max_tokens=self.config.max_token_length,
                    temperature=0.0,  # Deterministic for eval
                )

            response = completion.choices[0].message.content
            diff_text = self._extract_diff_from_response(response)

            score, failure_reason, patch_error = await self._score_single_patch(
                task_id=task["task_id"],
                diff_text=diff_text
            )

            eval_results.append({
                "task_id": task["task_id"],
                "passed": score > 0,
                "failure_reason": failure_reason,
                "response": response[:500],  # Truncate for logging
            })

        # Calculate metrics
        pass_count = sum(1 for r in eval_results if r["passed"])
        pass_rate = pass_count / len(eval_results) if eval_results else 0

        end_time = time.time()

        eval_metrics = {
            "eval/pass_rate": pass_rate,
            "eval/pass_count": pass_count,
            "eval/total_tasks": len(eval_results),
        }

        await self.evaluate_log(
            metrics=eval_metrics,
            samples=eval_results,
            start_time=start_time,
            end_time=end_time,
            generation_parameters={
                "temperature": 0.0,
                "max_tokens": self.config.max_token_length,
            },
        )


if __name__ == "__main__":
    SecureCodeReviewEnv.cli()
