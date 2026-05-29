from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from .workflow import TaskSpec, WorkflowSpec, load_workflow


class RunnerError(RuntimeError):
    pass


class Runner:
    def __init__(self, repo: str | Path, codex_bin: str = "codex") -> None:
        self.repo = Path(repo).expanduser().resolve()
        self.codex_bin = codex_bin

    def run(self, workflow_path: str | Path, dry_run: bool = False, run_id: Optional[str] = None) -> Dict[str, Any]:
        workflow = load_workflow(workflow_path)
        run_id = run_id or datetime.now().strftime("run-%Y%m%d-%H%M%S")
        run_dir = self.repo / workflow.artifact_dir / run_id
        self._ensure_layout(run_dir)

        planned: List[Dict[str, Any]] = []
        for phase in workflow.phases:
            for task in phase.tasks:
                planned.append(self._plan_task(workflow, task, run_dir))

        state: Dict[str, Any] = {
            "workflow": workflow.name,
            "run_id": run_id,
            "dry_run": dry_run,
            "repo": str(self.repo),
            "run_dir": str(run_dir),
            "tasks": planned,
        }
        self._write_json(run_dir / "state.json", state)

        if not dry_run:
            execution = self._execute(workflow, planned, run_dir)
            state["execution"] = execution
            self._write_json(run_dir / "state.json", state)
        return state

    def _plan_task(self, workflow: WorkflowSpec, task: TaskSpec, run_dir: Path) -> Dict[str, Any]:
        prompt_path = run_dir / "prompts" / f"{task.id}.md"
        prompt_path.write_text(task.prompt, encoding="utf-8")

        if task.worktree == "isolated":
            workdir = run_dir / "worktrees" / task.id
        else:
            workdir = self.repo

        result_md = run_dir / "results" / f"{task.id}.md"
        log_path = run_dir / "logs" / f"{task.id}.jsonl"
        command = [self.codex_bin, "exec", "--json"]
        if task.model:
            command.extend(["-m", task.model])
        if task.reasoning_effort:
            command.extend(["-c", f"model_reasoning_effort={task.reasoning_effort}"])
        command.extend(["-C", str(workdir)])
        if task.output_schema:
            command.extend(["--output-schema", task.output_schema])
        command.extend(["-o", str(result_md), task.prompt])

        return {
            "id": task.id,
            "phase": task.phase,
            "role": task.role,
            "model": task.model,
            "reasoning_effort": task.reasoning_effort,
            "fork_turns": task.fork_turns,
            "worktree_mode": task.worktree,
            "worktree": str(workdir),
            "prompt_path": str(prompt_path),
            "result_path": str(result_md),
            "log_path": str(log_path),
            "output_schema": task.output_schema,
            "timeout_sec": task.timeout_sec,
            "command": command,
            "write_scope": task.write_scope,
            "allow_failure": task.allow_failure,
            "depends_on": task.depends_on,
        }

    def _execute(self, workflow: WorkflowSpec, planned: List[Dict[str, Any]], run_dir: Path) -> Dict[str, Any]:
        by_phase: Dict[str, List[Dict[str, Any]]] = {}
        for task in planned:
            by_phase.setdefault(task["phase"], []).append(task)

        outcomes: List[Dict[str, Any]] = []
        for phase in workflow.phases:
            tasks = by_phase.get(phase.id, [])
            workers = max(1, min(int(phase.concurrency), len(tasks) or 1))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(self._execute_task, task, run_dir) for task in tasks]
                for future in as_completed(futures):
                    outcome = future.result()
                    outcomes.append(outcome)
                    if outcome["status"] != "success" and not outcome.get("allow_failure"):
                        raise RunnerError(f"task {outcome['id']} failed; see {outcome.get('log_path')}")
        return {"tasks": outcomes}

    def _execute_task(self, task: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
        if task["worktree_mode"] == "isolated":
            self._ensure_worktree(Path(task["worktree"]), task["id"])
        else:
            Path(task["worktree"]).mkdir(parents=True, exist_ok=True)

        log_path = Path(task["log_path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with log_path.open("w", encoding="utf-8") as stdout:
                completed = subprocess.run(
                    task["command"],
                    cwd=self.repo,
                    stdout=stdout,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=int(task["timeout_sec"]),
                    check=False,
                )
            if task["worktree_mode"] == "isolated":
                patch_path = run_dir / "diffs" / f"{task['id']}.patch"
                with patch_path.open("w", encoding="utf-8") as diff_out:
                    subprocess.run(
                        ["git", "diff"],
                        cwd=task["worktree"],
                        stdout=diff_out,
                        stderr=subprocess.STDOUT,
                        text=True,
                        check=False,
                    )
            else:
                patch_path = None
            status = "success" if completed.returncode == 0 else "failed"
            return {
                "id": task["id"],
                "status": status,
                "returncode": completed.returncode,
                "log_path": str(log_path),
                "result_path": task["result_path"],
                "diff_path": str(patch_path) if patch_path else None,
                "allow_failure": task.get("allow_failure", False),
            }
        except Exception as exc:
            return {
                "id": task["id"],
                "status": "failed",
                "error": str(exc),
                "log_path": str(log_path),
                "allow_failure": task.get("allow_failure", False),
            }

    def _ensure_worktree(self, path: Path, task_id: str) -> None:
        if path.exists():
            return
        branch = f"codex-flow/{task_id}"
        subprocess.run(
            ["git", "worktree", "add", str(path), "-b", branch, "HEAD"],
            cwd=self.repo,
            text=True,
            check=True,
        )

    def _ensure_layout(self, run_dir: Path) -> None:
        for name in ["prompts", "logs", "results", "diffs", "worktrees"]:
            (run_dir / name).mkdir(parents=True, exist_ok=True)

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
