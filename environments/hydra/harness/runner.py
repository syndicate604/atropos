#!/usr/bin/env python3
"""
Benchmark harness runner.

STDLIB ONLY - No external dependencies on host.

Week 2 additions:
- --patch-file to accept arbitrary diff files (for model-generated patches)
- Graceful handling of patch apply failures (structured JSON output)
- New failure reasons: patch_apply_failure, invalid_patch_format

Original fixes from v2 review:
1. PYTHONPATH set for pytest imports
2. Environment vars prevent cache writes in read-only container
3. No PyYAML - uses JSON for task config
4. patch binary checked at startup
5. Health poll instead of sleep(2)
6. Subprocess pipes handled safely (no deadlock)
"""

import json
import subprocess
import shutil
import tempfile
import argparse
import os
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Tuple
import sys
import time


@dataclass
class TaskResult:
    task_id: str
    patch_name: str
    passed: bool
    exploit_original_succeeded: bool
    exploit_patched_succeeded: bool
    tests_passed: bool
    scanner_clean: bool
    failure_reason: Optional[str]
    exploit_original_output: str = ""
    exploit_patched_output: str = ""
    tests_output: str = ""
    scanner_output: str = ""
    scanner_findings: List[dict] = field(default_factory=list)
    patch_error: str = ""  # New: capture patch application errors


