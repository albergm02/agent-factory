#!/usr/bin/env python3
"""Validate Markdown files in the repository (standard library only).

Checks: no UTF-8 BOM, no CR characters, final newline, relative links resolve,
#anchors match GitHub heading slugs, and tables have a consistent pipe count.

Usage: python scripts/check_docs.py [--git-index]

--git-index reads content of tracked files from the git index instead of the
working tree. Use it on Windows with core.autocrlf=true, where the working
tree has CRLF while the repository content is LF. CI (Linux) does not need it.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED = {".git", "node_modules"}
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
LINK_RE = re.compile(r"(?<!!)\[(?:[^\]]*)\]\(\s*<?([^)\s>]*)>?(?:\s+[^)]*)?\)")
IMG_RE = re.compile(r"!\[(?:[^\]]*)\]\(\s*<?([^)\s>]*)>?(?:\s+[^)]*)?\)")
CODE_SPAN_RE = re.compile(r"`+[^`]*`+")
SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def find_files():
    out = []
    for p in sorted(ROOT.rglob("*.md")):
        rel = p.relative_to(ROOT)
        if not EXCLUDED.intersection(rel.parts):
            out.append(rel)
    return out


def read_bytes(rel, use_index):
    if use_index:
        r = subprocess.run(
            ["git", "show", ":" + rel.as_posix()],
            cwd=ROOT, capture_output=True,
        )
        if r.returncode == 0:
            return r.stdout
    return (ROOT / rel).read_bytes()


def slugify(text):
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links -> text
    text = text.replace("`", "").replace("*", "")
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def scan_lines(lines):
    """Yield (lineno, line, in_fence) for each line."""
    fence = None
    for i, line in enumerate(lines, 1):
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker[0]
                yield i, line, True
                continue
            if marker[0] == fence:
                fence = None
                yield i, line, True
                continue
        yield i, line, fence is not None


def headings_of(lines):
    slugs, seen = set(), {}
    for _, line, in_fence in scan_lines(lines):
        if in_fence:
            continue
        m = HEADING_RE.match(line)
        if m:
            s = slugify(m.group(2))
            n = seen.get(s, 0)
            seen[s] = n + 1
            slugs.add(s if n == 0 else f"{s}-{n}")
    return slugs


def pipe_count(line):
    """Count unescaped pipes (GFM splits cells on them even inside code spans)."""
    return len(line.replace(chr(92) + "|", "").split("|")) - 1


def main():
    use_index = "--git-index" in sys.argv[1:]
    problems = []
    docs = {}
    for rel in find_files():
        raw = read_bytes(rel, use_index)
        docs[rel] = raw
    parsed = {}
    for rel, raw in docs.items():
        p = rel.as_posix()
        if raw.startswith(b"\xef\xbb\xbf"):
            problems.append(f"{p}:1: UTF-8 BOM present")
        if b"\r" in raw:
            ln = raw[: raw.index(b"\r")].count(b"\n") + 1
            problems.append(f"{p}:{ln}: CR character found (use LF line endings)")
        if raw and not raw.endswith(b"\n"):
            problems.append(f"{p}:{raw.count(chr(10).encode()) + 1}: missing final newline")
        text = raw.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        parsed[rel] = (lines, headings_of(lines))

    for rel, (lines, _) in parsed.items():
        p = rel.as_posix()
        table_counts = None
        for i, line, in_fence in scan_lines(lines):
            if in_fence:
                table_counts = None
                continue
            # tables
            if line.lstrip().startswith("|") or (table_counts is not None and "|" in line):
                c = pipe_count(line)
                if table_counts is None:
                    table_counts = c
                elif c != table_counts:
                    problems.append(f"{p}:{i}: table row has {c} pipes, expected {table_counts}")
            else:
                table_counts = None
            # links
            stripped = CODE_SPAN_RE.sub("", line)
            for m in list(LINK_RE.finditer(stripped)) + list(IMG_RE.finditer(stripped)):
                target = m.group(1)
                if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                    continue
                path_part, _, anchor = target.partition("#")
                if path_part:
                    dest = (ROOT / rel.parent / path_part.split("?")[0]).resolve()
                    try:
                        drel = dest.relative_to(ROOT)
                    except ValueError:
                        problems.append(f"{p}:{i}: link escapes repository: {target}")
                        continue
                    if not dest.exists():
                        problems.append(f"{p}:{i}: broken link target: {target}")
                        continue
                else:
                    drel = rel
                if anchor and not path_part.endswith("/"):
                    if drel in parsed:
                        slugs = parsed[drel][1]
                    elif dest_is_md(drel):
                        slugs = headings_of(read_bytes(drel, use_index).decode("utf-8", "replace").split("\n"))
                    else:
                        continue
                    if anchor.lower() not in slugs:
                        problems.append(f"{p}:{i}: broken anchor: {target}")

    for pr in problems:
        print(pr)
    if problems:
        print(f"{len(problems)} problem(s) found", file=sys.stderr)
        return 1
    print(f"OK: {len(parsed)} markdown file(s) checked")
    return 0


def dest_is_md(rel):
    return rel.suffix.lower() == ".md" and (ROOT / rel).is_file()


if __name__ == "__main__":
    sys.exit(main())
