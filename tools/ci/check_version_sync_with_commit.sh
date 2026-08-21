#!/bin/bash
# ============================================================================
# Wave 93 / v1.6.17 — commit-msg ↔ plugin/marketplace version sync check
# ============================================================================
# When a commit message advertises a version (e.g. "v1.6.17", "feat: 1.6.17"),
# this check verifies that:
#   - vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json `version`
#   - vibe-ic-marketplace/.claude-plugin/marketplace.json plugins[0].version
# both already equal that advertised version. Otherwise a "claim ahead of
# bump" pattern slips into history (we hit this 4 times: v1.6.10, v1.6.13,
# v1.6.16, almost v1.6.17). Bumping after the commit lands fixes the file
# but the commit message stays wrong forever.
#
# Behaviour:
#   * Reads commit message from $1 (commit-msg hook handoff) OR
#     .git/COMMIT_EDITMSG (pre-commit hook). Falls back to first arg.
#   * Extracts the FIRST `vX.Y.Z` mention in the SUBJECT line (line 1).
#     Body lines are scanned only if subject has no version. A mention
#     preceded (within a short look-back window) by "supersedes" / "(was" /
#     "fixes" / "from" / "since" / "replaces" / "history" / "deprecates" /
#     "predecessor" is a HISTORICAL reference and skipped — both the
#     "from v1.2.3" and the bare "from 1.2.3" spellings.
#   * If no version is advertised anywhere, exit 0 (skip — not applicable).
#   * If advertised version exists, BOTH plugin.json and marketplace.json
#     must already match it. Mismatch → exit 1 with diagnostic.
#
# Install: invoke from tools/ci/pre_commit_check.sh OR a commit-msg hook.
# Direct CLI: bash tools/ci/check_version_sync_with_commit.sh [<msg-file>]
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# 1. Locate commit message file
MSG_FILE=""
if [ $# -ge 1 ] && [ -f "$1" ]; then
    MSG_FILE="$1"
elif [ -f "$PROJECT_ROOT/.git/COMMIT_EDITMSG" ]; then
    MSG_FILE="$PROJECT_ROOT/.git/COMMIT_EDITMSG"
fi

if [ -z "$MSG_FILE" ] || [ ! -f "$MSG_FILE" ]; then
    # No commit message available (e.g. invoked outside a commit
    # context). Skip — this check is only meaningful at commit time.
    echo "  SKIP: no commit message file available"
    exit 0
fi

# 2. Locate plugin.json + marketplace.json
PLUGIN_JSON="$PROJECT_ROOT/vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json"
MARKET_JSON="$PROJECT_ROOT/vibe-ic-marketplace/.claude-plugin/marketplace.json"

if [ ! -f "$PLUGIN_JSON" ] || [ ! -f "$MARKET_JSON" ]; then
    echo "  SKIP: plugin.json or marketplace.json not found"
    exit 0
fi

# 3. Extract advertised version from commit message
#    - Subject line first; body only if subject has no candidate.
#    - Skip historical-reference mentions ("supersedes vX.Y.Z",
#      "(was vX.Y.Z)", "fixes vX.Y.Z", "from vX.Y.Z").
ADVERTISED=$(python3 - "$MSG_FILE" << 'PYEOF'
import re, sys
from pathlib import Path

msg = Path(sys.argv[1]).read_text(errors="replace")
# Strip comment lines (git uses '#' for hints)
lines = [ln for ln in msg.splitlines() if not ln.lstrip().startswith("#")]
# Drop trailing blank lines so subject is line[0]
while lines and not lines[0].strip():
    lines.pop(0)
if not lines:
    sys.exit(0)

# Pattern: optional 'v', then X.Y.Z (Z required). Reject e.g. "1.0" alone.
VER_RE = re.compile(r"\bv?(\d+\.\d+\.\d+)\b")
# Markers are 'v'-free: the look-back window is sliced at the DIGITS (see
# below), so for "from v1.2.3" the window ends "...from v" and for the bare
# "from 1.2.3" it ends "...from " — a bare "from " marker matches both.
# (ORGANIC-20260606-version-claim-marker-window-off-by-v: the old window was
# sliced at m.start() — the 'v' itself — so every marker that carried a
# trailing " v" could NEVER appear inside the window; "iter-5 from v0.2.50"
# hard-failed despite the documented exemption.)
HIST_MARKERS = ("supersedes", "superseded", "(was", "fixes ", "from ",
                "since ", "history", "deprecates", "replaces ",
                "predecessor", "ref ", "retire")

# In-repo SIBLING version namespaces (mirrors the staged-diff guard's
# carve-out): "flow v2.3.2" cites the canonical-flow DOC version, a
# namespace distinct from plugin semver — never a plugin-version claim.
SIBLING_NS = ("flow",)

def first_version(line: str):
    """Return the first non-historical vX.Y.Z mention in `line`, or None."""
    for m in VER_RE.finditer(line):
        # Look-back window left of the DIGITS (m.start(1)), keeping the
        # optional 'v' prefix inside the window so a marker can abut the
        # version mention in both its "v1.2.3" and "1.2.3" spellings.
        prefix_window = line[max(0, m.start(1) - 30):m.start(1)].lower()
        if any(mk in prefix_window for mk in HIST_MARKERS):
            continue
        # sibling-namespace: the immediately-preceding WORD names a
        # non-plugin version namespace (strict immediacy, same separator
        # set as the staged-diff guard's dependency carve-out).
        head = line[:m.start()].rstrip(" \t([-/:=@")
        w = re.search(r"([A-Za-z][A-Za-z0-9_]*)$", head)
        if w and w.group(1).lower() in SIBLING_NS:
            continue
        return m.group(1)
    return None

# Try subject (line 0) first
subject = lines[0]
ver = first_version(subject)
if ver:
    print(ver)
    sys.exit(0)

# Then scan body
for ln in lines[1:]:
    ver = first_version(ln)
    if ver:
        print(ver)
        sys.exit(0)

# No version advertised
sys.exit(0)
PYEOF
)

if [ -z "$ADVERTISED" ]; then
    # Commit message does not advertise a version → check not applicable
    echo "  SKIP: commit message does not advertise a vX.Y.Z version"
    exit 0
fi

# 4. Read plugin + marketplace versions
PLUGIN_VER=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('version',''))" "$PLUGIN_JSON")
MARKET_VER=$(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
plugins = d.get('plugins', [])
if not plugins:
    print('')
else:
    print(plugins[0].get('version',''))
" "$MARKET_JSON")

# 5. Compare
ERR=0
if [ "$PLUGIN_VER" != "$ADVERTISED" ]; then
    echo "  ERROR: commit msg claims v$ADVERTISED but plugin.json is v$PLUGIN_VER — bump first"
    ERR=1
fi
if [ "$MARKET_VER" != "$ADVERTISED" ]; then
    echo "  ERROR: commit msg claims v$ADVERTISED but marketplace.json plugins[0].version is v$MARKET_VER — bump first"
    ERR=1
fi

if [ $ERR -ne 0 ]; then
    echo "  HINT: edit $PLUGIN_JSON and $MARKET_JSON, set version to $ADVERTISED, restage, and re-commit."
    exit 1
fi

echo "  PASS: commit msg v$ADVERTISED ↔ plugin.json v$PLUGIN_VER ↔ marketplace.json v$MARKET_VER"
exit 0
