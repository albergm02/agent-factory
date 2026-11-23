import os
import unittest

from .helpers import IS_WINDOWS, TempCase, bash, git, make_repo, run_hook

H = "guard_protected_paths"


def write(path, cwd, tool="Write"):
    return {"tool_name": tool, "tool_input": {"file_path": path}, "cwd": cwd}


class ProtectedPaths(TempCase):
    def setUp(self):
        super().setUp()
        self.main = make_repo(os.path.join(self.tmp, "main"))
        self.wt = os.path.join(self.tmp, "wt")
        git(["worktree", "add", "-q", "-b", "feat/x", self.wt], self.main)
        self.wt = os.path.realpath(self.wt)

    def run_h(self, payload):
        return run_hook(H, payload, project_dir=self.main)

    def test_guardrail_files_blocked_in_main(self):
        for rel in [".claude/settings.json", ".claude/hooks/x.py", "CLAUDE.md", ".github/workflows/ci.yml",
                    "docs/architecture/a.md", "docs/decisions/ADR-1.md", "scripts/x.py",
                    "docs/CODEOWNERS", "CODEOWNERS"]:
            for tool in ("Write", "Edit", "MultiEdit"):
                with self.subTest(rel=rel, tool=tool):
                    self.assertBlocked(self.run_h(write(os.path.join(self.main, rel), self.main, tool)))

    def test_notebook_edit(self):
        p = {"tool_name": "NotebookEdit",
             "tool_input": {"notebook_path": os.path.join(self.main, "scripts", "n.ipynb")}, "cwd": self.main}
        self.assertBlocked(self.run_h(p))

    def test_relative_path_uses_cwd(self):
        self.assertBlocked(self.run_h(write("x.py", os.path.join(self.main, "scripts"))))
        self.assertAllowed(self.run_h(write("x.py", self.main)))

    def test_other_files_in_main_allowed(self):
        for rel in ["src/a.py", "README.md", "docs/guide.md", "tests/t.py"]:
            self.assertAllowed(self.run_h(write(os.path.join(self.main, rel), self.main)))

    def test_same_paths_in_other_worktree_allowed(self):
        for rel in [".claude/settings.json", "CLAUDE.md", ".github/workflows/ci.yml", "scripts/x.py",
                    "docs/decisions/a.md"]:
            with self.subTest(rel=rel):
                self.assertAllowed(self.run_h(write(os.path.join(self.wt, rel), self.wt)))

    def test_nested_worktree_inside_main_allowed(self):
        nested = os.path.join(self.main, ".claude", "worktrees", "n1")
        git(["worktree", "add", "-q", "-b", "feat/n", nested], self.main)
        self.assertAllowed(self.run_h(write(os.path.join(nested, ".github", "x.yml"), nested)))
        self.assertBlocked(self.run_h(write(os.path.join(self.main, ".claude", "hooks", "y.py"), nested)))

    def test_settings_local_always_blocked(self):
        self.assertBlocked(self.run_h(write(os.path.join(self.main, ".claude", "settings.local.json"), self.main)))
        self.assertBlocked(self.run_h(write(os.path.join(self.wt, ".claude", "settings.local.json"), self.wt)),
                           "settings.local.json")
        self.assertBlocked(self.run_h(write(os.path.join(self.tmp, "elsewhere", ".claude", "settings.local.json"),
                                            self.tmp)))

    def test_forward_slashes_and_dotdot(self):
        p = (self.main + "/src/../.github/x.yml").replace("\\", "/")
        self.assertBlocked(self.run_h(write(p, self.main)))

    @unittest.skipUnless(IS_WINDOWS, "Windows only")
    def test_windows_case_and_backslashes(self):
        p = os.path.join(self.main, ".GitHub", "X.yml").upper().replace("/", "\\")
        self.assertBlocked(self.run_h(write(p, self.main)))
        msys = "/" + self.main[0].lower() + self.main[2:].replace("\\", "/") + "/scripts/a.py"
        self.assertBlocked(self.run_h(write(msys, self.main)))

    def test_bash_redirect_and_tools(self):
        cases = [
            "echo hi > .github/x.yml",
            "echo hi >> CLAUDE.md",
            "cat a | tee scripts/z.py",
            "sed -i 's/a/b/' docs/decisions/ADR.md",
            "cp /tmp/a .claude/settings.json",
            "mv foo.md docs/architecture/foo.md",
            "echo x > .claude/settings.local.json",
            "cd scripts && echo x > y.py",
            "bash -c 'echo x > CODEOWNERS'",
        ]
        for cmd in cases:
            with self.subTest(cmd=cmd):
                self.assertBlocked(self.run_h(bash(cmd, self.main)))

    def test_bash_allowed(self):
        for cmd in ["echo hi > src/x.txt", "ls .github", "cat CLAUDE.md > /dev/null", "git status 2>&1"]:
            with self.subTest(cmd=cmd):
                self.assertAllowed(self.run_h(bash(cmd, self.main)))

    def test_bash_in_worktree_allowed(self):
        self.assertAllowed(self.run_h(bash("echo hi > .github/x.yml", self.wt)))
        self.assertAllowed(self.run_h(bash("cd %s && echo hi >> CLAUDE.md" % self.wt.replace("\\", "/"), self.main)))
        self.assertBlocked(self.run_h(bash("echo hi > .claude/settings.local.json", self.wt)))

    def test_unparseable_input_allows_and_warns(self):
        self.assertAllowed(run_hook(H, None, project_dir=self.main, raw=b"not json"))
        self.assertAllowed(run_hook(H, {"nothing": 1}, project_dir=self.main))
        log = os.path.join(self.main, ".claude", "audit", "agent-audit.jsonl")
        with open(log) as fh:
            self.assertIn("warning", fh.read())

    def test_unguarded_tool_allowed(self):
        self.assertAllowed(self.run_h({"tool_name": "Read",
                                       "tool_input": {"file_path": os.path.join(self.main, "CLAUDE.md")},
                                       "cwd": self.main}))


if __name__ == "__main__":
    unittest.main()
