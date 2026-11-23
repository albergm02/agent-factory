#!/usr/bin/env python3
"""PreToolUse: enforce the merge policy (ADR-0002 section 1) on PR merges.

* `gh pr merge`: squash only, no --admin/--auto, and the PR must satisfy the
  policy (labels, checks, merge-policy checklist comment) -- verified with
  `gh pr view --json labels,statusCheckRollup,comments`.
* `gh api` merge endpoints / GraphQL merge mutations and MCP merge tools:
  always blocked (agents must use `gh pr merge`).
"""
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

HOOK = "guard_merge"
MCP_MERGE = re.compile(r"^mcp__.*(merge.*pull|pull.*merge)", re.I)
API_MERGE = re.compile(r"pulls?/[^/\s]+/merge|mergePullRequest|enablePullRequestAutoMerge|enableAutoMerge", re.I)
OK_STATES = {"SUCCESS", "NEUTRAL", "SKIPPED"}
REQUIRED_CHECKS = ("docs-check", "secret-scan")
BLOCKING_LABELS = ("agents:halt", "needs-human")
TRUSTED_ASSOC = ("OWNER", "MEMBER", "COLLABORATOR")
OPT_WITH_VALUE = {"-b", "--body", "-F", "--body-file", "-t", "--subject", "-R", "--repo", "--match-head-commit", "-A", "--author-email"}


def is_guarded(data):
    name = c.tool_name(data)
    if name == "Bash":
        cmd = c.bash_command(data)
        return cmd is not None and "gh" in cmd.lower()
    return bool(MCP_MERGE.match(name))


def verify_pr(selector, repo, cwd):
    """Return a list of policy problems for the PR (empty list = OK)."""
    gh = shutil.which("gh")
    if not gh:
        return ["the 'gh' CLI was not found, so the merge policy cannot be verified"]
    cmd = [gh, "pr", "view"]
    if selector:
        cmd.append(selector)
    if repo:
        cmd += ["-R", repo]
    cmd += ["--json", "labels,statusCheckRollup,comments"]
    r = subprocess.run(cmd, cwd=c.existing_dir(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    if r.returncode != 0:
        return ["'gh pr view' failed, so the merge policy cannot be verified: %s" % r.stderr.strip()[:300]]
    info = json.loads(r.stdout)
    problems = []
    labels = [str(l.get("name", "")).lower() for l in info.get("labels") or []]
    for bad in BLOCKING_LABELS:
        if bad in labels:
            problems.append("PR carries the '%s' label" % bad)
    rollup = info.get("statusCheckRollup") or []
    results = {}
    for entry in rollup:
        name = entry.get("name") or entry.get("context") or "?"
        state = (entry.get("conclusion") or entry.get("state") or entry.get("status") or "").upper()
        results[name] = state
        if state not in OK_STATES:
            problems.append("check '%s' is %s (needs SUCCESS, NEUTRAL or SKIPPED)" % (name, state or "not finished"))
    for req in REQUIRED_CHECKS:
        if results.get(req) != "SUCCESS":
            problems.append("required check '%s' is not SUCCESS (found: %s)" % (req, results.get(req, "missing")))
    ok_comment = False
    for cm in info.get("comments") or []:
        if "merge-policy checklist" in str(cm.get("body", "")).lower() \
                and str(cm.get("authorAssociation", "")).upper() in TRUSTED_ASSOC:
            ok_comment = True
    if not ok_comment:
        problems.append("no 'Merge-policy checklist' comment by the owner/a collaborator on the PR")
    return problems


def check_gh_merge(seg):
    args = seg.words[1:]
    # find `pr merge`
    non_flag = [a for a in args if not a.startswith("-")]
    if len(non_flag) < 2 or non_flag[0] != "pr" or non_flag[1] != "merge":
        return None
    idx = args.index("merge")
    rest = args[idx + 1:]
    repo = None
    selector = None
    squash = False
    skip = False
    for i, a in enumerate(rest):
        if skip:
            skip = False
            continue
        if a == "--admin":
            return "--admin merges are blocked (ADR-0002 section 1.2: no administrator overrides)."
        if a in ("--auto",):
            return "--auto merges are blocked: the merge policy must be verified at merge time."
        if a in ("--merge", "--rebase") or c.flag_cluster(a, "mr"):
            return "only squash merges are allowed (use --squash)."
        if a == "--squash" or c.flag_cluster(a, "s"):
            squash = True
        if a in ("-R", "--repo") and i + 1 < len(rest):
            repo = rest[i + 1]
        elif a.startswith("--repo="):
            repo = a.split("=", 1)[1]
        if a in OPT_WITH_VALUE:
            skip = True
        elif not a.startswith("-") and selector is None:
            selector = a
    if not squash:
        return "state the merge method explicitly with --squash (squash is the only allowed method)."
    problems = verify_pr(selector, repo, seg.cwd)
    if problems:
        return "merge policy not satisfied (ADR-0002 section 1): " + "; ".join(problems) + "."
    return None


def evaluate(data):
    name = c.tool_name(data)
    if name != "Bash":
        return "MCP merge tools are blocked (%s). Merge with 'gh pr merge <n> --squash' so the merge policy is verified." % name
    for seg in c.iter_commands(c.bash_command(data), c.input_cwd(data)):
        if not c.is_gh(seg):
            continue
        words = seg.words
        if len(words) > 1 and words[1] == "api":
            blob = " ".join(words[2:]) + " " + " ".join(t for _, t in seg.redirs)
            if API_MERGE.search(blob):
                return "merging through 'gh api' is blocked. Use 'gh pr merge <n> --squash' so the merge policy is verified."
        else:
            reason = check_gh_merge(seg)
            if reason:
                return reason
    return None


if __name__ == "__main__":
    c.run_guard(HOOK, is_guarded, evaluate)
