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
#                                      # declared, nothing was DECIDED, or the
#                                      # wiring is wrong)
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
# WHY NOT_CHECKED NEEDS AN EXEMPTION (vibe-ic#584)
# ================================================
# Every state above is honest about the SINGLE run and said nothing about the
# TREND. Measured on this file before this paragraph existed: the sweep printed
# "74 declared, 3 NOT CHECKED — this is NOT a pass over: <names>" and exited 0,
# and `gatekeeper_review._hygiene_verdict` copied those names into its summary
# string and returned MERGE_OK. #539 fixed the SENTENCE and left the EXIT CODE
# and the CONSUMER alone — the sweep said it had not checked, and passed as if
# it had.
#
# There was also no ratchet. NOT_CHECKED is reachable ONLY through
# `run_tolerating_uncheckable` + rc 2 — a missing binary (rc 127), an uncaught
# exception (rc 1) and a plain `run` exiting 2 all become FAIL, which is loud,
# and that part was sound. But `run` -> `run_tolerating_uncheckable` is a
# ONE-WORD edit that converts a gate's every rc-2 refusal into a tolerated
# non-verdict, and nothing objected. The count could go 0 -> 3 with the only
# trace a log line nobody exits non-zero on, and each increment subtracted a
# gate from a set the reader still counts as 74.
#
# So the tolerance has to be BOUGHT, not assumed:
#
#   * `run_tolerating_uncheckable` without an `uncheckable_until` immediately
#     above it is a WIRING ERROR (rc 2). You cannot make a gate skippable by
#     forgetting something; you have to write down a date and a reason.
#   * An `uncheckable_until` on a plain `run` is ALSO a wiring error — it
#     describes a state that gate cannot reach, and a reader who saw it would
#     believe a tolerance that does not exist.
#   * An exemption whose date has PASSED fails the sweep (rc 1) whether or not
#     it fired. An exemption is a promise to revisit, not a permanent licence;
#     one kept past its reason is a blind spot exactly the size of the gate it
#     covers, and the run where it silently starts covering a real regression
#     is the run where nobody is looking.
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
# that reports NOT_CHECKED still exits 0, loudly, naming the gate and the
# exemption covering it — that is `run_tolerating_uncheckable`'s original
# purpose and it is intact. What changed is that the set of gates allowed to do
# so is now closed, dated and reasoned instead of open-ended.
#
# WHY ZERO DECIDED IS REFUSED (vibe-ic#1025)
# ==========================================
# #539 fixed the SENTENCE and #584 made each individual refusal BUY its
# tolerance. Neither asked what happens when the bought set is ALL of them.
# MEASURED on 75776dbbb, six gates each returning rc 2 under a live exemption:
# the sweep printed "0 of 6 gate(s) passed; 6 NOT CHECKED — this is NOT a pass"
# and EXITED 0, and `gatekeeper_review._hygiene_verdict` returned rc 0 —
# MERGE_OK — over that record. The sentence said "not a pass" and the exit code
# said pass, and every `-ne 0` consumer believes the exit code.
#
# `gate_dispatch_finish` therefore refuses a run in which NO gate reached a
# verdict, with rc 2 — the same tier, and for the same reason, as a script that
# declared no gate at all. See the branch itself for why it is rc 2 and not
# rc 1, and why the line is ZERO DECIDED rather than "any NOT_CHECKED".
#
# chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.

# --- state -----------------------------------------------------------------
GATE_DISPATCH_SUMMARY_JSON=""
GATE_DISPATCH_LIST_ONLY=0
# Optional machine channel written after each completed gate.  The hygiene
# script enables it for the real run; fixture users that source this library
# without the helper retain the historical execution path byte-for-byte.
GATE_DISPATCH_ATTESTATION_FILE="${GATE_DISPATCH_ATTESTATION_FILE:-}"
GATE_DISPATCH_ATTESTATION_HELPER="${GATE_DISPATCH_ATTESTATION_HELPER:-}"
# Optional live, owner-facing mirror.  The attestation file above may be a
# per-shard scratch record that is merged only at the end; this second channel
# receives the same complete records as soon as each owned gate finishes, so a
# supervisor waits on measured progress instead of a guessed whole-run timeout.
GATE_DISPATCH_PROGRESS_FILE="${GATE_DISPATCH_PROGRESS_FILE:-}"
GATE_DISPATCH_ATTESTATION_FAILED=0
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

# --- THE UNCHECKABLE EXEMPTION REGISTER (vibe-ic#584) -----------------------
#: Today, read ONCE per run so that a sweep spanning midnight cannot expire an
#: exemption for gate 60 that it honoured for gate 1 — one run, one date.
GATE_DISPATCH_TODAY=""
#: The exemption declared by `uncheckable_until` and not yet attached to a gate.
#: A SLOT rather than a lookup table keyed by label: adjacency is then a
#: property of the mechanism instead of a convention a reader has to honour, so
#: an exemption cannot drift away from the gate it excuses or outlive its
#: deletion. It also works unchanged inside `gate_dispatch_over`, where the
#: declaring line is executed once per item.
GATE_PENDING_UNTIL=""
GATE_PENDING_SCOPE=""
GATE_SCOPES=()
GATE_PENDING_WHY=""
#: Parallel to GATE_LABELS — empty for the (normal) unexempted gates.
declare -a GATE_EX_UNTIL=() GATE_EX_WHY=() GATE_WIRING_ERRORS=()

# --- CONCURRENCY (#P4) ------------------------------------------------------
# MEASURED on this tree at v1.10.53, 32 cores: the landing gate is 1305 s and
# `repo_hygiene_gates.sh` is 1082 s of it. 84 gates self-report 912 s and the
# wall was ~= that sum, so they ran one after another. There is no dominant
# gate to optimise — the slowest is 150 s and the tail averages ~11 s — so the
# only lever that reaches the whole 1082 s is running them at the same time.
#
# WHY A KNOB WITH A MEASURED DEFAULT, AND NOT `nproc`. Measured earlier on this
# same 32-core host: raising `gate_host_independence_check --jobs` from 8 to 28
# made that gate SLOWER, 213 s -> 227 s. The cores were waiting on DISK, not on
# CPU, and every one of these gates walks the same tree. So the default is a
# number that was timed here (see the sweep recorded with this change), not a
# number derived from the machine, and `GATEKEEPER_HYGIENE_JOBS` moves it.
#
# WHAT MUST NOT CHANGE, and it is the whole acceptance test: the set of
# (label -> state) pairs. Faster and different is a failure. Three properties
# buy that:
#
#   * DECLARATION STAYS SEQUENTIAL. Everything above — the exemption slot, the
#     scope slot, the wiring errors, the site counter, the label order — runs on
#     the main shell in declaration order exactly as before. Only the gate's
#     PROCESS moves. So the record is indexed identically and a gate's verdict
#     lands in its own slot by construction rather than by matching a label.
#
#   * OUTPUT IS BUFFERED AND REPLAYED IN DECLARATION ORDER, stdout to stdout and
#     stderr to stderr. Interleaved output from 8 gates is not merely unreadable:
#     a finding printed under the wrong label sends the next reader to the wrong
#     file, which is worse than no output. A gate is emitted whole, under its own
#     `── label`, and only once every gate declared before it has been emitted.
#
#   * A GATE THAT NEEDS THE WHOLE RUN RUNS ALONE. `gate_serial` (below) drains
#     the pool first. `gates are host-independent` READS the machine record every
#     other gate wrote and drives a `git worktree`; queued with the rest it would
#     find an incomplete record and report NOT CHECKED — faster, and wrong.
#
# EVERY GATE'S CHILD PROCESS GETS `GATEKEEPER_HYGIENE_JOBS=1`, in both modes.
# `gate_host_independence_check` re-runs THIS SCRIPT, eight times, in a scratch
# worktree. Without this, the knob would be inherited and the nested runs would
# multiply it — 8 x N processes for a reason nobody chose. Exactly one level of
# this script is parallel: the outermost.
GATE_DISPATCH_JOBS=1
#: Scratch for one run's per-gate buffers. Removed by `gate_dispatch_finish`.
GATE_POOL_DIR=""
#: Queued gate indices in DECLARATION order — the replay order, and the reason
#: completion order can never reach a reader.
declare -a GATE_POOL_IDX=()
#: How far along GATE_POOL_IDX the replay has already got.
GATE_POOL_FLUSHED=0
#: Workers whose result file never appeared. Their gates are NOT_CHECKED (never
#: PASS) and the run refuses — see `gate_dispatch_finish`.
GATE_DISPATCH_WORKERS_LOST=0
GATE_POOL_LOST_LABELS=""
#: Set by `gate_serial`; consumed by the next `_dispatch` the same way the
#: exemption and the scope are, so it can never stay armed for the gate after.
GATE_PENDING_SERIAL=0

