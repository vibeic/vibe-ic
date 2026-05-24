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
echo ""
echo "  The hook will run automatically before each 'git commit'."
echo "  To skip once: git commit --no-verify"
echo "  To uninstall: rm $HOOK_FILE"
echo "============================================"
