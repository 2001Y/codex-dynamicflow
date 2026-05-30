from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from .runner import Runner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-dynamicflow")
    parser.add_argument("--codex-bin", default="codex")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="validate workflow and write a dry-run execution plan")
    _add_common(plan)

    run = sub.add_parser("run", help="execute workflow with codex exec workers")
    _add_common(run)
    run.add_argument("--dry-run", action="store_true", help="only write the plan")

    return parser


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("workflow", help="workflow JSON/YAML file")
    parser.add_argument("--repo", default=".", help="git repository root")
    parser.add_argument("--run-id", default=None)


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    runner = Runner(repo=Path(args.repo), codex_bin=args.codex_bin)
    if args.command == "plan":
        payload = runner.run(args.workflow, dry_run=True, run_id=args.run_id)
    elif args.command == "run":
        payload = runner.run(args.workflow, dry_run=bool(args.dry_run), run_id=args.run_id)
    else:
        parser.error("unknown command")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
