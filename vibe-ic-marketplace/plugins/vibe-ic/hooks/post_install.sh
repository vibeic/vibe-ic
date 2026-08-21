#!/bin/bash
# Runs once after plugin install / update. Installs mcp's npm deps
# so the embedded MCP server can launch at next Claude Code load.
#
# v1.6.11 Fix 2 — NEVER block Claude session startup.
# This hook fires on SessionStart. If `set -e` were active, any transient
# failure (offline npm registry, full disk, unwritable cache, npm not in
# PATH on this user's profile) would propagate a non-zero exit and the
# Claude harness would refuse to start the session. The hook is purely an
# optimisation — the embedded mcp can still be installed
# manually later. Therefore: tolerate every failure, always exit 0.
set +e

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$(readlink -f "$0")")")}"
MCP_DIR="$PLUGIN_ROOT/mcp-eda"
if [[ -f "$MCP_DIR/package.json" ]] && [[ ! -d "$MCP_DIR/node_modules" ]]; then
    if command -v npm >/dev/null 2>&1; then
        echo "[vibe-ic post_install] Installing mcp dependencies…"
        # Wrapped so an offline npm / proxy outage / disk-full event does
        # NOT propagate failure out of the hook.
        ( cd "$MCP_DIR" && npm install --production --no-audit --no-fund ) \
            || echo "[vibe-ic post_install] warning: npm install failed (offline / no network / disk?). MCP tools will be unavailable until you run: cd $MCP_DIR && npm install --production" \
            || true
    else
        echo "[vibe-ic post_install] WARNING: npm not found. MCP tools will not work until you run:"
        echo "  cd $MCP_DIR && npm install --production"
    fi
fi

# Always exit 0 — never block session startup, even if the block above
# failed in some unexpected way (race on node_modules, permission error,
# read-only fs, …).
exit 0
