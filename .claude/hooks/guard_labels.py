#!/usr/bin/env python3
"""PreToolUse: agents never remove the `agents:halt` label (ADR-0002 section 1)."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

HOOK = "guard_labels"
HALT = re.compile(r"agents(:|%3a)halt", re.I)
MCP_NAMES = re.compile(r"^mcp__.*(label|issue_write|update_issue|update_pull_request|pull_request_write)", re.I)
HINT = " Only the owner removes 'agents:halt' (ADR-0002 section 1)."


def is_guarded(data):
    name = c.tool_name(data)
    if name == "Bash":
        cmd = c.bash_command(data)
        return cmd is not None and "gh" in cmd.lower()
    return bool(MCP_NAMES.match(name))


def check_gh(seg):
    words = seg.words
    args = words[1:]
    if not args:
        return None
    sub = [a for a in args if not a.startswith("-")][:2]
    if sub[:1] == ["label"] and len(sub) > 1 and sub[1] in ("delete", "edit"):
        if any(HALT.search(a) for a in args):
            return "deleting or renaming the 'agents:halt' label is blocked." + HINT
    if sub[:2] in (["pr", "edit"], ["issue", "edit"]):
        for i, a in enumerate(args):
            val = None
            if a == "--remove-label" and i + 1 < len(args):
                val = args[i + 1]
            elif a.startswith("--remove-label="):
                val = a.split("=", 1)[1]
            if val and HALT.search(val):
                return "removing the 'agents:halt' label is blocked." + HINT
    if sub[:1] == ["api"]:
        blob = " ".join(args) + " " + " ".join(t for _, t in seg.redirs)
        method = c.gh_method(args)
        if method == "DELETE" and re.search(r"labels/(agents(:|%3a)halt)\b", blob, re.I):
            return "deleting the 'agents:halt' label through the API is blocked." + HINT
        if method == "DELETE" and re.search(r"/issues/\d+/labels/?(\s|$)", blob):
            return "removing all labels through the API would drop 'agents:halt' and is blocked." + HINT
        if method == "PUT" and re.search(r"/issues/\d+/labels/?(\s|$)", blob) and not HALT.search(blob):
            return "replacing the label set through the API would drop 'agents:halt' and is blocked." + HINT
        if re.search(r"removeLabelsFromLabelable|deleteLabel|updateLabel", blob):
            return "GraphQL label removal/deletion mutations are blocked." + HINT
    return None


def check_mcp(data):
    name = c.tool_name(data)
    blob = json.dumps(c.tool_input(data), default=str)
    low = name.lower()
    if "label" in low and re.search(r"remove|delete", low + " " + blob.lower()) and HALT.search(blob):
        return "removing the 'agents:halt' label is blocked." + HINT
    if re.search(r"issue_write|update_issue|update_pull_request|pull_request_write", low):
        ti = c.tool_input(data)
        labels = ti.get("labels")
        if isinstance(labels, list) and not any(HALT.search(str(l)) for l in labels):
            return ("this call replaces the label set without 'agents:halt' and could drop it; "
                    "edit labels with 'gh issue edit --add-label' instead." + HINT)
    return None


def evaluate(data):
    if c.tool_name(data) != "Bash":
        return check_mcp(data)
    for seg in c.iter_commands(c.bash_command(data), c.input_cwd(data)):
        if c.is_gh(seg):
            reason = check_gh(seg)
            if reason:
                return reason
    return None


if __name__ == "__main__":
    c.run_guard(HOOK, is_guarded, evaluate)
