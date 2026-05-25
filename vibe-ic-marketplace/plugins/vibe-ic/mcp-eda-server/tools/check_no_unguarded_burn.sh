#!/bin/bash
# Wave 33 (mcp-eda v0.99.9) — CI sentinel: forbid unguarded burn paths.
#
# Forensic background: WAVE32_DUAL_GOVERNANCE_HOLE.md (Hole 1) showed
# eda_fpga_program had a direct `execSync("quartus_pgm -c ... -o ...")`
# call with NO pre-burn flow_compliance / RTL precheck guard. An agent
# routed through this path to burn a SOF whose
# phase23_completion_audit.json reported verdict=FAIL.
#
# Policy: every site that programs (i.e. burns) silicon — quartus_pgm
# with `-o "P;..."` semantics, or openocd `program` directives — must
# live inside a guarded path that calls _run_flow_compliance_pre_burn
# and respects the fail-closed verdict. Read-only enumerations
# (`quartus_pgm --list`, `quartus_pgm -l`) are NOT burn calls and are
# permitted.
#
# This script greps the mcp-eda-server source tree for burn-class
# invocations and FAILs whenever one appears outside a known-guarded
# sentinel context (driver.py, guarded_burn helpers, test fixtures).
# The grep output and exit code are CI-friendly.
#
# Usage:
#   bash mcp-eda-server/tools/check_no_unguarded_burn.sh
#
# Exit code 0  = OK, every burn site sits inside the guarded path.
# Exit code 1  = WAVE33_UNGUARDED_BURN_VIOLATION (one or more sites
#                outside the allow-list).

set -e

# Resolve the mcp-eda-server root regardless of CWD.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"
SRC="${ROOT}/src"

if [ ! -d "${SRC}" ]; then
  echo "WAVE33_UNGUARDED_BURN_VIOLATION: src/ not found at ${SRC}" >&2
  exit 1
fi

# Search for burn-class invocations:
#   1. execSync("...quartus_pgm ... -o ..." or "...quartus_pgm ... -m JTAG -o..."
#   2. spawn / spawnSync of quartus_pgm with the burn flags
#   3. execSync of openocd ... program ...
#
# We look at .js / .ts / .py files only.
PATTERN_BURN='execSync\(.*quartus_pgm[^)]*-o[[:space:]]*"P;|spawn[A-Za-z]*\(.*quartus_pgm[^)]*-o[[:space:]]*"P;|execSync\(.*openocd[^)]*program[[:space:]]'

# Allow-list (regex applied to the matching line). Sites that contain
# any of these tokens are considered guarded:
#   * `_run_flow_compliance_pre_burn` — Wave 30 fail-closed gate
#   * `guarded_burn` — explicit marker for a future helper
#   * filename starts with `test_` or contains /test/  (test fixtures)
#   * the eda_fpga_program Wave-33 wrapper that DELEGATES to driver.py
#     (the wrapper itself does not run quartus_pgm directly any more,
#     it spawns python3 driver.py — pattern PATTERN_BURN does not
#     match, so no allow-list entry needed for the wrapper).
ALLOW_TOKENS='_run_flow_compliance_pre_burn|guarded_burn'

# 1) Collect raw violation candidates.
RAW=$(grep -rEn "${PATTERN_BURN}" \
      "${SRC}" \
      --include="*.js" --include="*.ts" --include="*.py" \
      2>/dev/null || true)

# 2) Filter out test fixtures (path contains `/test` or starts with
#    `test_`).
FILTERED=""
if [ -n "${RAW}" ]; then
  while IFS= read -r line; do
    file_part="${line%%:*}"
    base="$(basename "${file_part}")"
    case "${file_part}" in
      */test/*|*/tests/*) continue ;;
    esac
    case "${base}" in
      test_*) continue ;;
    esac
    # 3) Filter out lines that contain the guarded-context tokens
    #    (pragma allow-list).
    if echo "${line}" | grep -qE "${ALLOW_TOKENS}"; then
      continue
    fi
    # 4) The driver.py burn site is acceptable: that file IS the
    #    guarded path. We accept any line inside the terasic-de10lite
    #    driver because mode_program() funnels through
    #    _run_flow_compliance_pre_burn at the top of the function.
    case "${file_part}" in
      */devices/fpga/*/driver.py) continue ;;
    esac
    FILTERED="${FILTERED}${line}
"
  done <<< "${RAW}"
fi

if [ -n "${FILTERED}" ]; then
  echo "WAVE33_UNGUARDED_BURN_VIOLATION:" >&2
  echo "${FILTERED}" >&2
  echo "" >&2
  echo "Every burn-class site (quartus_pgm -o \"P;...\" / openocd " \
       "program ...) must run inside a guarded path that invokes " \
       "_run_flow_compliance_pre_burn and respects the fail-closed " \
       "verdict, OR be marked with a `guarded_burn` token comment." \
       >&2
  exit 1
fi

echo "OK: all burn calls in mcp-eda-server/src/ guarded (Wave 33)"
exit 0
