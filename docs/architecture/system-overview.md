# System Overview

| | |
|---|---|
| **Status** | Accepted |
| **Last updated** | 2026-11-23 (public repository, `protect-main` ruleset, owner decisions D1–D6) |
| **Related** | [Security Model](security-model.md) · [ADR-0001](../decisions/ADR-0001-architecture.md) · [ADR-0002](../decisions/ADR-0002-autonomous-merge-and-human-decisions.md) |

## 1. Purpose and scope

Agent Factory is a reusable, human-supervised infrastructure of AI agents for software engineering. Its goal is to reach the **highest autonomy and quality that can be demonstrated with evidence**, while keeping humans in control of critical decisions.

This document describes:

- the subsystems and what each one is responsible for;
- the contracts between them;
- the task lifecycle and its human gates;
- the autonomy model;
- the phased roadmap.

Security controls are specified in the [Security Model](security-model.md). The rationale for the main technology choices is recorded in [ADR-0001](../decisions/ADR-0001-architecture.md).

**In scope:** planning, specifying, implementing, testing, reviewing and releasing software changes in GitHub repositories.

**Out of scope (for now):** production operations (on-call, incident remediation), autonomous deployment to production, and non-GitHub forges.

## 2. Quality goals and non-goals

| Priority | Quality goal | Meaning |
|---|---|---|
| 1 | **Safety and control** | No must-human decision (ADR-0002 §3) without human approval. Agents cannot relax guardrails. |
| 2 | **Quality** | Every change is specified, tested and independently reviewed by an agent before merge. |
| 3 | **Traceability** | Every change can be traced: spec → task → agent run → PR → tests → release. |
| 4 | **Autonomy** | Agents complete end-to-end work without human help inside their authorized envelope. |
| 5 | **Portability** | The architecture does not depend on any particular target project, and the agent runtime can be replaced. |

**Non-goals:**

- Replacing human accountability for what ships.
- Building a general-purpose agent platform.
- Maximizing autonomy at the expense of verifiability.

## 3. Architectural principles

From the [README](../../README.md):

1. Human oversight over autonomous execution.
2. Small, verifiable changes.
3. Independent quality evaluation.
4. Explicit permissions and security boundaries.
5. Reusable architecture, independent of any particular project.

Added by this document:

6. **Contracts before implementations.** Subsystems interact through versioned, schema-defined artifacts, never through implicit conventions.
7. **Deterministic enforcement for mandatory rules.** Any rule that must always hold is enforced by hooks, permissions, CI or repository rulesets. A prompt alone never enforces a mandatory rule.
8. **Evidence-based autonomy.** Autonomy is granted per role and risk class, based on measured evaluation results, and can be revoked.
9. **GitHub as the system of record.** State, approvals and history live in GitHub, where humans already work.
10. **Least privilege everywhere.** Each agent role receives only the tools, data and credentials its task requires.

## 4. System context

```mermaid
flowchart LR
    human([Human supervisor])
    subgraph AF[Agent Factory]
        core[Agent Factory subsystems]
    end
    gh[(GitHub<br/>Issues · PRs · Actions · Releases)]
    model[Model provider<br/>Claude API]
    mcp[MCP servers<br/>GitHub · Playwright · …]
    otel[(Telemetry backend<br/>OTLP)]
    target[(Target repositories)]

    human -- requests, decisions, visual feedback --> gh
    gh -- events --> core
    core -- branches, PRs, comments, status --> gh
    core -- prompts / completions --> model
    core -- tool calls --> mcp
    core -- OTel signals --> otel
    core -- read / write via PR --> target
```

Humans interact with Agent Factory **through GitHub**:

- they open issues;
- they take must-human decisions and give visual feedback in **GitHub Discussions**;
- they can halt agents with a label.

Agents open, review and merge PRs themselves under the merge policy of [ADR-0002](../decisions/ADR-0002-autonomous-merge-and-human-decisions.md). Phase 1 has no separate UI.

## 5. Container view

```mermaid
flowchart TB
    HCC[Human Control Center]
    ORC[Orchestration Engine]
    RT[Agent Runtime<br/>Claude Code]
    CAP[Capability Layer<br/>Skills · MCP · hooks]
    QE[Quality & Evaluation]
    OBS[Observability & Knowledge]
    INF[Engineering Infrastructure]

    HCC -- Work Request --> ORC
    ORC -- Approval Request --> HCC
    ORC -- Task Envelope --> RT
    RT -- Capability Invocation --> CAP
    RT -- Change Set + Evidence --> QE
    QE -- Verdict --> ORC
    QE -- Verdict --> HCC
    RT -. OTel .-> OBS
    ORC -. OTel .-> OBS
    QE -. OTel .-> OBS
    INF --- RT
    INF --- QE
```

