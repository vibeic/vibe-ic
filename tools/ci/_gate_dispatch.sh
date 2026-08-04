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
#     WROTE_CORPUS the gate ran and CHANGED benchmark-data/ — see below.
#
# THE CORPUS-WRITE GUARD (measured 2026-08-04)
# ============================================
# A gate that only needs to READ a run tree must not write into it, and one that
# does is invisible in the worst way: `flow_compliance_check` driven over a
# published tree adds 25 files and rewrites 17 tracked ones, and a measured A/B
# left 77 tracked files rewritten plus 64 untracked and 22 IGNORED artefacts
# behind. The ignored class is the dangerous one — `git status` does not show it,
# so the leftovers are invisible while still being read by the next gate. That is
# what tripped `step FAIL bubbles up` and `gates are host-independent` in two
# `gatekeeper_review` runs; the same 13 phantom FAILs reproduced on two unrelated
# PRs, which is how the tree rather than the PRs was identified. The main
# checkout was carrying 1078 such leftovers, which also inflated this script's
# own declared-gate count from 68 to 169 through the per-cell loop.
#
# So every gate is now bracketed by a snapshot of
# `git status --porcelain --ignored=traditional -- benchmark-data`, and a gate
# that changes it is named, failed, and told which paths it touched. `--ignored`
# is load-bearing: without it the guard cannot see the class that caused the
# trouble, and would report clean over exactly the leftovers it exists to find.
#
# A GENUINE PRODUCER declares itself with `run_writing_the_corpus`, the same way
# a gate that may legitimately refuse declares itself with
# `run_tolerating_uncheckable`. Declared in the wrapper NAME and not in a comment
# because two other programs PARSE this script for `run(?:_\w+)?` lines, so a new
# wrapper is covered by both of them for free.
#
# MEASURED BEFORE LANDING BLOCKING: all 59 statically-declared gates and all 3
# per-cell gates driven inside a throwaway worktree at HEAD, benchmark-data
# diffed across each — zero writers. The ratchet ships with no debt, so nothing
# has to be blessed for it to be green.
#
# chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.

# --- state -----------------------------------------------------------------
GATE_DISPATCH_SUMMARY_JSON=""
GATE_DISPATCH_LIST_ONLY=0
GATE_DISPATCH_FAIL=0
GATE_DISPATCH_T0=0
#: Repo whose corpus is watched, and the path inside it. Both overridable so a
#: test can point the guard at a throwaway repository and drive the REAL
#: dispatch rather than a fixture copy of it.
GATE_DISPATCH_CORPUS_ROOT="${GATE_DISPATCH_CORPUS_ROOT:-}"
GATE_DISPATCH_CORPUS_REL="${GATE_DISPATCH_CORPUS_REL:-benchmark-data}"
#: 1 once the guard has reported that it cannot look. Said ONCE, and said —
#: "the guard could not run" must never be indistinguishable from "no gate
#: wrote", which is the vacuous pass this repo removes from gates one at a time.
GATE_DISPATCH_CORPUS_BLIND=0
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

# The tree the corpus guard watches: the one the gates are being run against.
#
# `$ROOT` FIRST and this file's own location only as a fallback. Every caller of
# this library sets `$ROOT` to the tree under test, and the two differ in the
# case that matters — `gate_host_independence_check` drives the script inside a
# scratch worktree, and a guard keyed on `BASH_SOURCE` would there watch the
# ORIGINAL checkout while the gates wrote into the copy: it would attribute
# another tree's changes to these gates, and miss the ones they really made.
_gate_dispatch_corpus_root() {
  if [ -z "$GATE_DISPATCH_CORPUS_ROOT" ]; then
    local cand="${ROOT:-}"
    [ -n "$cand" ] || cand="$(dirname "${BASH_SOURCE[0]}")"
    GATE_DISPATCH_CORPUS_ROOT="$(git -C "$cand" rev-parse --show-toplevel \
      2>/dev/null || true)"
  fi
  echo "$GATE_DISPATCH_CORPUS_ROOT"
}

# One snapshot of the corpus. `--ignored=traditional` is the whole point: an
# ignored leftover is invisible to a bare `git status`, and the invisible ones
# are what cost hours. `traditional` collapses an ignored DIRECTORY into one
# entry rather than walking it, which keeps this at ~60 ms on a corpus carrying
# large build output — measured, over 68 gates.
#
# Prints nothing and returns 1 when it cannot look, so the caller can say so
# rather than read an empty snapshot as a clean one.
_gate_dispatch_corpus_state() {
  local root; root="$(_gate_dispatch_corpus_root)"
  [ -n "$root" ] || return 1
  [ -d "$root/$GATE_DISPATCH_CORPUS_REL" ] || return 1
  git -C "$root" status --porcelain --ignored=traditional -- \
      "$GATE_DISPATCH_CORPUS_REL" 2>/dev/null | LC_ALL=C sort
}

