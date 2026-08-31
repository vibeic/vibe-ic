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

# #1931 — the guard must ask the REAL question. `! -d node_modules` passed
# over a HALF-EXTRACTED tree (an interrupted `npm install` left 91 of 93
# packages in, the SDK dir holding only dist/, and .package-lock.json
# recording the install as complete), so the hook silently skipped the one
# state it exists to repair. deps_complete.mjs compares the installed set
# against the lockfile; a directory that merely exists no longer passes.
# node absent → fall back to the old directory test (npm needs node anyway,
# so no repair was possible on such a host either way).
_deps_incomplete() {
    if command -v node >/dev/null 2>&1; then
        node "$MCP_DIR/src/deps_complete.mjs" --pkg-root "$MCP_DIR" >/dev/null 2>&1
        [[ $? -ne 0 ]]
    else
        [[ ! -d "$MCP_DIR/node_modules" ]]
    fi
}

if [[ -f "$MCP_DIR/package.json" ]] && _deps_incomplete; then
    if command -v npm >/dev/null 2>&1; then
        echo "[vibe-ic post_install] Installing mcp dependencies…"
        # Wrapped so an offline npm / proxy outage / disk-full event does
        # NOT propagate failure out of the hook.
        ( cd "$MCP_DIR" && npm install --production --no-audit --no-fund ) \
            || echo "[vibe-ic post_install] warning: npm install failed (offline / no network / disk?). MCP tools will be unavailable until you run: cd $MCP_DIR && npm install --production" \
            || true
        if _deps_incomplete; then
            # npm read the (lying) .package-lock.json and no-opped, or tripped
            # on abandoned staging dirs. Corrupt beyond incremental repair —
            # the only recovery measured to work (#1931): wipe + fresh install.
            echo "[vibe-ic post_install] node_modules still incomplete after npm install — wiping and reinstalling"
            [[ -n "$MCP_DIR" && -d "$MCP_DIR/node_modules" ]] && rm -rf "$MCP_DIR/node_modules"
            ( cd "$MCP_DIR" && npm install --production --no-audit --no-fund ) \
                || echo "[vibe-ic post_install] warning: fresh npm install failed. Run manually: cd $MCP_DIR && rm -rf node_modules && npm install --production" \
                || true
        fi
        if ! _deps_incomplete && command -v node >/dev/null 2>&1; then
            # Repair succeeded — drop the MCP client's stale needs-auth cache
            # entry so the repaired server is retried, not left marked broken.
            node "$MCP_DIR/src/deps_complete.mjs" --clear-needs-auth-cache >/dev/null 2>&1 || true
        fi
    else
        echo "[vibe-ic post_install] WARNING: npm not found. MCP tools will not work until you run:"
        echo "  cd $MCP_DIR && npm install --production"
    fi
fi

# Always exit 0 — never block session startup, even if the block above
# failed in some unexpected way (race on node_modules, permission error,
# read-only fs, …).
exit 0
