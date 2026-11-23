#!/usr/bin/env python3
"""PreToolUse (Bash): block destructive and exfiltration patterns."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

HOOK = "guard_dangerous_commands"
PREFILTER = re.compile(r"\brm\b|git|chmod|curl|wget|iex|iwr|irm|invoke-|\|", re.I)
FETCHERS = r"(?:curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod)"
INTERPRETERS = (r"(?:sudo\s+)?(?:/\S*/)?(?:(?:ba|z|da|k|c)?sh|iex|invoke-expression|python3?|node|perl|ruby|pwsh|powershell)\b")
PIPE_TO_SHELL = re.compile(FETCHERS + r"\b[^\n;&]*(?<!\|)\|(?!\|)\s*" + INTERPRETERS, re.I)
SUBST_SHELL = re.compile(r"\b(?:(?:ba|z|da|k)?sh|iex|invoke-expression)\b[^\n]*(?:\$\(|<\(|`)\s*" + FETCHERS + r"\b", re.I)
IEX_FETCH = re.compile(r"\b(?:iex|invoke-expression)\b[^\n]*\b" + FETCHERS + r"\b", re.I)
DRIVE_ROOT = re.compile(r"^(?:[A-Za-z]:)?[/\\]*$|^/[A-Za-z]/?$")


def is_guarded(data):
    cmd = c.bash_command(data)
    return c.tool_name(data) == "Bash" and cmd is not None and bool(PREFILTER.search(cmd))


def check_rm(seg, main):
    args = seg.words[1:]
    recursive = any(a in ("--recursive",) or c.flag_cluster(a, "rR") for a in args)
    if not recursive:
        return None
    targets = [a for a in args if not a.startswith("-")]
    root = c.repo_root(seg.cwd) or c.resolve(".", seg.cwd)
    for t in targets:
        if "$" in t.replace("$HOME", "").replace("${HOME}", "") or "`" in t:
            return "recursive delete of '%s' uses an unresolved variable or substitution and is blocked." % t
        if DRIVE_ROOT.match(t) or t in ("~", "~/", "$HOME", "${HOME}", ".."):
            return "recursive delete of '%s' is blocked." % t
        if ".." in re.split(r"[/\\]", t) and not c.is_under(c.resolve(t, seg.cwd), root):
            return "recursive delete of '%s' escapes the repository and is blocked." % t
        p = c.resolve(t, seg.cwd)
        home = c.resolve("~", seg.cwd)
        if c.pkey(p) == c.pkey(home) or os.path.dirname(p) == p or DRIVE_ROOT.match(p.replace("\\", "/")):
            return "recursive delete of '%s' is blocked." % t
        if not c.is_under(p, root):
            return "recursive delete of '%s' is outside the repository (%s) and is blocked." % (t, root)
        if c.pkey(p) == c.pkey(root):
            return "recursive delete of the repository root is blocked."
    return None


def evaluate(data):
    cmd = c.bash_command(data)
    if PIPE_TO_SHELL.search(cmd) or SUBST_SHELL.search(cmd) or IEX_FETCH.search(cmd):
        return "piping or substituting downloaded content into a shell/interpreter (curl|sh, iex) is blocked."
    main = c.main_checkout(data)
    for seg in c.iter_commands(cmd, c.input_cwd(data)):
        w = seg.words
        name = c.base_cmd(w[0])
        if name == "rm":
            reason = check_rm(seg, main)
            if reason:
                return reason
        elif name == "chmod":
            if any(a.lstrip("0") == "777" or a in ("a+rwx", "ugo+rwx") for a in w[1:]):
                return "chmod 777 is blocked."
        elif name == "git":
            sub, args, eff, confs = c.parse_git(w, seg.cwd)
            if any(re.search(r"credential\.[^=]*helper", k, re.I) for k in confs):
                return "setting a git credential helper is blocked."
            if sub == "config" and any(re.search(r"credential\.[^=\s]*helper", a, re.I) for a in args):
                return "setting a git credential helper is blocked."
            if sub == "credential" or (sub and sub.startswith("credential-")):
                return "git credential commands are blocked."
            if sub in ("filter-branch", "filter-repo"):
                return "git %s rewrites history and is blocked." % sub
            if sub == "push" and any(a == "--mirror" for a in args):
                return "git push --mirror is blocked."
            if sub == "clean" and any(c.flag_cluster(a, "xX") or a in ("-x", "-X") for a in args):
                root = c.repo_root(eff)
                if root and main and c.pkey(root) == c.pkey(main):
                    return "git clean with -x/-X in the main checkout is blocked (it deletes ignored files such as local settings)."
    return None


if __name__ == "__main__":
    c.run_guard(HOOK, is_guarded, evaluate)
