#!/usr/bin/env python3
"""PreToolUse: block writes to guardrail files in the session's MAIN checkout.

Guardrail list: ADR-0002 section 5. Writes to the same paths inside other git
worktrees (feature branches that go through PR review) are allowed. Any
.claude/settings.local.json is always blocked (it never reaches PR review).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

HOOK = "guard_protected_paths"
FILE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
GUARDED_DIRS = [".claude", ".github", "docs/architecture", "docs/decisions", "scripts"]
GUARDED_FILES = ["CLAUDE.md"]
GUARDED_BASENAMES = ["CODEOWNERS"]


def fold(s):
    return s.lower() if c.IS_WINDOWS else s


def is_local_settings(path):
    k = c.pkey(path).split("/")
    return len(k) >= 2 and k[-1] == fold("settings.local.json") and k[-2] == fold(".claude")


def guarded_rel(rel):
    """rel: path relative to the main checkout, '/'-separated."""
    r = fold(rel)
    for d in GUARDED_DIRS:
        d = fold(d)
        if r == d or r.startswith(d + "/"):
            return True
    if r in [fold(f) for f in GUARDED_FILES]:
        return True
    return r.split("/")[-1] in [fold(b) for b in GUARDED_BASENAMES]


def check_target(raw, base, main):
    """Return a block reason or None."""
    if not raw or not isinstance(raw, str):
        return None
    path = c.resolve(raw, base)
    if is_local_settings(path):
        return ("writes to '%s' are blocked: .claude/settings.local.json is never "
                "writable by agents (ADR-0002 section 5)." % raw)
    if not main or not c.is_under(path, main):
        return None
    # A nested git worktree/repo below the main checkout is a different checkout.
    d = os.path.dirname(path)
    while c.is_under(d, main) and c.pkey(d) != c.pkey(main):
        if os.path.exists(os.path.join(d, ".git")):
            return None
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    rel = os.path.relpath(path, main).replace("\\", "/")
    if guarded_rel(rel):
        return ("'%s' is a guardrail file in the main checkout (ADR-0002 section 5). "
                "Make the change on a feature branch in a separate git worktree and open a PR; "
                "relaxing guardrails also needs a human decision (Discussion)." % raw)
    return None


def bash_targets(seg):
    """Best-effort write targets of one command segment."""
    words = seg.words
    name = c.base_cmd(words[0])
    args = list(words[1:])
    non_opt = [w for w in args if not w.startswith("-")]
    targets = [t for op, t in seg.redirs if op in (">", ">>") and t != "/dev/null"]
    if name == "tee":
        targets += non_opt
    elif name == "sed" and any(a == "--in-place" or a.startswith("--in-place=") or c.flag_cluster(a, "i") for a in args):
        targets += non_opt
    elif name in ("cp", "install", "ln", "rsync"):
        targets += non_opt[-1:]
    elif name in ("mv", "rm", "truncate", "touch", "chmod", "unlink", "rmdir"):
        targets += non_opt
    elif name == "dd":
        targets += [a[3:] for a in args if a.startswith("of=")]
    elif name == "perl" and any(c.flag_cluster(a, "i") for a in args):
        targets += non_opt
    return targets


def is_guarded(data):
    name = c.tool_name(data)
    return name in FILE_TOOLS or name == "Bash"


def evaluate(data):
    main = c.main_checkout(data)
    cwd = c.input_cwd(data)
    ti = c.tool_input(data)
    if c.tool_name(data) in FILE_TOOLS:
        raw = ti.get("file_path") or ti.get("notebook_path") or ti.get("path")
        return check_target(raw, cwd, main)
    cmd = c.bash_command(data)
    if not cmd:
        return None
    if not re.search(r">|\b(tee|sed|perl|cp|mv|rm|install|ln|rsync|truncate|touch|chmod|dd|unlink|rmdir)\b", cmd):
        return None
    for seg in c.iter_commands(cmd, cwd):
        for t in bash_targets(seg):
            reason = check_target(t, seg.cwd, main)
            if reason:
                return reason
    return None


if __name__ == "__main__":
    c.run_guard(HOOK, is_guarded, evaluate)
