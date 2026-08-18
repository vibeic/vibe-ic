#!/usr/bin/env bash
# install-git-hooks.sh — symlink this repo's tracked hooks into .git/hooks/.
#
# `.git/hooks/` is NOT tracked by git, so a hook committed to the repo does
# nothing until it is installed. This installer symlinks (not copies) so a later
# `git pull` that improves a hook takes effect immediately, with no re-install.
#
# Usage:
#     tools/install-git-hooks.sh            # install (refuses to clobber)
#     tools/install-git-hooks.sh --force    # replace existing hooks
set -euo pipefail

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

REPO_ROOT="$(git rev-parse --show-toplevel)"
SRC_DIR="$REPO_ROOT/tools/git-hooks"
DST_DIR="$(git rev-parse --git-path hooks)"
case "$DST_DIR" in /*) ;; *) DST_DIR="$REPO_ROOT/$DST_DIR" ;; esac

mkdir -p "$DST_DIR"
installed=0
skipped=0

for src in "$SRC_DIR"/*; do
  name="$(basename "$src")"
  # README / docs in the hooks dir are not hooks.
  case "$name" in *.md|*.txt) continue ;; esac
  dst="$DST_DIR/$name"

  if [ -e "$dst" ] || [ -L "$dst" ]; then
    # Already OUR symlink -> nothing to do (idempotent re-run).
    if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
      echo "ok       $name (already installed)"
      continue
    fi
    if [ "$FORCE" -ne 1 ]; then
      echo "SKIP     $name — a different hook is already installed." >&2
      echo "         Inspect $dst, then re-run with --force to replace it." >&2
      skipped=$((skipped + 1))
      continue
    fi
    rm -f "$dst"
  fi

  chmod +x "$src"
  ln -s "$src" "$dst"
  echo "installed $name -> $src"
  installed=$((installed + 1))
done

echo
echo "$installed hook(s) installed, $skipped skipped, into $DST_DIR"
if [ "$skipped" -ne 0 ]; then
  echo "WARNING: some hooks were NOT installed — the NDA message guard is" >&2
  echo "         only partially active. Re-run with --force." >&2
  exit 1
fi