# `gate_serial <why>` — the NEXT gate runs ALONE: every queued gate is drained
# and replayed first, and nothing new starts until it is done.
#
# NOT a performance hint. It is the declaration that a gate's subject is the
# STATE OF THE RUN ITSELF rather than the tree — the machine record the other
# gates wrote, the git worktree list, the checkout's dirtiness — any of which
# another gate running at the same time changes underneath it. A gate like that
# queued with the rest does not fail; it reports NOT CHECKED, which is the
# quietest possible way for concurrency to remove a gate from the set.
#
# Declared at the wiring site, above the gate, for the same reason
# `uncheckable_until` is: a registry keyed by label drifts when the gate is
# renamed, and deleting the gate must delete this with it.
gate_serial() {
  if [ "$GATE_PENDING_SERIAL" -ne 0 ]; then
    _gate_wiring_error "a 'gate_serial' was declared and never attached to a \
gate before 'gate_serial $*'"
  fi
  if [ "$#" -eq 0 ] || [ -z "${1:-}" ]; then
    _gate_wiring_error "'gate_serial' must state WHY the gate cannot share the \
run with another one"
  fi
  GATE_PENDING_SERIAL=1
}

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
  # ISO-8601 ONLY, so the expiry comparison can be a plain string compare: on
  # YYYY-MM-DD, lexicographic order IS chronological order, in every locale,
  # with no date library and no parsing that could itself fail open. A
  # well-shaped but calendar-impossible date (2026-02-31) still orders
  # correctly and still expires — it can hide nothing.
  if ! [[ "$until" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    _gate_wiring_error "'uncheckable_until ${until:-<empty>}': the review date \
must be ISO-8601 YYYY-MM-DD"
  fi
  # An exemption with no reason is a skip button with a date printed on it: the
  # reader it exists for cannot then tell a benign missing prerequisite from a
  # gate that has quietly stopped working.
  if [ -z "$why" ]; then
    _gate_wiring_error "'uncheckable_until ${until:-<empty>}': an exemption \
must state WHY the gate can be unable to run"
  fi
  GATE_PENDING_UNTIL="$until"; GATE_PENDING_WHY="$why"
}

# `gate_scope <path> [<path>…]` — declare the paths the NEXT gate reads (#P3).
#
# WHY A GATE MAY BE SKIPPED AT ALL. Measured over 45 recent PRs: 56% touch only
# `vibe-ic-marketplace/`, yet every landing ran all 80 gates over the whole tree.
# Running `tools/`-only checks for a PR that never touched `tools/` is time paid
# for an answer nobody could act on.
#
# THREE PROPERTIES, and they are the whole safety of this feature:
#
#   1. NARROWING IS OPT-IN. A gate with no `gate_scope` line ALWAYS runs. Silence
#      means "I do not know what this reads", and the only safe reading of that is
#      to run it. Nothing is skipped by default, ever.
#
#   2. AN UNKNOWN CHANGE SET RUNS EVERYTHING. If `GATEKEEPER_CHANGED_PATHS` is
#      unset or names a file that does not exist, scope is not consulted. "I could
#      not find out what changed" must never render as "nothing relevant changed" —
#      that is the empty-result-is-not-a-zero rule, and it is the failure this
#      feature would otherwise introduce.
#
#   3. A SKIP IS RECORDED AND PRINTED, never absent. It becomes state
#      `OUT_OF_SCOPE` in the summary record with the declared scope attached, and
#      it prints a SKIP line. A gate that vanishes from the roll-up would let a
#      shrinking denominator read as a clean sheet.
#
# The scope is matched as a PATH PREFIX against each changed path, so
# `gate_scope tools/` covers `tools/ci/x.sh`. Give the narrowest true prefix; a
# scope that is too narrow silently stops guarding, which is why the pairing test
# asserts a real change inside each declared scope still runs its gate.
gate_scope() {
  if [ -n "${GATE_PENDING_SCOPE:-}" ]; then
    _gate_wiring_error "a scope ($GATE_PENDING_SCOPE) was declared and never \
attached to a gate before 'gate_scope $*'"
  fi
  if [ "$#" -eq 0 ]; then
    _gate_wiring_error "'gate_scope' with no path: a scope that names nothing \
cannot be intersected, and an empty scope would skip the gate on every change"
  fi
  GATE_PENDING_SCOPE="$*"
}

#: Did anything in `$1` (space-separated prefixes) change? Answers "unknown" as
#: YES, so the caller runs the gate.
_gate_scope_hit() {                        # <scope-prefixes> -> 0 = run, 1 = skip
  local scope="$1" f p
  [ -n "${GATEKEEPER_CHANGED_PATHS:-}" ] || return 0     # unknown -> run
  [ -s "${GATEKEEPER_CHANGED_PATHS:-/nonexistent}" ] || return 0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    for p in $scope; do
      case "$f" in "$p"*) return 0 ;; esac
    done
  done < "$GATEKEEPER_CHANGED_PATHS"
  return 1
}

