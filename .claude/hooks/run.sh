#!/usr/bin/env bash
# Launcher for Agent Factory hooks. Works on Git Bash (Windows) and Linux.
# Usage: run.sh <hook-name>   (executes .claude/hooks/<hook-name>.py)
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
name="${1:-}"
case "$name" in
  guard_*|audit_*) ;;
  *) echo "[agent-factory guardrail] run.sh: invalid hook name" >&2; exit 2 ;;
esac
if [ ! -f "$dir/$name.py" ]; then
  echo "[agent-factory guardrail] run.sh: hook script $name.py not found. Blocked (fail closed)." >&2
  exit 2
fi
py=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)" >/dev/null 2>&1; then
    py="$cand"
    break
  fi
done
if [ -z "$py" ]; then
  echo "[agent-factory guardrail] run.sh: no working Python 3 found. Blocked (fail closed)." >&2
  case "$name" in audit_*) exit 0 ;; esac
  exit 2
fi
exec "$py" "$dir/$name.py"