class HarnessRunner:
    """Run benchmark tasks with proper isolation."""

    # Docker security hardening
    DOCKER_SECURITY_OPTS = [
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=100",
        "--memory=512m",
        "--cpus=1",
        "--tmpfs=/tmp:rw,exec,nosuid,size=128m",  # exec needed for pytest
    ]

    # Environment for container (prevents writes to read-only mounts)
    DOCKER_ENV = [
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-e", "PYTHONPYCACHEPREFIX=/tmp/pycache",
        "-e", "HOME=/tmp",
        "-e", "SEMGREP_CACHE_DIR=/tmp/semgrep-cache",
        "-e", "PYTHONPATH=/workspace",  # FIX: pytest can import app
    ]

    def __init__(self, tasks_dir: Path, image: str = "hydra-harness:latest"):
        self.tasks_dir = tasks_dir
        self.image = image
        self._check_patch_binary()

    def _check_patch_binary(self):
        """Verify patch is available on host."""
        result = subprocess.run(
            ["which", "patch"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise RuntimeError(
                "patch binary not found. Install: apt install patch / brew install gpatch"
            )

    def run_task(
        self,
        task_id: str,
        patch_name: Optional[str] = None,
        patch_file: Optional[Path] = None
    ) -> TaskResult:
        """
        Run a single task with a specific patch.

        Args:
            task_id: Task identifier (e.g., "sqli-001")
            patch_name: Name of patch in tasks/<id>/patches/ (e.g., "known-good")
            patch_file: Path to external patch file (for model-generated patches)

        One of patch_name or patch_file must be provided.
        """
        task_dir = self.tasks_dir / task_id

        if not task_dir.exists():
            raise ValueError(f"Task directory not found: {task_dir}")

        # Determine patch source
        if patch_file is not None:
            actual_patch_file = Path(patch_file)
            display_name = f"external:{actual_patch_file.name}"
        elif patch_name is not None:
            actual_patch_file = task_dir / "patches" / f"{patch_name}.diff"
            display_name = patch_name
            if not actual_patch_file.exists():
                raise ValueError(f"Patch not found: {actual_patch_file}")
        else:
            raise ValueError("Either patch_name or patch_file must be provided")

        # Load task config (JSON, not YAML - no host deps)
        config = self._load_config(task_dir / "task.json")

        # Create temp directory for workspace
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Copy workspace (will be modified by patch)
            workspace_src = task_dir / "workspace"
            workspace_dst = tmp_path / "workspace"
            shutil.copytree(workspace_src, workspace_dst)

            # Copy exploit (read-only)
            exploit_src = task_dir / "exploit"
            exploit_dst = tmp_path / "exploit"
            shutil.copytree(exploit_src, exploit_dst)

            # Step 1: Run exploit on ORIGINAL code
            print(f"  [1/5] Running exploit on original code...")
            exploit_original = self._run_exploit(workspace_dst, exploit_dst)

            # Step 2: Apply patch (with graceful failure handling)
            print(f"  [2/5] Applying patch: {display_name}...")
            patch_success, patch_error_code, patch_error_msg = self._apply_patch_safe(
                workspace_dst, actual_patch_file
            )

            if not patch_success:
                # Patch failed to apply - return early with structured result
                print(f"  [!] Patch failed: {patch_error_msg[:100]}...")
                return TaskResult(
                    task_id=task_id,
                    patch_name=display_name,
                    passed=False,
                    exploit_original_succeeded=exploit_original.returncode == 0,
                    exploit_patched_succeeded=False,
                    tests_passed=False,
                    scanner_clean=False,
                    failure_reason=patch_error_code,  # "invalid_patch_format" or "patch_apply_failure"
                    exploit_original_output=exploit_original.stdout + exploit_original.stderr,
                    exploit_patched_output="",
                    tests_output="",
                    scanner_output="",
                    scanner_findings=[],
                    patch_error=patch_error_msg
                )

            # Step 3: Run exploit on PATCHED code
            print(f"  [3/5] Running exploit on patched code...")
            exploit_patched = self._run_exploit(workspace_dst, exploit_dst)

            # Step 4: Run regression tests
            print(f"  [4/5] Running regression tests...")
            tests_result = self._run_tests(workspace_dst)

            # Step 5: Run scanner
            print(f"  [5/5] Running security scanner...")
            scanner_result = self._run_scanner(workspace_dst)

        # Parse results
        scanner_clean, scanner_findings = self._parse_scanner_result(
            scanner_result.stdout
        )

        # Determine pass/fail
        passed, failure_reason = self._evaluate(
            exploit_original_succeeded=exploit_original.returncode == 0,
            exploit_patched_succeeded=exploit_patched.returncode == 0,
            tests_passed=tests_result.returncode == 0,
            scanner_clean=scanner_clean
        )

        return TaskResult(
            task_id=task_id,
            patch_name=display_name,
            passed=passed,
            exploit_original_succeeded=exploit_original.returncode == 0,
            exploit_patched_succeeded=exploit_patched.returncode == 0,
            tests_passed=tests_result.returncode == 0,
            scanner_clean=scanner_clean,
            failure_reason=failure_reason,
            exploit_original_output=exploit_original.stdout + exploit_original.stderr,
            exploit_patched_output=exploit_patched.stdout + exploit_patched.stderr,
            tests_output=tests_result.stdout + tests_result.stderr,
            scanner_output=scanner_result.stdout,
            scanner_findings=scanner_findings,
            patch_error=""
        )

    def _run_exploit(
        self,
        workspace: Path,
        exploit: Path
    ) -> subprocess.CompletedProcess:
        """Run exploit in container."""
        return self._run_in_container(
            workspace=workspace,
            exploit=exploit,
            command=["python", "/exploit/exploit.py"],
            timeout=60  # Increased for server startup
        )

    def _run_tests(self, workspace: Path) -> subprocess.CompletedProcess:
        """Run pytest in container with correct PYTHONPATH."""
        return self._run_in_container(
            workspace=workspace,
            exploit=None,
            command=[
                "pytest",
                "/workspace/tests",
                "-v",
                "--tb=short",
                "-p", "no:cacheprovider",  # FIX: No cache writes
                "--basetemp=/tmp/pytest",  # FIX: Temp in tmpfs
                "--timeout=30",  # Per-test timeout
            ],
            timeout=120
        )

    def _run_scanner(self, workspace: Path) -> subprocess.CompletedProcess:
        """Run semgrep in container."""
        return self._run_in_container(
            workspace=workspace,
            exploit=None,
            command=[
                "semgrep", "scan",
                "--config=/harness/semgrep-rules",
                "--json",
                "--no-git-ignore",
                "/workspace"
            ],
            timeout=60
        )

    def _run_in_container(
        self,
        workspace: Path,
        exploit: Optional[Path],
        command: List[str],
        timeout: int
    ) -> subprocess.CompletedProcess:
        """Run command in hardened container with proper mounts."""
        docker_cmd = [
            "docker", "run", "--rm",
            *self.DOCKER_SECURITY_OPTS,
            *self.DOCKER_ENV,
            "-v", f"{workspace.absolute()}:/workspace:ro",
        ]

        if exploit:
            docker_cmd.extend(["-v", f"{exploit.absolute()}:/exploit:ro"])

        docker_cmd.extend([self.image, *command])

        try:
            # FIX: Use PIPE but with timeout to prevent deadlock
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result
        except subprocess.TimeoutExpired as e:
            return subprocess.CompletedProcess(
                args=docker_cmd,
                returncode=124,
                stdout=e.stdout or "",
                stderr=f"TIMEOUT after {timeout}s"
            )

    def _apply_patch_safe(
        self,
        workspace: Path,
        patch_file: Path
    ) -> Tuple[bool, str, str]:
        """
        Apply a diff patch to the workspace with graceful error handling.

        Returns:
            (success, error_code, error_message) tuple
            error_code is one of: "", "invalid_patch_format", "patch_apply_failure"
        """
        # Check if patch file exists
        if not patch_file.exists():
            return False, "patch_apply_failure", f"Patch file not found: {patch_file}"

        # Check if patch file is empty or invalid
        try:
            patch_content = patch_file.read_text()
            if not patch_content.strip():
                return False, "invalid_patch_format", "Patch file is empty"
            # Basic sanity check for diff format
            if not any(line.startswith(('---', '+++', 'diff '))
                       for line in patch_content.split('\n')[:10]):
                return False, "invalid_patch_format", "Missing diff headers (---, +++, or diff)"
        except Exception as e:
            return False, "patch_apply_failure", f"Could not read patch file: {e}"

        # Try to apply the patch with non-interactive flags to prevent hangs
        try:
            result = subprocess.run(
                [
                    "patch",
                    "-p1",
                    "--batch",      # Non-interactive, assume default answers
                    "--forward",    # Don't ask about reverse patches
                    "-d", str(workspace),
                    "-i", str(patch_file.absolute())
                ],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,  # Prevent reading from stdin
                timeout=30  # 30 second timeout for patch application
            )
        except subprocess.TimeoutExpired:
            return False, "patch_apply_failure", "Patch command timed out after 30s"

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown patch error"
            return False, "patch_apply_failure", error_msg.strip()

        return True, "", ""

    def _apply_patch(self, workspace: Path, patch_file: Path) -> None:
        """Apply a diff patch to the workspace (legacy, raises on failure)."""
        success, error_code, error_msg = self._apply_patch_safe(workspace, patch_file)
        if not success:
            raise RuntimeError(f"Failed to apply patch ({error_code}): {error_msg}")

    def _parse_scanner_result(self, stdout: str) -> Tuple[bool, List[dict]]:
        """Parse semgrep JSON output, return (clean, findings)."""
        try:
            data = json.loads(stdout)
            findings = data.get("results", [])
            return len(findings) == 0, findings
        except json.JSONDecodeError:
            # If we can't parse, treat as "has findings" (fail safe)
            return False, []

    def _evaluate(
        self,
        exploit_original_succeeded: bool,
        exploit_patched_succeeded: bool,
        tests_passed: bool,
        scanner_clean: bool
    ) -> Tuple[bool, Optional[str]]:
        """Determine pass/fail and reason."""

        # Original should be vulnerable
        if not exploit_original_succeeded:
            return False, "original_not_vulnerable"

        # Patched should NOT be vulnerable
        if exploit_patched_succeeded:
            return False, "patch_ineffective"

        # Tests should pass
        if not tests_passed:
            return False, "regression_test_failure"

        # Scanner should be clean
        if not scanner_clean:
            return False, "scanner_findings"

        return True, None

    def _load_config(self, path: Path) -> dict:
        """Load task JSON config (no YAML dependency)."""
        with open(path) as f:
            return json.load(f)


def main():
    parser = argparse.ArgumentParser(
        description="Run benchmark task",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s sqli-001 known-good
  %(prog)s sqli-001 known-bad --output results/test.json
  %(prog)s sqli-001 --patch-file /tmp/model_generated.diff
        """
    )
    parser.add_argument("task_id", help="Task ID (e.g., sqli-001)")
    parser.add_argument(
        "patch_name",
        nargs="?",
        default=None,
        help="Patch name from tasks/<id>/patches/ (e.g., known-good)"
    )
    parser.add_argument(
        "--patch-file",
        type=Path,
        help="Path to external patch file (for model-generated patches)"
    )
    parser.add_argument("--tasks-dir", default="tasks", help="Tasks directory")
    parser.add_argument("--output", help="Output JSON file")
    parser.add_argument("--image", default="hydra-harness:latest", help="Docker image")
    args = parser.parse_args()

    # Validate arguments
    if args.patch_name is None and args.patch_file is None:
        parser.error("Either patch_name or --patch-file must be provided")
    if args.patch_name is not None and args.patch_file is not None:
        parser.error("Provide patch_name OR --patch-file, not both")

    display_name = args.patch_name or f"file:{args.patch_file}"
    print(f"Running task: {args.task_id} with patch: {display_name}")
    print("-" * 50)

    runner = HarnessRunner(Path(args.tasks_dir), image=args.image)

    try:
        result = runner.run_task(
            args.task_id,
            patch_name=args.patch_name,
            patch_file=args.patch_file
        )
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Output
    result_dict = asdict(result)

    print("-" * 50)
    print(f"Result: {'PASSED' if result.passed else 'FAILED'}")
    if result.failure_reason:
        print(f"Reason: {result.failure_reason}")
    if result.patch_error:
        print(f"Patch Error: {result.patch_error[:200]}")

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(result_dict, f, indent=2)
        print(f"\nResults written to {output_path}")
    else:
        print(f"\n{json.dumps(result_dict, indent=2)}")

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
