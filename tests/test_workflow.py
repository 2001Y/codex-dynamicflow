import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from codex_dynamicflow.workflow import WorkflowValidationError, load_workflow
from codex_dynamicflow.runner import Runner


def write_workflow(path: Path) -> Path:
    workflow = {
        "version": 1,
        "name": "sample",
        "settings": {"max_concurrency": 4, "artifact_dir": ".codex-dynamicflow"},
        "models": {
            "fast": {"model": "gpt-fast", "reasoning_effort": "low"},
            "coding": {"model": "gpt-coding", "reasoning_effort": "high"},
        },
        "phases": [
            {
                "id": "discover",
                "tasks": [
                    {
                        "id": "scan",
                        "role": "scout",
                        "model_profile": "fast",
                        "fork_turns": "none",
                        "worktree": "read_only",
                        "prompt": "Find targets",
                    }
                ],
            },
            {
                "id": "implement",
                "depends_on": ["discover"],
                "tasks": [
                    {
                        "id": "fix_auth",
                        "role": "implementer",
                        "model_profile": "coding",
                        "worktree": "isolated",
                        "output_schema": "schemas/patch_result.schema.json",
                        "prompt": "Fix auth",
                    }
                ],
            },
        ],
    }
    path.write_text(json.dumps(workflow), encoding="utf-8")
    return path


class WorkflowTests(unittest.TestCase):
    def test_load_workflow_resolves_model_profiles(self):
        with TemporaryDirectory() as td:
            path = write_workflow(Path(td) / "workflow.json")
            wf = load_workflow(path)

        self.assertEqual(wf.name, "sample")
        self.assertEqual(wf.phases[0].tasks[0].model, "gpt-fast")
        self.assertEqual(wf.phases[0].tasks[0].reasoning_effort, "low")
        self.assertEqual(wf.phases[1].tasks[0].model, "gpt-coding")
        self.assertEqual(wf.phases[1].tasks[0].reasoning_effort, "high")

    def test_full_fork_rejects_model_or_effort_override(self):
        with TemporaryDirectory() as td:
            path = write_workflow(Path(td) / "workflow.json")
            data = json.loads(path.read_text())
            task = data["phases"][0]["tasks"][0]
            task["fork_turns"] = "all"
            task["model"] = "different-model"
            path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(WorkflowValidationError, "full-history fork"):
                load_workflow(path)

    def test_runner_dry_run_writes_plan_without_invoking_codex(self):
        with TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            workflow_path = write_workflow(repo / "workflow.json")

            result = Runner(repo=repo).run(workflow_path, dry_run=True, run_id="run-test")

            self.assertEqual(result["run_id"], "run-test")
            self.assertTrue(result["dry_run"])
            self.assertEqual(len(result["tasks"]), 2)
            plan_path = repo / ".codex-dynamicflow" / "run-test" / "state.json"
            self.assertTrue(plan_path.exists())
            plan = json.loads(plan_path.read_text())
            fix = next(task for task in plan["tasks"] if task["id"] == "fix_auth")
            self.assertEqual(fix["model"], "gpt-coding")
            self.assertEqual(fix["reasoning_effort"], "high")
            self.assertIn("model_reasoning_effort=high", " ".join(fix["command"]))
            self.assertTrue(fix["worktree"].endswith("worktrees/fix_auth"))

    def test_runner_exec_does_not_inherit_mcp_stdin(self):
        with TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            workflow = {
                "version": 1,
                "name": "stdin-guard",
                "phases": [
                    {"id": "smoke", "tasks": [{"id": "say_ok", "prompt": "Say OK"}]}
                ],
            }
            workflow_path = repo / "workflow.json"
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")

            with patch("codex_dynamicflow.runner.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(["fake-codex"], 0)

                result = Runner(repo=repo, codex_bin="fake-codex").run(
                    workflow_path, dry_run=False, run_id="stdin-guard"
                )

            self.assertEqual(result["execution"]["tasks"][0]["status"], "success")
            self.assertIs(run.call_args.kwargs["stdin"], subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
