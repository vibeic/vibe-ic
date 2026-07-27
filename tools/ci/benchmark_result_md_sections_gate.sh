#!/usr/bin/env bash
# tools/ci/benchmark_result_md_sections_gate.sh — wiring glue for
# vibe-ic/programs/benchmark_result_md_lint.py.
#
# WHY THIS FILE EXISTS (wire/benchmark_ip)
# ----------------------------------------
# `skills/open-benchmark-methodology/SKILL.md` § 6 states as binding doctrine that
# `benchmark_result_md_lint.py` "fails the run if any of the seven mandatory
# sections is missing". Repo-wide, the only two non-test mentions of that program
# were that skill line and a docstring in `run_output_completeness_check.py` that
# explicitly DISCLAIMS running it. Nothing executed it, so a § 6-incomplete
# RESULT.md was published with no gate firing.
#
# The linter takes ONE RESULT.md. This script is the population half and nothing
# else: it enumerates the canonical published results, calls the UNMODIFIED
# linter on each, and reports. It contains no checking logic of its own.
#
# SCOPE, STATED OUT LOUD
# ----------------------
# BLOCKING over `benchmark-data/evaluation/<bench>/RESULT.md` — the CANONICAL
# published per-benchmark result, which is what "the benchmark RESULT.md" means in
# § 6. Measured at wiring time: 3 files, 3 PASS. So this is GREEN today and its
# whole value is the NEXT publication.
#
# NOT blocking over the archived per-run `run_*/RESULT*.md`: 41 of 66 tracked
# evaluation RESULT*.md fail the same lint. Those are frozen records of runs that
# already happened; gating them would make the lane permanently red and the gate
# would then be deleted rather than obeyed. That debt is REAL, so it is counted
# and PRINTED below — a green verdict from this script can never be read as "the
# archive is clean".
#
# A benchmark directory with NO top-level RESULT.md is covered by nothing here —
# at wiring time that is cvdp, interconnect, phase1_parity and verilogeval_machine
# (cvdp publishes only RESULT_cvdp_*.md variants). The script NAMES them on every
# run rather than leaving the exclusion implicit.
#
# An EMPTY population is a FAILURE here, not a pass. A gate that examined nothing
# and said PASS is indistinguishable from a gate that examined everything and
# found nothing (vibe-ic#447).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LINT="$ROOT/vibe-ic-marketplace/plugins/vibe-ic/programs/benchmark_result_md_lint.py"
cd "$ROOT"

if [ ! -f "$LINT" ]; then
  echo "REFUSING a vacuous PASS: benchmark_result_md_lint.py not found at $LINT" >&2
  exit 1
fi

n=0
bad=0
for f in benchmark-data/evaluation/*/RESULT.md; do
  [ -f "$f" ] || continue
  n=$((n + 1))
  if ! python3 "$LINT" "$f"; then
    echo "   ^^ $f"
    bad=$((bad + 1))
  fi
done

# ADVISORY half — the archived-run debt, so the blocking verdict above discloses
# the population it did NOT judge. Never affects the exit code.
adv_n=0
adv_bad=0
for f in $(git ls-files 'benchmark-data/evaluation/RESULT*.md' \
                        'benchmark-data/evaluation/**/RESULT*.md' 2>/dev/null); do
  adv_n=$((adv_n + 1))
  python3 "$LINT" "$f" >/dev/null 2>&1 || adv_bad=$((adv_bad + 1))
done

# A benchmark directory that ships no top-level RESULT.md is judged by NOTHING
# here. Name those directories every run — an unnamed exclusion is how a gate
# comes to cover less than its label implies without anyone noticing.
uncovered=""
for d in benchmark-data/evaluation/*/; do
  [ -d "$d" ] || continue
  [ -f "$d/RESULT.md" ] || uncovered="$uncovered ${d%/}"
done

echo "   examined $n canonical published RESULT.md (BLOCKING); $bad § 6-incomplete"
echo "   ADVISORY: $adv_bad of $adv_n tracked evaluation RESULT*.md are"
echo "   § 6-incomplete — archived runs, deliberately NOT gated"
if [ -n "$uncovered" ]; then
  echo "   NOT COVERED (no top-level RESULT.md to gate):$uncovered"
fi

if [ "$n" -eq 0 ]; then
  echo "   REFUSING a vacuous PASS: found 0 canonical published RESULT.md under" \
       "benchmark-data/evaluation/*/ — an empty population is not a clean result" >&2
  exit 1
fi
[ "$bad" -eq 0 ]
