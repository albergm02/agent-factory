"""Shared helpers for the Agent Factory guardrail hooks (standard library only).

Hook contract (Claude Code): JSON on stdin; exit 2 blocks a PreToolUse call and
stderr is shown to Claude; exit 0 allows.

Error policy implemented by run_guard():
  * cannot read or classify the input        -> allow (exit 0) + warning in audit log
  * hook errors on a command it must guard  -> block (exit 2, fail closed)
"""
import json
import os
import re
import subprocess
import sys
import time

PREFIX = "[agent-factory guardrail]"
IS_WINDOWS = os.name == "nt"


# --------------------------------------------------------------------------
# I/O, audit warnings
# --------------------------------------------------------------------------
def _write_err(text):
    try:
        sys.stderr.buffer.write((text + "\n").encode("utf-8", "replace"))
        sys.stderr.buffer.flush()
    except Exception:
        pass


def audit_log_path():
    base = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return os.path.join(base, ".claude", "audit", "agent-audit.jsonl")


def append_audit(record):
    """Append one JSON line to the audit log. Never raises."""
    try:
        path = audit_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def warn(hook, message):
    append_audit(
        {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": "warning",
            "hook": hook,
            "message": message,
        }
    )


def block(message):
    _write_err("%s %s" % (PREFIX, message))
    sys.exit(2)


def load_input(hook):
    """Return the hook JSON as a dict, or None when it cannot be read."""
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("input is not a JSON object")
        return data
    except Exception as exc:  # cannot classify -> allow with warning
        warn(hook, "cannot parse hook input: %s" % exc)
        return None


def run_guard(hook, is_guarded, evaluate):
    """Standard main(): classify, then evaluate; see module docstring."""
    data = load_input(hook)
    if data is None:
        sys.exit(0)
    try:
        guarded = is_guarded(data)
    except Exception as exc:
        warn(hook, "cannot classify input: %r" % (exc,))
        sys.exit(0)
    if not guarded:
        sys.exit(0)
    try:
        reason = evaluate(data)
    except SystemExit:
        raise
    except Exception as exc:
        block("hook '%s' failed while checking a guarded action (%s: %s). Blocked (fail closed)."
              % (hook, type(exc).__name__, exc))
    if reason:
        block(reason)
    sys.exit(0)


def tool_name(data):
    name = data.get("tool_name")
    return name if isinstance(name, str) else ""


def tool_input(data):
    ti = data.get("tool_input")
    return ti if isinstance(ti, dict) else {}


def bash_command(data):
    cmd = tool_input(data).get("command")
    return cmd if isinstance(cmd, str) else None


def input_cwd(data):
    cwd = data.get("cwd")
    if isinstance(cwd, str) and cwd:
        return cwd
    return os.getcwd()


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
def to_native(p):
    """Convert Git Bash / cygwin style drive paths to Windows paths."""
    if IS_WINDOWS:
        m = re.match(r"^(?:/cygdrive)?/([A-Za-z])(?:/(.*))?$", p)
        if m:
            return "%s:/%s" % (m.group(1).upper(), m.group(2) or "")
    return p


def expand_home(p):
    home = os.path.expanduser("~")
    p = p.replace("${HOME}", home).replace("$HOME", home)
    if p == "~" or p.startswith("~/") or p.startswith("~\\"):
        p = home + p[1:]
    return p


def resolve(p, base):
    """Absolute, symlink-resolved path (does not need to exist)."""
    p = to_native(expand_home(p))
    if not os.path.isabs(p) or (IS_WINDOWS and not os.path.splitdrive(p)[0]):
        if IS_WINDOWS and p[:1] in ("/", "\\") and not os.path.splitdrive(p)[0]:
            p = os.path.splitdrive(base)[0] + p
        else:
            p = os.path.join(base, p)
    return os.path.realpath(p)


def pkey(p):
    """Comparison key: normalized slashes, case-folded on Windows, no trailing slash."""
    k = os.path.normcase(os.path.normpath(p)).replace("\\", "/")
    if len(k) > 1:
        k = k.rstrip("/")
    return k


def is_under(path, root):
    pk, rk = pkey(path), pkey(root)
    return pk == rk or pk.startswith(rk.rstrip("/") + "/")


