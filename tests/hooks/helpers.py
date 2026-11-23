"""Test helpers: run a hook script with JSON on stdin, build temp git repos, fake gh."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOK_DIR = os.path.join(ROOT, ".claude", "hooks")
IS_WINDOWS = os.name == "nt"


def run_hook(name, payload, project_dir=None, extra_env=None, raw=None):
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if project_dir:
        env["CLAUDE_PROJECT_DIR"] = project_dir
    env.update(extra_env or {})
    data = raw if raw is not None else json.dumps(payload).encode("utf-8")
    r = subprocess.run(
        [sys.executable, os.path.join(HOOK_DIR, name + ".py")],
        input=data, capture_output=True, env=env, timeout=120,
    )
    return r.returncode, r.stderr.decode("utf-8", "replace")


def bash(cmd, cwd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd}


def git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True)


def make_repo(path, branch="main"):
    os.makedirs(path, exist_ok=True)
    git(["init", "-q", "-b", branch], path)
    git(["config", "user.email", "t@example.com"], path)
    git(["config", "user.name", "t"], path)
    git(["config", "commit.gpgsign", "false"], path)
    with open(os.path.join(path, "README.md"), "w") as fh:
        fh.write("x\n")
    git(["add", "."], path)
    git(["commit", "-q", "-m", "init"], path)
    return os.path.realpath(path)


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="afhooks-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def assertBlocked(self, result, text=None):
        code, err = result
        self.assertEqual(code, 2, err)
        self.assertTrue(err.startswith("[agent-factory guardrail]"), err)
        if text:
            self.assertIn(text, err)

    def assertAllowed(self, result):
        code, err = result
        self.assertEqual(code, 0, err)


def make_fake_gh(dirpath, payload, rc=0):
    """Create a fake `gh` first on PATH. Returns env dict to pass to run_hook."""
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, "payload.json"), "w") as fh:
        json.dump(payload, fh)
    py = os.path.join(dirpath, "fake_gh.py")
    with open(py, "w") as fh:
        fh.write(
            "import sys\n"
            "if %d:\n    sys.stderr.write('boom')\n    sys.exit(%d)\n"
            "print(open(%r).read())\n" % (rc, rc, os.path.join(dirpath, "payload.json"))
        )
    if IS_WINDOWS:
        with open(os.path.join(dirpath, "gh.cmd"), "w") as fh:
            fh.write('@"%s" "%s" %%*\r\n' % (sys.executable, py))
    else:
        p = os.path.join(dirpath, "gh")
        with open(p, "w") as fh:
            fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, py))
        os.chmod(p, 0o755)
    return {"PATH": dirpath + os.pathsep + os.environ.get("PATH", "")}
