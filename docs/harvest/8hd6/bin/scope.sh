#!/usr/bin/env bash
# scope.sh -- for every checkout path on stdin, decide whether it is a checkout OF THIS
# REPOSITORY (and therefore in scope for the harvest) or a foreign / synthetic repo.
#
# In scope iff EITHER its git-common-dir is one of this host's vibe-ic clones (so it shares
# their object store), OR its own origin points at vibeic/vibe-ic. Anything else is a
# different repository and this triage has no rule for it -- reported, never judged.
set -uo pipefail
while read -r p; do
  cdir=$(git -C "$p" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || { printf '%s\tNOT_A_REPO\t-\t-\t-\n' "$p"; continue; }
  url=$(git -C "$p" config --get remote.origin.url 2>/dev/null)
  head=$(git -C "$p" rev-parse -q --verify HEAD 2>/dev/null)
  case "$cdir" in
    /home/reyerchu/vibe-ic/.git|/home/reyerchu/vibe-ic-shard/.git|/home/reyerchu/_jppa_power/tree/.git) scope=IN_SCOPE_SHARED_CLONE;;
    *) case "$url" in
         *vibeic/vibe-ic*) scope=IN_SCOPE_OWN_CLONE;;
         '') scope=OUT_NO_ORIGIN;;
         *) scope=OUT_FOREIGN_REPO;;
       esac;;
  esac
  reg=no
  git -C "$cdir" worktree list --porcelain 2>/dev/null | grep -qxF "worktree $p" && reg=yes
  printf '%s\t%s\t%s\t%s\treg=%s\n' "$p" "$scope" "$cdir" "${url:-(none)}" "$reg"
done
