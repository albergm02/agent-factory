#!/usr/bin/env python3
"""PostToolUse: append an audit line for every command that writes to GitHub.

Never fails: always exits 0. Log: $CLAUDE_PROJECT_DIR/.claude/audit/agent-audit.jsonl
(git-ignored). Tokens are redacted.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

HOOK = "audit_tool_use"
GH_WRITE = {("pr", v) for v in ("create", "comment", "merge", "edit", "close", "review", "ready", "reopen")} | {
    ("issue", v) for v in ("create", "comment", "edit", "close", "reopen", "delete")
}
MCP_WRITE = re.compile(r"create|add_|update|merge|delete|write|push|fork|submit|request_|sub_issue|comment", re.I)
URL_RE = re.compile(
    r"https://github\.com/[\w.\-]+/[\w.\-]+/(?:discussions|issues|pull)/\d+(?:#[\w\-]+)?"
)
NODE_RE = re.compile(r"\b(?:DC|IC|PR|D|PRR|PRRC)_[A-Za-z0-9_\-]{8,}")


def gh_write_kind(seg):
    words = seg.words
    args = words[1:]
    non_flag = [a for a in args if not a.startswith("-")]
    if len(non_flag) >= 2 and (non_flag[0], non_flag[1]) in GH_WRITE:
        return "gh %s %s" % (non_flag[0], non_flag[1])
    if non_flag[:1] == ["api"]:
        method = c.gh_method(args)
        blob = " ".join(args)
        if method in ("POST", "PATCH", "PUT", "DELETE"):
            return "gh api %s" % method
        if re.search(r"\bmutation\b", blob):
            return "gh api graphql mutation"
        if non_flag[1:2] and non_flag[1] == "graphql" and re.search(r"mutation", blob):
            return "gh api graphql mutation"
    return None


def writes_github(data):
    name = c.tool_name(data)
    if name == "Bash":
        cmd = c.bash_command(data) or ""
        for seg in c.iter_commands(cmd, c.input_cwd(data)):
            if c.is_gh(seg) and gh_write_kind(seg):
                return True
            if c.is_git(seg) and c.parse_git(seg.words, seg.cwd)[0] == "push":
                return True
        return False
    if name.startswith("mcp__"):
        return bool(MCP_WRITE.search(name.split("__", 2)[-1]))
    return False


def main():
    data = c.load_input(HOOK)
    if data is None:
        return
    if not writes_github(data):
        return
    name = c.tool_name(data)
    if name == "Bash":
        command = c.bash_command(data) or ""
    else:
        command = json.dumps(c.tool_input(data), ensure_ascii=False, default=str)
    resp = json.dumps(data.get("tool_response"), ensure_ascii=False, default=str)
    resp = c.redact(resp)
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": name,
        "command": c.redact(command)[:4000],
        "cwd": c.input_cwd(data),
        "session_id": data.get("session_id"),
        "urls": sorted(set(URL_RE.findall(resp))),
        "node_ids": sorted(set(NODE_RE.findall(resp))),
    }
    if not c.append_audit(record):
        c._write_err("[agent-factory audit] could not write the audit log")


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:  # never fail
        try:
            c.warn(HOOK, "audit hook error: %r" % (exc,))
        except BaseException:
            pass
    sys.exit(0)
