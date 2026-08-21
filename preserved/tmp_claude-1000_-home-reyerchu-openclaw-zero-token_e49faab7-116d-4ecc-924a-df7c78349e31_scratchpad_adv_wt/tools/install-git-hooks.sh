#!/usr/bin/env bash
# install-git-hooks.sh — symlink this repo's tracked hooks into .git/hooks/.
#
# `.git/hooks/` is NOT tracked by git, so a hook committed to the repo does
# nothing until it is installed. This installer symlinks (not copies) so a later
# `git pull` that improves a hook takes effect immediately, with no re-install.
#
# Usage:
#     tools/install-git-hooks.sh            # install (refuses to clobber)
#     tools/install-git-hooks.sh --force    # replace existing hooks, and
#                                           # install from a linked worktree
set -euo pipefail

FORCE=0
for _arg in "$@"; do
  case "$_arg" in
    --force) FORCE=1 ;;
    # AN UNRECOGNISED ARGUMENT WAS SILENTLY IGNORED, and the only flag this
    # script has is the one that disarms its refusals. `--frce`, or `--force`
    # in second position under the old `[ "${1:-}" = --force ]` test, read as
    # a plain install and the user was told nothing.
    *) echo "install-git-hooks.sh: unknown argument: $_arg" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(git rev-parse --show-toplevel)"
SRC_DIR="$REPO_ROOT/tools/git-hooks"
DST_DIR="$(git rev-parse --git-path hooks)"
# A RELATIVE GIT PATH IS RELATIVE TO CWD, NOT TO THE REPO ROOT. Joining it to
# `$REPO_ROOT` installed the hooks OUTSIDE the repository whenever the script was
# invoked from a subdirectory, and said "2 hook(s) installed" while doing it.
# MEASURED, git 2.34.1:
#
#     cwd = <repo>          git rev-parse --git-path hooks -> .git/hooks
#     cwd = <repo>/tools    git rev-parse --git-path hooks -> ../.git/hooks
#
# so `$REPO_ROOT/../.git/hooks` — a directory beside the repo, which `mkdir -p`
# creates without complaint. The report was a success, the guard was not
# installed, and nothing anywhere said so. Found by
# `test_a_main_checkout_installs_from_a_subdirectory_too`, which was written for
# the worktree detection and caught this instead.
case "$DST_DIR" in /*) ;; *) DST_DIR="$PWD/$DST_DIR" ;; esac

# --- INSTALLING FROM A LINKED WORKTREE ARMS A TIME BOMB IN EVERY CHECKOUT -----
#
# Hooks live in the SHARED git dir: `git rev-parse --git-path hooks` answers the
# common `.git/hooks` from a linked worktree too, which is the point of the
# feature and the whole problem here. So a `ln -s` against THIS worktree's
# `tools/git-hooks/` does not configure this worktree — it points the one hook
# every checkout of this repository runs at a directory that is, by the dispatch
# doctrine that tells every agent to work in a throwaway worktree, temporary.
#
# When the worktree is removed the symlink dangles, and git does not complain:
# a hook path that does not resolve is treated as NO HOOK AT ALL, with no
# message, no exit code, nothing in the push output. The guard that comes off is
# the NDA guard. Nobody finds out by pushing; you find out by auditing.
#
# The pre-push hook cannot cover this. Its own staleness self-check is inside the
# hook, and a hook that is never executed cannot check anything — which is why
# this refusal lives here, before the symlink exists, rather than there.
#
# DETECTED BY RESOLVING BOTH DIRS, not by comparing `--git-common-dir` to the
# string `.git`. MEASURED on git 2.34.1:
#
#     main checkout, cwd = toplevel    --git-dir .git      --git-common-dir .git
#     main checkout, cwd = tools/      --git-dir <abs>      --git-common-dir ../.git
#     linked worktree, any cwd         --git-dir <abs>/worktrees/<n>   <abs>/.git
#
# `--git-common-dir` is resolved RELATIVE TO CWD, so the literal-`.git` test
# reports "linked worktree" for a main checkout the moment someone runs this
# from a subdirectory — a false refusal of the ordinary case. Resolving both to
# physical paths is right in all six cells above.
OWN_GIT_DIR="$(git rev-parse --absolute-git-dir)"
COMMON_GIT_DIR="$(git rev-parse --git-common-dir)"
case "$COMMON_GIT_DIR" in /*) ;; *) COMMON_GIT_DIR="$PWD/$COMMON_GIT_DIR" ;; esac
OWN_GIT_DIR="$(cd "$OWN_GIT_DIR" && pwd -P)"
COMMON_GIT_DIR="$(cd "$COMMON_GIT_DIR" && pwd -P)"

if [ "$OWN_GIT_DIR" != "$COMMON_GIT_DIR" ]; then
  MAIN_WORKTREE="$(git worktree list --porcelain | sed -n '1s/^worktree //p')"
  if [ "$FORCE" -ne 1 ]; then
    echo "install-git-hooks.sh: REFUSING — this is a linked worktree, not the main checkout." >&2
    echo "    worktree git dir: $OWN_GIT_DIR" >&2
    echo "    shared git dir:   $COMMON_GIT_DIR" >&2
    echo "    Hooks live in the SHARED git dir, so every checkout of this repository" >&2
    echo "    runs the one hook installed there. Installing from here would point it at" >&2
    echo "        $SRC_DIR" >&2
    echo "    which disappears with this worktree. git treats a dangling hook symlink as" >&2
    echo "    NO HOOK and says nothing, so the NDA guard would come off for every" >&2
    echo "    checkout, silently, at a moment nobody is watching." >&2
    if [ -n "${MAIN_WORKTREE:-}" ]; then
      echo "    Run it from the main checkout instead:" >&2
      echo "        $MAIN_WORKTREE/tools/install-git-hooks.sh" >&2
    fi
    echo "    Or pass --force to install from here anyway — and re-run it from the main" >&2
    echo "    checkout before this worktree is removed." >&2
    exit 1
  fi
  echo "WARNING: installing from a LINKED WORKTREE because --force was given." >&2
  echo "         The shared hooks in $COMMON_GIT_DIR/hooks will point into" >&2
  echo "         $SRC_DIR and STOP RUNNING — silently — when this worktree is" >&2
  echo "         removed. Re-run from ${MAIN_WORKTREE:-the main checkout} before then." >&2
fi

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
