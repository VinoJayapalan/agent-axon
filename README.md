# Axon

**Agentic SDLC orchestration — from idea to PR.**

Axon takes a natural language feature request and autonomously runs a full software delivery lifecycle through a multi-agent pipeline: Product Owner → Scrum Master → Developer (Agent Dave) → QA → Human Approval.

---

## Prerequisites

- Python 3.11+
- Node.js + npm (for the target repository build/test steps)
- An Anthropic API key
- A GitHub Personal Access Token (for PR creation)

---

## Setup

```bash
# 1. Clone
git clone <repo>
cd agent-axon

# 2. Virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Install package
pip install -e ".[dev]"

# 4. Configure
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY, TARGET_REPO_PATH, GITHUB_TOKEN, etc.
```

### `.env` variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Claude API key |
| `ANTHROPIC_MODEL` | | Model name (default: `claude-sonnet-4-6`) |
| `MODEL_PROVIDER` | | `anthropic` or `stub` (default: `anthropic`) |
| `TARGET_REPO_PATH` | ✅ | Absolute path to the repo Axon will edit |
| `GITHUB_TOKEN` | ✅ | GitHub PAT with `repo` scope |
| `GITHUB_OWNER` | ✅ | GitHub repo owner |
| `GITHUB_REPO` | ✅ | GitHub repo name |
| `GITHUB_BASE_BRANCH` | | Base branch for PRs (default: `main`) |
| `AXON_DB_PATH` | | SQLite DB path (default: `data/axon.db`) |
| `ARTIFACTS_BASE_PATH` | | Artifact root (default: `artifacts/`) |

---

## Usage

### Submit a request

```bash
python -m axon.cli.main run "Add a dark mode toggle to the settings page"
```

Axon runs the full PO → SM → Dev → QA pipeline and prints a workflow summary:

```
──────────────────────────────────────────────────────────────────────
  AXON WORKFLOW SUMMARY
──────────────────────────────────────────────────────────────────────
  Workflow ID  : 3e06fc7a-...
  Status       : HUMAN_APPROVAL_REQUIRED
──────────────────────────────────────────────────────────────────────
  Agents Run   : po, sm, dev, qa
  QA Verdict   : PASS
──────────────────────────────────────────────────────────────────────
  ACTION REQUIRED: QA verdict: PASS. Run `axon approve <id>` to release.
──────────────────────────────────────────────────────────────────────
  Artifacts    :
    • artifacts/<id>/po/user_stories.json
    • artifacts/<id>/sm/execution_plan.json
    • artifacts/<id>/dev/dev_output_task_1.json
    • artifacts/<id>/qa/qa_signoff.json
──────────────────────────────────────────────────────────────────────
```

### Approve a paused workflow

The pipeline pauses at every human gate (`PO_AMBIGUOUS`, `HUMAN_APPROVAL_REQUIRED`). Use `approve` to advance:

```bash
python -m axon.cli.main approve <workflow-id>
```

If the workflow has Dev artifacts, approval skips straight to QA.

### Check workflow status

```bash
python -m axon.cli.main status <workflow-id>
```

### Standalone Dev Agent

Run just Agent Dave (plan + edit + build + PR) without the full pipeline:

```bash
python agent.py "Add loading spinner to the dashboard fetch calls"
```

---

## How It Works

### 1. PO Agent
- Scans the target repository to build a **product catalog** (use cases, components, design decisions)
- Evaluates the request against the catalog and existing backlog
- Produces: PRD, user stories with acceptance criteria, feasibility report, open questions
- Flags the request as **ambiguous** if design questions must be answered before implementation (pauses for human)
- Flags as **high risk** if `risk_level = High` (also pauses)

### 2. SM Agent
- Reads the PO artifacts
- Checks **Definition of Ready** on each user story
- Breaks stories into 2–5 concrete tasks with Fibonacci story points
- Produces a sequenced `execution_plan.json` — each entry is a self-contained requirement string passed verbatim to Agent Dave
- Produces: sprint_goal, task_breakdown, dependency_graph, risk_notes

### 3. Developer Agent (Agent Dave)
For each requirement string in the execution plan:
1. **Plans** the change — asks Claude which existing files to edit and which new files to create
2. **Edits** existing files (minimal diff)
3. **Creates** new files from scratch (fixed in v1.0 — `new_files` field in `AgentPlan`)
4. **Installs** dependencies if `package.json` changed
5. **Builds** the project (`npm run build`)
6. On success: creates a git branch, commits, pushes, opens a GitHub PR

### 4. QA Agent
- Reads acceptance criteria and dev outputs
- Generates up to 5 test cases and writes them
- Runs `npm test` on the target repo
- Asks Claude to analyse test results against the sprint goal
- Issues a **verdict**: `PASS` / `CONDITIONAL_PASS` / `FAIL`
- `FAIL` on first attempt → SM replan (QA defect report fed back to SM)
- `FAIL` on second attempt → escalate to human
- Any `PASS` → pauses for human approval

### 5. Human Approval Gate
The pipeline always stops at `HUMAN_APPROVAL_REQUIRED` before any release action.
Run `axon approve <id>` to advance (or inspect artifacts and reject).

### 6. DevOps / Prod Agents (Placeholder)
Return deployment readiness checklists and release gate information.
Production deployment is permanently gated — no automated deployment is performed.

---

## Artifacts

Every workflow writes structured JSON artifacts:

```
artifacts/<workflow-id>/
  engine/  raw_request.txt
  po/      prd.json  user_stories.json  acceptance_criteria.json
           feasibility_report.json  open_questions.json
  sm/      sprint_goal.json  task_breakdown.json  execution_plan.json
           dependency_graph.json  risk_notes.json
  dev/     dev_output_task_1.json  …  dev_output_task_N.json
  qa/      test_cases.json  test_results.json  defect_report.json  qa_signoff.json
```

Workflow state is also persisted to `data/axon.db` (SQLite).

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Workflow reached DONE |
| `2` | Paused at HUMAN_APPROVAL_REQUIRED |
| `1` | Error / FAILED |

---

## Project Layout

```
src/axon/
  cli/          Command-line interface
  orchestrator/ WorkflowEngine, StateMachine, AgentRouter
  agents/       PO, SM, Dev, QA, DevOps, Prod
  core/         Domain models (Event, WorkflowState, AgentResult, errors)
  llm/          LLMProvider port + ClaudeProvider adapter
  stores/       ArtifactStore + StateStore ports + SQLite/local adapters
  policies/     Command allowlist, approval logic, agent permissions
  tools/        File I/O, git, GitHub, repo scan, build validation
  config/       Pydantic settings
```

See [design.md](design.md) for full architecture details.
