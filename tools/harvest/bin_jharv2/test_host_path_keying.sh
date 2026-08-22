#!/usr/bin/env bash
# Rows are keyed by (host, path), NEVER by path alone.
#
# Six worktrees in verdicts_joined.tsv exist at the same path on two different hosts -- 355 rows,
# 349 distinct paths. A dict keyed by path silently collapses those six pairs, and the result looks
# like rows were DELETED. I made that mistake four times in one day in ad-hoc checks, once
# concluding the consumable had gone stale when nothing had changed at all.
#
# The shipped tools key correctly. This pins that, and the CONTROL showed the failure is not the one
# I assumed: keying build_verdicts_all.py by path alone does NOT drop a row -- the tool retains both
# sides of a disagreement, so the pair surfaces as a FALSE CONFLICT instead. Two worktrees that
# happen to share a path on different machines are not a dispute about one worktree. A reader would
# go looking for an argument between two agents that never happened.
#
# So the two failure shapes are: a path-keyed CHECK invents a discrepancy or a phantom deletion, and
# a path-keyed BUILDER manufactures a conflict. Neither loses data here; both mislead. That is why
# the conflict arm below is the one that actually fires.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin_jharv2"
cp "$here/build_verdicts_all.py" "$here/derived_freshness_check.py" "$T/bin_jharv2/"
rc=0

# two rows, same path, different hosts, DIFFERENT verdicts
printf 'host\tpath\tverdict\tevidence\tshard\n105\t/same/path\tRECOVER\tev-a\ts\n102\t/same/path\tLANDED\tev-b\ts\n' > "$T/verdicts_joined.tsv"
printf 'host\tpath\tverdict\tevidence\tshard\n105\t/only/extra\tRECOVER\te\textra-8hd9\n' > "$T/verdicts_extras_joined.tsv"
printf 'path\tverdict\tevidence\n/only/extra\tRECOVER\te\n' > "$T/verdicts_extra_8hd9.tsv"
printf 'path\tverdict\tevidence\n' > "$T/verdicts_extra_8hd7.tsv"

python3 "$T/bin_jharv2/build_verdicts_all.py" "$T" >/dev/null 2>&1
n=$(tail -n +2 "$T/verdicts_all.tsv" 2>/dev/null | grep -c '')
printf '  %-52s %s rows\n' "cross-host duplicate paths are both retained" "$n"
[ "$n" = 3 ] || { echo "     FAIL: expected 3, got $n -- a path-keyed dict collapsed a pair"; rc=1; }
for h in 105 102; do
  awk -F'\t' -v H=$h 'NR>1 && $1==H && $2=="/same/path"' "$T/verdicts_all.tsv" | grep -q . \
    || { echo "     FAIL: host $h row for /same/path is missing"; rc=1; }
done

# and a genuine cross-host CONFLICT must be surfaced, not silently deduped to one winner
c=$(awk -F'\t' 'NR>1 && $6=="CONFLICT"' "$T/verdicts_all.tsv" | grep -c '' || true)
printf '  %-52s %s\n' "different hosts are NOT a conflict (different worktrees)" "${c:-0}"
[ "${c:-0}" = 0 ] || { echo "     FAIL: same path on two hosts is two worktrees, not a dispute"; rc=1; }

# derived_freshness must also key by (host,path): give it a source pair sharing a path
printf 'path\tverdict\tevidence\n/same/path\tRECOVER\tev-a\n' > "$T/verdicts_extra_8hd9.tsv"
printf 'path\tverdict\tevidence\n/same/path\tLANDED\tev-b\n' > "$T/verdicts_extra_8hd7.tsv"
printf 'host\tpath\tverdict\tevidence\tshard\n105\t/same/path\tRECOVER\tev-a\textra-8hd9\n102\t/same/path\tLANDED\tev-b\textra-8hd7\n' > "$T/verdicts_extras_joined.tsv"
out=$(python3 "$T/bin_jharv2/derived_freshness_check.py" "$T" 2>&1); e=$?
printf '  %-52s rc=%s\n' "derived check sees both cross-host rows as matching" "$e"
[ "$e" = 0 ] || { echo "$out" | sed 's/^/       /'; echo "     FAIL: a path-keyed derived check would report a false mismatch"; rc=1; }

[ $rc -eq 0 ] && echo "  PASS"; exit $rc
