# Axon — MVP Plan & Roadmap

**Product:** Axon — Agentic SDLC Orchestration  
**Tagline:** From idea to PR, autonomously.  
**CLI:** `python -m axon.cli.main run "<request>"`

---

## Agent Flow

```
Raw Feature Request
  → PO Agent       catalog refresh + feasibility + user stories
  → SM Agent       sprint planning + DoR check + execution plan
  → Dev Agent      Agent Dave — edit/create files, build, PR per task
  → QA Agent       test generation + npm test + defect analysis + verdict
  → HUMAN_APPROVAL_REQUIRED
  → DevOps (placeholder) → Prod (placeholder)
```

---

## MVP Implementation Status

### ✅ Phase 0 — Project scaffold
- `pyproject.toml`, `.env.example`, `src/axon/` package, `__init__.py` files
- `.gitignore` updated (artifacts, DB, .venv)

### ✅ Phase 1 — Cleanup
- Deleted: `tester.py`, `tester_orchestrator.py`, root `tools/` dir, root `config.py`
- Stripped `TesterAdapter` from `model_adapter.py`
- Removed: root `model_adapter.py` (stale copy), `requirements.txt` (superseded by pyproject.toml), `prompts/` dir

### ✅ Phase 2 — Core domain models
- `core/errors.py` — `AxonError`, `PolicyViolationError`, `LLMValidationError`, `WorkflowTransitionError`
- `core/events.py` — `Event`, `ArtifactRef`, `EventStatus`
- `core/workflow.py` — `WorkflowStatus` (17 states), `WorkflowState`, `WorkflowSummary`
- `core/results.py` — `AgentResult`
- `core/artifacts.py` — `artifact_path()` helper

### ✅ Phase 3 — LLM provider
- `llm/base.py` — `LLMProvider` Protocol
- `llm/claude.py` — `ClaudeProvider` (direct HTTP, no SDK)
- `llm/fake.py` — `FakeLLMProvider` (substring-match dict)

### ✅ Phase 4 — Stores
- `stores/artifact_store.py` — `ArtifactStore` Protocol
- `stores/local_artifact_store.py` — writes to `artifacts/<wf_id>/<agent>/<name>`
- `stores/state_store.py` — `StateStore` Protocol
- `stores/sqlite_state_store.py` — full SQLite implementation (4 tables)

### ✅ Phase 5 — Policies
- `policies/command_policy.py` — `ALLOWED_COMMANDS` frozenset + `BLOCKED_PATTERNS`
- `policies/approval_policy.py` — `ApprovalPolicy.requires_human()`
- `policies/agent_permissions.py` — per-agent tool category map

### ✅ Phase 6 — Base agent
- `agents/base.py` — `BaseAgent` ABC with template method `run()`, `_check_permissions()`

### ✅ Phase 7 — Adapter tools
- `tools/shell_executor.py` — `ShellExecutor` validated by `CommandPolicy`
- `tools/git_adapter.py` — re-exports git functions
- Moved `file_tools`, `git_tools`, `github_tools`, `repo_tools`, `validator_tools` into `src/axon/tools/`

### ✅ Phase 8 — Developer Agent (Agent Dave)
- `agents/dev/schemas.py` — `DevInput`, `DevOutput`
- `agents/dev/prompts.py` — `load_execution_plan()`
- `agents/dev/model_adapter.py` — `AnthropicAdapter` with `new_files` support
- `agents/dev/orchestrator.py` — `run_agent()` with auto `npm install` on `package.json` change
- `agents/dev/agent.py` — `DevAgent` wrapping Agent Dave pipeline per SM task

### ✅ Phase 9 — PO Agent
- `agents/po/schemas.py`, `prompts.py`, `agent.py`
- Phase 1: catalog refresh (repo scan → Claude → SQLite + catalog.md snapshot)
- Phase 2: request assessment (PRD, user stories, ACs, feasibility, open questions)
- Phase 3 (post-approved): story completion + release notes

### ✅ Phase 10 — SM Agent
- `agents/sm/schemas.py`, `prompts.py`, `agent.py`
- DoR validation, task breakdown, execution plan, dependency graph, risk notes

### ✅ Phase 11 — QA Agent
- `agents/qa/schemas.py`, `prompts.py`, `agent.py`
- Test case generation (capped at 5), `npm test`, defect analysis, PASS/FAIL verdict

