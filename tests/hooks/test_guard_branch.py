import os
import unittest

from .helpers import TempCase, bash, git, make_repo, run_hook

H = "guard_branch"


class GuardBranch(TempCase):
    def setUp(self):
        super().setUp()
        self.main = make_repo(os.path.join(self.tmp, "main"))
        self.wt = os.path.join(self.tmp, "wt")
        git(["worktree", "add", "-q", "-b", "feat/x", self.wt], self.main)
        self.wt = os.path.realpath(self.wt)

    def run_h(self, cmd, cwd):
        return run_hook(H, bash(cmd, cwd))

    def fwd(self, p):
        return p.replace("\\", "/")

    def test_commit_on_main_blocked(self):
        self.assertBlocked(self.run_h("git commit -m x", self.main), "main")
        self.assertBlocked(self.run_h("git add . && git commit -am x", self.main))

    def test_commit_on_topic_branch_allowed(self):
        self.assertAllowed(self.run_h("git commit -m x", self.wt))

    def test_git_dash_C(self):
        self.assertBlocked(self.run_h("git -C %s commit -m x" % self.fwd(self.main), self.wt))
        self.assertAllowed(self.run_h("git -C %s commit -m x" % self.fwd(self.wt), self.main))

    def test_cd_and(self):
        self.assertBlocked(self.run_h("cd %s && git commit -m x" % self.fwd(self.main), self.wt))
        self.assertAllowed(self.run_h("cd %s && git commit -m x" % self.fwd(self.wt), self.main))

    def test_checkout_in_same_command(self):
        self.assertAllowed(self.run_h("git checkout -b feat/y && git commit -m x", self.main))
        self.assertAllowed(self.run_h("git switch -c feat/z && git commit -m x", self.main))
        self.assertBlocked(self.run_h("git switch main && git commit -m x", self.wt))

    def test_push_to_main_blocked(self):
        for cmd in ["git push origin main", "git push origin HEAD:main", "git push origin +main",
                    "git push origin feat/x:main", "git push origin HEAD:refs/heads/main",
                    "git push origin refs/heads/main", "git push -u origin HEAD:main",
                    "git push origin :main", "git push --delete origin main", "git push --mirror origin",
                    "git push --all origin"]:
            with self.subTest(cmd=cmd):
                self.assertBlocked(self.run_h(cmd, self.wt))

    def test_force_push_blocked(self):
        for cmd in ["git push --force origin feat/x", "git push -f origin feat/x",
                    "git push --force-with-lease origin feat/x", "git push --force-with-lease=feat/x:abc origin feat/x",
                    "git push -fu origin feat/x", "git push origin +feat/x"]:
            with self.subTest(cmd=cmd):
                self.assertBlocked(self.run_h(cmd, self.wt), "force")

    def test_push_topic_allowed(self):
        for cmd in ["git push origin feat/x", "git push -u origin feat/x", "git push origin HEAD",
                    "git push origin feat/x:feat/x", "git push", "git push origin HEAD:refs/heads/feat/x",
                    "git push -o ci.skip origin feat/x"]:
            with self.subTest(cmd=cmd):
                self.assertAllowed(self.run_h(cmd, self.wt))

    def test_implicit_push_from_main_blocked(self):
        self.assertBlocked(self.run_h("git push", self.main))
        self.assertBlocked(self.run_h("git push origin HEAD", self.main))
        self.assertAllowed(self.run_h("git push origin feat/x", self.main))

    def test_non_git_and_other_subcommands_allowed(self):
        for cmd in ["echo git push origin main", "git status", "git log main", "git checkout main", "ls"]:
            with self.subTest(cmd=cmd):
                self.assertAllowed(self.run_h(cmd, self.main))

    def test_push_inside_bash_c_and_subshell(self):
        self.assertBlocked(self.run_h("bash -c 'git push origin main'", self.wt))
        self.assertBlocked(self.run_h("echo $(git push origin main)", self.wt))

    def test_bad_input_allows(self):
        self.assertAllowed(run_hook(H, None, raw=b"{"))
        self.assertAllowed(run_hook(H, {"tool_name": "Bash", "tool_input": {"command": 5}}))


if __name__ == "__main__":
    unittest.main()
