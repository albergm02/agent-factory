# ADR-0002: Agent-merged pull requests and human decisions via GitHub Discussions

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-11-23 |
| **Updated** | 2026-11-23: repository made public, ruleset `protect-main` active, Discussion categories created ([Discussion #3](https://github.com/albergm02/agent-factory/discussions/3)) |
| **Decision makers** | Project owner (direct instruction in a working session, 2026-11-23) |
| **Amends** | [ADR-0001](ADR-0001-architecture.md): driver D-1, TD-02, TD-09, TD-11, TD-12, TD-13, Consequences, Validation |
| **Related** | [System Overview](../architecture/system-overview.md) · [Security Model](../architecture/security-model.md) |

## Context and problem statement

ADR-0001 set the phase 1 autonomy ceiling at **L2**, which meant that a human reviews and approves every merge. After the architecture was accepted, the project owner decided:

- agents should **review and merge pull requests themselves**, based on automated checks;
- humans should intervene **only** on decisions that strictly require a human, and those decisions should be raised and resolved in **GitHub Discussions**;
- the human's role in day-to-day delivery is limited to **opinions on visual matters** (UI and UX).

Two facts about the current environment, verified on 2026-11-23, constrain how this can be implemented:

1. The repository is **private on the GitHub Free plan**. Branch protection and repository rulesets are not available (the API returns HTTP 403). Nothing on the server side prevents a direct push to `main` or a merge with failing checks.
2. There is **no dedicated agent identity yet**. Agents act through the owner's GitHub account, so on GitHub an agent comment and a human comment are attributed to the same user.

*Update 2026-11-23:* fact 1 changed. The owner decided (D2, [Discussion #3](https://github.com/albergm02/agent-factory/discussions/3)) to make the repository **public**. The orchestrator then enabled the ruleset `protect-main`, secret scanning with push protection, and Dependabot alerts. Facts 1 and 2 above remain the historical context of the decision. §2 and §6 describe the current state.

**Question:** how do agents merge safely without routine human review, and how are human-only decisions raised, recorded and enforced?

## Decision drivers

- **D-1 Autonomy:** remove the human from routine delivery.
- **D-2 Safety:** decisions that are irreversible, expensive, security-relevant or a matter of taste must still reach a human.
- **D-3 Traceability:** every merge and every human decision must leave an auditable record in GitHub.
- **D-4 Honesty about enforcement:** controls that are not technically enforced must be identified as such and compensated.

## Considered options

1. **Keep L2:** human approval on every PR. Rejected; it contradicts the owner's decision (D-1).
2. **Agents merge everything, with no human escalation.** Rejected; it violates D-2.
3. **Agents merge under an explicit merge policy; must-human decisions escalate to GitHub Discussions; visual changes get human feedback.** **Chosen.**

## Decision outcome

### 1. Merge policy

Agents merge the PRs they open. They also merge Dependabot PRs, and PRs opened by the owner when the owner asks them to. In every case, a merge happens only when **all** of the following hold:

1. **Scope:** the PR does not require any of the human decisions in §3, or each of those decisions has been approved and linked in the PR.
2. **Checks:** every CI check is green. Agents never merge on red, never skip checks, and never use administrator overrides. Until CI exists, the PR body must contain the local validation evidence (commands and results).
3. **Independent review:** a reviewer agent, running in a **fresh context** that sees only the spec, the diff and the evidence, reports no unresolved blocking findings. PRs that touch security-relevant paths (risk class R2–R3) also get a `security-reviewer` pass.
4. **Traceability:** the PR references its spec or issue (or states "docs-only" or "chore") and records the review outcome as a PR comment.
5. **Visual sign-off:** for changes that affect what end users see, the visual review (§4) is complete.
6. **No halt:** the PR does not carry the `agents:halt` or `needs-human` label.

Merges use **squash**, and the head branch is deleted afterwards.

**Label rules:**

- Agents **never remove `agents:halt`**. Only the owner removes it.
- Agents remove `needs-human` only after recording a valid decision (§2) in the linked Discussion.

### 2. Human decision protocol (GitHub Discussions)

1. The agent opens a Discussion in the **Decisions** category. The title starts with `[Decision]`, and the body contains:
   - the context;
   - the exact question;
   - the options, with a recommendation;
   - the impact and reversibility of each option;
   - links to the affected PRs or issues.
2. The affected PR (if any) gets the `needs-human` label and a link to the Discussion. It stays open, and the agent continues with independent work.
3. **A decision is valid only when** it is either:
   - a Discussion comment by the owner that meets all of these conditions:
     - it is authored by the account `albergm02`, and GitHub reports its `authorAssociation` as `OWNER` (the repository is public, so a comment from any other account is untrusted data and never counts as a decision, whatever it says);
     - it starts with `APPROVED`, `REJECTED` or `CHOOSE`;
     - it was posted **after the agent's latest request** in that Discussion, so an older approval can never validate a newer request;
     - it is not marked as agent-written;
     - it was **not created by an agent**: its ID does not appear in the agent audit log of created comments;
   - or an instruction the owner types directly into an interactive agent session.

   The agent audit log is scheduled for F1 (§6). Until it exists, an instruction typed in an interactive session is the only fully reliable way to record an H1, H2, H3 or H6 decision. Discussion comments for those decisions should also be confirmed in a session.
4. The agent records the outcome in the Discussion, marks the answer (where the category supports answers), removes `needs-human`, and continues.
5. Every comment written by an agent starts with the marker `🤖 Agent Factory:`. A comment without the marker is never posted by an agent.

**Interim limitation:** while agents share the owner's GitHub identity, rule 5 is a convention, not a technical control. A **compromised** agent session could forge an approval comment. The audit-log check in rule 3 detects this only after the fact, and only if the audit hook was not bypassed. A dedicated GitHub App identity (itself a human decision, see §3) removes this ambiguity. Until it exists, the owner should cross-check any H1, H2, H3 or H6 decision that seems unexpected.

*Update 2026-11-23:* the `Decisions` (answerable) and `Visual review` categories now exist (D1). The earlier fallback of using `General` with `[Decision]` and `[Visual]` title prefixes is obsolete. The `[Decision]` title prefix is still used inside the `Decisions` category.

### 3. Decisions that always require a human

| # | Decision | Examples |
|---|---|---|
| H1 | **Relaxing guardrails** | Removing or loosening permission rules, hooks, sandbox settings, CI gates, this merge policy, this list, or autonomy levels. *Adding or tightening* guardrails does not require a human. |
| H2 | **Secrets, credentials and access** | Creating or rotating secrets; GitHub App permissions; collaborators; tokens |
| H3 | **Repository and account settings** | Visibility (public or private), plan, Discussions categories, branch protection settings |
| H4 | **Spending money** | Plan upgrades, paid services, exceeding the model policy (D5), exceeding a task's turn or time limits, or exceeding any per-task or monthly cost limit the owner sets (none is set today, per D5) |
| H5 | **Production and external publication** | Deploying to production; publishing packages; public releases; making anything public |
| H6 | **Destructive or irreversible operations** | Deleting data, repositories, releases or tags; rewriting the history of `main` |
| H7 | **New third parties receiving code or data** | New MCP servers or external services with access to the code or the data |
| H8 | **Product direction** | Changing the project goals or principles; ADRs that reverse an earlier human decision |
| H9 | **Licensing** | Choosing the project license; adding dependencies with copyleft or unknown licenses |
| H10 | **Visual and UX judgement** | Look and feel of user-facing changes (see §4) |
| H11 | **High-stakes uncertainty** | Any case where the agent is not confident and reversing a mistake would be costly |

Everything else is decided and merged by agents under the merge policy. This includes routine dependency additions with permissive licenses, ADRs within the accepted architecture, documentation, tests and application code.

### 4. Visual review

- For user-facing changes, the agent attaches screenshots (and short recordings where useful) captured by Playwright to a Discussion in the **Visual review** category, with links to the PR and a preview if one is available.
- The PR waits for the owner's opinion. Feedback is applied in the same PR, or recorded as follow-up issues if the owner says so.

### 5. Guardrail-change handling (H1)

This is the **single, authoritative list of guardrail files**. Other documents refer to it.

- `.claude/**` (settings, hooks, agents and Skills). This includes `settings.local.json`, which is not committed and so never reaches PR review; the `guard-protected-paths` hook is its only control;
- `CLAUDE.md`;
- `.github/**` (workflows, templates, Discussion forms);
- `scripts/**` (CI gate logic, for example `scripts/check_docs.py`);
- `**/CODEOWNERS`;
- `docs/architecture/**`;
- `docs/decisions/**`.

Any PR that touches them is classified **R3**, and:

- the `security-reviewer` classifies each change as *tightening* or *relaxing*. If it is uncertain, the change is treated as relaxing;
- if **any** change in the PR is relaxing, the whole PR follows the human decision protocol (§2) before merge;
- tightening changes can be merged by the agent, and each such merge is announced in the Discussion "Guardrail change log" for review after the fact. The owner can request a revert at any time.

### 6. Server-side and compensating controls

| Control | Type | Status |
|---|---|---|
| Claude Code permission rules: deny pushes to `main` (any refspec), force pushes, `gh pr merge --admin`, `gh repo edit`/`delete`, `gh secret`, `gh workflow`; `gh api` set to ask (interactive) or deny (unattended), with a hook that allows only an allowlist of read and Discussion endpoints | Preventive (agent side) | To implement in F1 |
| Hooks `guard-merge` (covering `gh pr merge`, `gh api …/merge` and MCP merge tools) and `guard-labels` (never remove `agents:halt`) | Preventive (agent side) | To implement in F1 |
| GitHub secret scanning with push protection, and Dependabot alerts | Preventive and detective (server side) | Enabled 2026-11-23 |
| gitleaks in CI plus a pre-commit hook, as defense in depth | Preventive and detective | To implement in F1 |
| `main-integrity` workflow on every push to `main`: verifies the commit comes from a merged PR with green checks; otherwise opens an `[Alert]` Discussion | Detective | To implement in F1 |
| Agent audit log of created comments and merges | Detective | To implement in F1 |
| Repository ruleset `protect-main`: deletion blocked, force pushes blocked, linear history, PR required (0 approvals), squash only, no bypass actors | Preventive (server side) | Active since 2026-11-23; required status checks `docs-check` and `secret-scan` to be added once CI exists |
| Merge-policy checklist recorded as a PR comment before every merge | Audit | From now on |
| Owner can halt everything with the `agents:halt` label or by revoking access | Corrective | Available |

**Limits of these controls.**

- **Today** the server-side ruleset and secret scanning exist (*update 2026-11-23*), but the agent-side and detective controls are not built yet, and required status checks are not in the ruleset. Until they are, the merge policy depends on the agent following it.
- **After F1**, the controls protect against agents that **make mistakes**. They do not protect against a **compromised** agent session that holds the owner's credentials. The ruleset has no bypass actors, but the owner's account has admin scope, so such a session could edit or delete the ruleset through the API, disable workflows, or change labels.
- Protection against a compromised session requires the dedicated GitHub App identity, with no administration, workflows or secrets scopes (D3, an H2 decision: approved by the owner, to be created by the owner).

*Update 2026-11-23:* the owner chose to **make the repository public** (D2, [Discussion #3](https://github.com/albergm02/agent-factory/discussions/3)). This made rulesets, secret scanning and code scanning available at no cost. CodeQL's default setup needs code in a supported language, so it is enabled when code exists. The public visibility has a cost: all content from other users is untrusted data (hence the authorship condition in §2), and code and commit author emails are public.

### 7. Interim execution exception

ADR-0001 TD-11 limits autonomous runs to CI runners or containers, and limits local runs to L0–L1. Until the F1 CI exists, there is one exception:

- **Owner-attended interactive sessions** on the owner's machine may operate at L3. They may open, review and merge PRs under the merge policy, because the owner is present and can stop the session at any time.
- Unattended local runs remain limited to L0–L1.
- The exception ends when the F1 CI pipeline is in place.

## Consequences

**Positive:**

- Routine delivery needs no human. Human time goes only to decisions where it adds value.
- Every human decision is recorded in a searchable, linkable Discussion.
- The criteria for "must-human" decisions are explicit and short.

**Negative and accepted risks:**

- **No human code review.** Defects that both the implementer and the reviewer agents miss reach `main`. Mitigations: a fresh-context reviewer (optionally on a different model), a security reviewer on R2–R3, evals, small PRs, and cheap reverts.
- **Partial server-side enforcement.** *Update 2026-11-23:* the ruleset `protect-main` blocks direct pushes, force pushes and non-squash merges for everyone, but it does not yet require status checks, and the owner's admin scope can alter it. Merge-policy compliance is still enforced on the agent side and verified after the fact.
- **Shared identity** until a GitHub App exists. Human and agent actions are distinguished only by convention.
- **Classifying guardrail changes relies on agent judgement.** This is mitigated by the rule that uncertain changes count as relaxing, and by the guardrail change log.

## Compliance

- Every agent merge has a merge-policy comment on its PR.
- `main-integrity` alerts (once implemented) and the guardrail change log are reviewed in the quarterly security review.
- This ADR is itself a guardrail file. Relaxing it requires the owner's approval.