gate_dispatch_init() {
  GATE_DISPATCH_T0="$SECONDS"
  # #P4 — 8 BY MEASUREMENT, not by `nproc`. Two reps of this exact gate set (80
  # declared) on a 32-core host, sequential arm 412 s:
  #
  #       jobs      4      8     12     16     24     32
  #       rep 1   112s    68s    58s    54s    53s    55s
  #       rep 2   115s    77s    58s    54s    56s    52s
  #
  # 4 -> 8 is the last large step (-44 s, -39%). 8 -> 12 buys 14 s more, and
  # everything past 12 is flat inside the noise: 24 and 32 straddle 53 s in both
  # directions, which is the same shape as the earlier measurement where
  # `gate_host_independence_check --jobs` 8 -> 28 made that gate SLOWER
  # (213 s -> 227 s) because the cores were waiting on DISK. Every gate here
  # walks the same tree, so that ceiling is the one being hit.
  #
  # 8 AND NOT 12, deliberately. The 14 s is real and it is 3% of the landing
  # gate; against it, 8 leaves three quarters of a 32-core host for the
  # parallelism the GATES themselves already use (`--jobs 6`, `--jobs 8`, a
  # pytest session), it is the one concurrency number in this repo that was
  # measured before (that same host-independence gate), and the fleet is not all
  # 32-core. A host with headroom sets `GATEKEEPER_HYGIENE_JOBS=12` and the
  # table above says what it will get. 1 restores the exact pre-#P4 execution
  # path, gate for gate and byte for byte.
  GATE_DISPATCH_JOBS="${GATEKEEPER_HYGIENE_JOBS:-8}"
  # A malformed knob is REFUSED, not rounded to 1. Silently falling back to
  # sequential would make a run that a caller asked to parallelise take twenty
  # minutes for no stated reason; silently falling back to `nproc` would be the
  # measured-slower default this file exists to avoid.
  if ! [[ "$GATE_DISPATCH_JOBS" =~ ^[0-9]+$ ]] || [ "$GATE_DISPATCH_JOBS" -lt 1 ]
  then
    _gate_wiring_error "GATEKEEPER_HYGIENE_JOBS='${GATEKEEPER_HYGIENE_JOBS}' is \
not a positive integer; refusing to guess how much of this run to parallelise"
    GATE_DISPATCH_JOBS=1
  fi
  GATE_DISPATCH_TODAY="$(date -u +%F 2>/dev/null || true)"
  # Fail CLOSED on the clock. An empty or malformed `today` would make every
  # `until` compare as not-yet-due, so every exemption would be immortal and
  # the expiry half of #584 would be silently absent — a check that stops
  # checking without saying so, which is the class this file exists to remove.
  # Reported through the same channel as a mis-wired gate, so it lands as rc 2
  # (nothing was certified) rather than as a gate verdict.
  [[ "$GATE_DISPATCH_TODAY" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] \
    || _gate_wiring_error "could not read today's date as YYYY-MM-DD (got \
'${GATE_DISPATCH_TODAY:-<empty>}'), so no uncheckable exemption could be \
checked for expiry"
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
  # `GIT_OPTIONAL_LOCKS=0` ONLY WHEN THERE ARE PEERS (#P4). `git status`
  # opportunistically REFRESHES and rewrites the index, which takes
  # `.git/index.lock`; eight of these at once contend for it, and a snapshot
  # that failed to take is an EMPTY snapshot — which this guard would compare
  # against the next empty one and call clean. The flag tells git to do the read
  # and skip the write, so the porcelain output is identical and the lock is
  # never taken. Left OFF at jobs=1 so the sequential path is byte-for-byte and
  # syscall-for-syscall what it has always been.
  if [ "${GATE_DISPATCH_JOBS:-1}" -gt 1 ]; then
    GIT_OPTIONAL_LOCKS=0 git -C "$root" status --porcelain \
        --ignored=traditional -- "$GATE_DISPATCH_CORPUS_REL" 2>/dev/null \
      | LC_ALL=C sort
  else
    git -C "$root" status --porcelain --ignored=traditional -- \
        "$GATE_DISPATCH_CORPUS_REL" 2>/dev/null | LC_ALL=C sort
  fi
}

# `_dispatch <tolerate_rc2> <may_write_corpus> <label> <cwd> <cmd...>` — the ONE
# place a gate is executed and the ONE place its outcome is recorded.
_dispatch() {
  local tolerate="$1" may_write="$2" label="$3" wd="$4"; shift 4
  # vibe-ic#584 — consume the pending exemption FIRST and unconditionally, so a
  # mis-wired gate cannot leave it armed for the next one: an exemption written
  # for gate N silently excusing gate N+1 is worse than none at all.
  local ex_until="$GATE_PENDING_UNTIL" ex_why="$GATE_PENDING_WHY"
  GATE_PENDING_UNTIL=""; GATE_PENDING_WHY=""
  # Same rule as the exemption above and for the same reason (#584): consume the
  # pending scope UNCONDITIONALLY, so a scope written for gate N can never be left
  # armed to silence gate N+1.
  local scope="${GATE_PENDING_SCOPE:-}"
  GATE_PENDING_SCOPE=""
  # #P4, same rule again and for the same reason: a `gate_serial` written for
  # gate N must never still be armed at gate N+1. Consumed unconditionally,
  # before any branch can return.
  local serial="${GATE_PENDING_SERIAL:-0}"
  GATE_PENDING_SERIAL=0
  if [ "$tolerate" -eq 1 ] && [ -z "$ex_until" ]; then
    _gate_wiring_error "\"$label\" is wired with run_tolerating_uncheckable, so \
it can report NOT_CHECKED, but no 'uncheckable_until <YYYY-MM-DD> <why>' line \
precedes it — tolerance has to be bought, not defaulted into"
  elif [ "$tolerate" -eq 0 ] && [ -n "$ex_until" ]; then
    _gate_wiring_error "\"$label\" carries an 'uncheckable_until $ex_until' \
exemption but is wired with a wrapper that can never report NOT_CHECKED — the \
exemption describes a state this gate cannot reach"
  fi
  GATE_EX_UNTIL+=("$ex_until"); GATE_EX_WHY+=("$ex_why")
  GATE_LABELS+=("$label")
  #: One append per gate, at the SAME point as the label, because the record is
  #: read by index: a scope appended on only some code paths would attribute one
  #: gate's scope to another gate's verdict.
  GATE_SCOPES+=("$scope")
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
  # #P3 — the gate declared what it reads, and this change touched none of it.
  #
  # ITS OWN STATE, deliberately not folded into any existing one. It is not a PASS
  # (nothing ran and nothing was examined), not NOT_CHECKED (the gate is perfectly
  # able to run — it simply has nothing here to say), and not LISTED (this is a
  # real run). Folding it into PASS is exactly the shape this repo keeps paying
  # for: a shrinking denominator reading as a clean sheet.
  #
  # It PRINTS, so the roll-up a human reads shows what was not asked, and the
  # scope goes into the record so the next reader can check the claim rather than
  # inherit it.
  if [ -n "$scope" ] && ! _gate_scope_hit "$scope"; then
    GATE_STATES+=("OUT_OF_SCOPE"); GATE_SECONDS+=("0")
    # #P4 — THE SKIP LINE IS BUFFERED TOO, when there is a pool. It is decided
    # instantly, at declaration time, while the gates declared BEFORE it are
    # still running; printed straight out it would appear above output it comes
    # after, and a reader scanning for the gate a finding belongs to would be
    # reading a log whose order is not the declaration order the roll-up uses.
    # Found by reading this path, not by a failing run: `GATEKEEPER_CHANGED_PATHS`
    # is unset outside a landing, so no test that does not set it can reach here.
    if [ "$GATE_DISPATCH_JOBS" -gt 1 ]; then
      _gate_pool_precomputed "$(( ${#GATE_LABELS[@]} - 1 ))" \
        "$(printf '  SKIP  %s  — reads [%s]; this change touches none of it\n' \
             "$shown" "$scope")"
    else
      printf '  SKIP  %s  — reads [%s]; this change touches none of it\n' \
        "$shown" "$scope"
    fi
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
  # #P4 — from here down the gate is EXECUTED, and that is the only part that
  # may move off the main shell. Everything above is DECLARATION and stays
  # exactly where it was, in exactly its old order.
  if [ "$GATE_DISPATCH_JOBS" -le 1 ] || [ "$serial" -eq 1 ] \
     || [ "$may_write" -eq 1 ]; then
    # `may_write` joins `serial` deliberately: a declared corpus PRODUCER is by
    # definition the one gate whose writes every other gate's read would race.
    # There are none today; the rule ships with the wrapper so that wiring one
    # cannot silently make the corpus guard meaningless for the rest of the run.
    [ "$GATE_DISPATCH_JOBS" -le 1 ] || _gate_pool_drain
    _gate_execute "$tolerate" "$may_write" "$label" "$shown" \
                  "$ex_until" "$ex_why" "$wd" "$@"
    GATE_STATES+=("$_GX_STATE"); GATE_SECONDS+=("$_GX_SECS")
    case "$_GX_STATE" in FAIL|WROTE_CORPUS) GATE_DISPATCH_FAIL=1 ;; esac
    return 0
  fi
  # The slot is claimed NOW, at declaration time, and filled in by
  # `_gate_pool_collect` when the worker's verdict comes back. Appending on
  # completion instead would order the record by whichever gate finished first —
  # the exact unattributability this is here to prevent.
  GATE_STATES+=("QUEUED"); GATE_SECONDS+=("0")
  _gate_pool_submit "$(( ${#GATE_LABELS[@]} - 1 ))" \
                    "$tolerate" "$may_write" "$label" "$shown" \
                    "$ex_until" "$ex_why" "$wd" "$@"
  return 0
}

