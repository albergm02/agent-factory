import json
import os
import shutil
import subprocess
import unittest

from .helpers import ROOT, TempCase, bash, run_hook

H = "audit_tool_use"


class Audit(TempCase):
    def log(self):
        p = os.path.join(self.tmp, ".claude", "audit", "agent-audit.jsonl")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def run_h(self, payload, **kw):
        return run_hook(H, payload, project_dir=self.tmp, **kw)

    def post(self, cmd, resp=None):
        p = bash(cmd, self.tmp)
        p["tool_response"] = resp if resp is not None else {"stdout": "", "stderr": ""}
        return p

    def test_logs_github_writes(self):
        cmds = [
            "gh pr create --title x --body y", "gh pr comment 3 -b hi", "gh pr merge 3 --squash",
            "gh pr edit 3 --add-label x", "gh pr close 3", "gh pr review 3 --approve",
            "gh issue create -t x", "gh issue comment 3 -b x", "gh issue edit 3 -t y", "gh issue close 3",
            "gh api -X POST repos/o/r/issues/3/comments -f body=x", "gh api --method PATCH repos/o/r/issues/3",
            "gh api -X PUT repos/o/r/x", "gh api -X DELETE repos/o/r/x",
            "gh api graphql -f query='mutation { addDiscussionComment(input:{}) { comment { id } } }'",
            "git push origin feat/x", "git -C /x push", "cd /tmp && gh pr comment 1 -b x",
        ]
        for c in cmds:
            self.assertEqual(self.run_h(self.post(c))[0], 0)
        self.assertEqual(len(self.log()), len(cmds))

    def test_ignores_reads(self):
        for c in ["gh pr view 3", "gh pr list", "gh issue view 3", "gh api repos/o/r/pulls/3", "git status",
                  "git log", "ls", "gh api graphql -f query='query { viewer { login } }'"]:
            self.assertEqual(self.run_h(self.post(c))[0], 0)
        self.assertEqual(self.log(), [])

    def test_fields_urls_and_ids(self):
        resp = {"stdout": "https://github.com/o/r/pull/3#issuecomment-99\n"
                          "see https://github.com/o/r/discussions/7#discussioncomment-123456 "
                          "id DC_kwDOAbcdEfg IC_kwDOZZZZZZ1 PR_kwDOAAAAAAA D_kwDOBBBBBBB"}
        self.run_h(self.post("gh pr comment 3 -b hi", resp))
        rec = self.log()[0]
        self.assertEqual(rec["tool"], "Bash")
        self.assertEqual(rec["cwd"], self.tmp)
        self.assertRegex(rec["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIn("https://github.com/o/r/pull/3#issuecomment-99", rec["urls"])
        self.assertIn("https://github.com/o/r/discussions/7#discussioncomment-123456", rec["urls"])
        for nid in ("DC_kwDOAbcdEfg", "IC_kwDOZZZZZZ1", "PR_kwDOAAAAAAA", "D_kwDOBBBBBBB"):
            self.assertIn(nid, rec["node_ids"])

    def test_redacts_tokens(self):
        secrets = ["ghp_" + "a" * 36, "github_pat_" + "B" * 30, "sk-ant-api03-" + "c" * 30, "gho_" + "d" * 25]
        self.run_h(self.post("GH_TOKEN=%s gh pr comment 3 -b '%s %s %s'" % (secrets[0], secrets[1], secrets[2], secrets[3])))
        with open(os.path.join(self.tmp, ".claude", "audit", "agent-audit.jsonl"), encoding="utf-8") as fh:
            text = fh.read()
        for s in secrets:
            self.assertNotIn(s, text)
        self.assertIn("[REDACTED]", text)

    def test_mcp_write_tools(self):
        p = {"tool_name": "mcp__claude_ai_github__add_issue_comment", "tool_input": {"body": "x"},
             "tool_response": "https://github.com/o/r/issues/1#issuecomment-5", "cwd": self.tmp}
        self.run_h(p)
        self.run_h({"tool_name": "mcp__claude_ai_github__list_issues", "tool_input": {}, "cwd": self.tmp})
        recs = self.log()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["tool"], "mcp__claude_ai_github__add_issue_comment")
        self.assertEqual(recs[0]["urls"], ["https://github.com/o/r/issues/1#issuecomment-5"])

    def test_never_fails(self):
        self.assertEqual(self.run_h(None, raw=b"garbage")[0], 0)
        self.assertEqual(self.run_h({"tool_name": "Bash", "tool_input": {"command": None}})[0], 0)
        self.assertEqual(self.run_h({"tool_name": "Bash", "tool_input": {"command": "gh pr create"}, "tool_response": None})[0], 0)
        # unwritable audit location: .claude is a file
        bad = os.path.join(self.tmp, "bad")
        os.makedirs(bad)
        with open(os.path.join(bad, ".claude"), "w") as fh:
            fh.write("x")
        code, _ = run_hook(H, self.post("gh pr create"), project_dir=bad)
        self.assertEqual(code, 0)

    def test_gitignore_has_audit_dir(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8-sig") as fh:
            self.assertIn(".claude/audit/", fh.read().split())


@unittest.skipUnless(shutil.which("bash"), "bash not available")
class Launcher(TempCase):
    def test_run_sh_dispatches_and_rejects(self):
        run = os.path.join(ROOT, ".claude", "hooks", "run.sh").replace("\\", "/")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.tmp)
        p = bash("git push origin main", self.tmp)
        r = subprocess.run(["bash", run, "guard_branch"], input=json.dumps(p).encode(), capture_output=True, env=env)
        self.assertEqual(r.returncode, 2, r.stderr)
        r = subprocess.run(["bash", run, "guard_branch"], input=json.dumps(bash("ls", self.tmp)).encode(),
                           capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(["bash", run, "../evil"], input=b"{}", capture_output=True, env=env)
        self.assertEqual(r.returncode, 2)
        r = subprocess.run(["bash", run, "guard_nope"], input=b"{}", capture_output=True, env=env)
        self.assertEqual(r.returncode, 2)


class SettingsFile(unittest.TestCase):
    def test_settings_valid_and_wired(self):
        with open(os.path.join(ROOT, ".claude", "settings.json"), encoding="utf-8") as fh:
            s = json.load(fh)
        deny = s["permissions"]["deny"]
        for rule in ["Read(.env*)", "Bash(git push --force*)", "Bash(git push * main*)", "Bash(gh pr merge * --admin*)",
                     "Bash(curl *)", "Bash(wget *)", "Bash(gh secret *)", "Bash(gh workflow *)"]:
            self.assertIn(rule, deny)
        self.assertFalse([r for r in s["permissions"].get("ask", []) if "gh api" in r])
        self.assertFalse([r for r in deny if "gh api" in r])
        wired = set()
        for entries in s["hooks"].values():
            for e in entries:
                for h in e["hooks"]:
                    name = h["command"].split()[-1]
                    wired.add(name)
                    self.assertTrue(os.path.exists(os.path.join(ROOT, ".claude", "hooks", name + ".py")))
        self.assertEqual(wired, {"guard_protected_paths", "guard_branch", "guard_merge", "guard_labels",
                                 "guard_dangerous_commands", "audit_tool_use"})


if __name__ == "__main__":
    unittest.main()
