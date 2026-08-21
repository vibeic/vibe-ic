#!/usr/bin/env bash
# harvest_host.sh -- decide EVERY checkout of this repository on THIS host, by content.
#
# One command, so a second agent can take another host without re-deriving any of this.
# Run it on the host whose disk you can read. It writes:
#     ~/_harv_shard_<tag>.tsv        one line per checkout, with verdict
#     ~/_harv_remaining_<tag>.tsv    the enumeration before judging, for the merge
#     ~/_harv_shard_<tag>_RESULT.md  is NOT written -- prose is yours to write
#
# It DELETES NOTHING. It creates no worktree and no checkout. Every read goes through a
# temp index. The only writes to any clone are the fetches' own remote-tracking updates.
#
# Sharding is BY HOST on purpose: two agents fetching in one shared clone is what corrupted
# the first 223 verdicts. Run one instance per host, never two against the same clone.
#
# The four things this exists to get right, each of which cost a wrong answer once:
#   1. `git worktree list` shows only REGISTERED worktrees. Sweep the FILESYSTEM. A bare
#      clone has no .git at all and must be detected structurally.
#   2. FETCH FIRST, once per clone. A stale origin/main silently invents work.
#   3. Judge by CONTENT (blob OIDs = sha256 of the bytes), never by ancestry or "ahead".
#      This repo lands by SQUASH: every branch reads as ahead, and a third of them are
#      fully landed.
#   4. DROP only when EVERY file the branch owns is byte-identical to main. Uncommitted
#      state can only ever turn a DROP into a KEEP.
set -uo pipefail
BIN=$(cd "$(dirname "$0")" && pwd)
TAG=${1:-$(hostname)}
OUT=${OUT:-$HOME}
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
say(){ printf '[harvest] %s\n' "$*" >&2; }

say '1/6 sweeping the filesystem for every repository (not git worktree list)'
bash "$BIN/find_checkouts.sh" | sort -u > "$W/all"
say "    $(grep -c '' "$W/all") repositories on disk"

say "2/6 deciding which are checkouts of THIS repository, on evidence"
bash "$BIN/scope.sh" < "$W/all" > "$W/scoped.tsv"
awk -F'\t' '$2 ~ /^IN_SCOPE/{print $1}' "$W/scoped.tsv" | sort > "$W/inscope"
say "    $(grep -c '' "$W/inscope") in scope, $(awk -F'\t' '$2 !~ /^IN_SCOPE/' "$W/scoped.tsv" | grep -c '') excluded"

say "3/6 fetching each clone ONCE, before any verdict"
awk -F'\t' '$2 ~ /^IN_SCOPE/{print $3}' "$W/scoped.tsv" | sort -u | sed 's#/\.git$##' | while read -r clone; do
  say "    fetch $clone"
  git -C "$clone" fetch origin >/dev/null 2>&1 || say "    WARN fetch failed: $clone"
done

say "4/6 judging by content"
: > "$W/all.tsv"
awk -F'\t' '$2 ~ /^IN_SCOPE/{print $3}' "$W/scoped.tsv" | sort -u | sed 's#/\.git$##' | while read -r clone; do
  bash "$BIN/judge.sh" "$clone" 2>>"$W/err"
done > "$W/registered.tsv"
# checkouts the registration lost -- invisible to judge.sh, judged from the path instead
comm -23 "$W/inscope" <(cut -f2 "$W/registered.tsv" | sort -u) > "$W/unregistered"
say "    $(grep -c '' "$W/unregistered") checkouts are NOT registered with their clone"
bash "$BIN/judge_paths.sh" < "$W/unregistered" > "$W/unreg.tsv" 2>>"$W/err"
cat "$W/registered.tsv" "$W/unreg.tsv" > "$W/all.tsv"
awk -F'\t' -v OFS='\t' '{print (($5 ~ /^KEEP/)?"KEEP":"DROP"), $2}' "$W/all.tsv" > "$W/rows.tsv"

say "5/6 re-deciding every DROP by an independent route"
# DROP verdicts must come out of a second, independent derivation before anyone acts
ROWS="$W/rows.tsv" ALL="$W/all.tsv" bash "$BIN/verify_drops.sh" > "$W/drops_verified.tsv" 2>/dev/null
d=$(grep -c '' "$W/drops_verified.tsv"); c=$(grep -c CONFIRMED "$W/drops_verified.tsv")
say "    $c of $d DROPs confirmed"
[ "$c" = "$d" ] || say "    *** $((d-c)) DISAGREE -- do not ship until each is explained ***"

say "6/6 writing $OUT/_harv_shard_$TAG.tsv"
{ printf '# every checkout of this repository on host %s, judged by CONTENT against origin/main %s\n' \
    "$TAG" "$(git -C "$(head -1 "$W/inscope")" rev-parse origin/main 2>/dev/null)"
  printf '# verdict is the DECISION only. Nothing was deleted; deleting is the owner-s call.\n'
  printf '#host\tclone\tcheckout\tbranch\thead\tverdict\tclass\town\tdiffer\tnovel\tsuperseded\ttrk\tunt\n'
  awk -F'\t' -v OFS='\t' -v h="$TAG" '{v=($5 ~ /^KEEP/)?"KEEP":"DROP"; cls=$5;
      # A DROP whose COMMITTED content is landed can still hold uncommitted work, and that
      # work is on NO REF at all -- the most losable state there is. Do not leave this to a
      # footnote the next agent may skip: mark the row so it cannot be acted on blind.
      if(v=="DROP" && ($11+0>0 || $12+0>0)){ v="DROP_PENDING_DIRTY_CHECK"; cls=$5"__RUN_dirty.sh_FIRST" }
      print h,$1,$2,$3,substr($4,1,9),v,cls,$6,$7,$8,$9,$11,$12}' "$W/all.tsv"
} > "$OUT/_harv_shard_$TAG.tsv"
awk -F'\t' -v OFS='\t' -v h="$TAG" 'BEGIN{print "#host","clone","checkout","branch","head"}
    {print h,$1,$2,$3,substr($4,1,9)}' "$W/all.tsv" > "$OUT/_harv_remaining_$TAG.tsv"

say "done: $(grep -vc '^#' "$OUT/_harv_shard_$TAG.tsv") checkouts decided"
grep -v '^#' "$OUT/_harv_shard_$TAG.tsv" | cut -f6 | sort | uniq -c >&2
pend=$(grep -v '^#' "$OUT/_harv_shard_$TAG.tsv" | awk -F'\t' '$6=="DROP_PENDING_DIRTY_CHECK"' | grep -c '')
if [ "$pend" -gt 0 ]; then
  say "*** $pend row(s) marked DROP_PENDING_DIRTY_CHECK: committed content is landed, but the"
  say "    tree holds uncommitted work that is on NO REF. Run bin/dirty.sh on each before acting."
  grep -v '^#' "$OUT/_harv_shard_$TAG.tsv" | awk -F'\t' '$6=="DROP_PENDING_DIRTY_CHECK"{print "      "$3}' >&2
fi