# `_gate_execute <tolerate> <may_write> <label> <shown> <until> <why> <cwd>
#                <cmd...>`
#
# Runs ONE gate and classifies it. Sets `_GX_STATE` and `_GX_SECS`; prints the
# gate's own output on stdout and the dispatcher's diagnostics on stderr, on
# whatever streams the caller gave it.
#
# THE ONE EXECUTION PATH, called by the inline arm and by the worker alike. Two
# copies — one "fast" and one "safe" — is how a concurrent run comes to classify
# an rc differently from a sequential one while both look correct in review.
#
# ALWAYS RETURNS 0. Its caller may be a worker running under `set -e`, where a
# non-zero return would kill the worker BEFORE it wrote its result file, and a
# missing result file is read (correctly) as a killed worker. A gate that merely
# FAILED must never present as a lost one.
_gate_execute() {
  local tolerate="$1" may_write="$2" label="$3" shown="$4"
  local ex_until="$5" ex_why="$6" wd="$7"; shift 7
  _GX_STATE=""; _GX_SECS=0
  echo "── $shown"
  local t0="$SECONDS" rc=0 before="" after="" watched=1 capture=""
  before="$(_gate_dispatch_corpus_state)" || watched=0
  # `|| rc=$?` and NOT a bare `( ... ); rc=$?` — the caller runs under `set -e`,
  # where a failing subshell aborts before the next line and the disclosure
  # below would never print.
  if [ -n "$GATE_DISPATCH_ATTESTATION_FILE" ]; then
    if [ -f "$GATE_DISPATCH_ATTESTATION_HELPER" ]; then
      capture="$(mktemp "${GATE_DISPATCH_ATTESTATION_FILE}.gate.XXXXXX")"
      local -a _pipe_rc=()
      # One combined stream is intentional: it is the process evidence a human
      # sees in the landing log, and tee keeps that stream live while the helper
      # derives the machine record from the exact same bytes.
      if ( cd "$wd" && export GATEKEEPER_HYGIENE_JOBS=1 && "$@" ) 2>&1 \
           | tee "$capture"; then
        _pipe_rc=("${PIPESTATUS[@]}")
      else
        _pipe_rc=("${PIPESTATUS[@]}")
      fi
      rc="${_pipe_rc[0]}"
      if [ "${_pipe_rc[1]:-1}" -ne 0 ]; then
        GATE_DISPATCH_ATTESTATION_FAILED=1
        echo "   ^^ PROCESS ATTESTATION FAILED: $label — tee could not" \
             "preserve the complete process stream; a partial record is not" \
             "accepted as evidence" >&2
      elif ! python3 "$GATE_DISPATCH_ATTESTATION_HELPER" \
          --label "$label" --returncode "$rc" --output-log "$capture" \
          --append-jsonl "$GATE_DISPATCH_ATTESTATION_FILE" \
          --root "${ROOT:-$wd}" --root "$wd" -- "$@"; then
        GATE_DISPATCH_ATTESTATION_FAILED=1
        echo "   ^^ PROCESS ATTESTATION FAILED: $label — the gate ran, but its" \
             "machine verdict record was not written; host comparison will" \
             "refuse rather than reconstruct it from prose" >&2
      elif [ -n "$GATE_DISPATCH_PROGRESS_FILE" ] \
           && [ "$GATE_DISPATCH_PROGRESS_FILE" != "$GATE_DISPATCH_ATTESTATION_FILE" ] \
           && ! python3 "$GATE_DISPATCH_ATTESTATION_HELPER" \
          --label "$label" --returncode "$rc" --output-log "$capture" \
          --append-jsonl "$GATE_DISPATCH_PROGRESS_FILE" \
          --root "${ROOT:-$wd}" --root "$wd" -- "$@"; then
        GATE_DISPATCH_ATTESTATION_FAILED=1
        echo "   ^^ PROCESS PROGRESS MIRROR FAILED: $label — the gate ran, but" \
             "its live completion event was not preserved; this run cannot" \
             "claim observable progress" >&2
      fi
      rm -f -- "$capture"
    else
      ( cd "$wd" && export GATEKEEPER_HYGIENE_JOBS=1 && "$@" ) || rc=$?
      GATE_DISPATCH_ATTESTATION_FAILED=1
      echo "   ^^ PROCESS ATTESTATION FAILED: $label — helper missing at" \
           "${GATE_DISPATCH_ATTESTATION_HELPER:-<unset>}; this run cannot" \
           "certify a tree from console prose" >&2
    fi
  else
    ( cd "$wd" && export GATEKEEPER_HYGIENE_JOBS=1 && "$@" ) || rc=$?
  fi
  local secs=$(( SECONDS - t0 ))
  _GX_SECS="$secs"
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
      _GX_STATE="WROTE_CORPUS"
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
    _GX_STATE="PASS"
  elif [ "$tolerate" -eq 1 ] && [ "$rc" -eq 2 ]; then
    _GX_STATE="NOT_CHECKED"
    # The exemption is echoed WITH the refusal, not only in the roll-up: this is
    # the line a reader reaches first, and "could not look" is benign only if
    # they can see which prerequisite was missing.
    echo "   ^^ NOT CHECKED (rc 2, non-fatal): $label [${secs}s]" \
         "— exempt until ${ex_until:-<NONE>}: ${ex_why:-<no reason declared>}" >&2
  else
    _GX_STATE="FAIL"
    echo "   ^^ FAILED: $label [${secs}s]" >&2
  fi
  return 0
}

