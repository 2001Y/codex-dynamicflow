import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))


def subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    return env


class CliTests(unittest.TestCase):
    def test_cli_plan_prints_json_and_writes_state(self):
        with TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            workflow = {
                "version": 1,
                "name": "cli-sample",
                "models": {"fast": {"model": "gpt-fast", "reasoning_effort": "low"}},
                "phases": [
                    {"id": "discover", "tasks": [{"id": "scan", "model_profile": "fast", "prompt": "scan"}]}
                ],
            }
            workflow_path = repo / "workflow.json"
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "codex_dynamicflow.cli",
                    "plan",
                    str(workflow_path),
                    "--repo",
                    str(repo),
                    "--run-id",
                    "cli-run",
                ],
                text=True,
                capture_output=True,
                env=subprocess_env(),
                check=True,
            )

            payload = json.loads(completed.stdout)
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["tasks"][0]["id"], "scan")
            self.assertTrue((repo / ".codex-dynamicflow" / "cli-run" / "state.json").exists())


if __name__ == "__main__":
    unittest.main()