Engineering Infrastructure is the substrate under every other subsystem: repository, CI/CD, runners, identity, secrets and sandboxes. Observability & Knowledge receives signals from every subsystem.

## 6. Subsystems

### 6.1 Human Control Center (HCC)

**Responsibilities:**

- Intake of work.
- Human decisions on the must-human list (ADR-0002 §3).
- Visual and UX feedback.
- Configuration of autonomy policies and risk classes.
- Emergency stop.
- Audit visibility.

**Exposes:**

- *Work Request*, as a GitHub issue created from a template.
- Decisions, as comments in GitHub Discussions that follow the decision protocol (ADR-0002 §2).

**Consumes:** *Approval Request* (a Discussion) and *Verdict*.

**Phase 1 implementation:**

- Issue forms.
- GitHub Discussions with the categories **Decisions** (answerable) and **Visual review**, which now exist. Decision threads keep the `[Decision]` title prefix.
- A label taxonomy (`state:*`, `risk:*`, `autonomy:*`, `needs-human`, `agents:halt`).
- Required reviewers on GitHub Environments for production deployments (available because the repository is public).

**Evolution:** a read-only dashboard over GitHub and telemetry data. A dedicated UI only if GitHub proves insufficient.

### 6.2 Orchestration Engine

**Responsibilities:**

- Run the task state machine (§8).
- Decompose work into tasks.
- Route each task to an agent role.
- Enforce budgets (turns, wall-clock time, retries; cost is enforced when the owner sets a limit, none today per D5).
- Apply the effective autonomy level (§13).
- Escalate to humans.

**Exposes:** *Task Envelope* and *Approval Request*.

**Consumes:** *Work Request* and *Verdict*.

**Phase 1 implementation:**

- An orchestrator Claude Code session (orchestrator role) that delegates to specialized subagents.
- GitHub Actions workflows that react to issue and PR events and start runs.
- Task state kept in GitHub labels, plus a machine-readable comment.

**Evolution:** if the native mechanisms hit measured limits (concurrency, durability, cross-repository coordination), introduce a dedicated orchestration service behind the same contracts. Candidates to evaluate first: Claude Code agent teams, dynamic workflows, and the Agent SDK.

### 6.3 Agent Runtime

**Responsibilities:**

- Execute one bounded task inside an isolated workspace, with a role-specific toolset.
- Produce a *Change Set* and *Evidence*.
- Emit telemetry.

**Exposes:** *Change Set + Evidence*.

**Consumes:** *Task Envelope*.

**Phase 1 implementation:** Claude Code.

- Interactive CLI for levels L0–L1.
- Headless mode (`claude -p`) or the Agent SDK for scripted runs.
- `anthropics/claude-code-action@v1` for runs triggered from CI.
- Roles are defined as subagents in `.claude/agents/*.md`.
- One branch, plus a git worktree when running locally, per task.

**Runtime Contract:** any runtime must:

- accept a Task Envelope;
- honor the permission policy;
- deliver changes only through a branch or PR;
- emit OTel signals with the correlation attributes in §14.

This keeps Claude Code replaceable.

### 6.4 Capability Layer

**Responsibilities:** provide agents with knowledge and tools in a governed, least-privilege way.

| Mechanism | Use for | Example |
|---|---|---|
| **Skill** (`.claude/skills/<name>/SKILL.md`) | Procedural know-how: *how* to do something | "write a spec", "add a Playwright test", "prepare a release" |
| **MCP server** | *Access* to an external system | GitHub, Playwright browser automation |
| **Hook** (`settings.json`) | Rules that must *always* hold | Block writes to protected paths; audit tool calls |
| **CLAUDE.md** | Persistent project *context* and conventions | Build commands, code style, architecture links |
| **Subagent** (`.claude/agents/*.md`) | A *role*: prompt, tools, model, isolated context | `implementer`, `reviewer` |

**Governance:**

