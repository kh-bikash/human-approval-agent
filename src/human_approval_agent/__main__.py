"""Review and execute approved local file actions."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from .engine import ApprovalStore
from .web import serve

WEB_ACTIONS = {
    "propose": [
        (
            "relative_path",
            "Output file path relative to output directory",
            "text",
            True,
        ),
        ("content", "File content", "textarea", True),
        ("idempotency_key", "Idempotency key (optional)", "text", False),
    ],
    "list": [],
    "approve": [
        ("request_id", "Request ID", "text", True),
        ("actor", "Reviewer name", "text", True),
    ],
    "reject": [
        ("request_id", "Request ID", "text", True),
        ("actor", "Reviewer name", "text", True),
    ],
    "execute": [("request_id", "Approved request ID", "text", True)],
    "history": [("request_id", "Request ID", "text", True)],
}


def _write_file(action: str, payload: dict, outdir: Path) -> dict:
    if action != "write-file":
        raise ValueError("unsupported action")
    root = outdir.resolve()
    relative_path = payload["relative_path"]
    if not isinstance(relative_path, str) or not isinstance(payload["content"], str):
        raise TypeError("invalid file payload")
    target = (root / relative_path).resolve()
    if target == root or root not in target.parents:
        raise ValueError("output path escapes configured directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent, delete=False
    ) as file:
        file.write(payload["content"])
        temporary = Path(file.name)
    os.replace(temporary, target)
    return {"written": str(target)}


def execute(action: str, values: dict, *, db: str, outdir: Path) -> object:
    store = ApprovalStore(db)
    if action == "propose":
        request = store.propose(
            "write-file",
            {"relative_path": values["relative_path"], "content": values["content"]},
            confidence=0.0,
            idempotency_key=values.get("idempotency_key") or None,
        )
        return request.__dict__
    if action == "list":
        return [request.__dict__ for request in store.list_requests()]
    if action in {"approve", "reject"}:
        status = store.decide(
            values["request_id"], actor=values["actor"], approve=action == "approve"
        )
        return {"status": status}
    if action == "execute":
        return store.resume(
            values["request_id"],
            executor=lambda name, payload: _write_file(name, payload, outdir),
        )
    if action == "history":
        return [
            {"actor": actor, "event": event, "at": at}
            for actor, event, at in store.history(values["request_id"])
        ]
    raise ValueError("unknown action")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Durable file approval workflow")
    parser.add_argument("--db", default="approvals.sqlite3")
    parser.add_argument("--outdir", default="approved-output")
    commands = parser.add_subparsers(dest="command", required=True)
    propose = commands.add_parser("propose")
    propose.add_argument("relative_path")
    propose.add_argument("content")
    propose.add_argument("--idempotency-key")
    commands.add_parser("list")
    for name in ("approve", "reject"):
        decision = commands.add_parser(name)
        decision.add_argument("request_id")
        decision.add_argument("--actor", required=True)
    run = commands.add_parser("execute")
    run.add_argument("request_id")
    history = commands.add_parser("history")
    history.add_argument("request_id")
    browser = commands.add_parser("serve")
    browser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    if args.command == "serve":
        serve(
            "Human Approval Agent",
            WEB_ACTIONS,
            lambda action, values: execute(
                action, values, db=args.db, outdir=Path(args.outdir)
            ),
            port=args.port,
        )
    else:
        print(
            json.dumps(
                execute(args.command, vars(args), db=args.db, outdir=Path(args.outdir)),
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
