# Runbook: create the `agent-factory-bot` GitHub App (D3)

| | |
|---|---|
| **Audience** | Repository owner (`albergm02`) |
| **Status** | Pending: the owner has approved the App (D3); it has not been created yet |
| **Related** | [Security Model section 6](../architecture/security-model.md#6-identity-and-access) · [ADR-0002](../decisions/ADR-0002-autonomous-merge-and-human-decisions.md) |

Creating the App, granting its permissions, and storing its credentials are H2 decisions (ADR-0002 section 3). **Only the owner can do the steps marked OWNER.** Agents must not create the App, generate keys, or write secrets. Agents may do the steps marked AGENT only after the owner has finished the OWNER steps and says so.

## 1. Why

Today agents act through the owner's `gh` login, which carries administration, workflows and secrets scopes. A compromised session could edit the ruleset or forge an owner decision. A dedicated App identity has only the permissions listed below, is visibly a different account (`agent-factory-bot[bot]`), and issues short-lived tokens.

## 2. Create the App (OWNER)

1. GitHub, profile picture, **Settings**, **Developer settings**, **GitHub Apps**, **New GitHub App**.
2. **GitHub App name:** `agent-factory-bot` (at most 34 characters, unique across GitHub; add a suffix if taken and note the final name here).
3. **Homepage URL:** `https://github.com/albergm02/agent-factory`.
4. **Webhook:** clear **Active**. No webhook is needed initially.
5. **Identifying and authorizing users, callback URL, setup URL:** leave empty. Do not enable "Request user authorization (OAuth) during installation".
6. **Repository permissions** (set exactly these, everything else stays **No access**):

   | Permission | Access |
   |---|---|
   | Contents | Read and write |
   | Pull requests | Read and write |
   | Issues | Read and write |
   | Discussions | Read and write |
   | Checks | Read-only |
   | Metadata | Read-only (mandatory, set automatically) |

   **Do not grant:** Administration, Workflows, Secrets, Environments, Members, Actions, Pages, Webhooks, or any organization or account permission.
7. **Subscribe to events:** none.
8. **Where can this GitHub App be installed?** **Only on this account**.
9. Click **Create GitHub App**.
10. On the App page, note the **Client ID** (and the numeric **App ID**, which is a different value).
11. Under **Private keys**, click **Generate a private key**. A `.pem` file downloads. Treat it as a password: never commit it, never paste it into an issue, Discussion, PR or chat.

## 3. Install the App on this repository only (OWNER)

1. App settings, **Install App**, choose your account, **Install**.
2. Select **Only select repositories**, choose `albergm02/agent-factory`, then **Install**.
3. Confirm under Settings, **Applications**, **Installed GitHub Apps**, **Configure** that only this repository is listed and the permissions match the table above.

## 4. Store the credentials (OWNER)

Set these in the repository, Settings, **Secrets and variables**, **Actions**:

| Kind | Name | Value |
|---|---|---|
| Variable | `AF_APP_CLIENT_ID` | The App **Client ID** (`create-github-app-token` recommends the Client ID; the legacy `app-id` input also works) |
| Variable | `AF_APP_ID` | The numeric **App ID** (optional, for tooling that still needs it) |
| Secret | `AF_APP_PRIVATE_KEY` | The full contents of the `.pem` file, including the BEGIN and END lines |

Then delete the downloaded `.pem` from disk, or move it to your password manager. Do not store it in the repository, in Dependabot secrets, or in an environment unless a workflow needs it there.

The names above are the convention workflows will use. If you choose different names, tell the orchestrator so the workflows match.

## 5. Use the App in workflows (AGENT, after section 4 is done)

Workflows mint a short-lived installation token (valid for one hour, revoked when the job ends) with `actions/create-github-app-token`, pinned by full commit SHA (project rule: third-party actions are pinned by SHA).

Resolved on 2026-11-23: tag `v3.4.0` points to a commit directly (a lightweight tag, no dereferencing needed):

```
actions/create-github-app-token@f418cff399f7aef4c2f0ad47e25ca7a6abbdd6fc  # v3.4.0
```

To re-resolve a newer tag:

```bash
gh api repos/actions/create-github-app-token/git/ref/tags/<tag> --jq '.object.type + " " + .object.sha'
# if the type is "tag" (annotated), dereference it:
gh api repos/actions/create-github-app-token/git/tags/<sha> --jq '.object.sha'
```

Example job (request only the permissions the job needs; selected permissions must already be granted to the installation):

```yaml
permissions:
  contents: read
jobs:
  example:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/create-github-app-token@f418cff399f7aef4c2f0ad47e25ca7a6abbdd6fc  # v3.4.0
        id: app-token
        with:
          client-id: ${{ vars.AF_APP_CLIENT_ID }}
          private-key: ${{ secrets.AF_APP_PRIVATE_KEY }}
          permission-pull-requests: write
          permission-issues: write
      - env:
          GH_TOKEN: ${{ steps.app-token.outputs.token }}
        run: gh pr comment "$PR" --body "🤖 Agent Factory: ..."
```

Without `owner` or `repositories` inputs the token covers only the current repository. Workflow files are guardrail files: adding them follows ADR-0002 section 5, and the `workflows` permission is deliberately not granted, so the App can never edit workflows.

## 6. Local agent sessions

`create-github-app-token` runs in Actions only. Until a local token helper exists, interactive and local agent sessions keep using the owner's `gh` login, so the interim risks in Security Model section 6 still apply locally. A future helper (a script that signs a JWT with the key and requests an installation token) would need the private key on the owner's machine, which is itself an H2 decision and a new risk, so it needs a separate decision and ADR. Do not copy the key to a developer machine without that decision.

## 7. Rotate the key (OWNER)

Rotate on a schedule (for example every 90 days) and immediately after any suspected leak.

1. App settings, **Private keys**, **Generate a private key** (a second key now exists).
2. Update the `AF_APP_PRIVATE_KEY` secret with the new key.
3. Run a workflow that mints a token to confirm it works.
4. Delete the old key on the App page.

## 8. Revoke: the kill switch (OWNER)

- **Fast stop:** App settings, **Advanced**, or the installation page, **Suspend** the installation. All tokens stop working.
- **Hard stop:** uninstall the App, or delete the private keys on the App page. Delete the `AF_APP_PRIVATE_KEY` secret.
- Existing installation tokens expire after one hour at the latest.
- Independently, the `agents:halt` label stops agents by policy (ADR-0002 section 1); the App suspension is the technical backstop.

## 9. What changes in ADR-0002 once the App exists

These follow-ups are separate PRs on guardrail files (tightening unless stated); this runbook does not change them.

- **Agent identity is distinct** from the owner. ADR-0002 section 2 rule 3 can then rely on the author login (`agent-factory-bot[bot]` versus `albergm02`) in addition to the audit log, so a forged owner approval by an agent becomes detectable and non-valid by construction. Threat T14 (forged human decision) is mitigated.
- **The owner should remove the agents' admin path:** agents stop using the owner's `gh` login for PR, merge and comment actions; the owner's admin credentials are used only by the owner. This is what makes the compensating controls of ADR-0002 section 6 protective against a compromised agent session (no ability to edit the ruleset, workflows or secrets).
- The "Interim limitation" in section 2 and the "Limits of these controls" in section 6 should be updated, and the `protect-main` ruleset can then require status checks and may add the App as the only merger if the owner wants stricter control. Any change that relaxes a guardrail still needs a human decision.

## 10. Verification checklist (OWNER, then AGENT)

- [ ] App permissions match section 2 exactly; no extra permission.
- [ ] Installed on `albergm02/agent-factory` only.
- [ ] Webhook inactive; no events subscribed.
- [ ] Variables and secret set; `.pem` removed from disk.
- [ ] A test workflow mints a token and posts a `🤖 Agent Factory:` comment as `agent-factory-bot[bot]`.
- [ ] The App cannot edit workflows or repository settings (a deliberate failure test).
