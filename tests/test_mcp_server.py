import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


def send(proc, payload):
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


class McpServerTests(unittest.TestCase):
    def test_mcp_server_lists_and_calls_plan_tool(self):
        with TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            workflow = {
                "version": 1,
                "name": "mcp-sample",
                "models": {"fast": {"model": "gpt-fast", "reasoning_effort": "low"}},
                "phases": [
                    {"id": "discover", "tasks": [{"id": "scan", "model_profile": "fast", "prompt": "scan"}]}
                ],
            }
            workflow_path = repo / "workflow.json"
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")

            proc = subprocess.Popen(
                [sys.executable, "-m", "codex_flow.mcp_server"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                init = send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
                self.assertEqual(init["result"]["serverInfo"]["name"], "codex-flow")

                tools = send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                names = {tool["name"] for tool in tools["result"]["tools"]}
                self.assertIn("workflow_plan", names)

                call = send(
                    proc,
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "workflow_plan",
                            "arguments": {
                                "workflow_path": str(workflow_path),
                                "repo": str(repo),
                                "run_id": "mcp-run",
                            },
                        },
                    },
                )
                text = call["result"]["content"][0]["text"]
                payload = json.loads(text)
                self.assertEqual(payload["run_id"], "mcp-run")
                self.assertEqual(payload["tasks"][0]["id"], "scan")
            finally:
                proc.terminate()
                proc.wait(timeout=5)
                if proc.stdin:
                    proc.stdin.close()
                if proc.stdout:
                    proc.stdout.close()
                if proc.stderr:
                    proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
