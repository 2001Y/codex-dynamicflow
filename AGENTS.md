# Development rules

- Use TDD for behavior changes.
- Keep runtime dependency-free unless the benefit is explicit.
- `src/codex_flow/mini_yaml.py` intentionally supports only a small YAML subset; expand with tests first.
- Do not pass raw child JSONL logs into synthesis prompts by default. Use compact artifacts under `.codex-flow/<run>/results/`.
- Write-capable Codex workers should use isolated git worktrees.
