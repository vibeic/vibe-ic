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

#: A line every hook in tools/git-hooks/ carries, used ONLY to tell "our hook,
#: out of date" apart from "somebody else's hook". Matched in the first 40 lines.
HOOK_MARKER="vibe-ic"
stale=0

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
      # TWO DIFFERENT SITUATIONS, AND THEY USED TO PRINT THE SAME SENTENCE.
      # "a different hook is already installed" is true of somebody's
      # deliberate local hook AND of a STALE COPY of this very file — and only
      # one of those is a problem. MEASURED 2026-08-28: a copy of `pre-push`
      # installed on 2026-08-17 was still telling people to re-run with
      # `--differential`, a flag REMOVED on 2026-08-28. It had been eleven days
      # out of date and every re-run of this installer said "SKIP" and moved on,
      # because a stale copy of our own hook is "a different hook" too.
      if [ ! -L "$dst" ] && cmp -s <(sed 's/[[:space:]]*$//' "$src") \
                                   <(sed 's/[[:space:]]*$//' "$dst"); then
        echo "ok       $name (installed as a copy, content matches)"
        continue
      fi
      if [ ! -L "$dst" ] && head -40 "$dst" 2>/dev/null | grep -q "$HOOK_MARKER"; then
        echo "STALE    $name — this is OUR hook, but an OUT-OF-DATE COPY." >&2
        echo "         Installed $(date -r "$dst" +%F 2>/dev/null || echo 'at an unknown date'), and the tracked" >&2
        echo "         version has since changed. A stale hook does not fail loudly:" >&2
        echo "         it enforces yesterday's rules and names flags that no longer" >&2
        echo "         exist. Re-run with --force to replace it." >&2
        stale=$((stale + 1))
        continue
      fi
      echo "SKIP     $name — a hook that is not ours is already installed." >&2
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
echo "$installed hook(s) installed, $skipped skipped, $stale stale, into $DST_DIR"
if [ "$stale" -ne 0 ]; then
  echo "WARNING: $stale hook(s) are OUR OWN, INSTALLED AND OUT OF DATE." >&2
  echo "         This is the worse of the two states and it is why it exits" >&2
  echo "         non-zero: a MISSING hook enforces nothing and you find out at" >&2
  echo "         the first push, whereas a STALE hook runs, passes, and" >&2
  echo "         enforces the rules of the day it was copied. Re-run with --force." >&2
fi
if [ "$skipped" -ne 0 ]; then
  echo "WARNING: some hooks were NOT installed — the NDA message guard is" >&2
  echo "         only partially active. Re-run with --force." >&2
fi
if [ "$skipped" -ne 0 ] || [ "$stale" -ne 0 ]; then
  exit 1
fi
