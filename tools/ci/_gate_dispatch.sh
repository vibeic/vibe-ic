#!/usr/bin/env bash
# tools/ci/_gate_dispatch.sh — how a hygiene gate is RUN and RECORDED.
#
# WHY THIS FILE EXISTS (vibe-ic#538)
# ==================================
# `gatekeeper_review` — the gate a maintainer runs before every push, whose
# MERGE_OK reads as "this will land green" — carried its own list of gates and
# overlapped `repo_hygiene_gates.sh` in FIVE of 34. It answered MERGE_OK
# without consulting the other 29. Twice in one day that verdict was wrong:
# v1.7.89 landed RED on `published_record_staleness_check`, and v1.7.92 was
# refused only because the maintainer had by then taken to running the hygiene
# script BY HAND. One of the two was caught by a habit, not by the tool.
#
# The repair is that the merge gate INVOKES the hygiene script rather than
# re-listing it. To invoke it honestly the merge gate has to be able to report
# what ran and what did not, and that record has to come from the single place
# each gate is declared — reconstructing it caller-side would be the second
# hand-maintained list all over again, which is the drift shape #527, #530 and
# #534 each spent a version removing.
#
# The recording therefore lives HERE rather than inline in the gate script, so
# that:
#   * every `run*` wrapper funnels through ONE `_dispatch`, and a third wrapper
#     added later cannot accidentally skip the recording;
#   * a test can source this file, declare two toy gates and exercise the REAL
#     dispatch and the REAL summary writer, instead of a fixture copy of them
#     that would drift from what actually runs in CI.
#
# CONTRACT
# ========
#     source "<dir>/_gate_dispatch.sh"
#     gate_dispatch_init "$@"          # parses --list / --summary-json PATH
#     run                     <label> <cwd> <cmd...>
#     run_tolerating_uncheckable <label> <cwd> <cmd...>
#     gate_dispatch_finish             # writes the record, prints the roll-up,
#                                      # and EXITS (0 clean / 1 a gate failed /
#                                      # 2 nothing was declared)
#
# The two flags are ADDITIVE: with neither, behaviour is exactly what it was
# before #538, which is how both CI workflows still call the gate script.
#
# STATES, AND WHY THEY ARE FOUR AND NOT TWO
# =========================================
#     PASS         the gate ran and found nothing
#     FAIL         the gate ran and found something
#     NOT_CHECKED  the gate REFUSED — it could not look (rc 2 from a
#                  `run_tolerating_uncheckable` gate, e.g. host-independence on
#                  a dirty tree). Never folded into PASS: "I could not look"
#                  must not reach a reader as "I looked and it was clean".
#                  This is the `_vacuous_exit` convention one level up.
#     LISTED       declared but deliberately not executed (`--list`).
#
# chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.

# --- state -----------------------------------------------------------------
GATE_DISPATCH_SUMMARY_JSON=""
GATE_DISPATCH_LIST_ONLY=0
GATE_DISPATCH_FAIL=0
GATE_DISPATCH_T0=0
# `declare -a ... =()` so `set -u` is safe while the lists are still empty.
declare -a GATE_LABELS=() GATE_STATES=() GATE_SECONDS=()

gate_dispatch_init() {
  GATE_DISPATCH_T0="$SECONDS"
  while [ $# -gt 0 ]; do
    case "$1" in
      --list) GATE_DISPATCH_LIST_ONLY=1; shift ;;
      --summary-json)
        GATE_DISPATCH_SUMMARY_JSON="${2:-}"
        [ -n "$GATE_DISPATCH_SUMMARY_JSON" ] || {
          echo "gate_dispatch: --summary-json needs a PATH" >&2; exit 2; }
        shift 2 ;;
      -h|--help)
        echo "usage: $(basename "${0}") [--list] [--summary-json PATH]"
        exit 0 ;;
      # An unknown flag is refused rather than ignored: a caller that thinks it
      # asked for a narrower run and silently got the default would read the
      # result as covering something it does not.
      *) echo "gate_dispatch: unknown argument: $1" >&2; exit 2 ;;
    esac
  done
}

# `_dispatch <tolerate_rc2> <label> <cwd> <cmd...>` — the ONE place a gate is
# executed and the ONE place its outcome is recorded.
_dispatch() {
  local tolerate="$1" label="$2" wd="$3"; shift 3
  GATE_LABELS+=("$label")
  if [ "$GATE_DISPATCH_LIST_ONLY" -eq 1 ]; then
    GATE_STATES+=("LISTED"); GATE_SECONDS+=("0")
    echo "$label"
    return 0
  fi
  echo "── $label"
  local t0="$SECONDS" rc=0
  # `|| rc=$?` and NOT a bare `( ... ); rc=$?` — the caller runs under `set -e`,
  # where a failing subshell aborts before the next line and the disclosure
  # below would never print.
  ( cd "$wd" && "$@" ) || rc=$?
  local secs=$(( SECONDS - t0 ))
  GATE_SECONDS+=("$secs")
  if [ "$rc" -eq 0 ]; then
    GATE_STATES+=("PASS")
  elif [ "$tolerate" -eq 1 ] && [ "$rc" -eq 2 ]; then
    GATE_STATES+=("NOT_CHECKED")
    echo "   ^^ NOT CHECKED (rc 2, non-fatal): $label [${secs}s]" >&2
  else
    GATE_STATES+=("FAIL")
    echo "   ^^ FAILED: $label [${secs}s]" >&2
    GATE_DISPATCH_FAIL=1
  fi
  return 0
}

