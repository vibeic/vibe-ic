#!/usr/bin/env bash
# Does the recovery procedure in README section 10 actually recover anything?
#
# Three refs carry this work, and "three refs carry it, so losing one is survivable" was asserted
# for a long time before it was ever tried. When it was tried, the shallow arm produced a directory
# in which every deliverable file was byte-identical to the real one -- including
# rescued_commits.txt, all 3039 lines of it -- while carrying NONE of the 3039 commits that file
# lists. The recovery contains the complete index of the content it does not have.
#
# That finding lived in prose, which is where measured facts go to become stale. This runs it.
#
# It is also the negative control for `branch preserves the rescued set`: that gate is only worth
# its green if it can go red. Here it is handed a tree that LOOKS right and must reject it. If the
# shallow arm ever passes, the preservation gate is not discriminating and this fails loudly --
# a check that cannot fail is not evidence, and that is the whole reason this file exists.
#
# Fails closed. Cannot reach origin, refs disagree, clone fails -> non-zero with the input named.
# Never silently green.
set -uo pipefail
BASE=${1:-tools/harvest}
REPO=${2:-.}
BR=harvest/worktree-triage-jharvest
MIRROR=$BR-mirror
TAG=harvest-jharv2-final
rc=0

MAN="$BASE/rescued_commits.txt"
[ -s "$MAN" ] || { echo "  *** manifest $MAN missing or empty -- nothing to check ***"; exit 2; }
N=$(grep -c . "$MAN")

# --- 1. the three refs must agree. The authority is ls-remote; refs/remotes is a cache and has
# been wrong in both directions here. "I pushed the branch and forgot the mirror" is the failure
# this catches, and it leaves every local file looking perfect.
LS=$(timeout 300 git -C "$REPO" ls-remote origin \
        "refs/heads/$BR" "refs/heads/$MIRROR" "refs/tags/$TAG" 2>/dev/null)
[ -n "$LS" ] || { echo "  *** UNDETERMINED: origin did not answer ls-remote ***"; exit 2; }
n_refs=$(printf '%s\n' "$LS" | grep -c .)
shas=$(printf '%s\n' "$LS" | awk '{print $1}' | sort -u)
n_sha=$(printf '%s\n' "$shas" | grep -c .)
echo "  refs on origin  : $n_refs  distinct shas: $n_sha"
printf '%s\n' "$LS" | while read -r s r; do printf '    %s %s\n' "$(echo "$s" | cut -c1-11)" "$r"; done
if [ "$n_refs" -ne 3 ]; then echo "  *** expected 3 refs, origin advertises $n_refs ***"; rc=1; fi
if [ "$n_sha" -ne 1 ]; then echo "  *** the three refs DISAGREE -- redundancy is not what it claims ***"; rc=1; fi
SHA=$(printf '%s\n' "$shas" | head -1)

