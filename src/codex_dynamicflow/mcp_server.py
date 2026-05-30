from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

from .runner import Runner


SERVER_INFO = {"name": "codex-dynamicflow", "version": "0.1.0"}


def main() -> int:
    server = JsonRpcMcpServer()
    server.serve()
    return 0


class JsonRpcMcpServer:
    def serve(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self.handle(request)
            except Exception as exc:
                response = self.error(None, -32603, str(exc))
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()

    def handle(self, request: Dict[str, Any]) -> Dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}
        if method == "initialize":
            return self.result(
                request_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO,
                },
            )
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return self.result(request_id, {})
        if method == "tools/list":
            return self.result(request_id, {"tools": tools()})
        if method == "tools/call":
            return self._call_tool(request_id, params)
        return self.error(request_id, -32601, f"method not found: {method}")

    def _call_tool(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            if name == "workflow_plan":
                payload = call_workflow(arguments, dry_run=True)
            elif name == "workflow_run":
                payload = call_workflow(arguments, dry_run=bool(arguments.get("dry_run", False)))
            elif name == "workflow_status":
                payload = call_status(arguments)
            else:
                return self.error(request_id, -32602, f"unknown tool: {name}")
            return self.result(
                request_id,
                {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}]},
            )
        except Exception as exc:
            return self.result(
                request_id,
                {"isError": True, "content": [{"type": "text", "text": str(exc)}]},
            )

    def result(self, request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def error(self, request_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def tools() -> list[Dict[str, Any]]:
    path_arg = {"type": "string", "description": "Path to workflow JSON/YAML"}
    repo_arg = {"type": "string", "description": "Git repository root; defaults to workflow parent"}
    run_id_arg = {"type": "string", "description": "Optional deterministic run id"}
    return [
        {
            "name": "workflow_plan",
            "description": "Validate a Codex workflow and write a dry-run plan without invoking Codex.",
            "inputSchema": {
                "type": "object",
                "properties": {"workflow_path": path_arg, "repo": repo_arg, "run_id": run_id_arg},
                "required": ["workflow_path"],
            },
        },
        {
            "name": "workflow_run",
            "description": "Run a Codex workflow. Set dry_run=true to only plan; false invokes codex exec workers.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "workflow_path": path_arg,
                    "repo": repo_arg,
                    "run_id": run_id_arg,
                    "dry_run": {"type": "boolean", "default": False},
                },
                "required": ["workflow_path"],
            },
        },
        {
            "name": "workflow_status",
            "description": "Read a codex-dynamicflow state.json file for an existing run.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repo": repo_arg,
                    "run_id": {"type": "string"},
                    "artifact_dir": {"type": "string", "default": ".codex-dynamicflow"},
                },
                "required": ["repo", "run_id"],
            },
        },
    ]


def call_workflow(arguments: Dict[str, Any], dry_run: bool) -> Dict[str, Any]:
    workflow_path = Path(str(arguments["workflow_path"])).expanduser().resolve()
    repo = Path(str(arguments.get("repo") or workflow_path.parent)).expanduser().resolve()
    runner = Runner(repo=repo, codex_bin=str(arguments.get("codex_bin") or "codex"))
    return runner.run(workflow_path, dry_run=dry_run, run_id=arguments.get("run_id"))


def call_status(arguments: Dict[str, Any]) -> Dict[str, Any]:
    repo = Path(str(arguments["repo"])).expanduser().resolve()
    artifact_dir = str(arguments.get("artifact_dir") or ".codex-dynamicflow")
    run_id = str(arguments["run_id"])
    state_path = repo / artifact_dir / run_id / "state.json"
    return json.loads(state_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
