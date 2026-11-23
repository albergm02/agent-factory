import os
import unittest

from .helpers import TempCase, bash, make_fake_gh, run_hook

H = "guard_merge"


def pr(labels=(), checks=None, comment=True, assoc="OWNER"):
    if checks is None:
        checks = {"docs-check": "SUCCESS", "secret-scan": "SUCCESS"}
    return {
        "labels": [{"name": n} for n in labels],
        "statusCheckRollup": [
            {"__typename": "CheckRun", "name": k, "status": "COMPLETED", "conclusion": v} for k, v in checks.items()
        ],
        "comments": ([{"body": "Merge-policy checklist\n- [x] ok", "authorAssociation": assoc}] if comment else []),
    }


class GuardMerge(TempCase):
    def run_h(self, cmd, payload=None, rc=0):
        env = make_fake_gh(os.path.join(self.tmp, "bin"), payload if payload is not None else pr(), rc)
        return run_hook(H, bash(cmd, self.tmp), extra_env=env)

    def test_happy_path(self):
        self.assertAllowed(self.run_h("gh pr merge 7 --squash --delete-branch"))
        self.assertAllowed(self.run_h("gh pr merge 7 -s -d"))
        self.assertAllowed(self.run_h("gh pr merge 7 --squash --body 'x y' -R o/r"))

    def test_neutral_and_skipped_ok(self):
        checks = {"docs-check": "SUCCESS", "secret-scan": "SUCCESS", "a": "NEUTRAL", "b": "SKIPPED"}
        self.assertAllowed(self.run_h("gh pr merge 7 --squash", pr(checks=checks)))

    def test_admin_blocked(self):
        self.assertBlocked(self.run_h("gh pr merge 7 --squash --admin"), "--admin")

    def test_non_squash_blocked(self):
        for flag in ("--merge", "--rebase", "-m", "-r"):
            with self.subTest(flag=flag):
                self.assertBlocked(self.run_h("gh pr merge 7 " + flag), "squash")
        self.assertBlocked(self.run_h("gh pr merge 7"), "squash")

    def test_auto_blocked(self):
        self.assertBlocked(self.run_h("gh pr merge 7 --squash --auto"))

    def test_halt_and_needs_human(self):
        self.assertBlocked(self.run_h("gh pr merge 7 --squash", pr(labels=["agents:halt"])), "agents:halt")
        self.assertBlocked(self.run_h("gh pr merge 7 --squash", pr(labels=["needs-human"])), "needs-human")
        self.assertAllowed(self.run_h("gh pr merge 7 --squash", pr(labels=["docs"])))

    def test_failing_pending_or_missing_checks(self):
        self.assertBlocked(self.run_h("gh pr merge 7 --squash", pr(checks={"docs-check": "SUCCESS", "secret-scan": "FAILURE"})))
        self.assertBlocked(self.run_h("gh pr merge 7 --squash", pr(checks={"docs-check": "SUCCESS", "secret-scan": ""})))
        self.assertBlocked(self.run_h("gh pr merge 7 --squash", pr(checks={"docs-check": "SUCCESS"})), "secret-scan")
        self.assertBlocked(self.run_h("gh pr merge 7 --squash", pr(checks={})))
        self.assertBlocked(self.run_h("gh pr merge 7 --squash",
                                      pr(checks={"docs-check": "SUCCESS", "secret-scan": "SUCCESS", "x": "CANCELLED"})))

    def test_status_context_entries(self):
        payload = pr(checks={"docs-check": "SUCCESS", "secret-scan": "SUCCESS"})
        payload["statusCheckRollup"].append({"__typename": "StatusContext", "context": "ext", "state": "PENDING"})
        self.assertBlocked(self.run_h("gh pr merge 7 --squash", payload))
        payload["statusCheckRollup"][-1]["state"] = "SUCCESS"
        self.assertAllowed(self.run_h("gh pr merge 7 --squash", payload))

    def test_checklist_comment_required(self):
        self.assertBlocked(self.run_h("gh pr merge 7 --squash", pr(comment=False)), "Merge-policy checklist")
        self.assertBlocked(self.run_h("gh pr merge 7 --squash", pr(assoc="NONE")), "Merge-policy checklist")

    def test_gh_failure_blocks(self):
        self.assertBlocked(self.run_h("gh pr merge 7 --squash", rc=1), "cannot be verified")

    def test_missing_gh_blocks(self):
        env = {"PATH": os.path.join(self.tmp, "empty")}
        os.makedirs(env["PATH"])
        # keep python reachable through sys.executable; PATH holds no gh
        self.assertBlocked(run_hook(H, bash("gh pr merge 7 --squash", self.tmp), extra_env=env))

    def test_api_merge_blocked(self):
        for cmd in ["gh api -X PUT repos/o/r/pulls/7/merge", "gh api repos/o/r/pulls/7/merge -f merge_method=squash",
                    "gh api graphql -f query='mutation { mergePullRequest(input:{pullRequestId:\"x\"}) { clientMutationId } }'",
                    "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input:{}) { clientMutationId } }'"]:
            with self.subTest(cmd=cmd):
                self.assertBlocked(self.run_h(cmd), "gh api")

    def test_api_other_allowed(self):
        self.assertAllowed(self.run_h("gh api repos/o/r/pulls/7"))
        self.assertAllowed(self.run_h("gh pr view 7"))
        self.assertAllowed(self.run_h("echo hello"))

    def test_mcp_merge_blocked(self):
        for name in ["mcp__claude_ai_github__merge_pull_request", "mcp__github__pull_request_merge"]:
            with self.subTest(name=name):
                self.assertBlocked(run_hook(H, {"tool_name": name, "tool_input": {}}), "MCP")
        self.assertAllowed(run_hook(H, {"tool_name": "mcp__github__list_pull_requests", "tool_input": {}}))

    def test_nested_in_compound(self):
        self.assertBlocked(self.run_h("echo ok && gh pr merge 7 --merge"))


if __name__ == "__main__":
    unittest.main()
