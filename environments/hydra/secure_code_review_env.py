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


# System prompt template for secure code review (use _get_system_prompt to format)
SYSTEM_PROMPT_TEMPLATE = """You are an expert security engineer. Your task is to fix security vulnerabilities by generating unified diff patches.

STRICT OUTPUT FORMAT - Follow this EXACTLY:
1. Output ONLY a diff, no text before or after
2. Use this EXACT format for the target file {target_file}:

```diff
diff --git a/{target_file} b/{target_file}
--- a/{target_file}
+++ b/{target_file}
@@ -LINE,COUNT +LINE,COUNT @@ function_name
 context line (space prefix)
-removed line (minus prefix)
+added line (plus prefix)
 context line (space prefix)
```

RULES:
- File path MUST be: {target_file} (NOT workspace/{target_file})
- Headers MUST have a/ and b/ prefixes
- Each line MUST start with: space, +, -, or @@
- NO explanations, NO prose, NO comments outside the diff

CRITICAL CONSTRAINTS:
- Make the SMALLEST change that fixes the vulnerability
- Do NOT add "FIXED:" comments or docstrings
- Do NOT change routes, HTTP methods, or function signatures unless required by the fix
- Hunk context lines (space prefix) must be copied EXACTLY from the provided code
- Do NOT invent or paraphrase lines - only modify lines that exist verbatim in the file

EXAMPLE - Fixing SQL injection (CWE-89) in {target_file}:
```diff
diff --git a/{target_file} b/{target_file}
--- a/{target_file}
+++ b/{target_file}
@@ -38,6 +38,6 @@ def search_users():
     conn = get_db()
     init_db(conn)

-    sql = f"SELECT * FROM users WHERE username LIKE '%{{query}}%'"
-    cursor = conn.execute(sql)
+    sql = "SELECT * FROM users WHERE username LIKE ?"
+    cursor = conn.execute(sql, (f"%{{query}}%",))

     results = [dict(row) for row in cursor.fetchall()]
```

Generate the diff now:"""


def _get_system_prompt(target_file: str = "app.py") -> str:
    """Format the system prompt with the target filename."""
    return SYSTEM_PROMPT_TEMPLATE.format(target_file=target_file)