# `_dispatch <tolerate_rc2> <may_write_corpus> <label> <cwd> <cmd...>` — the ONE
# place a gate is executed and the ONE place its outcome is recorded.
_dispatch() {
  local tolerate="$1" may_write="$2" label="$3" wd="$4"; shift 4
  GATE_LABELS+=("$label")
  if [ "$GATE_DISPATCH_LIST_ONLY" -eq 1 ]; then
    GATE_STATES+=("LISTED"); GATE_SECONDS+=("0")
    echo "$label"
    return 0
  fi
  echo "── $label"
  local t0="$SECONDS" rc=0 before="" after="" watched=1
  before="$(_gate_dispatch_corpus_state)" || watched=0
  # `|| rc=$?` and NOT a bare `( ... ); rc=$?` — the caller runs under `set -e`,
  # where a failing subshell aborts before the next line and the disclosure
  # below would never print.
  ( cd "$wd" && "$@" ) || rc=$?
  local secs=$(( SECONDS - t0 ))
  GATE_SECONDS+=("$secs")
  if [ "$watched" -eq 0 ]; then
    if [ "$GATE_DISPATCH_CORPUS_BLIND" -eq 0 ]; then
      GATE_DISPATCH_CORPUS_BLIND=1
      echo "   ^^ corpus-write guard NOT ACTIVE: no" \
           "$GATE_DISPATCH_CORPUS_REL/ under a git repo reachable from" \
           "$(dirname "${BASH_SOURCE[0]}") — a gate writing into the corpus" \
           "would go unreported in this run" >&2
    fi
  elif [ "$may_write" -eq 0 ]; then
    after="$(_gate_dispatch_corpus_state)" || after="$before"
    if [ "$before" != "$after" ]; then
      GATE_STATES+=("WROTE_CORPUS")
      GATE_DISPATCH_FAIL=1
      echo "   ^^ WROTE INTO THE CORPUS: $label [${secs}s]" >&2
      echo "      This gate changed $GATE_DISPATCH_CORPUS_REL/ while" \
           "auditing it. Every later gate then reads a tree this run" \
           "modified, and the ignored part of it is invisible to a plain" \
           "\`git status\` — which is how two gatekeeper_review runs were" \
           "failed by leftovers rather than by the change under review." >&2
      echo "      Make it read-only (preferred), send its output outside" \
           "the corpus, or declare it with \`run_writing_the_corpus\` if it" \
           "is genuinely a producer." >&2
      diff <(printf '%s\n' "$before") <(printf '%s\n' "$after") \
        | sed -n '1,20p' | sed 's/^/      /' >&2 || true
      return 0
    fi
  fi
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
  _dispatch 0 0 "$@"
}

# Same as `run`, but rc 2 means "could not check" rather than "found a defect".
# A probe that needs a CLEAN tree cannot fail the suite for a developer whose
# tree has untracked scratch in it — that is how a check becomes permanently
# red and then ignored. rc 1 (a real finding) still fails; rc 2 is LOUD and
# non-fatal, and CI checks out clean so it genuinely runs there.
run_tolerating_uncheckable() {            # <label> <cwd> <cmd...>
  _dispatch 1 0 "$@"
}

# A gate that is genuinely a PRODUCER of corpus artefacts. There are none today
# — the wrapper exists so that wiring one is a visible, reviewable act rather
# than a silent regression of the guard above.
run_writing_the_corpus() {                # <label> <cwd> <cmd...>
  _dispatch 0 1 "$@"
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
    "ran": n("PASS") + n("FAIL") + n("NOT_CHECKED") + n("WROTE_CORPUS"),
    "passed": n("PASS"),
    "failed": n("FAIL"),
    "not_checked": n("NOT_CHECKED"),   # never folded into `passed`
    # Its own bucket, never folded into `failed`: the gate may well have found
    # nothing. What it did was change the tree every later gate reads, and a
    # consumer has to be able to tell those two apart.
    "wrote_corpus": n("WROTE_CORPUS"),
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
  local declared=${#GATE_LABELS[@]} notchecked=0 passed=0 wrote=0 i
  local total=$(( SECONDS - GATE_DISPATCH_T0 ))
  local refused="" writers=""
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
      WROTE_CORPUS)
        wrote=$(( wrote + 1 ))
        writers="${writers:+$writers, }${GATE_LABELS[$i]}" ;;
    esac
  done

  if [ "$wrote" -ne 0 ]; then
    # Named separately from a plain FAIL and BEFORE it: a gate that modified
    # the corpus has changed what every gate after it read, so any other
    # failure in this run may be about the leftovers rather than about the
    # commit — which is precisely the hours-long misattribution this guard
    # exists to stop.
    echo "repo_hygiene_gates: $wrote gate(s) WROTE INTO" \
         "$GATE_DISPATCH_CORPUS_REL/ — verdicts after them were taken over a" \
         "tree this run modified: $writers" >&2
  fi

  if [ "$GATE_DISPATCH_FAIL" -ne 0 ]; then
    echo "repo_hygiene_gates: at least one gate FAILED" \
         "($declared declared, $notchecked NOT CHECKED, $wrote WROTE CORPUS," \
         "${total}s)" >&2
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
