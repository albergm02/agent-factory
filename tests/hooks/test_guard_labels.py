import unittest

from .helpers import TempCase, bash, run_hook

H = "guard_labels"


class GuardLabels(TempCase):
    def run_h(self, cmd):
        return run_hook(H, bash(cmd, self.tmp))

    def test_remove_halt_blocked(self):
        for cmd in [
            "gh pr edit 3 --remove-label agents:halt",
            "gh issue edit 3 --remove-label agents:halt",
            "gh pr edit 3 --remove-label=agents:halt",
            "gh pr edit 3 --remove-label needs-human,agents:halt",
            "gh pr edit 3 --add-label x --remove-label 'agents:halt'",
            "gh label delete agents:halt --yes",
            "gh label edit agents:halt --name other",
            "gh api -X DELETE repos/o/r/issues/3/labels/agents:halt",
            "gh api repos/o/r/issues/3/labels/agents%3Ahalt --method DELETE",
            "gh api -XDELETE repos/o/r/labels/agents:halt",
            "gh api -X DELETE repos/o/r/issues/3/labels",
            "gh api -X PUT repos/o/r/issues/3/labels -f 'labels[]=x'",
            "echo a && gh pr edit 3 --remove-label agents:halt",
        ]:
            with self.subTest(cmd=cmd):
                self.assertBlocked(self.run_h(cmd), "agents:halt")

    def test_other_label_operations_allowed(self):
        for cmd in [
            "gh pr edit 3 --add-label agents:halt",
            "gh pr edit 3 --remove-label needs-human",
            "gh issue edit 3 --add-label bug",
            "gh label create foo",
            "gh label delete foo",
            "gh api -X DELETE repos/o/r/issues/3/labels/needs-human",
            "gh api repos/o/r/issues/3/labels",
            "gh pr list",
            "echo agents:halt",
        ]:
            with self.subTest(cmd=cmd):
                self.assertAllowed(self.run_h(cmd))

    def test_mcp(self):
        self.assertBlocked(run_hook(H, {"tool_name": "mcp__x__remove_label",
                                        "tool_input": {"labels": ["agents:halt"]}}))
        self.assertAllowed(run_hook(H, {"tool_name": "mcp__x__add_label", "tool_input": {"labels": ["agents:halt"]}}))
        self.assertAllowed(run_hook(H, {"tool_name": "mcp__x__remove_label", "tool_input": {"labels": ["bug"]}}))
        self.assertBlocked(run_hook(H, {"tool_name": "mcp__github__issue_write",
                                        "tool_input": {"method": "update", "labels": ["bug"]}}))
        self.assertAllowed(run_hook(H, {"tool_name": "mcp__github__issue_write",
                                        "tool_input": {"method": "update", "title": "t"}}))
        self.assertAllowed(run_hook(H, {"tool_name": "mcp__github__issue_write",
                                        "tool_input": {"labels": ["bug", "agents:halt"]}}))

    def test_bad_input(self):
        self.assertAllowed(run_hook(H, None, raw=b""))


if __name__ == "__main__":
    unittest.main()
