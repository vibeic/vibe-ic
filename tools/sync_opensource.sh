#!/bin/bash
# sync_opensource.sh — mirror vibe-ic-marketplace/ + mcp-eda-server/ to
# opensource_repo/ so the public-release tree stays byte-identical with
# the working tree.
#
# Why this exists: between v0.119.5 and v0.119.24 the manual sync step
# was repeatedly missed; the mirror fell behind by 11 new programs +
# 9 modified programs + 12 tests + the entire mcp src/lib refactor
# before anyone noticed. This script makes the sync deterministic and
# verifiable.
#
# Usage
# -----
#   bash tools/sync_opensource.sh           # sync + verify
#   bash tools/sync_opensource.sh --check   # report drift, no changes
#   bash tools/sync_opensource.sh --no-test # sync + verify diff but
#                                           # skip pytest run
#
# Exit codes
# ----------
#   0  — mirror in sync (or successfully brought into sync)
#   1  — sync failed OR post-sync drift detected OR mirror tests failed
#   2  — usage error / project root not found
#
# To invoke automatically before every push, add to
# `.git/hooks/pre-push`:
#   #!/bin/bash
#   bash "$(git rev-parse --show-toplevel)/tools/sync_opensource.sh" || exit 1

set -e

# ---- locate project root --------------------------------------------------
PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$PROJECT_ROOT" ] || [ ! -d "$PROJECT_ROOT/opensource_repo" ]; then
    echo "ERROR: not inside a git repo, or opensource_repo/ not found" >&2
    exit 2
fi
cd "$PROJECT_ROOT"

# ---- arg parsing ----------------------------------------------------------
MODE="sync"
RUN_TESTS=1
for a in "$@"; do
    case "$a" in
        --check)   MODE="check" ;;
        --no-test) RUN_TESTS=0 ;;
        -h|--help)
            sed -n '/^# Usage/,/^# Exit codes/p' "$0" | sed 's/^# \?//'
            exit 0 ;;
        *) echo "unknown flag: $a" >&2; exit 2 ;;
    esac
done

# ---- paths to mirror ------------------------------------------------------
SOURCES=(
    "vibe-ic-marketplace/"
    "mcp-eda-server/"
)

# ---- rsync excludes (share between sync + check diff) ---------------------
EXCLUDES=(
    --exclude='__pycache__'
    --exclude='.pytest_cache'
    --exclude='*.pyc'
    --exclude='node_modules'
    --exclude='.git'
    --exclude='serv_req_info.txt'   # local-only ops note
    # v0.119.25: stray sim outputs and node lock noise — neither is part
    # of the public-release surface, both showed up as drift after a
    # local pytest / npm install.
    --exclude='*.vcd'               # iverilog / verilator sim dumps
    --exclude='*.fst'               # GTKWave fast-sim dumps
    --exclude='package-lock.json'   # node lock — different per host
)

# ---- helpers --------------------------------------------------------------
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
RESET='\033[0m'
say() { printf "${1}${2}${RESET}\n" >&2; }

drift_count() {
    local src=$1 dst=$2
    diff -rq \
        --exclude=__pycache__ --exclude=.pytest_cache \
        --exclude='*.pyc' --exclude=node_modules --exclude=.git \
        --exclude=serv_req_info.txt \
        --exclude='*.vcd' --exclude='*.fst' \
        --exclude=package-lock.json \
        "$src" "$dst" 2>/dev/null | wc -l
}

# ---- Wave 82 mcp-eda dual-tree precheck ------------------------------------
# Before touching opensource_repo/, verify the two in-repo copies of
# mcp-eda-server (root vs plugin mirror) agree. Otherwise the sync
# would happily propagate stale plugin mirror to opensource_repo/.
if [ -x "tools/mcp_eda_sync_check.py" ] || [ -f "tools/mcp_eda_sync_check.py" ]; then
    if ! python3 tools/mcp_eda_sync_check.py >/dev/null 2>&1; then
        say "$RED" "mcp-eda dual-tree drift detected — run:"
        say "$RED" "    python3 tools/mcp_eda_sync_check.py"
        say "$RED" "to see details and reconcile root ↔ plugin BEFORE syncing."
        exit 1
    fi
