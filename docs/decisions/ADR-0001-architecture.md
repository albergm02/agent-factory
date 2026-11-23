# ADR-0001: Claude Code–native, GitHub-controlled layered architecture

| | |
|---|---|
| **Status** | Accepted. Amended by [ADR-0002](ADR-0002-autonomous-merge-and-human-decisions.md) (D-1, TD-02, TD-09, TD-11, TD-12, TD-13, Consequences, Validation) |
| **Date** | 2026-11-23 |
| **Decision makers** | Project owner |
| **Related** | [System Overview](../architecture/system-overview.md) · [Security Model](../architecture/security-model.md) |

## Context and problem statement

Agent Factory aims to maximize the autonomy and quality of AI-driven software engineering while keeping humans in control of critical decisions (see the [README](../../README.md)). Before any agent is built, the project needs an architecture that:

- organizes the system into seven subsystems with clear responsibilities: Human Control Center, Orchestration Engine, Agent Runtime, Capability Layer, Quality & Evaluation, Observability & Knowledge, and Engineering Infrastructure;
- delivers value quickly, without building a platform first;
- enforces safety deterministically, not through model compliance;
- avoids locking the project into decisions that are hard to reverse, given how fast agent tooling and protocols are changing (MCP, A2A, Claude Code itself).

**Question:** what architectural approach and initial technology choices should Agent Factory adopt?

## Decision drivers

- **D-1 Human control:** critical actions must be gated by humans, using mechanisms that agents cannot bypass. *Amended by ADR-0002:* "critical" now means the must-human list H1–H11. Mechanisms that agents cannot bypass are a target that requires the GitHub App identity and server-side rulesets; see ADR-0002 §6.
- **D-2 Quality:** every change must be specified, tested and independently reviewed.
- **D-3 Time to first value:** a working end-to-end vertical slice should be possible within weeks.
- **D-4 Traceability:** every change must be traceable from request to release.
- **D-5 Portability:** the design must stay independent of any target project and allow the agent runtime to be replaced.
- **D-6 Operating cost:** a small team must be able to operate it, with no custom infrastructure to maintain.
- **D-7 Security:** least privilege, isolation and auditability by default.

## Considered options

### Option A: custom orchestration platform from day one

Build a dedicated service, using an agent framework, a database and a queue, that orchestrates LLM calls and tools directly, together with a custom UI for approvals.

- **Pros:**
  - Full control over the orchestration logic and state.
  - No dependency on a specific agent product.
- **Cons:**
  - Months of platform work before delivering value (D-3).
  - Re-implements capabilities that already exist: tool use, context management, permissions, sandboxing.
  - A second control plane competes with GitHub (D-4, D-6).
  - Larger attack surface to secure (D-7).

### Option B: Claude Code–native runtime, GitHub as the control plane, runtime-agnostic contracts (**chosen**)

- Use Claude Code (subagents, Skills, hooks, permissions, sandbox, headless mode, Agent SDK, GitHub Action) as the execution plane.
- Use GitHub (issues, PRs, rulesets, Actions, Environments) as the system of record and approval plane.
- Define the interfaces between subsystems as versioned contracts, so that individual pieces can be replaced later.

- **Pros:**
  - Fastest route to value (D-3).
  - Human gates rely on GitHub controls that already exist and are well understood (D-1, D-4).
  - Mature, deterministic guardrails: hooks, permission rules, the sandbox (D-7).
  - No custom infrastructure (D-6).
- **Cons:**
  - Partial vendor dependency on Claude Code and GitHub (D-5), mitigated by the contracts.
  - Orchestration durability and concurrency are limited by Actions and session semantics.
  - Claude Code evolves quickly, so features and defaults change.

### Option C: managed commercial agent platform

Adopt a hosted autonomous-engineering product.

- **Pros:**
  - Minimal setup.
- **Cons:**
  - Limited control over guardrails, evaluation and telemetry (D-1, D-7).
  - Opaque internals make independent quality evaluation hard (D-2).
  - Strong lock-in (D-5).
  - Conflicts with the goal of building a reusable architecture of our own.

## Decision outcome

**Chosen option: B.** It best satisfies D-1, D-3, D-4, D-6 and D-7. Its main weakness, portability (D-5), is reduced by contracts, OpenTelemetry and A2A-compatible role manifests.

The decision includes the following technical decisions:

