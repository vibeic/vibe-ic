#!/usr/bin/env bash
# audit_63x9.sh — the 63x9 audit, run WHERE ITS CORPUS IS.
#
# WHAT THIS IS, AND WHAT IT IS NOT
# ================================
# 63 = the flow steps declared in flow/phase1_phase2_phase3.yaml. 9 = the audit
# dimensions. This script answers ONE question: is the published audit of that
# matrix still honest — do the figures in matrix_63x8/README.md still match what a
# live join produces, and does every published cell state a verdict its own live
# predicate agrees with.
#
# It is NOT the landing gate and must never be run as part of one. A landing asks
# "did this change break something that used to work". This asks "is a published
# artefact still true". Entangling them cost this repo both ways:
#
#   * the landing paid for it — and more importantly was REFUSED by it. A landing
#     tree carries no corpus (benchmark-data left this repo in v1.10.56), so the
#     12 corpus-reading assertions could not audit anything there. They were not
#     slow, they were VOID, and their permanent red refused landings that broke
#     nothing. MEASURED in a corpus-less tree: `-m audit_63x9` -> 12 failed;
#     `-m "not audit_63x9"` -> 35 passed, rc=0, same three files.
#   * the audit paid too, in the direction that is easy to miss: it inherited the
#     landing harness's 180 s item bound, which is why a matrix test carries
#     `@pytest.mark.timeout(0)` to escape a budget that was never about it.
#
# WHY A REFUSAL AND NOT A FAILURE WHEN THE CORPUS IS ABSENT
# ========================================================
# The house rule (gate_zero_denominator_refuses_check): a verdict over an empty
# population is a refusal, never a pass — and equally, never a failure. "I could
# not look" and "I looked and it is wrong" are different sentences and a reader
# must be able to tell them apart. rc=2 is the first; rc=1 is the second.
#
# WHAT STILL GUARDS THE PUBLISHED FIGURES
# =======================================
# The freshness check used to sit in repo_hygiene_gates.sh, and its comment there
# recorded exactly why: matrix_63x8/README.md publishes the campaign headline and
# went STALE TWICE with nothing noticing — once hand-written and four rows adrift,
# once generated at the wrong vintage (main published 28 CONTRADICTED / 12 NA
# while its own live join produced 29 / 11). It was wired into a merge path
# because "a generated artefact whose freshness check runs in no merge path will
# go stale again".
#
# That reasoning is still correct, and this script is not a licence to stop
# running it. It is the entry point that makes running it possible WHERE IT CAN
# ANSWER. Its scheduling is an owner decision that is still open — until it is
# taken, this script being present and callable is the whole of the guarantee,
# and that is stated here rather than implied.
#
# USAGE
#   tools/ci/audit_63x9.sh [--repo DIR]
#   VIBE_IC_BENCHMARK_DATA=/path/to/benchmark-data tools/ci/audit_63x9.sh
#
# EXIT
#   0  audited, everything consistent
#   1  a finding: a published figure or cell state contradicts the live join
#   2  NOT DETERMINED — no corpus to audit. Never a pass.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    -h|--help) sed -n '1,60p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
PLUGIN="$REPO/vibe-ic-marketplace/plugins/vibe-ic"

# ── WHERE IS THE CORPUS ──────────────────────────────────────────────────────
# Same order as programs/_corpus_location.py, deliberately: seven gates already
# agree where the corpus is by agreeing with that module, and a second dialect
# here could disagree with all of them while looking correct.
CORPUS=""
if [ -d "$REPO/benchmark-data" ]; then
  CORPUS="$REPO/benchmark-data"
elif [ -n "${VIBE_IC_BENCHMARK_DATA:-}" ] && [ -d "$VIBE_IC_BENCHMARK_DATA" ]; then
  CORPUS="$VIBE_IC_BENCHMARK_DATA"
fi

if [ -z "$CORPUS" ]; then
  cat >&2 <<EOF