### ✅ Phase 12 — Placeholder agents
- `agents/devops/` — returns deployment checklist, always gated
- `agents/prod/` — returns release gate, always gated with required approvals

### ✅ Phase 13 — Orchestrator
- `orchestrator/state_machine.py` — 25 transitions + wildcard fallback
- `orchestrator/router.py` — `AgentRouter` mapping `WorkflowStatus → agent`
- `orchestrator/engine.py` — `WorkflowEngine.run()` + `_resume_from_sm()` + `_resume_from_qa()`

### ✅ Phase 14 — CLI
- `cli/main.py` — `run`, `approve`, `status` subcommands
- Smart resume: detects existing Dev artifacts, skips to QA on `approve`
- Raw request persisted to `artifacts/<id>/engine/raw_request.txt` for recovery

### ✅ Phase 15 — Bug fixes (post-demo)
- `max_tokens` increased: PO 4096, SM 4096, QA gen 6000, QA analysis 3000
- QA prompt capped: max 5 test cases, no `test_content` generation (avoids truncation)
- `new_files` field added to `AgentPlan` — fixes Dev Agent single-file creation limitation
- Auto `npm install` in orchestrator when `package.json` is modified
- Error messages surfaced in CLI summary output

---

## Deferred

- **Tests** — unit/integration test suite (deferred for demo; `FakeLLMProvider` in `llm/fake.py` is ready)

---

## Future Roadmap

### Near-term (v1.1)

- [ ] **Unit + integration tests**  
  Cover `StateMachine`, `SQLiteStateStore`, each agent with `FakeLLMProvider`, CLI commands

- [ ] **Dev Agent: multi-PR strategy**  
  Currently all tasks run sequentially on the same branch. Investigate parallel branches per task + merge strategy

- [ ] **Dev Agent: rollback on build failure**  
  Auto-revert partial edits via `git checkout` when a task fails the build, keeping the repo clean for retry

- [ ] **SM: DoR enforcement**  
  Surface specific DoR failure reasons to the human approval screen so operators can fix them without re-running PO

- [ ] **QA: test framework detection**  
  Auto-detect Jest vs pytest vs Vitest and generate appropriate test file format

- [ ] **Workflow resume from any state**  
  `axon approve` currently only resumes from PO_AMBIGUOUS or HUMAN_APPROVAL_REQUIRED.  
  Add `axon resume --from-phase <po|sm|dev|qa>` for finer control

### Medium-term (v1.2)

- [ ] **Product catalog versioning**  
  Store catalog snapshots per workflow and diff them to detect breaking changes automatically

- [ ] **PO: duplicate detection improvement**  
  Current implementation uses substring title matching. Replace with embedding-based similarity search

- [ ] **Multiple target repos**  
  Support a `REPOS` config array so one Axon instance can manage multiple services

- [ ] **Approval webhook**  
  Replace CLI `approve` with a webhook endpoint so approvals can come from Slack/GitHub PR review/JIRA

- [ ] **Dev Agent: TypeScript support**  
  Current file scanning only picks up `.js`, `.jsx`, `.json`. Add `.ts`, `.tsx` detection and adjust edit prompts

### Long-term (v2.0)

- [ ] **DevOps Agent — real implementation**  
  Run `terraform plan`, validate staging deployment, integrate with Kubernetes health checks  
  _(Currently a gated placeholder — production deployment disabled by design)_

- [ ] **Prod Agent — real implementation**  
  Integrate with Change Advisory Board API, enforce mandatory approval SLAs, trigger blue/green deploy  
  _(Currently a gated placeholder — all approvals manual)_

- [ ] **Observability**  
  Structured logging (JSON) per agent, OpenTelemetry spans, Axon dashboard UI

- [ ] **Multi-agent parallelism**  
  Run independent SM tasks in parallel (respect `depends_on` graph). Currently strictly sequential

- [ ] **LLM provider abstraction**  
  Swap `ClaudeProvider` for OpenAI, Gemini, or local Ollama via the existing `LLMProvider` Protocol without code changes

- [ ] **Security: secrets scanning**  
  Pre-commit hook + CI check to block LLM-generated code containing hardcoded credentials

- [ ] **Human approval UI**  
  Minimal web UI showing workflow summary, artifacts, QA report, and approve/reject buttons  
  _(Currently CLI-only)_