class SCRTask(TypedDict):
    """Type for a secure code review task."""
    task_id: str
    code: str
    metadata: Dict[str, Any]
    cwe: str
    description: str
    target_file: str  # Relative path for patch (e.g., "app.py")


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
            max_token_length=3072,
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

            # Extract relative target file for patch (strip workspace/ prefix)
            target_file = vuln_file
            if target_file.startswith("workspace/"):
                target_file = target_file[len("workspace/"):]

            task = SCRTask(
                task_id=task_meta["id"],
                code=code,
                metadata=task_meta.get("metadata", {}),
                cwe=task_meta.get("cwe", "Unknown"),
                description=task_meta.get("metadata", {}).get("description", ""),
                target_file=target_file
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
        target_file = task.get('target_file', 'app.py')
        return f"""## Vulnerability Information
- CWE: {task['cwe']}
- Description: {task['description']}
- Language: {task['metadata'].get('language', 'python')}
- Framework: {task['metadata'].get('framework', 'unknown')}
- Target file: {target_file}

## Vulnerable Code ({target_file})
```python
{task['code']}
```

## Requirements
1. Fix the security vulnerability described above
2. Maintain all existing functionality
3. The patch must pass regression tests
4. The code must be clean of security scanner findings

Generate a unified diff patch for {target_file} to fix this vulnerability:"""

    def _normalize_path(self, path: str) -> str:
        """
        Normalize a file path for diff format.

        Patches are applied with `-d /workspace`, so paths should be
        relative to the workspace directory (e.g., 'app.py' not 'workspace/app.py').
        """
        path = path.strip()
        # Remove timestamps
        if '\t' in path:
            path = path.split('\t')[0]
        # Remove leading ./
        if path.startswith('./'):
            path = path[2:]
        # Remove workspace/ prefix - paths should be relative to workspace dir
        if path.startswith('workspace/'):
            path = path[len('workspace/'):]
        # Remove a/ or b/ prefix (will be re-added)
        if path.startswith('a/') or path.startswith('b/'):
            path = path[2:]
        # Remove another workspace/ in case it was doubled (a/workspace/app.py)
        if path.startswith('workspace/'):
            path = path[len('workspace/'):]
        return path

    def _normalize_diff_headers(self, diff_text: str) -> str:
        """
        Aggressively normalize diff headers for `patch -p1` compatibility.

        Handles common model mistakes:
        - Missing a/b prefixes
        - Missing workspace/ in path
        - Leading ./ in paths
        - Missing diff --git header
        - Prose between headers (stripped)
        """
        lines = diff_text.split('\n')
        normalized = []
        has_git_header = False
        in_diff = False
        file_path = None

        for line in lines:
            # Track if we have a git header
            if line.startswith('diff --git'):
                has_git_header = True
                in_diff = True
                normalized.append(line)
                continue

            # Fix --- header
            if line.startswith('--- '):
                in_diff = True
                path = self._normalize_path(line[4:])
                # Remove any existing a/ prefix before re-adding
                if path.startswith('a/'):
                    path = path[2:]
                file_path = path
                line = f'--- a/{path}'
                normalized.append(line)
                continue

            # Fix +++ header
            if line.startswith('+++ '):
                path = self._normalize_path(line[4:])
                if path.startswith('b/'):
                    path = path[2:]
                line = f'+++ b/{path}'
                normalized.append(line)
                continue

            # Keep hunk headers and diff content
            if line.startswith('@@') or line.startswith('+') or line.startswith('-') or line.startswith(' '):
                in_diff = True
                normalized.append(line)
                continue

            # If we're in diff mode and see non-diff content, might be prose - skip it
            if in_diff and line.strip() and not line.startswith(('#', 'diff', '---', '+++', '@@', '+', '-', ' ', '\\')):
                # Skip prose lines within diff
                continue

            # Keep empty lines and other valid content
            normalized.append(line)

        result = '\n'.join(normalized)

        # Add diff --git header if missing but we have file path
        if not has_git_header and file_path:
            git_header = f'diff --git a/{file_path} b/{file_path}\n'
            result = git_header + result

        return result

    def _extract_diff_from_response(self, response: str) -> Optional[str]:
        """Extract a unified diff from the model response and normalize headers."""
        # Try to find diff in code block first (most reliable)
        # Check ALL fenced blocks, not just the first one (models often emit
        # explanation blocks before the actual diff block)
        diff_pattern = r'```(?:diff)?\s*\n(.*?)```'
        matches = re.findall(diff_pattern, response, re.DOTALL)

        for match in matches:
            diff_text = match.strip()
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
    # Split patch_apply_failure into subreasons for better variance
    FAILURE_SCORES = {
        # Format failures (worst - no valid diff extracted)
        "invalid_patch_format": -1.0,
        "patch_apply_truncated": -0.97,      # Output truncated mid-line
        # Patch apply subreasons (creates variance even when all fail to apply)
        "patch_apply_malformed": -0.95,      # "malformed patch" / "patch: ****"
        "patch_apply_path_not_found": -0.9,  # "can't find file to patch"
        "patch_apply_hunk_failed": -0.85,    # "Hunk #X FAILED"
        "patch_apply_other": -0.92,          # Other apply errors
        # Post-apply failures (patch applied successfully)
        "scanner_findings": -0.6,
        "regression_test_failure": -0.4,
        "patch_ineffective": -0.2,
        # Unknown failure
        "unknown": -0.8,
    }

    def _sanitize_diff_text(self, diff_text: str) -> Tuple[str, Optional[str]]:
        """
        Sanitize diff text before applying patch.

        Returns: (sanitized_diff, truncation_error_or_none)

        Fixes:
        1. Normalize CRLF to LF
        2. Strip trailing markdown fences
        3. Ensure final newline
        4. Detect truncation (incomplete diff structure)
        """
        # 1. Normalize line endings
        diff_text = diff_text.replace("\r\n", "\n").replace("\r", "\n")

        # 2. Strip trailing fences defensively
        had_final_newline = diff_text.endswith("\n")

        # Drop trailing blank lines, then a trailing fence line if present.
        lines = diff_text.split("\n")
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and lines[-1].strip() in ("```", "```diff"):
            lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
        diff_text = "\n".join(lines)

        # 3. Detect truncation BEFORE ensuring final newline
        # Common signs of truncation:
        # - Response likely ended due to max_tokens (no final newline + other indicators)
        # - Incomplete diff structure (missing required headers / hunk content)
        truncation_error = None

        # Heuristic: lack of final newline alone isn't enough (diffs may contain
        # "\ No newline at end of file"). Only treat it as truncation if the last
        # line also looks suspicious.
        if not had_final_newline and diff_text:
            last_line = diff_text.split("\n")[-1]
            diff_prefixes = (" ", "+", "-", "@", "\\", "diff", "---", "+++")
            if len(last_line) > 200 and not last_line.startswith(diff_prefixes):
                truncation_error = (
                    "Diff truncated mid-line (suspicious last line, no final newline)"
                )

        # Check for incomplete diff structure
        has_git_header = 'diff --git' in diff_text
        has_file_headers = '---' in diff_text and '+++' in diff_text
        has_hunk_marker = '@@' in diff_text

        if has_git_header or has_hunk_marker:
            # If we have diff structure, check completeness
            if not has_file_headers:
                truncation_error = "Incomplete diff structure (missing --- or +++)"
            elif has_hunk_marker:
                # Check if last hunk looks complete (should have at least one diff line after @@)
                hunk_lines = [i for i, line in enumerate(diff_text.split('\n')) if line.startswith('@@')]
                if hunk_lines:
                    last_hunk_idx = hunk_lines[-1]
                    lines_after_hunk = diff_text.split('\n')[last_hunk_idx + 1:]
                    # Filter to lines that are actual diff content (not empty)
                    content_lines = [l for l in lines_after_hunk if l and not l.isspace()]
                    # Need at least one line of context/changes after hunk header
                    if not content_lines:
                        truncation_error = "Incomplete hunk (no content after @@ marker)"

        # 4. Ensure final newline (after truncation check)
        if diff_text and not diff_text.endswith("\n"):
            diff_text += "\n"

        return diff_text, truncation_error

    def _classify_patch_error(self, error_text: str) -> str:
        """Classify patch application error into subreasons for variance."""
        error_lower = error_text.lower()
        # Check for truncation indicators first
        if "unexpectedly ends" in error_lower or "ends in middle of line" in error_lower:
            return "patch_apply_truncated"
        elif "malformed patch" in error_lower or "patch: ****" in error_text:
            return "patch_apply_malformed"
        elif "can't find file to patch" in error_lower:
            return "patch_apply_path_not_found"
        elif "hunk" in error_lower and "failed" in error_lower:
            return "patch_apply_hunk_failed"
        else:
            return "patch_apply_other"

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

        # Sanitize diff text (normalize line endings, strip fences, detect truncation)
        diff_text, truncation_error = self._sanitize_diff_text(diff_text)

        # If we detected truncation, return early with specific failure
        if truncation_error:
            return self.FAILURE_SCORES["patch_apply_truncated"], "patch_apply_truncated", truncation_error

        # Write sanitized diff to temp file
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
                # Split patch_apply_failure into subreasons for variance
                if failure_reason == "patch_apply_failure" and result.patch_error:
                    failure_reason = self._classify_patch_error(result.patch_error)
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
        target_file = item.get('target_file', 'app.py')
        system_prompt = _get_system_prompt(target_file)
        user_message = {"role": "user", "content": self._build_user_prompt(item)}

        async with self.server.managed_server(tokenizer=self.tokenizer) as managed:
            chat_completions = await managed.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
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
                    {"role": "system", "content": system_prompt},
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

            # Filter out very short completions (disabled for smoke testing)
            # Short completions will have poor harness scores anyway
            masks = item["masks"]
            completion_len = sum(1 for m in masks if m != -100)
            if completion_len < 10:
                # Keep item to prevent groups from collapsing below 2 members
                pass

            scores["tokens"].append(item["tokens"])
            scores["masks"].append(masks)
            scores["inference_logprobs"].append(item["logprobs"])
            scores["scores"].append(score_value)

        # Debug: log group scores
        print(f"[SCR] Group scores: {group_scores}")
        print(f"[SCR] Items after filtering: {len(scores['tokens'])}/{len(group_scores)}")

        # Need at least 2 items with different scores for GRPO
        if len(scores["tokens"]) < 2:
            print(f"[SCR] Group dropped: only {len(scores['tokens'])} items (need >= 2)")
            return None

        # If all scores are the same, can't learn from this
        # Can be disabled via --env.ensure_scores_are_not_same false for smoke testing
        all_same = all(s == scores["scores"][0] for s in scores["scores"])
        if all_same:
            print(f"[SCR] Uniform scores detected, ensure_scores_are_not_same={self.config.ensure_scores_are_not_same}")
        if self.config.ensure_scores_are_not_same and all_same:
            print(f"[SCR] Group dropped: all scores identical ({scores['scores'][0]})")
            return None

        # Populate ref_logprobs from inference_logprobs (rollout policy serves as reference)
        scores["ref_logprobs"] = scores["inference_logprobs"]

        print(f"[SCR] Group accepted! Returning {len(scores['tokens'])} scored items")
        return scores

    async def handle_send_to_api(self, scored_data, item=None, do_send_to_api=True, abort_on_any_max_length_exceeded=True):
        """Override to disable token length checking for smoke testing."""
        # Always disable abort_on_any_max_length_exceeded for smoke testing
        # Long patches will have poor scores anyway
        return await super().handle_send_to_api(
            scored_data,
            item,
            do_send_to_api,
            abort_on_any_max_length_exceeded=False  # Always False
        )

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
            target_file = task.get('target_file', 'app.py')
            system_prompt = _get_system_prompt(target_file)
            user_prompt = self._build_user_prompt(task)

            async with self.server.managed_server(tokenizer=self.tokenizer) as managed:
                completion = await managed.chat_completion(
                    messages=[
                        {"role": "system", "content": system_prompt},
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
                "response": response,
                "diff_text": diff_text,
                "patch_error": patch_error,
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