[NOT DETERMINED] audit_63x9: no corpus to audit — this is a REFUSAL, not a pass.
    looked for : $REPO/benchmark-data
    then       : \$VIBE_IC_BENCHMARK_DATA (currently '${VIBE_IC_BENCHMARK_DATA:-unset}')
    scanned    : 0 published cell(s)
  benchmark-data left this repo in v1.10.56. Point \$VIBE_IC_BENCHMARK_DATA at a
  checkout of it and re-run. A run that could not look has not passed.
EOF
  exit 2
fi
echo "audit_63x9: corpus = $CORPUS"

# A DIRECTORY IS NOT A CORPUS. Resolving a path only answers "something is there";
# it does not answer "there is anything to audit". Without this, an empty or
# half-synced directory sends every arm below into failure, and the run reports
# `[FAIL] a published figure contradicts the live join` when the truth is that
# nothing could be looked at. MEASURED while writing this: an empty corpus dir gave
# exactly that sentence. "I could not look" and "I looked and it is wrong" must not
# collapse into each other -- so the population is counted BEFORE anything judges it.
_cells=$(cd "$CORPUS" && find . -path '*/phase3/stage3/pnr/routed.def' 2>/dev/null | wc -l)
_eval=$([ -d "$CORPUS/evaluation" ] && echo 1 || echo 0)
echo "audit_63x9: population = $_cells published cell(s), evaluation/ present=$_eval"
if [ "$_cells" -eq 0 ] && [ "$_eval" -eq 0 ]; then
  cat >&2 <<EOF
[NOT DETERMINED] audit_63x9: '$CORPUS' exists but carries nothing to audit —
  0 published cells and no evaluation/ tree. This is a REFUSAL, not a pass and
  not a failure: a verdict over an empty population is neither.
EOF
  exit 2
fi

RC=0
note() { printf '  %-4s %s\n' "$1" "$2"; }

# ── 1. THE MARKED ASSERTIONS, wherever they live ─────────────────────────────
# Selected by MARKER, not by path or filename. Three of these files are MIXED —
# they carry both real landing regressions and audit assertions — so any
# file-level or directory-level split would move the wrong tests. The marker sits
# on the test itself, where a reader of that test can see it.
echo "--- marked audit assertions ---"
out="$( cd "$REPO" && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q \
        -p pytest_timeout -p no:cacheprovider \
        -m audit_63x9 \
        vibe-ic-marketplace/plugins/vibe-ic/programs/tests \
        tools 2>&1 )"
prc=$?
printf '%s\n' "$out" | tail -3 | sed 's/^/      /'
# EXIT 5 IS "no tests collected". Here that is not a pass: the markers are the
# whole selection mechanism, so collecting none means the mechanism is broken or
# every assertion was deleted. Either way nothing was audited.
if [ "$prc" -eq 5 ]; then
  note FAIL "no test carried the audit_63x9 marker — nothing was audited"
  RC=1
elif [ "$prc" -ne 0 ]; then
  note FAIL "marked audit assertions"
  RC=1
else
  note PASS "marked audit assertions"
fi

# ── 2. THE PUBLISHED CENSUS, re-derived ──────────────────────────────────────
# Moved here from tools/ci/repo_hygiene_gates.sh. Its cost is why it matters that
# it moved: 2m07s measured, and gate_host_independence_check re-ran it in a fresh
# worktree, so it was ~6 min of every landing round for a question no landing asks.
echo "--- published census freshness ---"
if [ -f "$PLUGIN/tools/gen_matrix_63x8_census.py" ]; then
  GEN="$PLUGIN/tools/gen_matrix_63x8_census.py"
elif [ -f "$REPO/tools/gen_matrix_63x8_census.py" ]; then
  GEN="$REPO/tools/gen_matrix_63x8_census.py"
else
  GEN=""
