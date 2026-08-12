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
#     uncheckable_until <YYYY-MM-DD> <why>   # REQUIRED before the next line
#     run_tolerating_uncheckable <label> <cwd> <cmd...>
#     gate_dispatch_finish             # writes the record, prints the roll-up,
#                                      # and EXITS (0 clean / 1 a gate failed or
#                                      # an exemption expired / 2 nothing was
#                                      # declared, or the wiring is wrong)
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
# WHY NOT_CHECKED NEEDS AN EXEMPTION (vibe-ic#584)
# ================================================
# The four states above were honest about the SINGLE run and said nothing about
# the TREND. Measured on this file before this paragraph existed: NOT_CHECKED
# was reachable ONLY through `run_tolerating_uncheckable`, which is a one-word
# edit away from `run` — and the roll-up exited 0 over any number of them. So
# the count could go 0 -> 1 -> 3 with nothing objecting, and each increment
# subtracted a gate from a set the reader still counts as 74. A sweep that
# names a gate it did not run and then exits as if it had is the same shape as
# the gate defects this repo has spent thirty versions removing, one level up.
#
# The repair is that the tolerance has to be BOUGHT, not assumed:
#
#   * `run_tolerating_uncheckable` without an `uncheckable_until` immediately
#     above it is a WIRING ERROR (rc 2). You cannot make a gate skippable by
#     forgetting something; you have to write down a date and a reason.
#   * An `uncheckable_until` on a plain `run` is ALSO a wiring error — it
#     describes a state that gate cannot reach, and a reader who saw it would
#     believe a tolerance that does not exist.
#   * An exemption whose date has PASSED fails the sweep (rc 1) whether or not
#     it fired. An exemption is a promise to revisit, not a permanent licence;
#     one that outlives its reason is a blind spot exactly the size of the gate
#     it covers, and the only way it gets revisited is if it makes noise.
#
# WHY THE EXEMPTION LIVES AT THE GATE AND NOT IN A LIST FILE. A separate
# registry would be a second hand-maintained list keyed by gate LABEL, which is
# the drift shape #527, #530, #534 and #538 each spent a version removing: a
# renamed gate silently loses its entry, a deleted gate leaves a rotting one.
# Declared at the wiring site it cannot desynchronise, because deleting the
# gate line deletes the exemption with it. It is enforced by the DISPATCHER
# rather than by a static checker for the same reason the recording is here —
# one mechanism, on the path every run takes, that a new wrapper cannot dodge.
#
# WHY THIS DOES NOT REINTRODUCE THE PERMANENTLY-RED SCRIPT. An EXEMPTED gate
# that reports NOT_CHECKED still exits 0, loudly, naming the gate and its
# exemption — that is `run_tolerating_uncheckable`'s original purpose and it is
# intact. What changed is that the set of gates allowed to do so is now closed,
# dated and reasoned instead of open-ended.
#
# chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.

# --- state -----------------------------------------------------------------
GATE_DISPATCH_SUMMARY_JSON=""
GATE_DISPATCH_LIST_ONLY=0
GATE_DISPATCH_FAIL=0
GATE_DISPATCH_T0=0
GATE_DISPATCH_TODAY=""
# The exemption declared by `uncheckable_until` and not yet attached to a gate.
# A SLOT rather than a lookup table: adjacency is then a property of the
# mechanism instead of a convention a reader has to honour, so an exemption
# cannot drift away from the gate it excuses or outlive its deletion.
GATE_PENDING_UNTIL=""
GATE_PENDING_WHY=""
# `declare -a ... =()` so `set -u` is safe while the lists are still empty.
# GATE_EX_* stay INDEX-ALIGNED with GATE_LABELS — every gate gets an entry,
# empty for the (normal) unexempted ones.
declare -a GATE_LABELS=() GATE_STATES=() GATE_SECONDS=()
declare -a GATE_EX_UNTIL=() GATE_EX_WHY=() GATE_WIRING_ERRORS=()

# A defect in how the script DECLARES its gates, as opposed to a defect the
# gates found. Collected rather than fatal-on-first so one run names every
# mis-wired gate; `gate_dispatch_finish` turns any into rc 2, because a set
# whose own wiring is wrong has not certified the tree it was pointed at.
_gate_wiring_error() {
  GATE_WIRING_ERRORS+=("$1")
  echo "gate_dispatch: WIRING ERROR — $1" >&2
}

