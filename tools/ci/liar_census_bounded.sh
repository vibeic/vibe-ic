#!/usr/bin/env bash
# tools/ci/liar_census_bounded.sh — run one pytest file under whichever bound
# this host can actually impose, and SAY which one that was.
#
# WHY THIS IS A FILE AND NOT THREE LINES IN THE CALLER (main-red, 2026-08-19)
# --------------------------------------------------------------------------
# `pytest_timeout` is a third-party plugin and it is NOT in the pinned runner
# image. `-p pytest_timeout` on a pytest that cannot import it does not degrade:
# it raises `ImportError: Error importing plugin "pytest_timeout"` during
# pre-parse and exits 1 before collecting a single test. `repo_hygiene_gates.sh`
# named it, so the gate `liar census controls still fire` could not start at all
# on a clean checkout of main.
#
# Deciding the bound INLINE in the caller was the obvious repair and it is the
# wrong one: it puts a shell variable into the `run` declaration, and
# `gate_host_independence_check` reads those declarations as TEXT. A variable it
# cannot resolve makes the gate NOT PROBED — measured, on the first attempt at
# this fix: the census gate silently left the 72 gates that probe run drives.
# Trading a red gate for an unprobed one is not a repair. A fixed command naming
# this file keeps the declaration drivable by a reader, and the branch lives
# where bash is the only thing that has to read it.
#
# THE TWO BOUNDS ARE NOT THE SAME MEASUREMENT, which is why the number moves
# with the unit:
#   * with the plugin, 180 s is PER TEST, and reaching it takes the whole
#     session down (`--timeout-method=thread`) rather than failing the test;
#   * without it, only the WHOLE SESSION can be bounded. 180 s as a session
#     budget is a flake generator on a file measured at 25 s and at 137 s on one
#     tree, and a session killed at its bound reports nothing at all — so the
#     external bound is 900 s, matching the census's own per-arm ceiling
#     (`--mutation-timeout`). Blowing it is rc 124, which the caller reads as a
#     FAILED gate; the bound is never dropped and never silently loosened.
#
# usage: liar_census_bounded.sh <pytest-file> [pytest-arg …]
set -euo pipefail

[ "$#" -ge 1 ] || {
  echo "liar_census_bounded: usage: $0 <pytest-file> [pytest-arg ...]" >&2
  exit 2
}

# Asked of the interpreter that will actually run pytest, not assumed from the
# image's name or from a requirements file nobody installed.
if python3 -c 'import importlib.util, sys
sys.exit(0 if importlib.util.find_spec("pytest_timeout") else 1)' 2>/dev/null; then
  echo "liar_census_bounded: bounded PER TEST at 180 s by pytest_timeout" >&2
  exec env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
      python3 -m pytest -q -p pytest_timeout \
      --timeout=180 --timeout-method=thread "$@"
fi

echo "liar_census_bounded: pytest_timeout is NOT INSTALLED for this python3, so" \
     "this file is bounded as a WHOLE SESSION at 900 s by an external" \
     "\`timeout\` instead of PER TEST at 180 s. A hang now costs every result" \
     "in the file rather than one test, and the run FAILS (rc 124) rather than" \
     "being quietly unbounded." >&2
exec timeout --kill-after=60 900 \
    env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q "$@"