fi
if [ -z "$GEN" ]; then
  note FAIL "gen_matrix_63x8_census.py not found — the census cannot be re-derived"
  RC=1
else
  cout="$( cd "$PLUGIN" && VIBE_IC_BENCHMARK_DATA="$CORPUS" \
           python3 "$GEN" --check 2>&1 )"
  crc=$?
  printf '%s\n' "$cout" | tail -4 | sed 's/^/      /'
  if [ "$crc" -eq 0 ]; then note PASS "published census is fresh"
  elif [ "$crc" -eq 2 ]; then note "NOT" "census NOT DETERMINED — not a pass"; [ "$RC" -eq 0 ] && RC=2
  else note FAIL "published census is STALE"; RC=1
  fi
fi

# ── 3. THE PUBLISHED CELLS, re-judged ────────────────────────────────────────
# Moved here from tools/ci/repo_hygiene_gates.sh, where `_per_published_cell_gates`
# ran these over `git ls-files benchmark-data/ic/*/*/phase3/stage3/pnr/routed.def`
# on every landing round. MEASURED: a landing tree tracks ZERO such files, so that
# dispatch expanded over 0 items every time -- void, not slow.
#
# Three of these four are flow step gates the flow ALREADY runs at their step
# (macro OBS -> 21, DRC-vacuous -> 31, inner-FAIL-bubble-up -> 36), so this arm is
# a RE-JUDGEMENT of what was published, which is what an audit is. The fourth,
# tool_diagnostic_id_gate, is declared by no flow step; it is here because its
# subject is a published cell too, and that gap is stated rather than hidden.
echo "--- published cells re-judged ---"
CELLS=$(cd "$CORPUS" 2>/dev/null && \
        find . -path '*/phase3/stage3/pnr/routed.def' 2>/dev/null | wc -l)
echo "      published cells carrying a routed DEF: $CELLS"
if [ "$CELLS" -eq 0 ]; then
  # A CORPUS THAT EXISTS BUT PUBLISHES NOTHING IS STILL NOT A PASS. This is the
  # zero-denominator rule: the gates below would each return "nothing to judge",
  # and N of those does not add up to a verdict.
  note "NOT" "the corpus carries no published cell — nothing to re-judge"
  [ "$RC" -eq 0 ] && RC=2
else
  while IFS= read -r def; do
    cell="$CORPUS/$(dirname "$(dirname "$(dirname "$(dirname "$def")")")")"
    for prog in macro_obs_geometry_intersect_check drc_vacuous_pass_check \
                step_internal_fail_bubble_up_check tool_diagnostic_id_gate; do
      [ -f "$PLUGIN/programs/$prog.py" ] || continue
      pout="$( cd "$PLUGIN" && python3 "programs/$prog.py" "$cell" 2>&1 )"
      prc=$?
      case "$prc" in
        0) : ;;
        # rc 2 is the gates' documented "this cell ships nothing I can read" --
        # an honest refusal per cell, not a finding and not a pass.
        2) printf '      NOT  %s on %s\n' "$prog" "$(basename "$cell")" ;;
        *) printf '      FAIL %s on %s\n' "$prog" "$(basename "$cell")"
           printf '%s\n' "$pout" | tail -2 | sed 's/^/           /'
           RC=1 ;;
      esac
    done
  done <<CELLEOF
$(cd "$CORPUS" && find . -path '*/phase3/stage3/pnr/routed.def' 2>/dev/null)
CELLEOF
  [ "$RC" -ne 1 ] && note PASS "published cells re-judged ($CELLS cell(s))"
fi

echo
case "$RC" in
  0) echo "[PASS] audit_63x9: the published 63x9 audit matches the live join." ;;
  1) echo "[FAIL] audit_63x9: a published figure or cell state contradicts the live join." ;;
  2) echo "[NOT DETERMINED] audit_63x9: something could not be looked at. Not a pass." ;;
esac
exit "$RC"