- MCP servers and Skills are allowlisted and pinned.
- Capabilities change only through PRs under the merge policy.
- New third parties that receive code or data (for example new MCP servers), and any relaxation of guardrails, need a human decision. See [Security Model §11](security-model.md#11-capability-governance).

**Evolution:** package the reusable roles, Skills and hooks as a Claude Code **plugin**, so they can be installed into target repositories.

### 6.5 Quality & Evaluation

**Responsibilities:**

- Turn specs into acceptance tests.
- Run the quality gates.
- Perform independent review.
- Evaluate the agents themselves (EDD, §12).

**Exposes:** *Verdict* (`pass` | `fail` | `needs-human`, plus findings).

**Consumes:** *Change Set + Evidence*.

**Phase 1 quality gates, run by CI:**

"Blocking" means the merge policy and the `guard-merge` hook refuse to merge while the gate fails. The ruleset `protect-main` already exists (PR required, linear history, squash only, no force push or deletion). Required status checks (`docs-check` and `secret-scan` from workflow `ci.yml`) will be added to it once CI exists; until then, blocking on checks is enforced by the merge policy and the hook, not by the server (ADR-0002 §6).

| Gate | Tooling (indicative) | Blocking |
|---|---|---|
| Lint, format, type check | Project-specific | Yes |
| Unit and integration tests, with a coverage threshold | Project-specific | Yes |
| End-to-end tests | Playwright | Yes, for UI-affecting changes |
| Static analysis (SAST) | CodeQL when code in a supported language exists; Semgrep optional | Yes, on high severity |
| Secret detection | GitHub secret scanning with push protection (enabled), plus gitleaks (CI job `secret-scan`, and pre-commit) as defense in depth | Yes |
| Dependency vulnerabilities | Dependabot alerts plus an audit step in CI (for example `npm audit` or `pip-audit`) | Yes, on new high-severity vulnerabilities |
| Spec traceability check | Custom script (the PR references a spec) | Yes |
| Independent AI review | `reviewer` (fresh context); `security-reviewer` for R2–R3 | Yes |
| Visual review | Playwright screenshots in a *Visual review* Discussion; owner's opinion | Yes, for user-facing changes |
| Merge policy | Checklist comment on the PR (ADR-0002 §1) | Yes |

There is no routine human code review. Agents merge when the merge policy is satisfied. Decisions on the must-human list escalate to a Discussion.

### 6.6 Observability & Knowledge

**Responsibilities:**

- Collect correlated telemetry for every run.
- Compute cost and quality metrics.
- Preserve institutional knowledge.

**Phase 1 implementation:**

- **Telemetry:** Claude Code's native OpenTelemetry export, with metrics and events (logs). Distributed traces are beta and opt-in. Prompt content is off by default.
- **Correlation:** shared attributes (§14) on every signal, including CI signals.
- **Knowledge:** ADRs (`docs/decisions/`), specs (`specs/`), `CLAUDE.md`, and a lessons-learned log fed by retrospectives on failed or reverted runs.

**Open:** the telemetry backend (local stack or SaaS) is deferred to a follow-up ADR.

### 6.7 Engineering Infrastructure

**Responsibilities:**

- Provide reproducible execution environments, identity, secrets, CI/CD and branch protection.

**Phase 1 implementation:**

- GitHub repository ruleset `protect-main`, **active** on the default branch with no bypass actors: deletion blocked, force pushes blocked, linear history, PR required (0 approvals), squash only. Required status checks are added once CI exists. The repository is public, with secret scanning, push protection and Dependabot alerts enabled. The compensating controls of ADR-0002 §6 still apply, because agents act through the owner's admin account until the GitHub App exists.
- GitHub Actions on ephemeral runners.
- A dedicated GitHub App identity for agents (interim: the owner's account, ADR-0002 §2 and Security Model §6).
- A devcontainer for local reproducibility.
- OIDC for cloud credentials.
- The Claude Code Bash sandbox on Linux, macOS or WSL2.

## 7. Contracts between subsystems

All contracts are versioned (`contract: <name>/v<major>`). Phase 1 represents them as Markdown with YAML frontmatter, so humans and agents can both read them, plus JSON Schema files under `schemas/` (to be created).

| Contract | From → To | Key fields | Phase 1 carrier |
|---|---|---|---|
| **Work Request** | HCC → ORC | `objective`, `context`, `acceptance_criteria[]`, `risk_class`, `requested_autonomy` | Issue form |
| **Task Envelope** | ORC → RT | `task_id`, `spec_ref`, `role`, `allowed_capabilities[]`, `budget{turns, minutes, cost}`, `autonomy_level`, `workspace{repo, branch}` | Workflow inputs and prompt preamble |
| **Capability Invocation** | RT → CAP | MCP JSON-RPC, Skill load, tool call | Native Claude Code mechanisms, mediated by permissions and hooks |
| **Change Set + Evidence** | RT → QE | `branch`, `pr`, `spec_ref`, `tests_run[]`, `self_assessment`, `open_questions[]` | Pull request body (template) |
| **Verdict** | QE → ORC/HCC | `result`, `findings[]{severity, location, rationale}`, `gates{}` | Check runs and review comments |
| **Approval Request** | ORC → HCC | `action`, `risk_class`, `evidence_refs[]`, `alternatives[]`, `recommendation`, `reversibility` | GitHub Discussion (*Decisions* or *Visual review*), linked from the PR with the `needs-human` label |
| **Telemetry** | All → OBS | OTel signals plus the attributes in §14 | OTLP |

Role manifests (§9) and these contracts are designed so they can later be published as **A2A Agent Cards** (§16).

## 8. Task lifecycle

```mermaid
stateDiagram-v2
    [*] --> Intake
    Intake --> Triaged: orchestrator classifies risk
    Triaged --> Specified: planner drafts spec
    Specified --> Planned: reviewer agent approves spec
    Specified --> AwaitingHuman: must-human decision
    Planned --> Implementing
    Implementing --> Verifying: change set ready
    Verifying --> Implementing: gate failed (within retry budget)
    Verifying --> InReview: all gates green
    InReview --> Implementing: changes requested
    InReview --> Merged: merge policy satisfied (agent merges)
    InReview --> AwaitingHuman: must-human decision or visual review
    AwaitingHuman --> InReview: ⛔ human decides (PR stage)
    AwaitingHuman --> Planned: ⛔ human decides (spec stage or escalation)
    AwaitingHuman --> Implementing: ⛔ human requests changes
    Merged --> Released: agent releases (⛔ production or public release)
    Released --> [*]
    Implementing --> Escalated: budget exhausted / blocked
    Verifying --> Escalated: retry budget exhausted
    Escalated --> AwaitingHuman
    AwaitingHuman --> [*]: ⛔ human cancels
```

⛔ marks a human decision, taken in a GitHub Discussion following the protocol in ADR-0002 §2. Every other transition is performed by agents.

A human decision never merges a PR by itself. After the decision, the PR returns to `InReview`, and the full merge policy (checks, independent review, checklist) still applies.

## 9. Agent model

**Initial role catalog:**

| Role | Purpose | Key tools | Writes code |
|---|---|---|---|
| `orchestrator` | Triage, decomposition, routing, budget tracking | Agent (delegation), GitHub | No |
| `planner` | Draft spec and task plan from a Work Request | Read, search, GitHub | Specs only |
| `implementer` | Implement one task on its branch | Read, Edit, Bash (sandboxed) | Yes |
| `test-author` | Derive tests from acceptance criteria | Read, Edit, Bash, Playwright MCP | Tests only |
| `reviewer` | Independent code review against spec and standards | Read-only | No |
| `security-reviewer` | Security-focused review | Read-only | No |
| `docs` | Documentation updates | Read, Edit (docs paths) | Docs only |

**Delegation depth:** Claude Code allows nested subagents, with a configurable maximum depth (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`, default 3 at the time of writing). By policy, phase 1 uses a **depth of 1**: only `orchestrator` holds the Agent tool, and worker roles cannot delegate further. This keeps runs auditable and costs bounded. Raising the depth requires an ADR and a human decision (H1).

**Independence:** `reviewer` runs in a fresh context. It never sees the implementer's reasoning, only the spec, the diff and the evidence. It can be configured to use a different model.

**Model selection:** each role's model is configuration, not code. **Model policy** (owner decision D5, [Discussion #3](https://github.com/albergm02/agent-factory/discussions/3)): Opus 5.5 is used only for the `orchestrator` role. All other roles use the cheapest adequate model (Sonnet 5.5 or Haiku 5.5). Opus 5.5 is forbidden for every other role. There are no numeric USD budget caps. Use Sonnet 5.5 where reasoning quality matters (for example `planner`, `implementer`, `reviewer`, `security-reviewer`) and Haiku 5.5 for simple, mechanical roles, as long as the evals show it is adequate.

## 10. Capability selection guide

```
Must it ALWAYS happen or NEVER happen?  → hook / permission rule / CI gate / ruleset
Does the agent need to reach an external system?  → MCP server (allowlisted)
Is it a repeatable procedure or know-how?  → Skill
Is it a stable fact or convention about this project?  → CLAUDE.md
Is it a distinct responsibility with its own tools and context?  → subagent role
```

## 11. Spec-Driven Development (SDD)

The spec is the source of truth for intent. Every change is traced from a spec to tests.

```
specs/<id>-<slug>/
  requirements.md   # user stories + acceptance criteria (Given/When/Then)
  design.md         # approach, affected components, risks (optional for R0)
  tasks.md          # ordered, independently verifiable tasks
```

**Rules:**

1. Implementation does not start until the reviewer agent approves the spec. A spec that involves a must-human decision (ADR-0002 §3) also needs the human decision.
2. Every PR references exactly one spec and the task IDs it implements.
3. Every acceptance criterion maps to at least one automated test. CI checks the mapping.
4. Specs change through PRs like code. Divergence between spec and code counts as a defect.

The format is kept minimal and compatible with existing SDD tooling (for example GitHub Spec Kit), so adopting such a tool later stays cheap.

## 12. Evaluation-Driven Development (EDD)

Agents, Skills and prompts are software. They are developed against evaluations.

```
evals/
  roles/<role>/        # golden tasks per agent role
  skills/<skill>/      # golden cases per Skill
  datasets/            # fixtures and seed repositories
```

- **When evals run:** in CI, on any change to `.claude/agents/`, `.claude/skills/`, `CLAUDE.md`, hooks or model configuration, and on a schedule to detect model drift.
- **Metrics:**
  - task success rate (pass@1 and pass@k);
  - gate pass rate on the first attempt;
  - rework rate;
  - review precision and recall (on seeded defects);
  - cost and time per task;
  - escaped defects (found after merge).
- **Regression policy:** a change that lowers a role's success rate below its threshold cannot be merged.
- **Link to autonomy:** eval results decide which autonomy level each role has earned (§13).
- **Tooling (to be evaluated):** Claude Code's plugin evaluation (`claude plugin eval`) for Skills and roles, plus a custom harness for end-to-end tasks.

## 13. Autonomy levels and risk classes

**Autonomy levels:**

| Level | Name | Agent may | Human must |
|---|---|---|---|
| L0 | Advisor | Read and propose | Do everything |
| L1 | Assisted | Make local changes; each effectful action is approved | Approve each action |
| L2 | Supervised | Create branches and PRs, run CI | Approve the spec and the merge |
| L3 | Conditional | Approve specs and merge PRs when the merge policy is satisfied | Take must-human decisions; give visual feedback; audit after the fact |
| L4 | Autonomous | Also deploy to production and publish | Out of scope (production and public releases are must-human) |

**Risk classes** (assigned at triage; the highest applicable class wins):

| Class | Examples |
|---|---|
| R0 | Docs, comments, tests only |
| R1 | Application code covered by tests |
| R2 | Dependencies, data schemas, public APIs, performance-sensitive paths |
| R3 | Security, authentication, CI/CD, infrastructure, data deletion or migration, and any guardrail file (the single list in [ADR-0002 §5](../decisions/ADR-0002-autonomous-merge-and-human-decisions.md#5-guardrail-change-handling-h1)) |

**Effective autonomy** = `min(ceiling for the risk class, level earned by the role through evals, level requested in the Work Request)`.

- The **phase 1 ceiling is L3** for every class ([ADR-0002](../decisions/ADR-0002-autonomous-merge-and-human-decisions.md)). The owner granted this level provisionally, before eval data existed. Until the F1 CI exists, L3 applies only to owner-attended interactive sessions (ADR-0002 §7).
- **Demotion is evidence-based:** a role whose evals regress, or that causes an escaped defect or a guardrail incident, drops to L2 until the cause is fixed.
- Risk class still matters: R2–R3 changes need a `security-reviewer` pass, and R3 guardrail changes follow ADR-0002 §5.
- The decisions that always need a human are listed in [Security Model §13](security-model.md#13-autonomy-and-human-approval-matrix).

## 14. Observability

**Signals:**

- Claude Code native OTel export: metrics (tokens, cost, sessions, lines changed, tool decisions) and events (tool results, API requests).
- Optional traces (beta).
- CI job telemetry.

**Correlation attributes** (resource or span attributes on every signal):

| Attribute | Example |
|---|---|
| `af.task.id` | `GH-123` |
| `af.spec.id` | `0007-login-rate-limit` |
| `af.agent.role` | `implementer` |
| `af.run.id` | GitHub Actions run ID or local UUID |
| `af.autonomy.level` | `L2` |
| `af.risk.class` | `R1` |
| `vcs.repository.name`, `vcs.ref.head.name` | Repository and branch |

**Conventions:**

- Follow the OpenTelemetry GenAI semantic conventions (`gen_ai.*`) where they apply.
- Those conventions are still in development, so pin the version used and review it when upgrading.

**Key metrics (dashboards):**

- Cost per task and per role.
- Success rate by role and risk class.
- Time from intake to merge.
- Number of human interventions per task.
- Escaped defects.
- Reverted PRs.

**Privacy:** collecting prompt text, tool details and tool content is **off** by default. See [Security Model §14](security-model.md#14-data-and-privacy).

## 15. Knowledge management

| Artifact | Location | Owner | Updated when |
|---|---|---|---|
| Architecture decisions | `docs/decisions/ADR-NNNN-*.md` (MADR) | Agents draft and accept; humans decide those on the must-human list | Any significant or irreversible decision |
| Architecture docs | `docs/architecture/` | Agents, under the merge policy | When an ADR changes the architecture |
| Specs | `specs/` | Planner drafts, reviewer agent approves | Per feature |
| Project context | `CLAUDE.md` | Agents, under the merge policy | When conventions change |
| Lessons learned | `docs/lessons/` | Orchestrator drafts, reviewer agent approves | After failed, escalated or reverted runs |

Persistent instructions such as `CLAUDE.md` and Skills change only through reviewed PRs. Reviewers check them for injected instructions, which guards against context poisoning. Changes that relax guardrails escalate to a human.

## 16. Future interoperability: A2A

Agent2Agent (A2A) reached v1.0 in 2026. Agent Factory **does not implement A2A in phase 1**, but stays compatible with it:

- Each role manifest (name, description, skills, inputs, outputs, auth requirements) maps directly onto an A2A **Agent Card**.
- The task lifecycle (§8) maps onto A2A task states.
- Contracts are transport-independent JSON-serializable documents.

A2A support will be considered when an external agent, or a second runtime, must collaborate with Agent Factory. It requires its own ADR and a security review of the inter-agent trust boundaries.

## 17. Proposed repository layout

```
.claude/
  agents/            # role definitions (subagents)
  skills/            # Skills
  settings.json      # shared permissions and hooks (protected)
.github/
  DISCUSSION_TEMPLATE/  # Decision and visual-review forms
  ISSUE_TEMPLATE/    # Work Request forms
  workflows/         # CI gates and agent triggers (protected)
  CODEOWNERS
  pull_request_template.md
docs/
  architecture/      # this document, security model
  decisions/         # ADRs
  lessons/
evals/               # EDD suites
schemas/             # contract JSON Schemas
specs/               # SDD specs
CLAUDE.md
```

## 18. Roadmap

| Phase | Goal | Exit criteria |
|---|---|---|
| **F0 Foundations** | Architecture, security model, ADR-0001 and ADR-0002 accepted | Documents merged |
| **F1 Vertical slice** | One issue → spec → PR → gates → independent review → agent merge, at L3, with human decisions via Discussions; CI and the compensating controls of ADR-0002 §6 | 10 tasks completed end to end; metrics visible; no guardrail bypass; no escaped critical defect |
| **F2 Evidence** | Eval suites per role; data-driven demotion and promotion | Eval thresholds met and stable across 2 model updates |
| **F3 Scale** | Plugin packaging, multiple repositories, orchestration service if needed, A2A if needed | Decided by ADRs based on F1 and F2 data |

## 19. Glossary

| Term | Definition |
|---|---|
| **ADR** | Architecture Decision Record |
| **A2A** | Agent2Agent protocol for inter-agent communication |
| **Agent Card** | A2A document that describes an agent's identity, capabilities and endpoints |
| **EDD** | Evaluation-Driven Development |
| **Gate** | A check that must pass, automated or human, before a lifecycle transition |
| **Hook** | Deterministic script that Claude Code runs on lifecycle events (for example `PreToolUse`) |
| **MCP** | Model Context Protocol, a standard for connecting agents to tools and data |
| **OTel** | OpenTelemetry |
| **Role** | An agent specialization, implemented as a Claude Code subagent |
| **SDD** | Spec-Driven Development |
| **Skill** | A packaged, reusable set of instructions and resources that Claude loads on demand |
