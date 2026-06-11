#!/usr/bin/env python3
"""Axon CLI — agentic SDLC orchestration platform.

Usage:
    python -m axon.cli.main run "<request>"
    python -m axon.cli.main status <workflow_id>
"""
from __future__ import annotations

import argparse
import sys

from axon.config.settings import settings
from axon.core.workflow import WorkflowSummary
from axon.llm.claude import ClaudeProvider
from axon.orchestrator.engine import WorkflowEngine
from axon.stores.local_artifact_store import LocalArtifactStore
from axon.stores.sqlite_state_store import SQLiteStateStore


# ─────────────────────────────────────────────────────────────────────────── #
# Wiring                                                                       #
# ─────────────────────────────────────────────────────────────────────────── #

def _build_engine() -> WorkflowEngine:
    llm = ClaudeProvider()
    artifact_store = LocalArtifactStore(base_path=settings.artifacts_base_path)
    state_store = SQLiteStateStore(db_path=settings.axon_db_path)
    return WorkflowEngine(llm=llm, artifact_store=artifact_store, state_store=state_store)


# ─────────────────────────────────────────────────────────────────────────── #
# Output                                                                       #
# ─────────────────────────────────────────────────────────────────────────── #

_WIDTH = 70
_SEP = "─" * _WIDTH


def _print_summary(summary: WorkflowSummary) -> None:
    print(f"\n{_SEP}")
    print("  AXON WORKFLOW SUMMARY")
    print(_SEP)
    print(f"  Workflow ID  : {summary.workflow_id}")
    print(f"  Status       : {summary.current_status.value}")
    print(_SEP)
    print(f"  Agents Run   : {', '.join(summary.agents_executed) or 'none'}")
    if summary.user_stories_created:
        print(f"  User Stories : {summary.user_stories_created}")
    if summary.prs_opened:
        print(f"  PRs Opened   : {', '.join(summary.prs_opened)}")
    if summary.qa_verdict:
        print(f"  QA Verdict   : {summary.qa_verdict}")
    print(_SEP)
    label = "ACTION REQUIRED" if summary.human_approval_required else "Next Step"
    print(f"  {label:13s}: {summary.next_recommended_step}")
    if summary.artifacts_created:
        print(_SEP)
        print("  Artifacts    :")
        for a in summary.artifacts_created[:12]:
            print(f"    • {a}")
        extra = len(summary.artifacts_created) - 12
        if extra > 0:
            print(f"    ... and {extra} more")
    print(f"{_SEP}\n")


# ─────────────────────────────────────────────────────────────────────────── #
# Commands                                                                     #
# ─────────────────────────────────────────────────────────────────────────── #

def cmd_run(args: argparse.Namespace) -> int:
    request: str = args.request.strip()
    if not request:
        print("Error: request cannot be empty.", file=sys.stderr)
        return 1

    preview = request[:80] + ("…" if len(request) > 80 else "")
    print(f"\nAxon: submitting request…\n  \"{preview}\"")

    engine = _build_engine()
    summary = engine.run(request)
    _print_summary(summary)

    # Exit 0 = completed/done, 2 = stopped for human approval, 1 = failed
    if summary.current_status.value in ("DONE", "QA_COMPLETED"):
        return 0
    if summary.human_approval_required:
        return 2
    return 1


def cmd_approve(args: argparse.Namespace) -> int:
    """Approve a paused workflow and advance to SM planning."""
    state_store = SQLiteStateStore(db_path=settings.axon_db_path)
    wf = state_store.get_workflow(args.workflow_id)
    if wf is None:
        print(f"Error: workflow '{args.workflow_id}' not found.", file=sys.stderr)
        return 1

    approvable = {"PO_AMBIGUOUS", "HUMAN_APPROVAL_REQUIRED", "SM_COMPLETED",
                  "QA_COMPLETED", "QA_FAILED"}
    if wf.status.value not in approvable:
        print(f"Error: workflow is in '{wf.status.value}' — not awaiting approval.", file=sys.stderr)
        return 1

    print(f"\nApproving workflow {args.workflow_id} (status: {wf.status.value})…")
    from pathlib import Path
    from axon.core.workflow import WorkflowStatus
    from axon.llm.claude import ClaudeProvider
    from axon.stores.local_artifact_store import LocalArtifactStore

    llm = ClaudeProvider()
    artifact_store = LocalArtifactStore(base_path=settings.artifacts_base_path)
    engine = WorkflowEngine(llm=llm, artifact_store=artifact_store, state_store=state_store)

    # Resume: find original request text from artifact file or event metadata
    events = state_store.list_events(args.workflow_id)
    raw_request = ""
    for ev in events:
        if ev.metadata.get("raw_request"):
            raw_request = ev.metadata["raw_request"]
            break

    if not raw_request:
        rr_path = Path(settings.artifacts_base_path) / args.workflow_id / "engine" / "raw_request.txt"
        if rr_path.exists():
            raw_request = rr_path.read_text(encoding="utf-8").strip()

    if not raw_request:
        raw_request = args.request or ""

    if not raw_request:
        print("Error: cannot resume — original request not found. Pass it with --request.",
              file=sys.stderr)
        return 1

    # Smart resume: if Dev artifacts already exist, jump straight to QA
    dev_dir = Path(settings.artifacts_base_path) / args.workflow_id / "dev"
    sm_ep = Path(settings.artifacts_base_path) / args.workflow_id / "sm" / "execution_plan.json"
    if dev_dir.exists() and any(dev_dir.glob("dev_output_*.json")) and sm_ep.exists():
        print("  Dev artifacts found — resuming from QA phase.")
        summary = engine._resume_from_qa(args.workflow_id, raw_request)
    else:
        summary = engine._resume_from_sm(args.workflow_id, raw_request)
    _print_summary(summary)
    return 0 if not summary.human_approval_required else 2



    state_store = SQLiteStateStore(db_path=settings.axon_db_path)
    wf = state_store.get_workflow(args.workflow_id)
    if wf is None:
        print(f"Error: workflow '{args.workflow_id}' not found.", file=sys.stderr)
        return 1
    print(f"\nWorkflow : {wf.workflow_id}")
    print(f"  Status : {wf.status.value}")
    print(f"  Stage  : {wf.current_stage}")
    print(f"  Created: {wf.created_at.isoformat()}")
    print(f"  Updated: {wf.updated_at.isoformat()}\n")
    return 0


# ─────────────────────────────────────────────────────────────────────────── #
# Entry point                                                                  #
# ─────────────────────────────────────────────────────────────────────────── #

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="axon",
        description="Axon — agentic SDLC orchestration platform",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Submit a request and run the full SDLC pipeline")
    run_p.add_argument("request", help="Natural language feature/bug request (quote it)")

    approve_p = sub.add_parser("approve", help="Approve a paused workflow and resume the pipeline")
    approve_p.add_argument("workflow_id", help="Workflow UUID to approve")
    approve_p.add_argument("--request", default="", help="Override request text (rarely needed)")

    status_p = sub.add_parser("status", help="Check status of an existing workflow")
    status_p.add_argument("workflow_id", help="Workflow UUID returned by `run`")

    args = parser.parse_args()

    if args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "approve":
        sys.exit(cmd_approve(args))
    elif args.command == "status":
        sys.exit(cmd_status(args))


if __name__ == "__main__":
    main()