def existing_dir(path):
    """Nearest existing directory at or above path."""
    p = path
    while p and not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p if os.path.isdir(p) else os.getcwd()


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------
def git_out(args, cwd, timeout=15):
    """Run git; return stdout stripped, or None when git exits non-zero."""
    r = subprocess.run(
        ["git"] + list(args),
        cwd=existing_dir(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def repo_root(cwd):
    out = git_out(["rev-parse", "--show-toplevel"], cwd)
    return os.path.realpath(out) if out else None


def current_branch(cwd):
    """Checked-out branch name, or None (detached HEAD / not a repo)."""
    out = git_out(["symbolic-ref", "--short", "-q", "HEAD"], cwd)
    return out or None


def main_checkout(data):
    """The session's main checkout: $CLAUDE_PROJECT_DIR, else cwd's repo root."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return resolve(env, os.getcwd())
    return repo_root(input_cwd(data))


# --------------------------------------------------------------------------
# Shell command parsing (best effort; Git Bash / POSIX syntax)
# --------------------------------------------------------------------------
class Segment(object):
    __slots__ = ("words", "redirs", "sep", "cwd")

    def __init__(self, words, redirs, sep):
        self.words = words
        self.redirs = redirs  # list of (operator, target)
        self.sep = sep  # separator that ENDS this segment
        self.cwd = None


def _balanced(text, i):
    """text[i] is the char after '$'; text[i] == '(' -> return index after matching ')'."""
    depth = 0
    j = i
    n = len(text)
    while j < n:
        c = text[j]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return n


def split_segments(cmd):
    segs = []
    st = {"words": [], "redirs": [], "pending": None, "cur": [], "has": False, "heredocs": []}

    def flush():
        if st["has"]:
            w = "".join(st["cur"])
            if st["pending"] is not None:
                op = st["pending"]
                st["redirs"].append((op, w))
                if op in ("<<", "<<-"):
                    st["heredocs"].append((w, op == "<<-"))
                st["pending"] = None
            else:
                st["words"].append(w)
        st["cur"] = []
        st["has"] = False

    def end(sep):
        flush()
        if st["words"] or st["redirs"]:
            segs.append(Segment(st["words"], st["redirs"], sep))
        st["words"] = []
        st["redirs"] = []
        st["pending"] = None

    i = 0
    n = len(cmd)
    while i < n:
        c = cmd[i]
        if c in " \t\r":
            flush()
        elif c == "\n":
            end("\n")
            while st["heredocs"]:
                delim, strip = st["heredocs"].pop(0)
                while i + 1 < n:
                    j = cmd.find("\n", i + 1)
                    line = cmd[i + 1 : (j if j != -1 else n)]
                    i = j if j != -1 else n
                    if (line.lstrip("\t") if strip else line).rstrip("\r") == delim:
                        break
        elif c == "#" and not st["has"]:
            j = cmd.find("\n", i)
            i = (j if j != -1 else n) - 1
        elif c == "'":
            j = cmd.find("'", i + 1)
            j = n if j == -1 else j
            st["cur"].append(cmd[i + 1 : j])
            st["has"] = True
            i = j
        elif c == '"':
            st["has"] = True
            i += 1
            while i < n and cmd[i] != '"':
                if cmd[i] == "\\" and i + 1 < n and cmd[i + 1] in '"\\$`':
                    st["cur"].append(cmd[i + 1])
                    i += 2
                elif cmd[i] == "$" and i + 1 < n and cmd[i + 1] == "(":
                    j = _balanced(cmd, i + 1)
                    st["cur"].append(cmd[i:j])
                    i = j
                else:
                    st["cur"].append(cmd[i])
                    i += 1
        elif c == "\\":
            if i + 1 < n and cmd[i + 1] == "\n":
                i += 1
            elif i + 1 < n and cmd[i + 1] in " \t\"'$`&|;<>()#*?\\":
                st["cur"].append(cmd[i + 1])
                st["has"] = True
                i += 1
            else:
                st["cur"].append("\\")
                st["has"] = True
        elif c == "$" and i + 1 < n and cmd[i + 1] == "(":
            j = _balanced(cmd, i + 1)
            st["cur"].append(cmd[i:j])
            st["has"] = True
            i = j - 1
        elif c == "`":
            j = cmd.find("`", i + 1)
            j = n - 1 if j == -1 else j
            st["cur"].append(cmd[i : j + 1])
            st["has"] = True
            i = j
        elif c == ";":
            end(";")
        elif c == "|":
            if i + 1 < n and cmd[i + 1] == "|":
                end("||")
                i += 1
            elif i + 1 < n and cmd[i + 1] == "&":
                end("|&")
                i += 1
            else:
                end("|")
        elif c == "&":
            if i + 1 < n and cmd[i + 1] == "&":
                end("&&")
                i += 1
            elif i + 1 < n and cmd[i + 1] == ">":
                flush()
                i += 1
                if i + 1 < n and cmd[i + 1] == ">":
                    i += 1
                st["pending"] = ">"
            else:
                end("&")
        elif c == ">":
            if st["has"] and "".join(st["cur"]).isdigit():
                st["cur"] = []
                st["has"] = False
            flush()
            if i + 1 < n and cmd[i + 1] == ">":
                i += 1
                st["pending"] = ">>"
            elif i + 1 < n and cmd[i + 1] == "|":
                i += 1
                st["pending"] = ">"
            elif i + 1 < n and cmd[i + 1] == "&":
                i += 1
                while i + 1 < n and cmd[i + 1] in "0123456789-":
                    i += 1
            else:
                st["pending"] = ">"
        elif c == "<":
            flush()
            if cmd.startswith("<<<", i):
                i += 2
                st["pending"] = "<<<"
            elif cmd.startswith("<<-", i):
                i += 2
                st["pending"] = "<<-"
            elif cmd.startswith("<<", i):
                i += 1
                st["pending"] = "<<"
            else:
                st["pending"] = "<"
        elif c in "()":
            end("(")
        else:
            st["cur"].append(c)
            st["has"] = True
        i += 1
    end("\n")
    return segs


_PREFIX_WORDS = {"sudo", "env", "command", "nohup", "time", "exec", "builtin", "nice", "!", "{", "}"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}


def base_cmd(word):
    b = os.path.basename(word.replace("\\", "/")).lower()
    if b.endswith(".exe"):
        b = b[:-4]
    return b


def strip_prefix(words):
    i = 0
    while i < len(words) and (words[i] in _PREFIX_WORDS or _ASSIGN.match(words[i])):
        i += 1
    return words[i:]


def find_subshells(word):
    """Inner command strings of $(...) and `...` inside one word."""
    out = []
    i = 0
    while i < len(word):
        if word.startswith("$(", i):
            j = _balanced(word, i + 1)
            out.append(word[i + 2 : j - 1])
            i = j
        elif word[i] == "`":
            j = word.find("`", i + 1)
            if j == -1:
                break
            out.append(word[i + 1 : j])
            i = j + 1
        else:
            i += 1
    return out


def _cd_target(words, cwd):
    args = [w for w in words[1:] if w not in ("--", "-L", "-P", "-e", "-@")]
    if not args:
        return resolve("~", cwd)
    if args[0] == "-":
        return cwd
    return resolve(args[0], cwd)


def iter_commands(cmd, cwd, depth=0):
    """Yield Segment objects (words already prefix-stripped, .cwd = effective cwd).

    Tracks `cd`/`pushd`, and recurses into `bash -c "..."`, `eval` and $(...).
    """
    if depth > 4:
        return
    cur = cwd
    for seg in split_segments(cmd):
        # nested command substitutions in words and redirect targets
        subs = []
        for w in seg.words + [t for _, t in seg.redirs]:
            subs.extend(find_subshells(w))
        for inner in subs:
            for s in iter_commands(inner, cur, depth + 1):
                yield s
        words = strip_prefix(seg.words)
        if not words:
            continue
        name = base_cmd(words[0])
        if name in ("cd", "pushd", "chdir"):
            try:
                cur = _cd_target(words, cur)
            except Exception:
                pass
            continue
        seg.words = words
        seg.cwd = cur
        yield seg
        if name in _SHELLS:
            for k, w in enumerate(words[1:], 1):
                if w.startswith("-") and not w.startswith("--") and "c" in w[1:] and k + 1 < len(words):
                    for s in iter_commands(words[k + 1], cur, depth + 1):
                        yield s
                    break
        elif name == "eval" and len(words) > 1:
            for s in iter_commands(" ".join(words[1:]), cur, depth + 1):
                yield s


def parse_git(words, cwd):
    """Parse `git [global opts] <sub> args`.

    Returns (subcommand or None, args, effective_cwd, config_pairs).
    """
    i = 1
    eff = cwd
    confs = []
    n = len(words)
    while i < n:
        w = words[i]
        if w == "-C" and i + 1 < n:
            eff = resolve(words[i + 1], eff)
            i += 2
        elif w == "-c" and i + 1 < n:
            confs.append(words[i + 1])
            i += 2
        elif w in ("--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix") and i + 1 < n:
            i += 2
        elif w.startswith("-"):
            i += 1
        else:
            break
    sub = words[i] if i < n else None
    return sub, words[i + 1 :], eff, confs


def is_git(seg):
    return bool(seg.words) and base_cmd(seg.words[0]) == "git"


def is_gh(seg):
    return bool(seg.words) and base_cmd(seg.words[0]) == "gh"


def flag_cluster(arg, letters):
    """True when arg is a short-option cluster (-fdx) containing any of letters."""
    return arg.startswith("-") and not arg.startswith("--") and len(arg) > 1 and any(c in arg[1:] for c in letters)


def gh_method(words):
    """HTTP method of a `gh api` call from -X/--method, else None."""
    for i, w in enumerate(words):
        if w in ("-X", "--method") and i + 1 < len(words):
            return words[i + 1].upper()
        if w.startswith("--method="):
            return w.split("=", 1)[1].upper()
        if w.startswith("-X") and len(w) > 2:
            return w[2:].upper()
    return None


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------
_TOKEN_PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
]


def redact(text):
    for pat in _TOKEN_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text
