#!/usr/bin/env bash
# install-git-hooks.sh — symlink this repo's tracked hooks into .git/hooks/,
# and register this repo's tracked merge drivers in .git/config.
#
# `.git/hooks/` is NOT tracked by git, so a hook committed to the repo does
# nothing until it is installed. This installer symlinks (not copies) so a later
# `git pull` that improves a hook takes effect immediately, with no re-install.
#
# `.git/config` is not tracked either, and a merge driver NAMED by the tracked
# `.gitattributes` is inert until it is DEFINED there — the same failure mode one
# step over, and a quieter one: git falls back to the ordinary 3-way merge without
# a word, so an uninstalled driver is indistinguishable from no driver at all.
# Both are therefore installed by the same command.
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

# ---------------------------------------------------------------------------
# Merge drivers. `.gitattributes` NAMES them; `.git/config` DEFINES them.
# ---------------------------------------------------------------------------
DRIVER_SRC="$REPO_ROOT/tools/git-merge-drivers/programs_index_merge.sh"
if [ -f "$DRIVER_SRC" ]; then
  chmod +x "$DRIVER_SRC"
  git config merge.programs-index.name \
    "regenerate programs/INDEX.md from the merged tree (tools/gen_programs_index.py)"
  git config merge.programs-index.driver "'$DRIVER_SRC' %O %A %B %P"
  echo "installed merge driver programs-index -> $DRIVER_SRC"
else
  echo "SKIP     merge driver programs-index — $DRIVER_SRC not found." >&2
  skipped=$((skipped + 1))
fi

echo
echo "$installed hook(s) installed, $skipped skipped, into $DST_DIR"
if [ "$skipped" -ne 0 ]; then
  echo "WARNING: some hooks were NOT installed — the NDA message guard is" >&2
  echo "         only partially active. Re-run with --force." >&2
  exit 1
fi
