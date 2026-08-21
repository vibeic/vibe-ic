#!/usr/bin/env bash
# run_gate_harnesses.sh — DISCOVER and RUN every `tools/ci/test_*.sh`.
#
# WHY THIS FILE EXISTS
# ====================
# `_gate_dispatch.sh` — the dispatcher every hygiene gate runs through — ships
# with three paired guards beside it, and the #P3 landing commit cites one of
# them by name as its acceptance evidence ("Paired guard: tools/ci/
# test_gate_scope.sh, 10 tests, every case in both directions … 10 passed,
# 0 failed").
#
# MEASURED on origin/main at v1.10.64: nothing in this repository invokes any of
# them. `grep -rn` for their filenames outside `tools/ci/test_gate*.sh` returns
# only their own cross-references. `gatekeeper-land.sh::run_repo_tools_pytest`
# sweeps `tools/` for PYTEST; these are bash, so they fall through it.
# `repo_hygiene_gates.sh` declares 83 gates and none of them is a harness.
#
#     tools/ci/test_gate_scope.sh          10 assertions   run by nothing
#     tools/ci/test_gate_scope_pairing.sh   6 assertions   run by nothing
#     tools/ci/test_gate_concurrency.sh    25 assertions   run by nothing
#
# 41 assertions over the one file every gate's verdict passes through, executed
# only when a human remembers. Colocation without discovery is a fixture next to
# a check that nothing ever fires.
#
# ADOPTED FROM deepseek-harness. Its equivalents (`scripts/change-scope.spec.ts`,
# `scripts/run-gates.spec.ts`, 44 `*.spec.ts` beside 145 `scripts/*.ts`) sit in
# the same directory as the code they guard AND are swept by a declared gate —
# `pnpmExec('docs-site-projection', ['vitest', 'run', 'scripts/…spec.ts'])` in
# `run-gates.ts`. The colocation half was already true here; this file is the
# discovery half, and it is the half that makes the colocation mean anything.
#
# WHAT IT COSTS, STATED: it adds harnesses to the landing gate rather than
# removing any. Measured wall time is printed by every run and by the gate row
# it is wired into.
#
# CONTRACT
# ========
#     rc 0   every discovered harness passed
#     rc 1   at least one failed (each named, with its exit status)
#     rc 2   DISCOVERY FOUND NOTHING, or the directory is unreadable
#
# rc 2 AND NOT rc 0 ON AN EMPTY SWEEP, and this is the whole safety of the file.
# A sweeper whose glob stops matching prints "0 failed" and exits clean, and the
# 41 assertions vanish with no reader told. An empty result is not a zero; it is
# a refusal, in the same tier `_gate_dispatch.sh` uses for a set that declared
# nothing.
#
# chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR="${1:-$HERE}"

if [ ! -d "$DIR" ]; then
  echo "[ERROR] run_gate_harnesses: not a directory: $DIR" >&2
  exit 2
fi

# `find` rather than a glob: a glob that matches nothing expands to its own
# literal text under `set -u`, which would then be "run" and fail as a missing
# command — an empty sweep presenting as one broken harness.
mapfile -t HARNESSES < <(find "$DIR" -maxdepth 1 -type f -name 'test_*.sh' \
                         | LC_ALL=C sort)

if [ "${#HARNESSES[@]}" -eq 0 ]; then
  echo "[ERROR] run_gate_harnesses: DISCOVERED NOTHING under $DIR — this is a" \
       "refusal, not a pass. Either the harnesses moved or the pattern" \
       "'test_*.sh' stopped matching them; either way no assertion ran and" \
       "nothing about the gate dispatcher has been certified by this run." >&2
  exit 2
fi

total=0; failed=0; names=""
for h in "${HARNESSES[@]}"; do
  total=$(( total + 1 ))
  t0="$SECONDS"
  echo "── $(basename "$h")"
  bash "$h"
  rc=$?
  secs=$(( SECONDS - t0 ))
  if [ "$rc" -ne 0 ]; then
    failed=$(( failed + 1 ))
    names="${names:+$names, }$(basename "$h") (exit $rc)"
    echo "   ^^ HARNESS FAILED: $(basename "$h") [${secs}s] exit $rc" >&2
  else
    echo "   ok $(basename "$h") [${secs}s]"
  fi
done

# THE DENOMINATOR IS PRINTED WHETHER OR NOT ANYTHING FAILED. `gate_discloses_
# denominator_check` demands of every gate that a PASS say how much it looked
# at, and "all harnesses passed" without a count is the sentence that survives a
# glob quietly shrinking from three files to one.
if [ "$failed" -ne 0 ]; then
  echo "[FAIL] run_gate_harnesses: $failed of $total discovered harness(es)" \
       "failed: $names" >&2
  exit 1
fi
echo "[PASS] run_gate_harnesses: $total discovered harness(es) passed"
exit 0