| ID | Decision | Notes |
|---|---|---|
| TD-01 | **Claude Code is the initial Agent Runtime**, behind a *Runtime Contract* (Task Envelope in; Change Set, Evidence and OTel out). | Modes: interactive CLI (L0–L1), headless `claude -p` and the Agent SDK, `anthropics/claude-code-action@v1` in CI. |
| TD-02 | **GitHub is the system of record and the control plane** in phase 1. | Issues = Work Requests, labels = state, PRs = change sets, reviews and environments = approvals. No custom database. *Amended by ADR-0002:* human decisions are taken in GitHub Discussions. |
| TD-03 | **Hierarchical orchestration, delegation depth 1.** One `orchestrator` role delegates to specialized subagent roles (`.claude/agents/`). Actions workflows trigger runs. | Claude Code supports deeper nesting (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`); we cap depth at 1 by policy for auditability and cost. A dedicated orchestration service is deferred until measured limits justify it. |
| TD-04 | **Capability selection rule:** Skills for know-how, MCP for access to external systems, hooks, permissions and CI for mandatory rules, `CLAUDE.md` for context. | No mandatory rule is enforced by a prompt alone. |
| TD-05 | **MCP servers are allowlisted, pinned and reviewed.** Initial set: GitHub and Playwright. Each new server needs a short ADR. | The supported MCP protocol version is pinned (current specification `2026-07-28`). |
| TD-06 | **A2A is not implemented in phase 1**, but role manifests and contracts are designed to map onto A2A Agent Cards and task states. | A2A v1.0 is stable. Adoption requires an ADR and a security review. |
| TD-07 | **Spec-Driven Development:** specs in `specs/<id>-<slug>/` (requirements with Given/When/Then acceptance criteria, design, tasks). A spec is approved before implementation, and every PR references it. | The format stays compatible with existing SDD tooling (for example GitHub Spec Kit). |
| TD-08 | **Evaluation-Driven Development:** `evals/` holds golden tasks per role and per Skill. They run in CI on any change to agents, Skills, prompts or model configuration, and on a schedule. Results decide earned autonomy. | Candidate tooling: `claude plugin eval` plus a custom end-to-end harness. |
| TD-09 | **Quality gates as code** (required status checks): lint, types, unit and integration tests with coverage, Playwright E2E, CodeQL, secret scanning, dependency review, spec traceability. AI review is advisory; human code-owner review blocks. | Thresholds are defined per target project. *Amended by ADR-0002:* independent AI review blocks; there is no routine human code review, only visual review of user-facing changes. |
| TD-10 | **OpenTelemetry is the only telemetry standard.** Claude Code's native export (metrics, events, and traces in beta) with common `af.*` correlation attributes and the GenAI semantic conventions where applicable. | Backend chosen in a follow-up ADR. Content logging is off by default. |
| TD-11 | **Isolation:** one branch (plus a worktree or container) per task; Bash sandbox enabled; autonomous runs only on ephemeral runners or in containers. | The sandbox does not support native Windows; use WSL2 or containers. *Amended by ADR-0002 §7:* owner-attended interactive sessions may operate at L3 until the F1 CI exists. |
| TD-12 | **Agent identity:** a dedicated GitHub App with minimal permissions. No personal tokens. | Keeps authorship separate. *Amended by ADR-0002:* until the App exists, agents use the owner's account and mark their comments with `🤖 Agent Factory:`. Creating the App is a human decision. |
| TD-13 | **Autonomy model:** levels L0–L4 × risk classes R0–R3. Effective level = min(class ceiling, earned, requested). Phase 1 ceiling: L2 for all classes; R3 is capped at L2 permanently. | Details in the System Overview (§13) and the Security Model (§13). *Amended by ADR-0002:* ceiling L3 (agents merge under the merge policy) for all classes; the decisions H1–H11 always escalate to a human. |
| TD-14 | **Model per role is configuration**, not code. The reviewer may use a different model or configuration for independence. | Avoids hard-coding model IDs into agent definitions. |
| TD-15 | **Docs-as-code:** Markdown, MADR-format ADRs, Mermaid diagrams, C4 levels 1–2. | |

### Consequences

**Positive:**

- An end-to-end vertical slice (issue → spec → PR → gates → human merge) can be built without custom infrastructure. *Amended by ADR-0002:* the slice ends in an agent merge.
- Guardrails rely on mechanisms enforced outside the model: rulesets, CODEOWNERS, hooks, the sandbox and permissions. *Amended by ADR-0002:* rulesets are unavailable on the current plan, and CODEOWNERS is used for notification only.
- Humans work in a familiar tool (GitHub), and every action has an audit trail there.
- Autonomy can grow incrementally, backed by evaluation data rather than opinion.

**Negative and accepted trade-offs:**

- **Vendor coupling** to Claude Code and GitHub. Accepted. Mitigated by TD-01 (Runtime Contract), TD-06 and TD-10.
- **Orchestration limits:** long-running, highly concurrent or cross-repository workflows may outgrow Actions plus sessions. Revisit at F3.
- **Platform churn:** Claude Code, MCP and A2A change quickly. Mitigated by pinning versions, recording verification dates and quarterly reviews.
- **GitHub plan dependency:** some controls (rulesets on private repositories, code scanning, secret scanning) depend on the GitHub plan. *Confirmed 2026-11-23:* the repository is private on GitHub Free, so these controls are unavailable. ADR-0002 §6 defines the compensating controls.

### Validation

The decision is considered validated when phase F1 (vertical slice at L2 on a pilot repository) meets all of the following:

- 10 tasks completed end to end with human approval at every gate;
- zero guardrail bypasses (no unauthorized push, protected-path edit or secret read) in audit logs;
- telemetry shows cost, duration and success rate per task and per role;
- no critical rework of the contracts defined in the System Overview §7.

If F1 shows that Option B cannot meet these criteria, this ADR is superseded.

*Amended by ADR-0002:* F1 runs at **L3**. The first criterion becomes "10 tasks completed end to end and merged by agents under the merge policy, with every must-human decision taken in a Discussion". A further criterion is added: no escaped critical defect.

## Follow-up decisions

| ADR | Topic |
|---|---|
| [ADR-0002](ADR-0002-autonomous-merge-and-human-decisions.md) | Agent-merged PRs and human decisions via GitHub Discussions (**accepted**) |
| ADR-0003 | Contract schemas (Work Request, Task Envelope, Change Set, Verdict) and their versioning |
| ADR-0004 | Telemetry backend (local OTLP stack vs. SaaS) and retention policy |
| ADR-0005 | Initial MCP servers (GitHub MCP vs. `gh` CLI; Playwright MCP) |
| ADR-0006 | Spec format and tooling (custom minimal format vs. adopting an SDD toolkit) |
| ADR-0007 | Evaluation harness and autonomy-promotion and demotion thresholds |
| ADR-0008 | Distribution model: in-repo configuration vs. Claude Code plugin for target repositories |

## Open questions

These questions need a human decision. Defaults apply until they are resolved.

| # | Question | Default until resolved |
|---|---|---|
| Q1 | Does Agent Factory operate only on this repository, or as a reusable kit installed into other repositories? | Design as a reusable kit and validate on one pilot repository |
| Q2 | Where do autonomous runs execute: a local Windows machine, GitHub Actions, or the cloud? | **Resolved ([Discussion #3](https://github.com/albergm02/agent-factory/discussions/3), D4):** GitHub Actions and containers. Interim exception in ADR-0002 §7 |
| Q3 | How many human approvers are there? | **Resolved (ADR-0002):** one owner, who decides only H1–H11 decisions and visual matters |
| Q4 | Which GitHub plan applies? Does it support rulesets, secret scanning and code scanning on private repositories? | **Resolved:** GitHub Free, private repository, so no rulesets or branch protection. Whether to go public or upgrade is a human decision (ADR-0002 §6) |
| Q5 | How is the model accessed (API key or subscription), and what data-retention terms apply? Is there code that must not be sent? | **Partly resolved (Discussion #3, D6):** an API key stored as an Actions secret. Still open: data-retention terms and code that must not be sent; default: no sensitive repositories in F1 |
| Q6 | What are the budget limits per task and per month? | **Pending confirmation (Discussion #3, D5).** Proposed: 2 USD per task, 50 USD per month |
| Q7 | Should the documentation language stay English? | English, consistent with the README |

## References

Verified on 2026-11-23:

- Claude Code documentation: [subagents](https://code.claude.com/docs/en/sub-agents), [skills](https://code.claude.com/docs/en/skills), [hooks](https://code.claude.com/docs/en/hooks), [permissions](https://code.claude.com/docs/en/permissions), [sandboxing](https://code.claude.com/docs/en/sandboxing), [monitoring (OpenTelemetry)](https://code.claude.com/docs/en/monitoring-usage), [GitHub Actions](https://code.claude.com/docs/en/github-actions)
- Model Context Protocol: [versioning](https://modelcontextprotocol.io/specification/versioning), [2026-07-28 specification announcement](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- Agent2Agent protocol: [a2aproject/A2A](https://github.com/a2aproject/A2A), [Linux Foundation announcement](https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year)
- OpenTelemetry: [GenAI semantic conventions (attribute registry)](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)
- [MADR: Markdown Architectural Decision Records](https://adr.github.io/madr/)
