#!/usr/bin/env bash
# pruned_content.sh -- for each pruned checkout on stdin, emit every file whose ON-DISK bytes are
# not on main, with its blob hash and size. Content-addressed, so copies of the same work across
# many scratch directories collapse to one entry: the question is how much UNIQUE content would
# be lost, not how many directories hold it.
# Objects go to a temp store via GIT_OBJECT_DIRECTORY with the clone as an alternate, so hashing
# writes nothing into anybody's repository.
set -uo pipefail
R=/home/reyerchu/vibe-ic
MAP=/home/reyerchu/_harvb/basemap.tsv
MF=vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/obj"
export GIT_OBJECT_DIRECTORY="$T/obj"
export GIT_ALTERNATE_OBJECT_DIRECTORIES="$R/.git/objects"
isnoise(){ case "$1" in *.claude-plugin/plugin.json|*marketplace.json|*/VERSION|VERSION|*CHANGELOG.md) return 0;; esac; return 1; }
while read -r wt; do
  [ -d "$wt" ] && [ -f "$wt/$MF" ] || continue
  mb=$(git -C "$R" hash-object -- "$wt/$MF" 2>/dev/null)
  base=$(awk -F'\t' -v b="$mb" '$1==b{print $2; exit}' "$MAP"); [ -n "$base" ] || continue
  export GIT_INDEX_FILE="$T/idx"; rm -f "$T/idx"
  git --git-dir="$R/.git" --work-tree="$wt" read-tree "$base" 2>/dev/null || continue
  { git --git-dir="$R/.git" --work-tree="$wt" diff --name-only -- . 2>/dev/null
    git --git-dir="$R/.git" --work-tree="$wt" ls-files --others --exclude-standard -- . 2>/dev/null; } | sort -u | while read -r f; do
    [ -n "$f" ] || continue
    isnoise "$f" && continue
    [ -f "$wt/$f" ] || continue
    a=$(git -C "$R" hash-object -- "$wt/$f" 2>/dev/null) || continue
    b=$(git -C "$R" rev-parse -q --verify "origin/main:$f" 2>/dev/null)
    [ "$a" = "$b" ] && continue
    sz=$(stat -c '%s' "$wt/$f" 2>/dev/null || echo 0)
    printf '%s\t%s\t%s\t%s\n' "$a" "$sz" "$f" "$wt"
  done
done