# --- 2. recover the shallow way, which is the way someone in a hurry recovers.
U=$(git -C "$REPO" remote get-url origin 2>/dev/null)
case "$U" in /*) FU="file://$U";; *) FU="$U";; esac
T=$(mktemp -d "${TMPDIR:-/tmp}/recovery_drill.XXXXXX") || exit 2
trap 'rm -rf "$T"' EXIT
if ! timeout 400 git clone -q --depth 1 --no-checkout --single-branch \
        --branch "$MIRROR" "$FU" "$T/shallow" 2>/dev/null; then
  echo "  *** UNDETERMINED: shallow clone of $MIRROR from origin failed ***"; exit 2
fi
sh_n=$(git -C "$T/shallow" rev-list --count HEAD 2>/dev/null)
echo "  shallow recovery: $sh_n commit(s) reachable, shallow=$(git -C "$T/shallow" rev-parse --is-shallow-repository)"

# --- 3. the trap: the files are RIGHT. If this ever stops being true the README's "looks entirely
# correct" is no longer the finding, and the paragraph must be rewritten rather than trusted.
# `git show ... | sha256sum` hashes the EMPTY STRING when git fails, so two failed reads compare
# EQUAL and four files report IDENTICAL without either side ever being opened. Measured on this very
# gate: pointed at a BASE outside the repo it printed "identical: 4". Read into a variable, and
# require both sides to be non-empty before the comparison counts.
same=0; diff_n=0; unread=0
for f in verdicts_shard_b.tsv README.md rescued_commits.txt verdicts_all.tsv; do
  ta=$(git -C "$REPO" show "$SHA:$BASE/$f" 2>/dev/null); ra=$?
  tb=$(git -C "$T/shallow" show "HEAD:$BASE/$f" 2>/dev/null); rb=$?
  if [ $ra -ne 0 ] || [ $rb -ne 0 ] || [ -z "$ta" ] || [ -z "$tb" ]; then
    unread=$((unread+1)); echo "    UNREAD $f (full rc=$ra ${#ta}B, shallow rc=$rb ${#tb}B)"; continue
  fi
  a=$(printf '%s' "$ta" | sha256sum | cut -c1-16); b=$(printf '%s' "$tb" | sha256sum | cut -c1-16)
  if [ "$a" = "$b" ]; then same=$((same+1)); else diff_n=$((diff_n+1)); echo "    DIFFERS $f"; fi
done
[ "$unread" -eq 0 ] || { echo "  *** $unread of 4 deliverables could not be read from BOTH sides -- this arm did not run ***"; rc=1; }
echo "  deliverable files identical in the shallow recovery: $same (differing: $diff_n)"
[ "$diff_n" -eq 0 ] || { echo "  *** the shallow tree no longer looks correct -- README section 10 is stale ***"; rc=1; }

# --- 4. the negative control. The preservation gate must REJECT this tree.
echo "  -- preservation gate against the shallow recovery (must FAIL) --"
out=$(python3 "$BASE/bin_jharv2/branch_preserves_rescued_check.py" "$BASE" "$T/shallow" HEAD 2>&1); nrc=$?
sh_reach=$(printf '%s\n' "$out" | sed -n 's/.*reachable from HEAD: *\([0-9]*\).*/\1/p' | head -1)
echo "    rc=$nrc  rescued reachable: ${sh_reach:-?}/$N"
if [ "$nrc" -eq 0 ]; then
  echo "  *** the preservation gate PASSED on a tree with $sh_n commit -- it is not discriminating ***"; rc=1
fi
if [ "${sh_reach:-1}" -ne 0 ]; then
  echo "  *** expected 0 rescued commits in a depth-1 recovery, measured ${sh_reach:-?} ***"; rc=1
fi

# --- 5. the positive arm, at the SAME sha the shallow arm was taken from, so the two differ in
# depth and in nothing else.
echo "  -- preservation gate against a full repo at the same sha (must PASS) --"
out2=$(python3 "$BASE/bin_jharv2/branch_preserves_rescued_check.py" "$BASE" "$REPO" "$SHA" 2>&1); prc=$?
full_reach=$(printf '%s\n' "$out2" | sed -n 's/.*reachable from [0-9a-f]*: *\([0-9]*\).*/\1/p' | head -1)
echo "    rc=$prc  rescued reachable: ${full_reach:-?}/$N"
[ "$prc" -eq 0 ] || { echo "  *** full recovery does NOT preserve the rescued set ***"; rc=1; }
[ "${full_reach:-0}" = "$N" ] || { echo "  *** full arm carries ${full_reach:-?} of $N ***"; rc=1; }

# --- 6. close the loop on the prose. The README states the drill's result; if the manifest grows,
# the sentence must grow with it or this goes red.
# Matched against the file with newlines and markdown emphasis flattened: the sentence is wrapped
# and bolded in the README, and a line-based grep -F reported the claim ABSENT while it was on the
# page. A matcher that cannot see a wrapped sentence manufactures a failure as readily as a pass.
want="0 of the $N preserved commits"
flat=$(tr '\n' ' ' < "$BASE/README.md" | tr -d '*' | tr -s ' ')
if printf '%s' "$flat" | grep -qF "$want"; then echo "  ok    README states \"$want\""
else echo "  *** README does not state \"$want\" -- the drill result and the prose have diverged ***"; rc=1; fi

[ "$rc" -eq 0 ] && echo "  RESULT: shallow recovers every file and none of the $N commits; full recovers both."
exit $rc