# `uncheckable_until <YYYY-MM-DD> <why>` — buy the right for the NEXT gate to
# report NOT_CHECKED, until a date, for a stated reason. See the header.
uncheckable_until() {
  local until="${1:-}" why="${2:-}"
  if [ -n "$GATE_PENDING_UNTIL" ]; then
    _gate_wiring_error "an exemption (until $GATE_PENDING_UNTIL) was declared \
and never attached to a gate before 'uncheckable_until ${until}'"
  fi
  # ISO-8601 ONLY, so that the expiry comparison below can be a plain string
  # compare: on YYYY-MM-DD, lexicographic order IS chronological order, in
  # every locale, with no date library and no parsing that could itself fail
  # open. A well-shaped but calendar-impossible date (2026-02-31) still orders
  # correctly and still expires — it can hide nothing.
  if ! [[ "$until" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    _gate_wiring_error "'uncheckable_until ${until:-<empty>}': the review date \
must be ISO-8601 YYYY-MM-DD"
  fi
  # An exemption with no reason is a skip button with a date printed on it: the
  # reader it exists for cannot tell a benign missing prerequisite from a gate
  # that has quietly stopped working.
  if [ -z "$why" ]; then
    _gate_wiring_error "'uncheckable_until ${until:-<empty>}': an exemption \
must state WHY the gate can be unable to run"
  fi
  GATE_PENDING_UNTIL="$until"; GATE_PENDING_WHY="$why"
}

gate_dispatch_init() {
  GATE_DISPATCH_T0="$SECONDS"
  # Read ONCE, so that a sweep spanning midnight cannot expire an exemption for
  # gate 40 that it honoured for gate 1 — one run, one verdict, one date.
  GATE_DISPATCH_TODAY="$(date -u +%F)"
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
  # Consume the pending exemption FIRST and unconditionally, so a mis-wired
  # gate cannot leave it armed for the next one — which would silently move an
  # exemption from the gate it was written for onto a different gate.
  local ex_until="$GATE_PENDING_UNTIL" ex_why="$GATE_PENDING_WHY"
  GATE_PENDING_UNTIL=""; GATE_PENDING_WHY=""
  if [ "$tolerate" -eq 1 ] && [ -z "$ex_until" ]; then
    _gate_wiring_error "\"$label\" is wired with run_tolerating_uncheckable, so \
it can report NOT_CHECKED, but no 'uncheckable_until <YYYY-MM-DD> <why>' line \
precedes it — tolerance has to be bought, not defaulted into"
  elif [ "$tolerate" -eq 0 ] && [ -n "$ex_until" ]; then
    _gate_wiring_error "\"$label\" carries an 'uncheckable_until $ex_until' \
exemption but is wired with plain 'run', which can never report NOT_CHECKED — \
the exemption describes a state this gate cannot reach"
  fi
  GATE_LABELS+=("$label"); GATE_EX_UNTIL+=("$ex_until"); GATE_EX_WHY+=("$ex_why")
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
    # The exemption is echoed WITH the refusal, not only in the roll-up: this
    # is the line a reader reaches first, and "could not look" is only benign
    # if they can see which prerequisite was missing.
    echo "   ^^ NOT CHECKED (rc 2, non-fatal): $label [${secs}s]" \
         "— exempt until ${ex_until:-<NONE>}: ${ex_why:-<no reason declared>}" >&2
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
  local path="$1" i n total nw
  n=${#GATE_LABELS[@]}
  nw=${#GATE_WIRING_ERRORS[@]}
  total=$(( SECONDS - GATE_DISPATCH_T0 ))
  local -a fields=()
  for (( i=0; i<n; i++ )); do
    fields+=("${GATE_STATES[$i]}" "${GATE_SECONDS[$i]}" \
             "${GATE_EX_UNTIL[$i]}" "${GATE_EX_WHY[$i]}" "${GATE_LABELS[$i]}")
  done
  # Wiring errors precede the gate fields and are length-prefixed by `nw`, so
  # neither variable-length list needs a delimiter that a label or a reason
  # could contain.
  python3 - "$path" "$total" "$GATE_DISPATCH_LIST_ONLY" "$GATE_DISPATCH_TODAY" \
      "$nw" ${GATE_WIRING_ERRORS[@]+"${GATE_WIRING_ERRORS[@]}"} \
      ${fields[@]+"${fields[@]}"} <<'PY'
import json, sys
out, total, list_only = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "1"
today, nw = sys.argv[4], int(sys.argv[5])
wiring = sys.argv[6:6 + nw]
rest = sys.argv[6 + nw:]
gates = [{"label": rest[i + 4], "state": rest[i], "seconds": int(rest[i + 1]),
          "exempt_until": rest[i + 2] or None,
          "exempt_reason": rest[i + 3] or None}
         for i in range(0, len(rest), 5)]
for g in gates:
    u = g["exempt_until"]
    # ISO-8601 lexicographic order is chronological order; see the note on
    # `uncheckable_until`. An exemption expires whether or not it FIRED — it is
    # a promise to revisit, and a promise nobody is reminded of is not one.
    g["exemption_expired"] = bool(u) and u < today
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
    # The two counts that make NOT_CHECKED load-bearing (vibe-ic#584). Both are
    # LISTS, not counts: a consumer that has to refuse a landing must be able to
    # name the gate, because a bare number cannot answer "was it the one I
    # cared about".
    "not_checked_unexempted": [g["label"] for g in gates
                               if g["state"] == "NOT_CHECKED"
                               and not g["exempt_until"]],
    "exemptions_expired": [g["label"] for g in gates if g["exemption_expired"]],
    "wiring_errors": wiring,
    "today": today,
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
  local refused="" expired="" nexpired=0

  # An exemption declared after the last gate attaches to nothing. Caught here
  # rather than ignored: the author believed they had covered a gate.
  if [ -n "$GATE_PENDING_UNTIL" ]; then
    _gate_wiring_error "an exemption (until $GATE_PENDING_UNTIL) was declared \
after the last gate and attaches to nothing"
  fi

  for (( i=0; i<declared; i++ )); do
    if [ -n "${GATE_EX_UNTIL[$i]}" ] \
       && [[ "${GATE_EX_UNTIL[$i]}" < "$GATE_DISPATCH_TODAY" ]]; then
      nexpired=$(( nexpired + 1 ))
      expired="${expired:+$expired, }${GATE_LABELS[$i]} (due ${GATE_EX_UNTIL[$i]})"
    fi
  done

  [ -z "$GATE_DISPATCH_SUMMARY_JSON" ] \
    || _gate_dispatch_emit "$GATE_DISPATCH_SUMMARY_JSON"

  # BEFORE the `--list` exit and before the gate verdicts: a script whose own
  # wiring is wrong has not certified anything, and this is the one class that
  # is a pure property of the DECLARATION, so the cheap `--list` run catches it
  # too. rc 2 — the same tier as "nothing was declared", for the same reason.
  if [ "${#GATE_WIRING_ERRORS[@]}" -ne 0 ]; then
    echo "gate_dispatch: ${#GATE_WIRING_ERRORS[@]} WIRING ERROR(s) in the gate" \
         "declarations (listed above) — the set was not correctly declared," \
         "so this run certifies NOTHING" >&2
    exit 2
  fi

  if [ "$GATE_DISPATCH_LIST_ONLY" -eq 1 ]; then
    # Expiry is deliberately NOT enforced here. `--list` answers "what does
    # this script declare", a question whose answer must not change with the
    # wall clock; the dated promise is collected by the run that could actually
    # have used it.
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
        refused="${refused:+$refused, }${GATE_LABELS[$i]}"
        refused="$refused (exempt until ${GATE_EX_UNTIL[$i]})" ;;
    esac
  done

  if [ "$GATE_DISPATCH_FAIL" -ne 0 ]; then
    echo "repo_hygiene_gates: at least one gate FAILED" \
         "($declared declared, $notchecked NOT CHECKED, ${total}s)" >&2
    [ "$nexpired" -eq 0 ] || echo "repo_hygiene_gates: and $nexpired" \
      "uncheckable exemption(s) are PAST their review date: $expired" >&2
    exit 1
  fi

  # vibe-ic#584 — a dated promise that nobody is reminded of is not a promise.
  # This fires whether or not the exemption FIRED: an exemption kept past its
  # reason is a blind spot the exact size of the gate it covers, and the run
  # where it silently starts covering a real regression is the run where nobody
  # is looking. Remedy is one line: re-review the gate and either extend the
  # date with a reason that is still true, or delete the exemption and the
  # `run_tolerating_uncheckable` with it.
  if [ "$nexpired" -ne 0 ]; then
    echo "repo_hygiene_gates: $passed of $declared gate(s) passed, but" \
         "$nexpired uncheckable exemption(s) are PAST their review date and" \
         "this is NOT a pass: $expired (${total}s)" >&2
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
  # rc stays 0 here, and since #584 that is a BOUNDED statement rather than an
  # open one. Every gate that reaches this branch has bought the tolerance with
  # a dated, reasoned `uncheckable_until`; an unexempted one is a wiring error
  # two branches up and never gets here, and an expired one failed one branch
  # up. Exiting non-zero for an exemption that is doing its job would make this
  # script permanently red for a maintainer whose tree is dirty BY
  # CONSTRUCTION (benchmark artefacts, build logs), and a permanently red gate
  # is a gate that gets skipped — the failure mode `run_tolerating_uncheckable`
  # was introduced to avoid.
  #
  # The old comment here justified rc 0 with "CI checks out clean, so
  # NOT_CHECKED never arises there". That premise was already false when it was
  # written: this repo lands by DIRECT PUSH through `gatekeeper-land.sh` on a
  # maintainer's machine, and three of the four tolerating gates refuse on a
  # missing NETWORK or CONTAINER rather than on a dirty tree, neither of which
  # a clean checkout supplies. The honesty cannot rest on where the script runs;
  # it rests on the exemption being explicit, dated and named on this line.
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
