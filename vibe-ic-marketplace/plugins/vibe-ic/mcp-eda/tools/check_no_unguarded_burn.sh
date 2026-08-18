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
# This script greps the mcp-eda source tree for burn-class
# invocations and FAILs whenever one appears outside a known-guarded
# sentinel context (driver.py, guarded_burn helpers, test fixtures).
# The grep output and exit code are CI-friendly.
#
# Usage:
#   bash mcp-eda/tools/check_no_unguarded_burn.sh
#
# Exit code 0  = OK, every burn site sits inside the guarded path.
# Exit code 1  = WAVE33_UNGUARDED_BURN_VIOLATION (one or more sites
#                outside the allow-list).
# Exit code 2  = WAVE33_SCAN_COULD_NOT_LOOK — the scan itself failed, so
#                this run carries NO verdict either way (vibe-ic#1476).
#                It is deliberately not 0: "I could not look" and "I looked
#                and the tree is clean" are different states and must never
#                be recorded the same way.

set -e

# vibe-ic#1476 — scan BYTES, not characters. Every pattern below is ASCII, so
# a byte-oriented locale cannot change a verdict; a character-oriented one
# can, and did. In a UTF-8 locale ONE truncated multi-byte character makes
# both halves of this scan lie, silently and in the safe-looking direction:
#
#   * GNU grep omits a matching line that carries an improperly-encoded
#     byte. Nothing reaches stdout, the notice goes to stderr, status 0.
#   * bash's `read` builtin is worse — it consumes the '\n' delimiter while
#     trying to complete the incomplete character, so the affected line is
#     MERGED with the next one, or, when it is the last line, produces no
#     iteration at all. Measured on bash 5.1.16, file "aa<0xE2>\nbb\n":
#         default locale  ->  1 line, $'aa\342\nbb'   (delimiter eaten)
#         LC_ALL=C        ->  2 lines, correct
#
# Both were reachable here at once: a burn call whose line ended in a bare
# 0xE2 left RAW populated and the loop with zero iterations, and the gate
# printed "OK: all burn calls guarded" for a tree that had an unguarded one.
export LC_ALL=C
export LANG=C

# Resolve the mcp-eda root regardless of CWD.
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

# 0) The denominator. vibe-ic#1476's remedy is that an empty result is not a
#    zero — so the number this gate looked at is measured and printed, and a
#    denominator of zero refuses instead of certifying an empty tree.
SCANNED="$(find "${SRC}" -type f \
             \( -name '*.js' -o -name '*.ts' -o -name '*.py' \) \
           | wc -l)"
if [ "${SCANNED}" -eq 0 ]; then
  echo "WAVE33_SCAN_COULD_NOT_LOOK: 0 .js/.ts/.py files under ${SRC}" >&2
  echo "A scan of nothing is not a clean tree — this run carries NO verdict." >&2
  exit 2
fi

# 1) Collect raw violation candidates.
#
# vibe-ic#1476 — `-a`, and the exit status is READ instead of discarded.
#
#   (a) `-a` ("process a binary file as if it were text") covers the case
#       LC_ALL=C above does not: a source file carrying a NUL byte is
#       binary in EVERY locale, and grep suppresses its matching lines
#       while still exiting 0. `-a` can only ADD candidate lines, never
#       remove one, so it cannot buy a green.
#
#   (b) `2>/dev/null || true` erased grep's OWN failures. grep exits >=2
#       for an unreadable tree or a bad pattern; that was recorded as
#       "rc 0, no matches", i.e. byte-identical to a clean tree. It now
#       refuses with exit 2 instead of attesting safety it never measured.
GREP_ERR="$(mktemp)"
RAW="$(grep -arEn "${PATTERN_BURN}" \
       "${SRC}" \
       --include="*.js" --include="*.ts" --include="*.py" \
       2>"${GREP_ERR}")" && GREP_RC=0 || GREP_RC=$?

if [ "${GREP_RC}" -ge 2 ]; then
  echo "WAVE33_SCAN_COULD_NOT_LOOK: grep exited ${GREP_RC} over ${SRC}" >&2
  sed 's/^/    /' "${GREP_ERR}" >&2
  echo "This run carries NO verdict — it is not a clean tree." >&2
  rm -f "${GREP_ERR}"
  exit 2
fi

# grep succeeded and still had something to say (a file it could not open,
# a symlink loop). Surface it: a warning swallowed is a measurement lost.
if [ -s "${GREP_ERR}" ]; then
  sed 's/^/WAVE33_SCAN_NOTE: /' "${GREP_ERR}" >&2
fi
rm -f "${GREP_ERR}"

# 2) Filter out test fixtures (path contains `/test` or starts with
#    `test_`).
CANDIDATES=0
FILTERED=""
if [ -n "${RAW}" ]; then
  CANDIDATES="$(printf '%s\n' "${RAW}" | wc -l)"
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
  # The backticks around the token were UNESCAPED inside a double-quoted
  # string, so bash ran `guarded_burn` as a command ("command not found" on
  # stderr) and substituted its empty output — the remediation line printed
  # as "...marked with a  token comment", omitting the one token an author
  # needs in order to comply. Escaped, so the instruction names the token.
  echo "Every burn-class site (quartus_pgm -o \"P;...\" / openocd " \
       "program ...) must run inside a guarded path that invokes " \
       "_run_flow_compliance_pre_burn and respects the fail-closed " \
       "verdict, OR be marked with a \`guarded_burn\` token comment." \
       >&2
  exit 1
fi

# vibe-ic#1476 — the PASS states its denominator. The old banner was an
# unqualified claim, so the run where the scan saw nothing and the run where
# it saw everything and found nothing printed the same sentence. These two
# numbers are what a reader needs to tell them apart.
echo "OK: all burn calls in mcp-eda/src/ guarded (Wave 33)" \
     "— scanned ${SCANNED} .js/.ts/.py file(s), ${CANDIDATES} burn-class line(s)"
exit 0