# --- the worker pool (#P4) --------------------------------------------------
# One background subshell per queued gate, bounded by `GATE_DISPATCH_JOBS`.
# Deliberately NOT a set of long-lived workers reading a shared queue: a gate is
# an argv, and a long-lived worker would need that argv marshalled through a
# pipe and unmarshalled — a quoting surface, on the path every gate takes, for
# no measured gain over `fork` on a run whose gates average eleven seconds.
_gate_pool_ensure() {
  [ -z "$GATE_POOL_DIR" ] || return 0
  GATE_POOL_DIR="$(mktemp -d -t gate-pool.XXXXXX)"
  # REAP FIRST, and this is not tidiness. `gate_dispatch_finish` removes this
  # directory on every path it controls, but it does not control two: a SIGKILL,
  # and a caller that sources this library and never calls `finish` at all —
  # which is exactly what a test fixture does. MEASURED while building this:
  # six abandoned pools in /tmp from one afternoon of running the scope harness.
  # Six directories of three small files is not the damage; the damage is that
  # this repo has already paid hours for scratch a killed run left behind, and a
  # mechanism that accumulates is the one that is eventually holding something
  # that matters.
  #
  # `-mmin +1440` — a DAY. No hygiene run lives anywhere near that (the longest
  # measured is seven minutes), so this can never take a live peer's pool on a
  # host where several land at once. `-maxdepth 1` so it removes pools and never
  # walks into one.
  find "$(dirname "$GATE_POOL_DIR")" -maxdepth 1 -type d -name 'gate-pool.*' \
       -mmin +1440 -exec rm -rf -- {} + 2>/dev/null || true
  # BLINDNESS IS DECIDED ONCE, HERE, and inherited by every worker. It is a
  # property of the TREE (is there a `benchmark-data/` under a git repo), not of
  # a gate, so asking per worker would print the same paragraph once per gate —
  # and the note exists to be READ, which a hundred copies of it are not.
  if ! _gate_dispatch_corpus_state >/dev/null 2>&1; then
    if [ "$GATE_DISPATCH_CORPUS_BLIND" -eq 0 ]; then
      GATE_DISPATCH_CORPUS_BLIND=1
      echo "   ^^ corpus-write guard NOT ACTIVE: no" \
           "$GATE_DISPATCH_CORPUS_REL/ under a git repo reachable from" \
           "$(dirname "${BASH_SOURCE[0]}") — a gate writing into the corpus" \
           "would go unreported in this run" >&2
    fi
  fi
}

_gate_pool_worker() {   # <idx> <tolerate> <may_write> <label> <shown> <until>
                        # <why> <cwd> <cmd...>
  local idx="$1"; shift
  local d="$GATE_POOL_DIR/$idx"
  # A PRIVATE attestation file per gate, concatenated back in DECLARATION order
  # by `_gate_pool_collect`. Eight processes appending JSON lines to one file
  # would interleave a record sooner or later, and the consumer of that file
  # (`gate_host_independence_check`) refuses a malformed one — so the failure
  # would be a NOT CHECKED for the whole comparison, at random, under load.
  # The PROGRESS mirror is deliberately left pointing at the shared file: it is
  # advisory and its entire purpose is to be observable WHILE the run is going.
  [ -z "$GATE_DISPATCH_ATTESTATION_FILE" ] \
    || GATE_DISPATCH_ATTESTATION_FILE="$d.attest"
  _GX_STATE=""; _GX_SECS=0
  _gate_execute "$@" > "$d.out" 2> "$d.err"
  # WRITTEN LAST, AND RENAMED INTO PLACE. The result file is the worker's proof
  # of life: `_gate_pool_collect` reads its absence as "this worker died" and
  # records NOT_CHECKED. A partial write would be read as a verdict, so it is
  # never partially visible under its final name.
  printf '%s\n%s\n%s\n' "$_GX_STATE" "$_GX_SECS" \
    "$GATE_DISPATCH_ATTESTATION_FAILED" > "$d.res.part"
  mv -f "$d.res.part" "$d.res"
}

# `_gate_pool_precomputed <idx> <stdout-text>` — a gate whose verdict needed no
# process (today: OUT_OF_SCOPE). It takes a place in the replay queue so its line
# appears exactly where its declaration is, and its STATE is already in the
# record: the marker `-` tells `_gate_pool_collect` to replay the text and leave
# `GATE_STATES[$idx]` alone. It is a distinct marker rather than the state name
# because the only thing `collect` must never do is accept, as a verdict, a value
# a live worker could not have written.
_gate_pool_precomputed() {
  _gate_pool_ensure
  local idx="$1" d="$GATE_POOL_DIR/$1"
  printf '%s\n' "$2" > "$d.out"
  : > "$d.err"
  printf -- '-\n0\n0\n' > "$d.res"
  GATE_POOL_IDX+=("$idx")
}

#: A DECLARATION-TIME NOTE that belongs where it was written. `gate_dispatch_over`
#: says two things — the producer failed, the corpus was empty — at the moment it
#: expands, which is while earlier gates are still running. MEASURED: without
#: this, the EMPTY CORPUS paragraph landed three gates early in the JOBS=8 log,
#: above diagnostics from gates declared before it. It names its corpus so it was
#: never unattributable, but a reader who trusts log order for everything else
#: should not have to know which lines are the exception.
#:
#: Keyed by a NAME rather than a gate index because it is not a gate: it takes a
#: place in the replay queue and touches no slot in the record.
GATE_POOL_NOTE_SEQ=0
_gate_pool_note() {                       # <stderr-text>
  _gate_pool_ensure
  GATE_POOL_NOTE_SEQ=$(( GATE_POOL_NOTE_SEQ + 1 ))
  local key="note.$GATE_POOL_NOTE_SEQ" d="$GATE_POOL_DIR/note.$GATE_POOL_NOTE_SEQ"
  : > "$d.out"
  printf '%s\n' "$1" > "$d.err"
  printf -- '-\n0\n0\n' > "$d.res"
  GATE_POOL_IDX+=("$key")
}

#: Say it now, or queue it — whichever puts it where it was written.
_gate_dispatch_say_err() {
  if [ "${GATE_DISPATCH_JOBS:-1}" -gt 1 ]; then
    _gate_pool_note "$1"
  else
    printf '%s\n' "$1" >&2
  fi
}

_gate_pool_submit() {   # <idx> <tolerate> <may_write> <label> <shown> <until>
                        # <why> <cwd> <cmd...>
  _gate_pool_ensure
  # Bounded by COUNTING this shell's live children rather than by a token FIFO:
  # `jobs -rp` is the same fact the kernel has, and a FIFO adds a file whose
  # loss would deadlock the run.
  local live
  while :; do
    live="$(jobs -rp | grep -c . || true)"
    [ "$live" -ge "$GATE_DISPATCH_JOBS" ] || break
    wait -n 2>/dev/null || true
    # Replay whatever PREFIX has completed while we were blocked, so a human
    # watching the log sees measured progress instead of ten silent minutes.
    _gate_pool_flush_prefix
  done
  GATE_POOL_IDX+=("$1")
  _gate_pool_worker "$@" &
}

