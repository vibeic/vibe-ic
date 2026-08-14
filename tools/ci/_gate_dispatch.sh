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
#: `--shard I/N` (vibe-ic#1144). -1 = not sharded, run everything.
GATE_DISPATCH_SHARD_I=-1
GATE_DISPATCH_SHARD_N=0
#: Labels this host owns, newline-separated, from `hygiene_shard_plan.py`.
GATE_DISPATCH_SHARD_LABELS=""
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

# --- LOOP-DRIVEN GATES SAY HOW MANY ITEMS THEY EXPANDED OVER (vibe-ic#957) --
# Three of this repo's gates are wired once and executed once per PUBLISHED
# CELL. `gate_discloses_denominator_check` already demands of every gate
# INDIVIDUALLY that a PASS say how much it looked at; the ROLL-UP was where
# that requirement was missing. Three green rows and a line counting them among
# ~74 gates read as "post-route geometry is checked across the published
# corpus", while the loop selects ONE cell. The number was true and the
# impression was false — the shape this repo removes from gates one at a time,
# one level up from the gates.
#
# THE DENOMINATOR IS COMPUTED HERE AND NOWHERE ELSE. `gate_dispatch_over`
# drives the iteration, so N is a fact the dispatcher measured rather than a
# number a gate author typed next to a label — and a future loop gets the
# disclosure by using the only expansion primitive there is.
#
# EMPTY OUTSIDE AN EXPANSION, AND THAT IS LOAD-BEARING: a gate that is not
# loop-driven prints byte-for-byte what it printed before this change, so the
# other ~70 rows cannot move.
GATE_DISPATCH_ITEM_NOTE=""
GATE_DISPATCH_CORPUS_CUR=""
GATE_DISPATCH_CORPUS_IDX=0
GATE_DISPATCH_CORPUS_TOTAL=0
#: One entry per `gate_dispatch_over` call: what it was called, how many items
#: it expanded over, how many gates that produced, and whether the producer
#: itself succeeded. A corpus that expands to ZERO declares no gate at all, so
#: nothing else in this record can carry it — which is exactly the case a
#: reader most needs told.
declare -a GATE_CORPUS_NAMES=() GATE_CORPUS_ITEMS=() GATE_CORPUS_GATES=()
declare -a GATE_CORPUS_STATE=()
#: Parallel to GATE_LABELS: which corpus (if any) each gate came from.
declare -a GATE_ITEM_CORPUS=() GATE_ITEM_IDX=() GATE_ITEM_TOTAL=()
#: `file:line` -> how many gates that source line has dispatched. A `run` line
#: fires ONCE unless it is inside a loop, so a second hit with no expansion
#: open is a loop written WITHOUT the dispatcher — the one way the disclosure
#: above can be bypassed. Detected and NAMED rather than assumed absent.
declare -A GATE_DISPATCH_SITES=()
declare -a GATE_UNDISCLOSED_LOOPS=()

gate_dispatch_init() {
  GATE_DISPATCH_T0="$SECONDS"
  while [ $# -gt 0 ]; do
    case "$1" in
      --list) GATE_DISPATCH_LIST_ONLY=1; shift ;;
      --shard)
        # `I/N`. The LABEL SET is supplied by --shard-labels rather than
        # computed here: six hosts must agree on the assignment, and the
        # one way to guarantee that is for all of them to read the same
        # plan produced from the same measured profile.
        case "${2:-}" in
          */*) GATE_DISPATCH_SHARD_I="${2%%/*}"
               GATE_DISPATCH_SHARD_N="${2##*/}" ;;
          *) echo "gate_dispatch: --shard wants I/N" >&2; exit 2 ;;
        esac
        shift 2 ;;
      --shard-labels)
        [ -r "${2:-}" ] || {
          echo "gate_dispatch: --shard-labels needs a readable PATH" >&2
          exit 2; }
        GATE_DISPATCH_SHARD_LABELS="$(cat "$2")"
        shift 2 ;;
      --summary-json)
        GATE_DISPATCH_SUMMARY_JSON="${2:-}"
        [ -n "$GATE_DISPATCH_SUMMARY_JSON" ] || {
          echo "gate_dispatch: --summary-json needs a PATH" >&2; exit 2; }
        shift 2 ;;
      -h|--help)
        echo "usage: $(basename "${0}") [--list] [--summary-json PATH]"
        echo "       [--shard I/N --shard-labels PATH]"
        exit 0 ;;
      # An unknown flag is refused rather than ignored: a caller that thinks it
      # asked for a narrower run and silently got the default would read the
      # result as covering something it does not.
      *) echo "gate_dispatch: unknown argument: $1" >&2; exit 2 ;;
    esac
  done
  # A shard with no label set would run EVERY gate while reporting itself as a
  # shard, so six hosts would each run everything and the aggregator would still
  # see full coverage. Refused rather than defaulted.
  if [ "$GATE_DISPATCH_SHARD_I" -ge 0 ] && [ -z "$GATE_DISPATCH_SHARD_LABELS" ]
  then
    echo "gate_dispatch: --shard needs --shard-labels; refusing to run every" \
         "gate while calling itself a shard" >&2
    exit 2
  fi
}

