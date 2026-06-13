#!/bin/bash
# ============================================================================
# Install Vibe-IC Pre-Commit Hook
# ============================================================================
# Installs the pre-commit check script into .git/hooks/pre-commit.
#
# Usage:
#   bash tools/ci/install_hooks.sh
#
# To uninstall:
#   rm .git/hooks/pre-commit
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GIT_DIR="$PROJECT_ROOT/.git"

# Check if we're in a git repository
if [ ! -d "$GIT_DIR" ]; then
    echo "ERROR: Not a git repository. Initialize with 'git init' first."
    exit 1
fi

# Create hooks directory if it doesn't exist
HOOKS_DIR="$GIT_DIR/hooks"
mkdir -p "$HOOKS_DIR"

# Install pre-commit hook
HOOK_FILE="$HOOKS_DIR/pre-commit"
PRE_COMMIT_SCRIPT="$PROJECT_ROOT/tools/ci/pre_commit_check.sh"

if [ ! -f "$PRE_COMMIT_SCRIPT" ]; then
    echo "ERROR: Pre-commit script not found at: $PRE_COMMIT_SCRIPT"
    exit 1
fi

# Back up existing hook if present
if [ -f "$HOOK_FILE" ]; then
    BACKUP="$HOOK_FILE.backup.$(date +%Y%m%d%H%M%S)"
    cp "$HOOK_FILE" "$BACKUP"
    echo "Existing pre-commit hook backed up to: $BACKUP"
fi

# Write the hook
cat > "$HOOK_FILE" << 'HOOKEOF'
#!/bin/bash
# Vibe-IC Pre-Commit Hook
# Installed by: tools/ci/install_hooks.sh
# To uninstall: rm .git/hooks/pre-commit

# Find project root (where .git lives)
PROJECT_ROOT="$(git rev-parse --show-toplevel)"
PRE_COMMIT_SCRIPT="$PROJECT_ROOT/tools/ci/pre_commit_check.sh"

if [ -f "$PRE_COMMIT_SCRIPT" ]; then
    bash "$PRE_COMMIT_SCRIPT"
    exit $?
else
    echo "WARNING: Pre-commit script not found at $PRE_COMMIT_SCRIPT"
    echo "Skipping pre-commit checks."
    exit 0
fi
HOOKEOF

chmod +x "$HOOK_FILE"

echo "============================================"
echo "  Vibe-IC Pre-Commit Hook Installed"
echo "============================================"
echo "  Hook:   $HOOK_FILE"
echo "  Script: $PRE_COMMIT_SCRIPT"

# ----------------------------------------------------------------------
# Wave 93 / v1.6.17 — also install commit-msg hook for version-sync.
# git passes the active commit-message file as $1 to commit-msg hooks,
# which is the only reliable place to enforce "commit msg vX.Y.Z must
# match plugin.json + marketplace.json". Pre-commit cannot read the
# active message reliably (-m bypass + COMMIT_EDITMSG residue).
# ----------------------------------------------------------------------
COMMIT_MSG_HOOK="$HOOKS_DIR/commit-msg"
VERSION_SYNC_SCRIPT="$PROJECT_ROOT/tools/ci/check_version_sync_with_commit.sh"

if [ -f "$VERSION_SYNC_SCRIPT" ]; then
    # Back up existing commit-msg hook if present
    if [ -f "$COMMIT_MSG_HOOK" ]; then
        BACKUP="$COMMIT_MSG_HOOK.backup.$(date +%Y%m%d%H%M%S)"
        cp "$COMMIT_MSG_HOOK" "$BACKUP"
        echo "Existing commit-msg hook backed up to: $BACKUP"
    fi

    cat > "$COMMIT_MSG_HOOK" << 'CMHOOKEOF'
#!/bin/bash
# Vibe-IC Commit-Msg Hook (Wave 93 / v1.6.17)
# Installed by: tools/ci/install_hooks.sh
# Validates: when commit msg advertises a vX.Y.Z, plugin.json +
# marketplace.json plugins[0].version must already match.
# To uninstall: rm .git/hooks/commit-msg

PROJECT_ROOT="$(git rev-parse --show-toplevel)"
SYNC_SCRIPT="$PROJECT_ROOT/tools/ci/check_version_sync_with_commit.sh"

if [ -x "$SYNC_SCRIPT" ]; then
    bash "$SYNC_SCRIPT" "$1"
    exit $?
else
    echo "WARNING: version-sync script not found at $SYNC_SCRIPT"
    echo "Skipping commit-msg version-sync check."
    exit 0
fi
CMHOOKEOF
    chmod +x "$COMMIT_MSG_HOOK"
    echo "  Hook:   $COMMIT_MSG_HOOK"
    echo "  Script: $VERSION_SYNC_SCRIPT"
fi

echo ""
echo "  The hooks run automatically on each 'git commit'."
echo "  To skip once: git commit --no-verify"
echo "  To uninstall: rm $HOOK_FILE $COMMIT_MSG_HOOK"
echo "============================================"