#: Emit every queued gate whose turn has come AND which has finished, stopping
#: at the first one that has not. Declaration order, never completion order.
_gate_pool_flush_prefix() {
  local n=${#GATE_POOL_IDX[@]} idx
  while [ "$GATE_POOL_FLUSHED" -lt "$n" ]; do
    idx="${GATE_POOL_IDX[$GATE_POOL_FLUSHED]}"
    [ -f "$GATE_POOL_DIR/$idx.res" ] || return 0
    _gate_pool_collect "$idx"
    GATE_POOL_FLUSHED=$(( GATE_POOL_FLUSHED + 1 ))
  done
  return 0
}

#: Replay ONE finished gate and fold its verdict into the record.
_gate_pool_collect() {
  local idx="$1" d="$GATE_POOL_DIR/$1" st="" secs="" attf=""
  if [ -f "$d.res" ]; then
    { IFS= read -r st || true
      IFS= read -r secs || true
      IFS= read -r attf || true; } < "$d.res"
  fi
  # The gate's own two streams, kept apart. `gatekeeper-land.sh` captures
  # STDOUT and reads it; folding a gate's stderr into it would change what that
  # caller sees, and folding stdout into stderr would hide it from them.
  [ ! -f "$d.out" ] || cat -- "$d.out"
  [ ! -f "$d.err" ] || cat -- "$d.err" >&2
  # AN UNRECOGNISED STATE IS A LOST WORKER, not a pass. This covers the killed
  # worker (no file), the worker killed mid-write (empty or truncated file) and
  # any future state name this branch has not been taught — all three are "no
  # verdict arrived", and the one thing none of them may become is PASS.
  case "$st" in
    # `-` is the no-process row placed by `_gate_pool_precomputed`: its state was
    # recorded at declaration time and there was never a worker to lose.
    -) return 0 ;;
    PASS|FAIL|NOT_CHECKED|WROTE_CORPUS) ;;
    *) st="" ;;
  esac
  if [ -z "$st" ]; then
    GATE_STATES[$idx]="NOT_CHECKED"
    GATE_SECONDS[$idx]="0"
    GATE_DISPATCH_WORKERS_LOST=$(( GATE_DISPATCH_WORKERS_LOST + 1 ))
    GATE_POOL_LOST_LABELS="${GATE_POOL_LOST_LABELS:+$GATE_POOL_LOST_LABELS, }\
${GATE_LABELS[$idx]}"
    echo "   ^^ WORKER LOST: ${GATE_LABELS[$idx]} — the process assigned this" \
         "gate never reported a verdict (killed, out of memory, or the host" \
         "went away). Recorded NOT CHECKED. It is NOT a pass, and this run" \
         "will refuse rather than certify a tree it did not finish looking" \
         "at." >&2
    return 0
  fi
  GATE_STATES[$idx]="$st"
  [[ "$secs" =~ ^[0-9]+$ ]] || secs=0
  GATE_SECONDS[$idx]="$secs"
  case "$st" in FAIL|WROTE_CORPUS) GATE_DISPATCH_FAIL=1 ;; esac
  [ "${attf:-0}" = "0" ] || GATE_DISPATCH_ATTESTATION_FAILED=1
  if [ -n "$GATE_DISPATCH_ATTESTATION_FILE" ] && [ -s "$d.attest" ]; then
    cat -- "$d.attest" >> "$GATE_DISPATCH_ATTESTATION_FILE"
  fi
  return 0
}

