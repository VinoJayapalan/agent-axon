# Axon — System Design

**Version:** 1.0 (MVP)  
**Last updated:** 2026-06-11  
**Package:** `src/axon/`  
**Entry point:** `python -m axon.cli.main run "<request>"`

---

## Overview

Axon is an agentic SDLC orchestration platform that takes a natural language feature request and autonomously executes a full software delivery lifecycle: product assessment → sprint planning → code implementation → quality assurance → human approval gate → (placeholder) release.

Each phase is implemented as an independent agent. Agents communicate exclusively through persisted artifacts and workflow events — they never call each other directly.

---

## Agent Pipeline

```
User Request (CLI)
     │
     ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  PO Agent   │───▶│  SM Agent   │───▶│  Dev Agent  │───▶│  QA Agent   │
│             │    │             │    │ (Agent Dave) │    │             │
│ PRD         │    │ Sprint plan │    │ Code edits  │    │ Test cases  │
│ User stories│    │ Task list   │    │ Build check │    │ npm test    │
│ Feasibility │    │ Exec plan   │    │ PR per task │    │ Defect rpt  │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                                                                │
                                              QA PASS ──▶ HUMAN_APPROVAL_REQUIRED
                                              QA FAIL ──▶ SM replan (1 retry)
                                              QA FAIL×2 ──▶ HUMAN_APPROVAL_REQUIRED
```

After QA passes the workflow always stops at `HUMAN_APPROVAL_REQUIRED`.  
Approving advances to `APPROVED → DONE` (DevOps/Prod are placeholder agents).

---

## Architecture

### Hexagonal / Ports-and-Adapters

```
┌───────────────────────────────────────────────────────────┐
│  CLI  (axon.cli.main)                                     │
│   └─ WorkflowEngine (axon.orchestrator.engine)            │
│        ├─ StateMachine  — deterministic state transitions  │
│        ├─ AgentRouter   — status → agent dispatch          │
│        └─ Agents (PO / SM / Dev / QA / DevOps / Prod)     │
│             ├─ LLMProvider port   → ClaudeProvider adapter │
│             ├─ ArtifactStore port → LocalArtifactStore     │
│             └─ StateStore port    → SQLiteStateStore       │
└───────────────────────────────────────────────────────────┘
```

**Ports (interfaces):** `llm/base.py`, `stores/artifact_store.py`, `stores/state_store.py`  
**Adapters (concrete):** `ClaudeProvider`, `LocalArtifactStore`, `SQLiteStateStore`

### Event-driven communication

All agents read from and write to the filesystem (`artifacts/<wf_id>/<agent>/`).  
The engine passes `Event` objects between phases — no direct agent-to-agent calls.  
The `StateMachine.transition(current_status, event_type) → next_status` function drives all state changes.

---

## Folder Structure

```
agent-axon/
  agent.py                         ← Standalone CLI: python agent.py "<req>"
  pyproject.toml                   ← Package definition + dependencies
  design.md                        ← This file
  README.md                        ← Quickstart + usage guide
  AXON_PLAN.md                     ← MVP plan + future roadmap
  .env                             ← Secrets (gitignored)
  .env.example                     ← Template

  src/axon/
    cli/
      main.py                      ← run / approve / status commands

    orchestrator/
      engine.py                    ← WorkflowEngine — drives PO→SM→Dev→QA
      state_machine.py             ← Deterministic TRANSITIONS dict
      router.py                    ← AgentRouter: status → agent

    agents/
      base.py                      ← BaseAgent ABC + template method run()
      po/   agent.py  prompts.py  schemas.py
      sm/   agent.py  prompts.py  schemas.py
      dev/  agent.py  orchestrator.py  model_adapter.py  prompts.py  schemas.py
      qa/   agent.py  prompts.py  schemas.py
      devops/  agent.py  schemas.py   ← Placeholder — production gated
      prod/    agent.py  schemas.py   ← Placeholder — production gated

    core/
      workflow.py   ← WorkflowStatus (17 states), WorkflowState, WorkflowSummary
      events.py     ← Event, ArtifactRef, EventStatus
      results.py    ← AgentResult
      errors.py     ← AxonError, PolicyViolationError, LLMValidationError, WorkflowTransitionError
      artifacts.py  ← artifact_path() path helper

    llm/
      base.py    ← LLMProvider Protocol
      claude.py  ← ClaudeProvider (direct HTTP, no SDK)
      fake.py    ← FakeLLMProvider (substring-match dict, for tests)

    stores/
      artifact_store.py        ← ArtifactStore Protocol
      local_artifact_store.py  ← Writes to artifacts/<wf_id>/<agent>/<name>
      state_store.py           ← StateStore Protocol
      sqlite_state_store.py    ← SQLite: workflows, events, user_stories, product_catalog

    policies/
      command_policy.py    ← Shell command allowlist / blocklist
      approval_policy.py   ← Determines if human gate is required
      agent_permissions.py ← Per-agent tool category permissions

    tools/
      file_tools.py       ← read_file, write_file
      git_tools.py        ← create_branch, commit_changes, push_branch
      github_tools.py     ← create_pull_request
      repo_tools.py       ← list_repo_files
      validator_tools.py  ← run_build (npm run build)
      shell_executor.py   ← ShellExecutor — validated via CommandPolicy
      git_adapter.py      ← Re-exports GitResult + git_tools

    config/
      settings.py    ← Pydantic BaseSettings + alias constants

  artifacts/                   ← Runtime: one dir per workflow_id
  data/axon.db                 ← SQLite state DB
```