#: True when this host owns `$1`. Whole-line match against the plan, so one
#: label cannot be matched by another that contains it.
_gate_dispatch_owns() {
  [ "$GATE_DISPATCH_SHARD_I" -ge 0 ] || return 0
  printf '%s\n' "$GATE_DISPATCH_SHARD_LABELS" | grep -qxF -- "$1"
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
  GATE_ITEM_CORPUS+=("$GATE_DISPATCH_CORPUS_CUR")
  GATE_ITEM_IDX+=("$GATE_DISPATCH_CORPUS_IDX")
  GATE_ITEM_TOTAL+=("$GATE_DISPATCH_CORPUS_TOTAL")
  # WHERE THE `run` LINE IS. `BASH_LINENO[1]` is the line that called the
  # wrapper (`run`, `run_tolerating_uncheckable`, …) and `BASH_SOURCE[2]` the
  # file it is in — i.e. the declaration a reader of the gate script sees, not
  # this library.
  local _site="${BASH_SOURCE[2]:-?}:${BASH_LINENO[1]:-0}"
  local _hits=$(( ${GATE_DISPATCH_SITES[$_site]:-0} + 1 ))
  GATE_DISPATCH_SITES["$_site"]=$_hits
  if [ -z "$GATE_DISPATCH_CORPUS_CUR" ] && [ "$_hits" -eq 2 ]; then
    # Said ONCE per site (at the second hit), for the same reason the
    # corpus-blind note is said once: a per-iteration repeat would bury it.
    GATE_UNDISCLOSED_LOOPS+=("$_site")
  fi
  #: The label is the gate's IDENTITY and is recorded UNCHANGED — two other
  #: programs parse the gate script and reconcile every recorded label against
  #: the `run` line that produced it, so a denominator glued into the label
  #: would make every loop-driven record unattributable. The denominator is a
  #: fact ABOUT this invocation, printed beside the label, not part of it.
  local shown="$label${GATE_DISPATCH_ITEM_NOTE:+  $GATE_DISPATCH_ITEM_NOTE}"
  if [ "$GATE_DISPATCH_LIST_ONLY" -eq 1 ]; then
    GATE_STATES+=("LISTED"); GATE_SECONDS+=("0")
    echo "$shown"
    return 0
  fi
  # vibe-ic#1144 — declared here, executed on another host. Its OWN state: not
  # a pass (nothing ran), not LISTED (this is not --list), not NOT_CHECKED
  # (nothing refused). The aggregator reconciles the shards' records and proves
  # every gate ran exactly once; without a distinct state it could not tell
  # "another host owns this" from "nobody does", and a shard that died would
  # shrink the denominator silently.
  if ! _gate_dispatch_owns "$label"; then
    GATE_STATES+=("OTHER_SHARD"); GATE_SECONDS+=("0")
    return 0
  fi
  echo "── $shown"
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

# --- the only way to wire a gate PER ITEM (vibe-ic#957) ---------------------
#     gate_dispatch_over <corpus-name> <body-fn> <producer-cmd...>
#
# `<producer-cmd>` prints one item per line; `<body-fn>` is called once per item
# with that item as `$1` and wires whatever gates the item deserves.
#
# WHY THE DISPATCHER OWNS THE LOOP rather than exporting a counter for a `for`
# body to quote: the count then cannot be stale, cannot be typed by hand, and
# cannot be omitted — every gate the body declares is bracketed by an expansion
# that knows both the index and the total, and a corpus that expands to ZERO
# still leaves a record even though it declares no gate. A `for` written next to
# this primitive instead of through it is caught by the site counter in
# `_dispatch` and NAMED in the roll-up; it is not silently trusted.
#
# THE PRODUCER'S EXIT STATUS IS KEPT. `git ls-files` inside a non-repository
# prints nothing and fails, and "the producer broke" must not reach a reader as
# "the corpus is empty" — the same distinction `NOT_CHECKED` draws for a gate.
# Its stderr is deliberately NOT swallowed: a producer that failed should say
# why, in the log, on the line above the disclosure that it produced nothing.
gate_dispatch_over() {
  local corpus="$1" body="$2"; shift 2
  local out="" rc=0 line i
  local -a items=()
  out="$("$@")" || rc=$?
  # `[ -n "$line" ]` because a here-string over an EMPTY producer still yields
  # one empty line, and an empty line is not an item.
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    items+=("$line")
  done <<<"$out"
  local n=${#items[@]} before=${#GATE_LABELS[@]}
  if [ "$rc" -ne 0 ]; then
    echo "   ^^ CORPUS PRODUCER FAILED (rc $rc) for \"$corpus\": the $n" \
         "item(s) below are what it managed to print and NOT the corpus —" \
         "read every verdict from this loop as covering an unknown fraction" \
         "of it" >&2
  fi
  GATE_DISPATCH_CORPUS_CUR="$corpus"
  GATE_DISPATCH_CORPUS_TOTAL="$n"
  for (( i=0; i<n; i++ )); do
    GATE_DISPATCH_CORPUS_IDX=$(( i + 1 ))
    GATE_DISPATCH_ITEM_NOTE="[item $GATE_DISPATCH_CORPUS_IDX of $n over $corpus]"
    "$body" "${items[$i]}"
  done
  GATE_DISPATCH_ITEM_NOTE=""
  GATE_DISPATCH_CORPUS_CUR=""
  GATE_DISPATCH_CORPUS_IDX=0
  GATE_DISPATCH_CORPUS_TOTAL=0
  # AN EMPTY CORPUS MUST LEAVE A GATE BEHIND (vibe-ic#1075).
  #
  # Until this existed, `n == 0` ran the body zero times, declared zero gates,
  # and cost the run NOTHING: the roll-up printed "no gate in this run reports
  # that, because none exists" and the script's exit status was unaffected. So
  # a corpus that silently emptied — a glob that stopped matching, a corpus
  # withdrawn from publication — read exactly like a corpus with nothing wrong
  # in it. MEASURED: `published cells carrying a routed DEF` is 1 item on
  # origin/main and 0 on the withdrawal branch, and at 0 the three gates it
  # dispatches simply cease to exist with no verdict anywhere.
  #
  # A synthetic NOT_CHECKED gate is the honest record, and it is not a new
  # tier: NOT_CHECKED already means "the gate REFUSED — it could not look
  # (rc 2)", which is exactly the state of a gate with nothing to look at. It
  # is deliberately NOT a FAIL — an empty corpus is not a broken design, and
  # calling it one would make every host without published evidence red for a
  # reason that is about the corpus. But it is never a silent PASS.
  if [ "$n" -eq 0 ] && [ "$rc" -eq 0 ]; then
    GATE_LABELS+=("corpus \"$corpus\" is EMPTY — nothing was checked over it")
    GATE_STATES+=("NOT_CHECKED")
    GATE_SECONDS+=("0")
    GATE_ITEM_CORPUS+=("$corpus")
    GATE_ITEM_IDX+=("0")
    GATE_ITEM_TOTAL+=("0")
    echo "   ^^ EMPTY CORPUS \"$corpus\": 0 item(s), so the gates it would" \
         "have dispatched did not run. Recorded NOT_CHECKED so the run" \
         "carries a verdict for it instead of no verdict at all." >&2
  fi
  GATE_CORPUS_NAMES+=("$corpus")
  GATE_CORPUS_ITEMS+=("$n")
  GATE_CORPUS_GATES+=("$(( ${#GATE_LABELS[@]} - before ))")
  if [ "$rc" -eq 0 ]; then
    GATE_CORPUS_STATE+=("EXPANDED")
  else
    GATE_CORPUS_STATE+=("PRODUCER_FAILED")
  fi
}

# One line per corpus, printed with the roll-up. It states the DENOMINATOR the
# loop expanded over, so a count of green gates cannot be read as a count of
# items — including when the expansion produced exactly one, and especially
# when it produced none, which is the only case that leaves no gate behind to
# speak for itself.
_gate_dispatch_corpora_rollup() {
  local declared="$1" i n name items gates
  n=${#GATE_CORPUS_NAMES[@]}
  [ "$n" -gt 0 ] || return 0
  for (( i=0; i<n; i++ )); do
    name="${GATE_CORPUS_NAMES[$i]}"
    items="${GATE_CORPUS_ITEMS[$i]}"
    gates="${GATE_CORPUS_GATES[$i]}"
    if [ "$items" -eq 0 ]; then
      echo "repo_hygiene_gates: loop corpus \"$name\" expanded over 0 item(s)" \
           "— it declared 0 gate(s) and NOTHING was checked over it; no gate" \
           "in this run reports that, because none exists"
    else
      echo "repo_hygiene_gates: loop corpus \"$name\" expanded over $items" \
           "item(s) -> $gates of $declared declared gate(s); those verdicts" \
           "cover $items item(s), NOT the corpus at large"
    fi
    [ "${GATE_CORPUS_STATE[$i]}" = "EXPANDED" ] || \
      echo "repo_hygiene_gates: loop corpus \"$name\" — its PRODUCER FAILED," \
           "so even that item count is a floor and not the corpus"
  done
}

# A loop that did not go through `gate_dispatch_over`: one `run` line, more
# than one gate, no expansion open. Reported for the same reason the corpus
# above is — the roll-up cannot say how many items such a loop covered, and a
# reader who is not told assumes the label's scope is the whole subject.
_gate_dispatch_undisclosed_loops() {
  [ "${#GATE_UNDISCLOSED_LOOPS[@]}" -ne 0 ] || return 0
  local site
  for site in "${GATE_UNDISCLOSED_LOOPS[@]}"; do
    echo "repo_hygiene_gates: LOOP WITHOUT A DECLARED DENOMINATOR at $site —" \
         "${GATE_DISPATCH_SITES[$site]} gate(s) came from one \`run\` line" \
         "without \`gate_dispatch_over\`, so this roll-up cannot say how many" \
         "items they covered. Wire the loop through \`gate_dispatch_over\`." >&2
  done
}

# --- the record ------------------------------------------------------------
# python3 rather than hand-built JSON: every gate in the set is already a
# `python3` invocation so it is not a new dependency, and argv carries the
# labels EXACTLY — no quoting or delimiter can corrupt a record.
_gate_dispatch_emit() {
  local path="$1" i n total nc
  n=${#GATE_LABELS[@]}
  nc=${#GATE_CORPUS_NAMES[@]}
  total=$(( SECONDS - GATE_DISPATCH_T0 ))
  # Fixed-width groups, gates first then corpora, with both counts passed
  # ahead of them: argv carries every label and corpus name EXACTLY, and no
  # separator token can be mistaken for one of them.
  local -a fields=()
  for (( i=0; i<n; i++ )); do
    fields+=("${GATE_STATES[$i]}" "${GATE_SECONDS[$i]}"
             "${GATE_ITEM_CORPUS[$i]}" "${GATE_ITEM_IDX[$i]}"
             "${GATE_ITEM_TOTAL[$i]}" "${GATE_LABELS[$i]}")
  done
  for (( i=0; i<nc; i++ )); do
    fields+=("${GATE_CORPUS_ITEMS[$i]}" "${GATE_CORPUS_GATES[$i]}"
             "${GATE_CORPUS_STATE[$i]}" "${GATE_CORPUS_NAMES[$i]}")
  done
  GATE_DISPATCH_SHARD_ID="$([ "$GATE_DISPATCH_SHARD_I" -ge 0 ] \
      && echo "$GATE_DISPATCH_SHARD_I/$GATE_DISPATCH_SHARD_N")" \
  python3 - "$path" "$total" "$GATE_DISPATCH_LIST_ONLY" "$n" "$nc" \
      ${fields[@]+"${fields[@]}"} \
      ${GATE_UNDISCLOSED_LOOPS[@]+"${GATE_UNDISCLOSED_LOOPS[@]}"} <<'PY'
import json, os, sys
out, total, list_only = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "1"
SHARD = os.environ.get("GATE_DISPATCH_SHARD_ID") or None
ng, nc = int(sys.argv[4]), int(sys.argv[5])
rest = sys.argv[6:]
gf, rest = rest[:ng * 6], rest[ng * 6:]
cf, undisclosed = rest[:nc * 4], rest[nc * 4:]
gates = []
for i in range(0, len(gf), 6):
    # The three loop keys are written ONLY for a gate a loop produced, so a
    # gate wired outside one records byte-for-byte what it recorded before
    # vibe-ic#957 — the record of the other ~70 must not move either.
    g = {"label": gf[i + 5], "state": gf[i], "seconds": int(gf[i + 1])}
    if gf[i + 2]:
        g["corpus"] = gf[i + 2]
        g["corpus_item"] = int(gf[i + 3])
        # The DENOMINATOR this gate's verdict covers, stated per gate as well
        # as per corpus: a consumer that reads one gate must not have to
        # reconstruct how many there were of it.
        g["corpus_items"] = int(gf[i + 4])
    gates.append(g)
corpora = [{"name": cf[i + 3], "items": int(cf[i]), "gates": int(cf[i + 1]),
            "expansion": cf[i + 2]}
           for i in range(0, len(cf), 4)]
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
    # Never folded into `passed` or `deferred`: this host declared the gate
    # and another host is responsible for it. The aggregator needs the
    # distinction to prove single coverage.
    "other_shard": n("OTHER_SHARD"),
    "shard": SHARD,
    # vibe-ic#957 — `declared` counts GATES. A loop-driven gate's subject is an
    # ITEM, and three green gates over one item is not three items checked.
    # One entry per expansion, present even when it produced no gate at all,
    # because a corpus that expanded to zero is invisible in `gates` by
    # construction and is the case a reader most needs told.
    "corpora": corpora,
    # Loops wired around the dispatcher instead of through it: their
    # denominator is unknown, and unknown is recorded rather than assumed 1.
    "undisclosed_loops": undisclosed,
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
    # TO STDERR IN LIST MODE, with the count line that is already there:
    # `--list`'s STDOUT is the gate labels and a caller may read it as such, so
    # a sentence about the run belongs on the same stream as the existing one.
    # A loop that expanded over nothing has no label to appear among them,
    # which is exactly why this must still print.
    _gate_dispatch_corpora_rollup "$declared" >&2
    _gate_dispatch_undisclosed_loops
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

  # vibe-ic#957 — BEFORE the verdict, and on the same stream as it: the
  # sentence a reader takes away is "N gates passed", and N counts GATES. What
  # each loop-driven gate covered is a different number, and it is the one the
  # label's scope invites a reader to assume.
  _gate_dispatch_corpora_rollup "$declared"
  _gate_dispatch_undisclosed_loops
  # Loop corpora that expanded over nothing, named so the closing sentence can
  # refuse to stand unqualified over them.
  local empty="" nempty=0
  for (( i=0; i<${#GATE_CORPUS_NAMES[@]}; i++ )); do
    [ "${GATE_CORPUS_ITEMS[$i]}" -eq 0 ] || continue
    nempty=$(( nempty + 1 ))
    empty="${empty:+$empty, }${GATE_CORPUS_NAMES[$i]}"
  done

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
  # vibe-ic#957 — a loop that expanded over NOTHING declares no gate, so it
  # cannot appear in `$declared` and cannot be NOT_CHECKED either: the set of
  # gates silently shrinks and the sentence below stays literally true while
  # the coverage it implies has gone to zero. That is the same aggregation
  # dishonesty #539 removed, arriving through the denominator instead of
  # through a state, so it is refused the same way — by NAME, in the sentence.
  if [ "$nempty" -ne 0 ]; then
    echo "repo_hygiene_gates: all $declared gate(s) passed, but $nempty loop" \
         "corpus/corpora expanded over 0 item(s) — NOTHING was checked over:" \
         "$empty (${total}s)"
    exit 0
  fi
  # Only now is the unqualified sentence true. It still states its own
  # denominator, so it cannot be read over a set that silently shrank.
  echo "repo_hygiene_gates: all $declared gate(s) passed (${total}s)"
  exit 0
}
