#!/usr/bin/env bash
# Every gate in this directory, in one command, runnable from a fresh checkout.
#
# Each entry declares the exit code it is EXPECTED to produce. extras_coverage.py is expected to
# FAIL: 1083 decided rows really are absent from verdicts_joined.tsv, and a gate turned green by
# aiming it at my own generated file would have stopped being a gate. Recording the expectation is
# how a known-open item stays visible instead of being quietly satisfied.
#
# Asserts its own denominator: if fewer gates ran than are declared, that is a failure. A loop that
# stops early reports no failures, which is indistinguishable from everything passing.
set -uo pipefail
cd "$(dirname "$0")/../../.." || exit 2       # repo root
H=tools/harvest; B=$H/bin_jharv2
declare -a NAME EXP CMD
add(){ NAME+=("$1"); EXP+=("$2"); CMD+=("$3"); }
add "predelete_guard self-test"        0 "bash $B/test_predelete_guard.sh"
add "abandon-audit collapse fixture"   0 "bash $B/test_abandon_audit_untracked_collapse.sh"
add "corrections_check self-test"      0 "bash $B/test_corrections_check.sh"
add "rows keyed by (host,path)"        0 "bash $B/test_host_path_keying.sh"
add "derived file matches its sources" 0 "python3 $B/derived_freshness_check.py $H"
add "README counts match the files"    0 "python3 $B/readme_numbers_check.py $H"
add "SCOPE.md is self-consistent"     0 "python3 $B/scope_selfconsistency_check.py $H"
add "verdicts_all is reproducible"     0 "d=\$(mktemp -d); cp $H/verdicts_joined.tsv $H/verdicts_extras_joined.tsv \$d/; python3 $B/build_verdicts_all.py \$d >/dev/null; cmp -s \$d/verdicts_all.tsv $H/verdicts_all.tsv; r=\$?; rm -rf \$d; exit \$r"
add "branch preserves the rescued set" 0 "python3 $B/branch_preserves_rescued_check.py $H . HEAD"
add "redundancy: >=2 refs carry it"   0 "python3 $B/redundancy_check.py $H"
add "survivability citations are live"  0 "python3 $B/live_ref_citation_check.py $H"
add "recovery drill: shallow vs full"  0 "bash $B/recovery_drill_check.sh $H ."
add "extras coverage (EXPECTED RED)"   1 "python3 $B/extras_coverage.py"
ran=0; bad=0
for i in "${!NAME[@]}"; do
  out=$(timeout 600 bash -c "${CMD[$i]}" 2>&1); rc=$?
  ran=$((ran+1))
  if [ "$rc" = "${EXP[$i]}" ]; then
    printf '  ok    %-40s rc=%s%s\n' "${NAME[$i]}" "$rc" "$( [ "${EXP[$i]}" != 0 ] && echo '  (expected)' )"
  else
    printf '  FAIL  %-40s rc=%s expected=%s\n' "${NAME[$i]}" "$rc" "${EXP[$i]}"
    printf '%s\n' "$out" | tail -4 | sed 's/^/          /'
    bad=$((bad+1))
  fi
done
printf '# %s gates declared, %s ran, %s unexpected\n' "${#NAME[@]}" "$ran" "$bad"
[ "$ran" -eq "${#NAME[@]}" ] || { echo "*** DENOMINATOR MISMATCH: $ran of ${#NAME[@]} gates ran"; exit 1; }
[ "$bad" -eq 0 ] || exit 1