run() {                                   # run <label> <cwd> <cmd...>
  _dispatch 0 "$@"
}

# Same as `run`, but rc 2 means "could not check" rather than "found a defect".
# A probe that needs a CLEAN tree cannot fail the suite for a developer whose
# tree has untracked scratch in it — that is how a check becomes permanently
# red and then ignored. rc 1 (a real finding) still fails; rc 2 is LOUD and
# non-fatal, and CI checks out clean so it genuinely runs there.
run_tolerating_uncheckable() {            # <label> <cwd> <cmd...>
  _dispatch 1 "$@"
}

# --- the record ------------------------------------------------------------
# python3 rather than hand-built JSON: every gate in the set is already a
# `python3` invocation so it is not a new dependency, and argv carries the
# labels EXACTLY — no quoting or delimiter can corrupt a record.
_gate_dispatch_emit() {
  local path="$1" i n total
  n=${#GATE_LABELS[@]}
  total=$(( SECONDS - GATE_DISPATCH_T0 ))
  local -a triples=()
  for (( i=0; i<n; i++ )); do
    triples+=("${GATE_STATES[$i]}" "${GATE_SECONDS[$i]}" "${GATE_LABELS[$i]}")
  done
  python3 - "$path" "$total" "$GATE_DISPATCH_LIST_ONLY" \
      ${triples[@]+"${triples[@]}"} <<'PY'
import json, sys
out, total, list_only = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "1"
rest = sys.argv[4:]
gates = [{"label": rest[i + 2], "state": rest[i], "seconds": int(rest[i + 1])}
         for i in range(0, len(rest), 3)]
n = lambda s: sum(1 for g in gates if g["state"] == s)
doc = {
    "listed_only": list_only,
    # `declared` is the DENOMINATOR: every gate the script wires, whether or
    # not it was executed. A consumer reports coverage against THIS, never
    # against the number that happened to run.
    "declared": len(gates),
    "ran": n("PASS") + n("FAIL") + n("NOT_CHECKED"),
    "passed": n("PASS"),
    "failed": n("FAIL"),
    "not_checked": n("NOT_CHECKED"),   # never folded into `passed`
    "deferred": n("LISTED"),
    "seconds": total,
    "gates": gates,
}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY
}

gate_dispatch_finish() {
  local declared=${#GATE_LABELS[@]} notchecked=0 passed=0 i
  local total=$(( SECONDS - GATE_DISPATCH_T0 ))
  local refused=""
  [ -z "$GATE_DISPATCH_SUMMARY_JSON" ] \
    || _gate_dispatch_emit "$GATE_DISPATCH_SUMMARY_JSON"

  if [ "$GATE_DISPATCH_LIST_ONLY" -eq 1 ]; then
    echo "gate_dispatch: $declared gate(s) declared; none run (--list)" >&2
    exit 0
  fi

  # A script that wired NOTHING must not answer "all gates passed" — that is
  # the vacuous PASS this repo removes from gates one at a time (#447/#511/#515).
  if [ "$declared" -eq 0 ]; then
    echo "gate_dispatch: NO gate was declared — nothing was checked, and this" \
         "is NOT a pass" >&2
    exit 2
  fi

  for (( i=0; i<declared; i++ )); do
    case "${GATE_STATES[$i]}" in
      PASS) passed=$(( passed + 1 )) ;;
      NOT_CHECKED)
        notchecked=$(( notchecked + 1 ))
        refused="${refused:+$refused, }${GATE_LABELS[$i]}" ;;
    esac
  done

  if [ "$GATE_DISPATCH_FAIL" -ne 0 ]; then
    echo "repo_hygiene_gates: at least one gate FAILED" \
         "($declared declared, $notchecked NOT CHECKED, ${total}s)" >&2
    exit 1
  fi

  # vibe-ic#539 — this line used to read `all gates passed` verbatim while
  # `gate_host_independence_check` had just said, in those words, "This is not
  # a pass" and exited 2. The GATE was honest; the AGGREGATION was not, and it
  # was the aggregation a reader believed. A run in which N gates could not be
  # evaluated must not print a sentence that is false, and it must NAME which
  # ones — a bare count cannot tell a reader whether the gate they care about
  # actually ran.
  #
  # rc stays 0 here. CI checks out clean, so NOT_CHECKED never arises there;
  # exiting non-zero would make this script permanently red for a maintainer
  # whose tree is dirty BY CONSTRUCTION (benchmark artefacts, build logs), and
  # a permanently red gate is a gate that gets skipped — the failure mode
  # `run_tolerating_uncheckable` was introduced to avoid. The honesty is
  # carried by this line and by the machine record, not by the exit status.
  if [ "$notchecked" -ne 0 ]; then
    echo "repo_hygiene_gates: $passed of $declared gate(s) passed;" \
         "$notchecked NOT CHECKED — this is NOT a pass over: $refused" \
         "(${total}s)"
    exit 0
  fi
  # Only now is the unqualified sentence true. It still states its own
  # denominator, so it cannot be read over a set that silently shrank.
  echo "repo_hygiene_gates: all $declared gate(s) passed (${total}s)"
  exit 0
}