---

## Workflow State Machine

17 states, deterministic transitions. `*` is a wildcard that matches any unhandled event.

```
REQUEST_RECEIVED ──start──▶ PO_IN_PROGRESS
  ├─ po.ambiguous / high-risk ──▶ PO_AMBIGUOUS ──human.approve──▶ SM_IN_PROGRESS
  ├─ po.success               ──▶ PO_COMPLETED  ──sm.start──▶     SM_IN_PROGRESS
  └─ po.failed                ──▶ FAILED

SM_IN_PROGRESS
  ├─ sm.success ──▶ SM_COMPLETED ──dev.start──▶ DEV_IN_PROGRESS
  └─ sm.failed  ──▶ HUMAN_APPROVAL_REQUIRED

DEV_IN_PROGRESS
  ├─ dev.all_tasks_complete ──▶ DEV_COMPLETED ──▶ QA_IN_PROGRESS
  └─ dev.failed             ──▶ BUILD_FAILED  ──*──▶ HUMAN_APPROVAL_REQUIRED

QA_IN_PROGRESS
  ├─ qa.success ──▶ QA_COMPLETED ──*──▶ HUMAN_APPROVAL_REQUIRED
  └─ qa.failed  ──▶ QA_FAILED
                     ├─ retry=0 ──▶ SM_IN_PROGRESS  (replan + re-dev)
                     └─ retry=1 ──▶ HUMAN_APPROVAL_REQUIRED

HUMAN_APPROVAL_REQUIRED
  ├─ human.approve ──▶ APPROVED ──*──▶ DONE
  └─ human.reject  ──▶ REJECTED ──*──▶ FAILED
```

---

## Agent Responsibilities

| Agent | LLM | Key inputs | Key outputs |
|---|---|---|---|
| **PO** | Claude | Raw request, repo catalog | PRD, user_stories, acceptance_criteria, feasibility_report, open_questions |
| **SM** | Claude | User stories, ACs, defect_report | sprint_goal, task_breakdown, execution_plan, dependency_graph, risk_notes |
| **Dev** | None (delegates) | execution_plan.json | dev_output_task_N.json, PR URL, build result |
| **QA** | Claude (×2) | ACs, dev outputs, sprint_goal | test_cases, test_results, defect_report, qa_signoff, verdict |
| **DevOps** | None | — | devops_assessment.json (gated) |
| **Prod** | None | — | prod_release_gate.json (gated) |

---

## Developer Agent (Agent Dave) Internals

```
For each task in SM execution_plan:
  1. plan_change(requirement, repo_files, file_previews)
       → AgentPlan { summary, relevant_files, new_files, suggested_change }

  2. generate_edits(requirement, plan, file_contents)
       → For each relevant_file: edit prompt  → apply minimal diff
       → For each new_file:      create prompt → write from scratch

  3. npm install  (if package.json was modified)

  4. npm run build  → PASS / FAIL

  5. On PASS: git checkout -b <branch>
              git commit
              git push
              GitHub PR created
```

Key fix: `new_files` field in `AgentPlan` enables the agent to create files that don't yet exist, resolving the previous single-file limitation.

---

## Data Layout

### Artifacts (`artifacts/<workflow_id>/`)
```
engine/  raw_request.txt
po/      prd.json  user_stories.json  acceptance_criteria.json
         feasibility_report.json  open_questions.json  [release_notes.json]
sm/      sprint_goal.json  task_breakdown.json  execution_plan.json
         dependency_graph.json  risk_notes.json  sprint_progress_summary.json
dev/     dev_output_task_1.json … dev_output_task_N.json
qa/      test_cases.json  test_results.json  defect_report.json  qa_signoff.json
devops/  devops_assessment.json
prod/    prod_release_gate.json
```

### SQLite tables (`data/axon.db`)
| Table | Key columns |
|---|---|
| `workflows` | id, status, current_stage, created_at, updated_at, retry_count |
| `events` | id, workflow_id, source_agent, target_agent, event_type, status, artifact_refs_json, retry_count |
| `user_stories` | story_id, workflow_id, title, description, acceptance_criteria_json, priority, status |
| `product_catalog` | catalog_id, workflow_id, use_cases_json, user_workflows_json, design_decisions_json, components_json, scanned_at |

---

## Security Controls

| Control | Implementation |
|---|---|
| Command allowlist | `CommandPolicy` — `ALLOWED_COMMANDS` frozenset, `BLOCKED_PATTERNS` regex list |
| Agent permissions | `AGENT_PERMISSIONS` dict — enforced in `BaseAgent._check_permissions()` |
| Production gate | `DevOpsAgent` and `ProdAgent` always set `human_approval_required=True` |
| No secrets in artifacts | API keys read from env vars only; never written to files |
| Blocked commands | `rm -rf`, `terraform`, `kubectl`, `sudo`, `git push origin main`, etc. |