fi

# ---- check mode: report drift then exit -----------------------------------
if [ "$MODE" = "check" ]; then
    total=0
    for src in "${SOURCES[@]}"; do
        dst="opensource_repo/$src"
        n=$(drift_count "$src" "$dst")
        total=$((total + n))
        if [ "$n" -gt 0 ]; then
            say "$YELLOW" "drift in $src — $n entries"
            diff -rq \
                --exclude=__pycache__ --exclude=.pytest_cache \
                --exclude='*.pyc' --exclude=node_modules --exclude=.git \
                --exclude=serv_req_info.txt \
                "$src" "$dst" 2>/dev/null | head -20 >&2
            [ "$n" -gt 20 ] && say "$YELLOW" "  ... +$((n - 20)) more"
        fi
    done
    if [ "$total" -gt 0 ]; then
        say "$RED" "TOTAL DRIFT: $total entries — run without --check to fix"
        exit 1
    fi
    say "$GREEN" "OK — no drift across $(echo "${SOURCES[@]}" | wc -w) trees"
    exit 0
fi

# ---- sync mode ------------------------------------------------------------
say "$GREEN" "syncing ${#SOURCES[@]} trees → opensource_repo/ ..."
for src in "${SOURCES[@]}"; do
    dst="opensource_repo/$src"
    mkdir -p "$dst"
    rsync -a --delete "${EXCLUDES[@]}" "$src" "$dst"
    say "$GREEN" "  ✓ rsynced $src"
done

# ---- verify zero diff -----------------------------------------------------
total=0
for src in "${SOURCES[@]}"; do
    dst="opensource_repo/$src"
    n=$(drift_count "$src" "$dst")
    total=$((total + n))
done
if [ "$total" -gt 0 ]; then
    say "$RED" "POST-SYNC DRIFT: $total entries — sync failed?"
    exit 1
fi
say "$GREEN" "verified zero drift after sync"

# ---- optionally run mirror tests -----------------------------------------
if [ "$RUN_TESTS" -eq 1 ]; then
    say "$GREEN" "running mirror tests ..."
    plugin_dir="opensource_repo/vibe-ic-marketplace/plugins/vibe-ic"
    mcp_dir="opensource_repo/mcp-eda-server"

    if [ -d "$plugin_dir/tests" ]; then
        if (cd "$plugin_dir" && python3 -m pytest tests/ -q --tb=no \
                >/tmp/sync_opensource_plugin.log 2>&1); then
            n=$(grep -oE '[0-9]+ passed' /tmp/sync_opensource_plugin.log \
                | tail -1 | awk '{print $1}')
            say "$GREEN" "  ✓ plugin: $n tests PASS"
        else
            say "$RED" "  ✗ plugin tests FAILED — see /tmp/sync_opensource_plugin.log"
            tail -20 /tmp/sync_opensource_plugin.log >&2
            exit 1
        fi
    fi

    if [ -d "$mcp_dir/test" ]; then
        if (cd "$mcp_dir" && python3 -m pytest test/ -q --tb=no \
                >/tmp/sync_opensource_mcp.log 2>&1); then
            n=$(grep -oE '[0-9]+ passed' /tmp/sync_opensource_mcp.log \
                | tail -1 | awk '{print $1}')
            say "$GREEN" "  ✓ mcp: $n tests PASS"
        else
            say "$RED" "  ✗ mcp tests FAILED — see /tmp/sync_opensource_mcp.log"
            tail -20 /tmp/sync_opensource_mcp.log >&2
            exit 1
        fi
    fi
fi

say "$GREEN" "DONE — opensource_repo is in sync. Stage with:"
echo "  git add opensource_repo/" >&2
exit 0