#: Wait for every queued gate and replay all of them, in declaration order.
#: Called by `gate_serial` (before the gate that must run alone) and by
#: `gate_dispatch_finish`.
_gate_pool_drain() {
  [ -n "$GATE_POOL_DIR" ] || return 0
  wait 2>/dev/null || true
  local n=${#GATE_POOL_IDX[@]}
  # Deliberately NOT `_gate_pool_flush_prefix`: that one stops at the first
  # unfinished gate, which after `wait` can only be a LOST one — and stopping
  # there would silently drop every gate behind it from the roll-up.
  while [ "$GATE_POOL_FLUSHED" -lt "$n" ]; do
    _gate_pool_collect "${GATE_POOL_IDX[$GATE_POOL_FLUSHED]}"
    GATE_POOL_FLUSHED=$(( GATE_POOL_FLUSHED + 1 ))
  done
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
    _gate_dispatch_say_err "   ^^ CORPUS PRODUCER FAILED (rc $rc) for \
\"$corpus\": the $n item(s) below are what it managed to print and NOT the \
corpus — read every verdict from this loop as covering an unknown fraction of it"
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
    # IN LOCKSTEP, and that is the whole point: every reader below indexes these
    # arrays by the SAME `i` out of `${#GATE_LABELS[@]}`. This synthetic row was
    # appending six of the eight, so `GATE_EX_UNTIL[$i]` was unbound for it and
    # `set -u` killed the run at the expiry sweep — a corpus that expands over
    # nothing took the whole dispatcher down. It carries no exemption, so the
    # honest value is empty, which every reader already treats as "none".
    GATE_EX_UNTIL+=("")
    GATE_EX_WHY+=("")
    GATE_ITEM_CORPUS+=("$corpus")
    GATE_ITEM_IDX+=("0")
    GATE_ITEM_TOTAL+=("0")
    _gate_dispatch_say_err "   ^^ EMPTY CORPUS \"$corpus\": 0 item(s), so \
the gates it would have dispatched did not run. Recorded NOT_CHECKED so the run \
carries a verdict for it instead of no verdict at all."
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
  local path="$1" i n total nc nw
  n=${#GATE_LABELS[@]}
  nc=${#GATE_CORPUS_NAMES[@]}
  nw=${#GATE_WIRING_ERRORS[@]}
  total=$(( SECONDS - GATE_DISPATCH_T0 ))
  # Fixed-width groups, gates first then corpora then wiring errors, with every
  # count passed ahead of them: argv carries every label, corpus name, exemption
  # reason and diagnostic EXACTLY, and no separator token can be mistaken for
  # one of them. `undisclosed_loops` remains the un-prefixed remainder.
  local -a fields=()
  for (( i=0; i<n; i++ )); do
    fields+=("${GATE_STATES[$i]}" "${GATE_SECONDS[$i]}"
             "${GATE_ITEM_CORPUS[$i]}" "${GATE_ITEM_IDX[$i]}"
             "${GATE_ITEM_TOTAL[$i]}" "${GATE_EX_UNTIL[$i]}"
             "${GATE_EX_WHY[$i]}" "${GATE_LABELS[$i]}")
  done
  for (( i=0; i<nc; i++ )); do
    fields+=("${GATE_CORPUS_ITEMS[$i]}" "${GATE_CORPUS_GATES[$i]}"
             "${GATE_CORPUS_STATE[$i]}" "${GATE_CORPUS_NAMES[$i]}")
  done
  # vibe-ic#1144 (shard id, via ENV) + vibe-ic#584 (`nw`, `today`, as ARGS).
  # Two independent extensions of one protocol; both are required, because the
  # record below carries `shard` AND `wiring_errors`/`today`.
  GATE_DISPATCH_SHARD_ID="$([ "$GATE_DISPATCH_SHARD_I" -ge 0 ] \
      && echo "$GATE_DISPATCH_SHARD_I/$GATE_DISPATCH_SHARD_N")" \
  python3 - "$path" "$total" "$GATE_DISPATCH_LIST_ONLY" "$n" "$nc" "$nw" \
      "$GATE_DISPATCH_TODAY" \
      ${fields[@]+"${fields[@]}"} \
      ${GATE_WIRING_ERRORS[@]+"${GATE_WIRING_ERRORS[@]}"} \
      ${GATE_UNDISCLOSED_LOOPS[@]+"${GATE_UNDISCLOSED_LOOPS[@]}"} <<'PY'
import json, os, sys
out, total, list_only = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "1"
SHARD = os.environ.get("GATE_DISPATCH_SHARD_ID") or None
ng, nc, nw = int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
today = sys.argv[7]
rest = sys.argv[8:]
# 8 per gate, not 6: vibe-ic#584 appended exempt_until/exempt_reason, and the
# loop below reads gf[i+5..7] positionally.
gf, rest = rest[:ng * 8], rest[ng * 8:]
cf, rest = rest[:nc * 4], rest[nc * 4:]
wiring, undisclosed = rest[:nw], rest[nw:]
gates = []
for i in range(0, len(gf), 8):
    # The three loop keys are written ONLY for a gate a loop produced, so a
    # gate wired outside one records byte-for-byte what it recorded before
    # vibe-ic#957 — the record of the other ~70 must not move either.
    g = {"label": gf[i + 7], "state": gf[i], "seconds": int(gf[i + 1])}
    if gf[i + 2]:
        g["corpus"] = gf[i + 2]
        g["corpus_item"] = int(gf[i + 3])
        # The DENOMINATOR this gate's verdict covers, stated per gate as well
        # as per corpus: a consumer that reads one gate must not have to
        # reconstruct how many there were of it.
        g["corpus_items"] = int(gf[i + 4])
    # vibe-ic#584. Always present, so a consumer never has to guess whether an
    # absent key means "unexempted" or "written by an older script".
    g["exempt_until"] = gf[i + 5] or None
    g["exempt_reason"] = gf[i + 6] or None
    # ISO-8601 lexicographic order is chronological order; see the note on
    # `uncheckable_until`. An exemption expires whether or not it FIRED — it is
    # a promise to revisit, and a promise nobody is reminded of is not one.
    g["exemption_expired"] = bool(g["exempt_until"]) and g["exempt_until"] < today
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
    # RAN IS NOT DECIDED, and the gap between the two is the whole subject of
    # vibe-ic#1025: a NOT_CHECKED gate ran and concluded nothing about its
    # subject, and a WROTE_CORPUS one never had its rc classified at all.
    # Derivable from `passed` + `failed`, and recorded anyway so a consumer
    # cannot arrive at a different number than the sentence the script printed.
    "decided": n("PASS") + n("FAIL"),
    "passed": n("PASS"),
    "failed": n("FAIL"),
    "not_checked": n("NOT_CHECKED"),   # never folded into `passed`
    # vibe-ic#584 — the two keys that make NOT_CHECKED load-bearing. Both are
    # LISTS, not counts: a consumer that has to refuse a landing must be able to
    # NAME the gate, because a bare number cannot answer "was it the one I
    # cared about".
    "not_checked_unexempted": [g["label"] for g in gates
                               if g["state"] == "NOT_CHECKED"
                               and not g["exempt_until"]],
    "exemptions_expired": [g["label"] for g in gates if g["exemption_expired"]],
    # Defects in how the script DECLARES its gates. Non-empty means no count in
    # this record means what it says.
    "wiring_errors": wiring,
    "today": today,
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
attestation_path = os.environ.get("GATE_DISPATCH_ATTESTATION_FILE", "")
process_attestations = []
if attestation_path and os.path.isfile(attestation_path):
    with open(attestation_path, encoding="utf-8") as af:
        for lineno, line in enumerate(af, start=1):
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("complete") is not True:
                raise SystemExit(
                    f"incomplete process attestation at line {lineno}")
            process_attestations.append(rec)
doc["process_attestations"] = process_attestations
with open(out, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY
}

gate_dispatch_finish() {
  # #P4 — FIRST, before anything counts anything. Every queued gate is waited
  # for and replayed in declaration order, so from this line down the record is
  # exactly the record a sequential run would have built, and every sentence
  # below reads the same arrays it always did.
  _gate_pool_drain
  [ -z "$GATE_POOL_DIR" ] || rm -rf -- "$GATE_POOL_DIR"
  local declared=${#GATE_LABELS[@]} notchecked=0 passed=0 wrote=0 i
  # vibe-ic#1025 — COUNTED, where they were not before. Every closing sentence
  # below could state `declared` and `notchecked`; none of them could state how
  # many gates reached a VERDICT, or how many of those were red, because
  # nothing here added either up.
  local failed=0 decided=0 elsewhere=0 ran=0
  local total=$(( SECONDS - GATE_DISPATCH_T0 ))
  local refused="" writers="" expired="" nexpired=0

  if [ "$GATE_DISPATCH_ATTESTATION_FAILED" -ne 0 ]; then
    _gate_wiring_error "one or more gate processes completed without a "\
"machine attestation; the run cannot certify a tree from a partial record"
  fi

  # vibe-ic#584 — an exemption declared after the last gate attaches to
  # nothing. Caught rather than ignored: the author believed they had covered a
  # gate, and the gate they meant to cover has no tolerance at all.
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

  # BEFORE the `--list` exit and before every gate verdict: a script whose own
  # wiring is wrong has not certified anything, and this is the one class that
  # is a pure property of the DECLARATION — so the cheap one-second `--list`
  # run catches it too. rc 2, the same tier as "nothing was declared", for the
  # same reason.
  if [ "${#GATE_WIRING_ERRORS[@]}" -ne 0 ]; then
    echo "gate_dispatch: ${#GATE_WIRING_ERRORS[@]} WIRING ERROR(s) in the gate" \
         "declarations (listed above) — the set was not correctly declared," \
         "so this run certifies NOTHING" >&2
    exit 2
  fi

  # A KILLED RUN MUST NOT LOOK GREEN (#P4).
  #
  # A lost worker's gate is already recorded NOT_CHECKED rather than PASS, which
  # is the first half. The second half is the EXIT CODE, and without this branch
  # it would be ZERO: an unexempted NOT_CHECKED does not set `GATE_DISPATCH_FAIL`,
  # so a run whose workers were killed would print "N NOT CHECKED — this is NOT a
  # pass" and exit 0, and every `-ne 0` consumer believes the exit code. That is
  # vibe-ic#1025 exactly, arriving through a new door.
  #
  # rc 2 AND NOT rc 1, by this repo's convention: 1 = a gate found a defect,
  # 2 = nothing could be determined. A killed worker found nothing; it never got
  # to look. Placed with the wiring errors because it is the same tier of claim —
  # this run did not certify the tree it was pointed at.
  if [ "$GATE_DISPATCH_WORKERS_LOST" -ne 0 ]; then
    echo "gate_dispatch: $GATE_DISPATCH_WORKERS_LOST gate worker(s) never" \
         "reported a verdict, so this run certifies NOTHING. NOT CHECKED:" \
         "$GATE_POOL_LOST_LABELS" >&2
    exit 2
  fi

  if [ "$GATE_DISPATCH_LIST_ONLY" -eq 1 ]; then
    # TO STDERR IN LIST MODE, with the count line that is already there:
    # `--list`'s STDOUT is the gate labels and a caller may read it as such, so
    # a sentence about the run belongs on the same stream as the existing one.
    # A loop that expanded over nothing has no label to appear among them,
    # which is exactly why this must still print.
    _gate_dispatch_corpora_rollup "$declared" >&2
    _gate_dispatch_undisclosed_loops
    # #584 — expiry is deliberately NOT enforced here. `--list` answers "what
    # does this script declare", a question whose answer must not change with
    # the wall clock: two other programs parse this script and reconcile their
    # gate list against this enumeration, and a calendar-dependent rc would make
    # those comparisons flap on a date boundary. The dated promise is collected
    # by the run that could actually have used it. It is still RECORDED here.
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
      FAIL) failed=$(( failed + 1 )) ;;
      # vibe-ic#1144 — declared here, owned by another host. Not something this
      # run declined to decide; something it was never asked to.
      OTHER_SHARD) elsewhere=$(( elsewhere + 1 )) ;;
      NOT_CHECKED)
        notchecked=$(( notchecked + 1 ))
        refused="${refused:+$refused, }${GATE_LABELS[$i]}"
        # TWO ARMS, because a NOT_CHECKED gate can now reach this line with no
        # exemption at all. The synthetic empty-corpus gate buys none — and
        # correctly so, since inventing one would grant every future empty
        # corpus a silent tolerance nobody declared at a wiring site.
        #
        # THIS BECAME REACHABLE ONE COMMIT AGO. Before the parent commit the
        # sweep DIED at the expiry sweep on an unbound `GATE_EX_UNTIL[$i]`, so
        # this line never printed for that gate. Repairing the crash published
        # the sentence, and unguarded it read:
        #
        #     ... is EMPTY — nothing was checked over it (exempt until )
        #
        # a tolerance asserted with a BLANK DATE, in the very line #539 added
        # so a reader could tell a bought refusal from an unbought one. An
        # absent date has to READ as absent.
        if [ -n "${GATE_EX_UNTIL[$i]}" ]; then
          refused="$refused (exempt until ${GATE_EX_UNTIL[$i]})"
        else
          refused="$refused (NO EXEMPTION DECLARED)"
        fi ;;
      WROTE_CORPUS)
        wrote=$(( wrote + 1 ))
        writers="${writers:+$writers, }${GATE_LABELS[$i]}" ;;
    esac
  done
  # A gate DECIDED when it reached a verdict about its subject: PASS or FAIL.
  # NOT_CHECKED did not — it declined to look. WROTE_CORPUS did not either: its
  # rc is never classified, because what it did was change the tree every gate
  # after it read. OTHER_SHARD is not this host's question at all.
  decided=$(( passed + failed ))
  ran=$(( declared - elsewhere ))

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
    # vibe-ic#1025 — this is the ONE closing sentence that could not state its
    # own denominator. It named `declared` and `notchecked` and never said how
    # many gates actually reached a verdict or how many of those were red, so a
    # reader could not tell one failure among 63 from forty. The other closing
    # sentences below already state `passed` against `declared`, from which
    # `decided` follows, and are left alone rather than padded with a number
    # they already imply.
    echo "repo_hygiene_gates: at least one gate FAILED" \
         "($decided of $declared decided — $passed passed, $failed failed;" \
         "$notchecked NOT CHECKED, $wrote WROTE CORPUS, ${total}s)" >&2
    [ "$nexpired" -eq 0 ] || echo "repo_hygiene_gates: and $nexpired" \
      "uncheckable exemption(s) are PAST their review date: $expired" >&2
    exit 1
  fi

  # vibe-ic#584 — a dated promise nobody is reminded of is not a promise. This
  # fires whether or not the exemption FIRED: one covering a gate that passes
  # today is dormant, not gone, and if it only expired when it fired then the
  # day the prerequisite disappears is the day a years-stale exemption silently
  # starts covering a live gate. Remedy is one line — re-review the named gate
  # and either restate the date with a reason that is still true, or delete the
  # exemption and the `run_tolerating_uncheckable` with it.
  if [ "$nexpired" -ne 0 ]; then
    echo "repo_hygiene_gates: $passed of $declared gate(s) passed, but" \
         "$nexpired uncheckable exemption(s) are PAST their review date and" \
         "this is NOT a pass: $expired (${total}s)" >&2
    exit 1
  fi

  # A SWEEP THAT DECIDED NOTHING IS NOT A PASS (vibe-ic#1025).
  #
  # This is the rule the file already applies ONE LEVEL DOWN, arriving through
  # a different door. `declared -eq 0` is refused with rc 2 forty lines up: a
  # script that wired nothing cannot certify anything. A script that wired 63
  # gates and got a verdict out of none of them is in the SAME state — nothing
  # was concluded — and was exiting 0. MEASURED on 75776dbbb, six gates each
  # returning rc 2 under a live exemption:
  #
  #     repo_hygiene_gates: 0 of 6 gate(s) passed; 6 NOT CHECKED —
  #     this is NOT a pass over: gate1 (exempt until 2999-01-01), … (1s)
  #     $ echo $?
  #     0
  #
  # The sentence says "this is NOT a pass" and the exit code says pass, and
  # every `-ne 0` consumer believes the exit code: `gatekeeper-land.sh` wraps
  # this in `if out="$(…)"`, and `gatekeeper_review._hygiene_verdict` returned
  # rc 0 — MERGE_OK — with the NOT-CHECKED count riding along in prose. #539
  # fixed the sentence and #584 made each individual refusal buy a dated
  # exemption; neither asked what happens when the exempted set is ALL of them.
  #
  # rc 2 AND NOT rc 1, deliberately: this repo's convention is 1 = found a
  # defect, 2 = could not determine. A vacuous sweep found no defect; it
  # produced no result. Reporting it as 1 would announce a finding that does
  # not exist — the mirror of the lie being removed.
  #
  # AND NOT "any NOT_CHECKED is non-zero": the rc-0-with-refusals branch below
  # has a measured reason (a maintainer whose tree is dirty BY CONSTRUCTION
  # would make this script permanently red, and a permanently red gate is a
  # gate that gets skipped — the failure mode `run_tolerating_uncheckable`
  # exists to avoid). The line drawn here is ZERO DECIDED, which is the
  # difference between a result with caveats and no result at all.
  #
  # GUARDED ON `ran`, so a shard that owns no gate is not caught by it: under
  # `--shard i/N` with more shards than gates, `plan()` can hand a host an
  # empty bucket, and that host was never asked the question. Proving every
  # gate ran exactly once ACROSS shards is `hygiene_shard_aggregate`'s job and
  # it has the records to do it; refusing here would only make a legitimately
  # empty shard permanently red, which is the failure mode above again.
  if [ "$ran" -ne 0 ] && [ "$decided" -eq 0 ]; then
    echo "repo_hygiene_gates: DECIDED NOTHING — 0 of $ran gate(s) that ran" \
         "reached a verdict ($notchecked NOT CHECKED, $declared declared)." \
         "A sweep that concluded nothing is not a pass, for the same reason a" \
         "sweep that wired no gate is not: NOT CHECKED over: $refused" \
         "(${total}s)" >&2
    exit 2
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
  # open one. Every gate reaching this branch bought the tolerance with a dated,
  # reasoned `uncheckable_until`; an unexempted one is a wiring error several
  # branches up and never gets here, and an expired one failed one branch up.
  # Exiting non-zero for an exemption that is doing its job would make this
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
  # it rests on the exemption being explicit, dated, and named on this line.
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
