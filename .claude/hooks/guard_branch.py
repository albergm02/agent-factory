#!/usr/bin/env python3
"""PreToolUse (Bash): no commits on main, no pushes to main, no force pushes."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

HOOK = "guard_branch"
PROTECTED = "main"
OPT_WITH_VALUE = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
HINT = " Work on a topic branch (feat/*, fix/*, docs/*, chore/*, agent/*) and merge through a PR."


def is_guarded(data):
    cmd = c.bash_command(data)
    return c.tool_name(data) == "Bash" and cmd is not None and "git" in cmd.lower()


def norm_ref(ref):
    r = ref
    if r.startswith("refs/heads/"):
        r = r[len("refs/heads/"):]
    return r


def check_push(args, branch):
    positional = []
    force = False
    mirror = False
    skip = False
    rest = False
    for a in args:
        if skip:
            skip = False
            continue
        if rest or not a.startswith("-"):
            positional.append(a)
            continue
        if a == "--":
            rest = True
        elif a in OPT_WITH_VALUE:
            skip = True
        elif a.startswith("--force"):
            force = True
        elif a in ("--mirror", "--all"):
            mirror = True
        elif c.flag_cluster(a, "f"):
            force = True
    if force:
        return "force pushes (--force, -f, --force-with-lease) are blocked." + HINT
    if mirror:
        return "'git push --mirror/--all' would update main and is blocked." + HINT
    refspecs = positional[1:]
    for p in positional:
        if norm_ref(p.lstrip("+")) == PROTECTED:
            return "pushing to main is blocked." + HINT
    for ref in refspecs:
        if ref.startswith("+"):
            return "force pushes (+refspec) are blocked." + HINT
        dst = ref.split(":", 1)[1] if ":" in ref else ref
        if norm_ref(dst) == PROTECTED:
            return "pushing to main (refspec '%s') is blocked." % ref + HINT
    implicit = not refspecs or any(r in ("HEAD", "@", "HEAD:") for r in refspecs)
    if implicit and branch == PROTECTED:
        return "main is checked out, so this push would update main; it is blocked." + HINT
    return None


def evaluate(data):
    cwd = c.input_cwd(data)
    overrides = {}  # repo dir key -> branch set by checkout/switch earlier in the command
    for seg in c.iter_commands(c.bash_command(data), cwd):
        if not c.is_git(seg):
            continue
        sub, args, eff, _ = c.parse_git(seg.words, seg.cwd)
        key = c.pkey(eff)
        if sub in ("checkout", "switch"):
            newb = None
            for i, a in enumerate(args):
                if a in ("-b", "-B", "-c", "-C") and i + 1 < len(args):
                    newb = args[i + 1]
                    break
            non_opt = [a for a in args if not a.startswith("-")]
            if newb is None and sub == "switch" and non_opt:
                newb = non_opt[0]
            if newb is None and sub == "checkout" and len(non_opt) == 1 and non_opt[0] == PROTECTED:
                newb = PROTECTED
            if newb:
                overrides[key] = newb
        elif sub in ("commit", "push"):
            branch = overrides.get(key)
            if branch is None:
                branch = c.current_branch(eff)
            if sub == "commit" and branch == PROTECTED:
                return "committing on main is blocked (main is checked out in '%s').%s" % (eff, HINT)
            if sub == "push":
                reason = check_push(args, branch)
                if reason:
                    return reason
    return None


if __name__ == "__main__":
    c.run_guard(HOOK, is_guarded, evaluate)
