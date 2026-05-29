# codex-flow

Codex CLIをClaude Code Dynamic Workflows級に使うための外部workflow runner。

## 実装済み

- phase / task workflow IR（JSON + 小さなYAML subset）
- task別 `model` / `reasoning_effort` routing
- `codex exec --json -o ...` worker起動計画
- read-only / isolated git worktree 実行
- phase単位の並列実行
- Don’t Peek向けartifact保存（`prompts/`, `results/`, `logs/`, `diffs/`）
- Hermesから使うためのstdio MCP server

詳細設計: `docs/codex-dynamic-workflows-parity.md`

## 使い方

```bash
cd ~/_dev/codex-flow
python3 -m codex_flow.cli plan examples/workflow.yaml --repo . --run-id smoke-plan
python3 -m codex_flow.cli run examples/smoke-real.json --repo . --run-id real-smoke
```

repo-local shim:

```bash
scripts/codex-flow-mcp
```

## Hermes連携

Hermes MCP serverとして登録済み。

```bash
hermes mcp list
hermes mcp test codex-flow
```

次のHermes新規セッション/再起動後、以下のMCP toolsとして使える。

- `mcp_codex_flow_workflow_plan`
- `mcp_codex_flow_workflow_run`
- `mcp_codex_flow_workflow_status`

## Workflow例

```yaml
version: 1
name: example
settings:
  max_concurrency: 4
models:
  fast:
    model: gpt-5.4-mini
    reasoning_effort: low
  strong:
    model: gpt-5.4
    reasoning_effort: xhigh
phases:
  - id: discover
    tasks:
      - id: scan
        model_profile: fast
        worktree: read_only
        fork_turns: none
        prompt: "Find independent implementation targets."
  - id: implement
    depends_on: [discover]
    concurrency: 4
    tasks:
      - id: impl_a
        model_profile: strong
        worktree: isolated
        prompt: "Implement target A in this isolated worktree."
```

## 検証

```bash
python3 -m unittest discover -s tests
python3 -m codex_flow.cli plan examples/workflow.yaml --repo . --run-id verify
python3 -m codex_flow.cli run examples/smoke-real.json --repo . --run-id real-smoke
```
