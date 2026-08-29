#!/usr/bin/env bash
# test_gate_concurrency.sh — the paired guard for running the gates AT THE SAME
# TIME (#P4). Sibling of `test_gate_scope.sh`, which guards #P3.
#
# WHY A SEPARATE HARNESS AND NOT MORE CASES IN THE SCOPE ONE. Both features make
# the sweep do LESS work, and both are therefore one assertion away from being a
# way to turn the suite off — but they fail differently. Scope removes a gate
# from the run and says so. Concurrency keeps every gate and can quietly change
# WHAT IT CONCLUDED: a verdict landing under the wrong label, a return code eaten
# by a pipe, a worker killed and its gate read as green. So the cases here are
# about the RECORD and the EXIT CODE, not about what ran.
#
# THE ORACLE, and it is the whole feature: the set of (label -> state) pairs a
# concurrent run produces must be IDENTICAL to the one a sequential run produces
# on the same tree. Faster and different is a failure. Every case below is an
# instance of that, or of one of the three ways it could be false while still
# looking right in review:
#
#   1. output attributed to the wrong gate (a finding under the wrong label
#      sends the next reader to the wrong file)
#   2. an exit code stolen by a pipe (this repo has shipped a false GATE_RC=0
#      that way)
#   3. a worker that died reading as a pass (the quietest possible green)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n     %s\n' "$1" "${2:-}"; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

# `drive <jobs> <script> [args...]` — run one toy gate script end to end, i.e.
# THROUGH `gate_dispatch_finish`, which is the only thing that drains the pool.
# Writes stdout, stderr and the summary record to files named for the arm, so a
# case can compare arms byte for byte rather than pattern-match prose.
#
# THE CORPUS ROOT IS PINNED TO THE SCRATCH TREE, and that is not tidiness. The
# dispatcher runs its gates ONE AT A TIME whenever the corpus-write guard is
# ACTIVE, because a per-gate before/after snapshot of a shared tree cannot be
# attributed to a gate that did not run alone inside it. Left to fall back on
# `$ROOT`/`BASH_SOURCE`, every case below would inherit THIS CHECKOUT's answer to
# "is there a `benchmark-data/` here" — so the whole harness would silently stop
# exercising the pool on a machine that has cloned the corpus back in-tree, and
# case 8 ("JOBS=8 did queue gates") would fail for a reason that is not about
# concurrency at all. `$T` holds no corpus, so these cases keep asking their own
# question; case 20 points it at a real one on purpose.
drive() {                       # -> rc; leaves $T/<tag>.{out,err,json}
  local tag="$1" jobs="$2" script="$3"; shift 3
  GATEKEEPER_HYGIENE_JOBS="$jobs" \
  GATE_DISPATCH_CORPUS_ROOT="${DRIVE_CORPUS_ROOT:-$T}" bash "$script" \
      --summary-json "$T/$tag.json" "$@" \
      > "$T/$tag.out" 2> "$T/$tag.err"
}

#: The label -> state pairs, in record order. The oracle reads THIS and not the
#: log: the logs of two arms may legitimately differ in per-gate seconds, and a
#: comparison that could be defeated by a timing digit is not a comparison.
pairs() { python3 - "$1" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for g in d["gates"]:
    print(f'{g["state"]}\t{g["label"]}')
PY
}

#: A log with the WALL CLOCK taken out of it. The dispatcher prints two kinds
#: of elapsed time — `[Ns]` beside a gate diagnostic and `(Ns)` at the end of
#: the roll-up — and a concurrent run is SUPPOSED to differ in exactly those.
#: Nothing else is normalised: an assertion that erased more than the clock
#: would stop being able to see a gate's output MOVE, which is what it is for.
# THE THIRD RULE IS NOT DECORATION. Every closing sentence in `_gate_dispatch.sh`
# spells its elapsed clock `(${total}s)` and the second rule catches all of them
# -- except ONE. The FAILED summary at `_gate_dispatch.sh:1788` grew a `decided`
# breakdown, so its clock now ends the line as `, ${total}s)` with a comma before
# it and no `(` of its own, and `\(([0-9]+)s\)$` does not match that. The two
# comparisons this helper feeds (`corpseq/corppar` and `twoseq/twopar`) both read
# a FAILING run's stderr, so both were comparing a wall clock while announcing
# "clock aside" -- green whenever the arms happened to round to the same second
# and red on host load, blaming the ordering property they exist to check.
# MEASURED: the aggregate arm of the repo-tools lane failed exactly here with a
# one-line diff of `, 1s)` against `, 2s)` and 35 other cases green.
norm() { sed -E 's/\[[0-9]+s\]/[<T>s]/g; s/\(([0-9]+)s\)$/(<T>s)/; s/, ([0-9]+)s\)$/, <T>s)/' "$1"; }

# ── the toy gate set ─────────────────────────────────────────────────────────
# Every state a gate can reach, plus a deliberate ordering trap: `slow-first`
# sleeps and is declared BEFORE `fast-second`, so any implementation that emits
# on completion instead of on declaration order prints them the wrong way round.
cat > "$T/mixed.sh" <<'EOF'
set -euo pipefail
. "${HERE:?}/_gate_dispatch.sh"
gate_dispatch_init "$@"
run "slow-first"  "$PWD" bash -c 'sleep 2; echo "SLOW body"'
run "fast-second" "$PWD" bash -c 'echo "FAST body"'
run "a-failure"   "$PWD" bash -c 'echo "the finding"; exit 1'
uncheckable_until 2099-01-01 "toy: this gate reports rc 2 on purpose"
run_tolerating_uncheckable "a-refusal" "$PWD" bash -c 'echo "cannot look"; exit 2'
run "another-pass" "$PWD" bash -c 'sleep 1; echo "fine"'
echo "POOL_DIR=${GATE_POOL_DIR:-none} QUEUED=${#GATE_POOL_IDX[@]}" >&2
gate_dispatch_finish
EOF

export HERE
drive seq 1 "$T/mixed.sh"; RC_SEQ=$?
drive par 8 "$T/mixed.sh"; RC_PAR=$?
# A THIRD ARM AT JOBS=2, AND IT IS NOT REDUNDANT. With 5 gates and 8 slots the
# pool never fills, so submission never blocks and every gate is emitted by the
# single ordered drain at the end — which orders correctly no matter what the
# incremental replay does. Measured: a mutant that emits in COMPLETION order
# from the incremental path passes all 17 cases against the 8-slot arm alone.
# The saturated arm is the only one that executes that path.
drive sat 2 "$T/mixed.sh"; RC_SAT=$?

# ── 1. THE ORACLE: same tree, same (label -> state) set ──────────────────────
if diff <(pairs "$T/seq.json") <(pairs "$T/par.json") > "$T/pairs.diff" 2>&1; then
  ok "concurrent run produces the SAME (label -> state) set as sequential"
else
  bad "the concurrent run DECIDED DIFFERENTLY — faster and different is a failure" \
      "$(cat "$T/pairs.diff")"
fi

# ── 2. …and the same EXIT CODE. The pairs can match while the rc does not, and
#       the rc is what every `-ne 0` consumer believes. ───────────────────────
if [ "$RC_SEQ" -eq "$RC_PAR" ]; then
  ok "same exit code in both arms (rc $RC_SEQ)"
else
  bad "exit code differs: sequential $RC_SEQ, concurrent $RC_PAR" \
      "$(tail -3 "$T/par.err")"
fi

# ── 3. OUTPUT IS ATTRIBUTABLE: byte-for-byte the same stdout ────────────────
#    Not "contains the right lines". Interleaving is precisely a rearrangement
#    of the right lines, so a containment assertion cannot see it.
if diff <(norm "$T/seq.out") <(norm "$T/par.out") > "$T/out.diff" 2>&1; then
  ok "stdout is identical to the sequential arm, clock aside"
else
  bad "stdout differs — a gate's output moved, so a finding may now sit under
     another gate's label" "$(head -20 "$T/out.diff")"
fi

# ── 4. DECLARATION ORDER, not completion order ──────────────────────────────
#    `slow-first` sleeps 2s and is declared first; `fast-second` finishes almost
#    immediately. This is the case that fails on every implementation that emits
#    a gate when it finishes.
for _arm in par sat; do
  _slow=$(grep -n '^── slow-first$'  "$T/$_arm.out" | cut -d: -f1)
  _fast=$(grep -n '^── fast-second$' "$T/$_arm.out" | cut -d: -f1)
  _fastbody=$(grep -n '^FAST body$'  "$T/$_arm.out" | cut -d: -f1)
  if [ -n "$_slow" ] && [ -n "$_fast" ] && [ "$_slow" -lt "$_fast" ] \
     && [ -n "$_fastbody" ] && [ "$_fastbody" -gt "$_slow" ]; then
    ok "[$_arm] a fast gate declared second is emitted after a slow gate declared first"
  else
    bad "[$_arm] completion order reached the log (slow@${_slow:-?} fast@${_fast:-?} body@${_fastbody:-?})" \
        "$(head -12 "$T/$_arm.out")"
  fi
done

# ── 4b. THE SATURATED ARM IS THE ONE THAT EXERCISES INCREMENTAL REPLAY, so its
#       stdout must match the sequential arm byte for byte as well. This is the
#       assertion the 8-slot arm structurally cannot make. ───────────────────
if diff <(norm "$T/seq.out") <(norm "$T/sat.out") > "$T/sat.diff" 2>&1; then
  ok "[sat, pool full] stdout is identical to the sequential arm, clock aside"
else
  bad "[sat, pool full] stdout differs — the incremental replay reordered output" \
      "$(head -20 "$T/sat.diff")"
fi
if diff <(pairs "$T/seq.json") <(pairs "$T/sat.json") > "$T/satp.diff" 2>&1 \
   && [ "$RC_SAT" -eq "$RC_SEQ" ]; then
  ok "[sat, pool full] same (label -> state) set and same exit code"
else
  bad "[sat, pool full] the saturated arm decided differently (rc $RC_SAT vs $RC_SEQ)" \
      "$(cat "$T/satp.diff")"
fi

# ── 5. A GATE THAT FAILS UNDER CONCURRENCY IS STILL FAILED, UNDER ITS OWN
#       LABEL. Both halves matter: a FAIL recorded against the wrong label is a
#       reader sent to the wrong file, which is worse than no report. ─────────
if grep -qF '^^ FAILED: a-failure' "$T/par.err" \
   && pairs "$T/par.json" | grep -qxF "$(printf 'FAIL\ta-failure')"; then
  ok "a gate that failed under concurrency is FAILED, named, in the log AND the record"
else
  bad "the failure did not reach the record under its own label" \
      "$(grep -a 'FAILED' "$T/par.err"; pairs "$T/par.json")"
fi

# ── 6. …AND NOTHING ELSE BECAME FAILED. The half that makes case 5 mean
#       something: an implementation that marks every gate FAIL passes case 5. ─
_nfail=$(pairs "$T/par.json" | grep -c '^FAIL	' || true)
if [ "$_nfail" -eq 1 ]; then
  ok "exactly one gate is FAILED — the failure did not smear onto its peers"
else
  bad "$_nfail gates are FAILED; exactly one gate fails in this toy set" \
      "$(pairs "$T/par.json")"
fi

# ── 7. rc 2 UNDER AN EXEMPTION IS STILL NOT_CHECKED, never folded into PASS ──
if pairs "$T/par.json" | grep -qxF "$(printf 'NOT_CHECKED\ta-refusal')"; then
  ok "a tolerated rc 2 is NOT_CHECKED under concurrency too"
else
  bad "the refusal was reclassified by the concurrent path" "$(pairs "$T/par.json")"
fi

# ── 8. WITH JOBS=1 NOTHING IS QUEUED AT ALL ─────────────────────────────────
#    The behaviour claim "jobs=1 is exactly today's" rests on the sequential arm
#    taking the ORIGINAL inline path, not on a pool of size one that merely
#    happens to serialise. Proven from the dispatcher's own state: no scratch
#    directory was ever created and no gate was ever queued.
if grep -qF 'POOL_DIR=none QUEUED=0' "$T/seq.err"; then
  ok "JOBS=1 queues nothing and creates no pool — the pre-#P4 path, unchanged"
else
  bad "JOBS=1 went through the pool" "$(grep -a POOL_DIR= "$T/seq.err")"
fi
if grep -qF 'QUEUED=0' "$T/par.err"; then
  bad "JOBS=8 queued nothing — the concurrent arm did not actually run concurrently,
     so every case above compared sequential against sequential" \
      "$(grep -a POOL_DIR= "$T/par.err")"
else
  ok "JOBS=8 did queue gates, so the arms above really are different execution paths"
fi

# ── 9. AND IT IS ACTUALLY FASTER. Without this the whole feature could be a
#       pool of size one and every case above would still pass.
#
#       ITS OWN TOY, with a margin that a busy host cannot close. The mixed set
#       above is 3 s sequential and ~2 s concurrent, and `SECONDS` has one-second
#       granularity: measured, that case reported "no speed-up: sequential 3s,
#       concurrent 3s" once in five runs on a loaded machine. A flaky assertion
#       is not a weaker assertion, it is one that gets ignored the day it is
#       right — so the gap here is 8x, not 1.5x.
cat > "$T/speed.sh" <<'EOF'
set -euo pipefail
. "${HERE:?}/_gate_dispatch.sh"
gate_dispatch_init "$@"
for i in $(seq 1 8); do run "s$i" "$PWD" sleep 1; done
gate_dispatch_finish
EOF
drive speedseq 1 "$T/speed.sh"
drive speedpar 8 "$T/speed.sh"
_secs() { python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['seconds'])" "$1"; }
_sseq=$(_secs "$T/speedseq.json")
_spar=$(_secs "$T/speedpar.json")
if [ "$_sseq" -ge 8 ] && [ $(( _spar * 2 )) -lt "$_sseq" ]; then
  ok "8 one-second gates: ${_sseq}s sequential -> ${_spar}s at JOBS=8"
else
  bad "no speed-up: sequential ${_sseq}s, concurrent ${_spar}s" ""
fi

# ── 10/11. A KILLED WORKER YIELDS NOT CHECKED, AND THE RUN REFUSES ──────────
#    The gate kills its own worker — the shell holding the buffers and the
#    result file — rather than the gate process, because those are two different
#    failures. A killed GATE is an rc, and the dispatcher already classifies it.
#    A killed WORKER produces no rc at all, and the only wrong answer is to let
#    the absence read as a pass.
cat > "$T/killed.sh" <<'EOF'
set -euo pipefail
. "${HERE:?}/_gate_dispatch.sh"
gate_dispatch_init "$@"
run "healthy-before" "$PWD" bash -c 'echo ok'
run "victim" "$PWD" bash -c '
  echo "victim starting"
  # $PPID is the ( cd … ) subshell; its parent is the WORKER.
  kill -9 "$(awk "{print \$4}" /proc/$PPID/stat)"
  sleep 30'
run "healthy-after" "$PWD" bash -c 'sleep 1; echo ok'
gate_dispatch_finish
EOF
drive killed 4 "$T/killed.sh"; RC_KILLED=$?

_vstate=$(pairs "$T/killed.json" | awk -F'\t' '$2=="victim"{print $1}')
if [ "$_vstate" = "NOT_CHECKED" ]; then
  ok "a worker killed mid-gate yields NOT CHECKED"
elif [ "$_vstate" = "PASS" ]; then
  bad "A KILLED WORKER WAS RECORDED AS PASS — the quietest possible green" \
      "$(pairs "$T/killed.json")"
else
  bad "a killed worker produced state '${_vstate:-<absent>}'" \
      "$(pairs "$T/killed.json")"
fi

#    NOT_CHECKED alone is not enough: an unexempted NOT_CHECKED does not set the
#    failure flag, so without an explicit branch the run would print "this is NOT
#    a pass" and exit 0 — the vibe-ic#1025 shape, arriving through a new door.
if [ "$RC_KILLED" -ne 0 ]; then
  ok "a run with a lost worker exits non-zero (rc $RC_KILLED), so it cannot read as green"
else
  bad "a run whose worker was KILLED exited 0; every '-ne 0' consumer believes
     the exit code, not the sentence" "$(tail -4 "$T/killed.err")"
fi

# ── 12. The gates that were NOT lost still reported ─────────────────────────
#    A lost worker must cost exactly its own gate. An implementation that
#    abandons the replay at the first missing result file would silently drop
#    every gate declared after it, and the roll-up would still look tidy.
if pairs "$T/killed.json" | grep -qxF "$(printf 'PASS\thealthy-after')"; then
  ok "a gate declared AFTER the lost one still reached the record"
else
  bad "the lost worker took its successors' verdicts with it" \
      "$(pairs "$T/killed.json")"
fi

# ── 13. A SERIAL GATE RUNS ALONE ────────────────────────────────────────────
#    Measured, not asserted from the code: every gate touches a counter file on
#    entry and on exit, and the serial gate reads it. If anything else is in
#    flight the counter is non-empty, and `gate_serial`'s only promise is that it
#    is not. This is the promise `gates are host-independent` depends on — it
#    reads the machine record every other gate writes.
cat > "$T/serial.sh" <<'EOF'
set -euo pipefail
. "${HERE:?}/_gate_dispatch.sh"
gate_dispatch_init "$@"
# ONE FILE PER LIVE GATE, not lines in one file: three processes appending to
# and rewriting a single file race with each other, and the leftovers of THAT
# race would read as an overlap that never happened — a flaky test is a test
# nobody believes the day it is right.
_busy() { : > "$LIVE/$$"; sleep "$1"; rm -f "$LIVE/$$"; }
export -f _busy
run "peer-a" "$PWD" bash -c '_busy 2'
run "peer-b" "$PWD" bash -c '_busy 2'
run "peer-c" "$PWD" bash -c '_busy 2'
gate_serial "toy: asserts nothing else is in flight"
run "alone" "$PWD" bash -c 'n=$(ls -1 "$LIVE" | grep -c . || true); echo "IN_FLIGHT=$n"; [ "$n" -eq 0 ]'
gate_dispatch_finish
EOF
mkdir -p "$T/live"
LIVE="$T/live" drive serial 8 "$T/serial.sh"
if grep -qF 'IN_FLIGHT=0' "$T/serial.out" \
   && pairs "$T/serial.json" | grep -qxF "$(printf 'PASS\talone')"; then
  ok "a gate_serial gate runs with no peer in flight"
else
  bad "a serial gate overlapped another — the record it reads may be half written" \
      "$(grep -a IN_FLIGHT "$T/serial.out"; pairs "$T/serial.json")"
fi

# ── 14. …AND THE PEERS REALLY DID OVERLAP. Case 13 passes trivially against an
#       implementation that never parallelises anything. ─────────────────────
_sser=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['seconds'])" "$T/serial.json")
if [ "$_sser" -lt 6 ]; then
  ok "the three 2s peers overlapped (${_sser}s total), so case 13 was a real test"
else
  bad "the peers ran one after another (${_sser}s) — nothing was concurrent" ""
fi

# ── 15. THE EXIT CODE IS NOT STOLEN BY THE PIPE ─────────────────────────────
#    The worker's own buffering must not sit between the gate and its rc. The
#    attestation path already pipes the gate through `tee`; a gate that writes a
#    lot and then fails is where `cmd | tail`-shaped bugs surface, and this repo
#    has shipped a false GATE_RC=0 exactly that way.
cat > "$T/loud.sh" <<'EOF'
set -euo pipefail
. "${HERE:?}/_gate_dispatch.sh"
gate_dispatch_init "$@"
run "loud-then-fails" "$PWD" bash -c 'seq 1 20000; exit 1'
run "loud-then-passes" "$PWD" bash -c 'seq 1 20000'
gate_dispatch_finish
EOF
drive loud 4 "$T/loud.sh"; RC_LOUD=$?
if pairs "$T/loud.json" | grep -qxF "$(printf 'FAIL\tloud-then-fails')" \
   && pairs "$T/loud.json" | grep -qxF "$(printf 'PASS\tloud-then-passes')" \
   && [ "$RC_LOUD" -ne 0 ]; then
  ok "a noisy gate's rc survives the buffering (FAIL stays FAIL, rc $RC_LOUD)"
else
  bad "the buffer ate the return code" "$(pairs "$T/loud.json"); rc=$RC_LOUD"
fi

# ── 16. A MALFORMED KNOB IS REFUSED, NOT ROUNDED ────────────────────────────
#    Falling back to 1 would make a run a caller asked to parallelise silently
#    take twenty minutes; falling back to `nproc` would be the measured-slower
#    default this whole change exists to avoid.
drive bogus "eight" "$T/loud.sh"; RC_BOGUS=$?
if [ "$RC_BOGUS" -eq 2 ] && grep -qF 'not a positive integer' "$T/bogus.err"; then
  ok "GATEKEEPER_HYGIENE_JOBS=eight is refused (rc 2), not guessed at"
else
  bad "a malformed jobs knob was accepted (rc $RC_BOGUS)" "$(tail -3 "$T/bogus.err")"
fi

# ── 17. THE KNOB REALLY BOUNDS. A knob that is read and not obeyed is worse
#       than no knob: the 8 -> 28 measurement that says more is slower here can
#       only be acted on if the number means something. Measured by the gates
#       themselves, counting their live peers. ────────────────────────────────
cat > "$T/bound.sh" <<'EOF'
set -euo pipefail
. "${HERE:?}/_gate_dispatch.sh"
gate_dispatch_init "$@"
_b() { : > "$LIVE/$$"; ls -1 "$LIVE" | grep -c . >> "$SEEN"; sleep 1; rm -f "$LIVE/$$"; }
export -f _b
for i in $(seq 1 12); do run "g$i" "$PWD" bash -c '_b'; done
gate_dispatch_finish
EOF
_boundfail=""
for _j in 2 3 8; do
  rm -rf "$T/live"; mkdir -p "$T/live"; : > "$T/seen"
  LIVE="$T/live" SEEN="$T/seen" drive "bound$_j" "$_j" "$T/bound.sh"
  _max=$(sort -n "$T/seen" | tail -1)
  [ "${_max:-0}" -le "$_j" ] || _boundfail="$_boundfail JOBS=$_j saw $_max;"
  [ "${_max:-0}" -eq "$_j" ] || _boundfail="$_boundfail JOBS=$_j only reached $_max;"
done
if [ -z "$_boundfail" ]; then
  ok "GATEKEEPER_HYGIENE_JOBS bounds concurrency exactly (measured at 2, 3 and 8)"
else
  bad "the knob is read but not obeyed:$_boundfail" ""
fi

# ── 18. AN OUT_OF_SCOPE SKIP IS BUFFERED INTO DECLARATION ORDER TOO ─────────
#    A #P3 skip is decided INSTANTLY, at declaration time, while the gates
#    declared before it are still running. Printed straight out it would appear
#    above output it comes after — the same unattributable log this whole
#    feature must not produce, arriving through the one gate that runs no
#    process at all.
cat > "$T/scoped.sh" <<'EOF'
set -euo pipefail
. "${HERE:?}/_gate_dispatch.sh"
gate_dispatch_init "$@"
run "slow-before-the-skip" "$PWD" bash -c 'sleep 2; echo "SLOW body"'
gate_scope tools/
run "skipped-gate" "$PWD" bash -c 'echo "MUST NOT RUN"'
run "after-the-skip" "$PWD" bash -c 'echo "AFTER body"'
gate_dispatch_finish
EOF
printf 'docs/only.md\n' > "$T/docs_only.txt"
GATEKEEPER_CHANGED_PATHS="$T/docs_only.txt" drive skipseq 1 "$T/scoped.sh"
GATEKEEPER_CHANGED_PATHS="$T/docs_only.txt" drive skippar 4 "$T/scoped.sh"
if diff <(norm "$T/skipseq.out") <(norm "$T/skippar.out") > "$T/skip.diff" 2>&1 \
   && diff <(pairs "$T/skipseq.json") <(pairs "$T/skippar.json") >> "$T/skip.diff" 2>&1; then
  ok "an OUT_OF_SCOPE skip lands in declaration order, and in the record, under both arms"
else
  bad "the skip line jumped its place in the log, or the state moved" \
      "$(cat "$T/skip.diff"; echo '--- par:'; cat "$T/skippar.out")"
fi
if grep -qF 'MUST NOT RUN' "$T/skippar.out"; then
  bad "the skipped gate RAN under concurrency — narrowing must mean the same thing
     in both arms" "$(cat "$T/skippar.out")"
else
  ok "the skipped gate did not run under concurrency either"
fi

# ── 19. A DECLARATION-TIME CORPUS NOTE KEEPS ITS PLACE TOO ──────────────────
#    `gate_dispatch_over` speaks at the moment it expands — while the gates
#    declared before it are still running. MEASURED on the real gate set before
#    this was buffered: the EMPTY CORPUS paragraph appeared THREE gates early in
#    the JOBS=8 stderr, above diagnostics belonging to gates declared before it.
cat > "$T/corpus.sh" <<'EOF'
set -euo pipefail
. "${HERE:?}/_gate_dispatch.sh"
gate_dispatch_init "$@"
_body() { run "per-item ($1)" "$PWD" true; }
run "slow-before-the-corpus" "$PWD" bash -c 'sleep 2; echo "SLOW body"; exit 1'
gate_dispatch_over "an empty toy corpus" _body true
run "after-the-corpus" "$PWD" bash -c 'echo AFTER'
gate_dispatch_finish
EOF
drive corpseq 1 "$T/corpus.sh"
drive corppar 4 "$T/corpus.sh"
if diff <(norm "$T/corpseq.err") <(norm "$T/corppar.err") > "$T/corp.diff" 2>&1; then
  ok "an EMPTY CORPUS note keeps its declared place in stderr under concurrency"
else
  bad "a declaration-time corpus note jumped over a running gate's diagnostics" \
      "$(cat "$T/corp.diff")"
fi
if diff <(pairs "$T/corpseq.json") <(pairs "$T/corppar.json") > /dev/null 2>&1; then
  ok "the synthetic empty-corpus gate is recorded identically in both arms"
else
  bad "the empty-corpus row differs between arms" \
      "$(diff <(pairs "$T/corpseq.json") <(pairs "$T/corppar.json"))"
fi

# ── 20. A CORPUS WRITE IS ATTRIBUTED TO THE GATE THAT MADE IT, IN BOTH ARMS ──
#    THE CASE THAT WAS MISSING, and its absence is why #P4 landed green over a
#    broken guard. Every gate above is corpus-blind, so nothing here ever drove
#    the one part of `_gate_execute` whose verdict depends on WHAT ELSE IS
#    RUNNING: the before/after snapshot of `benchmark-data/`.
#
#    MEASURED at v1.10.55 with one writer and one reader declared —
#
#        JOBS=1   wrote_corpus 1   passed 1   writer WROTE_CORPUS, reader PASS
#        JOBS=8   wrote_corpus 2   passed 0   BOTH recorded WROTE_CORPUS
#
#    — i.e. the oracle at the top of this file, violated: the reader wrote
#    nothing and the concurrent arm said it did. `git status` is a fact about
#    the TREE and both brackets span the same instant, so it cannot tell the two
#    apart; the dispatcher now runs the watched gates one at a time and says so.
#
#    A FRESH CORPUS PER ARM, deliberately. The writer writes the SAME bytes both
#    times, so a second run over a tree that already carries `stray.json` moves
#    nothing `git status` can see and the writer would come back PASS — a case
#    that agreed with itself while measuring nothing.
fresh_corpus() {                # <dir>
  rm -rf "$1"; mkdir -p "$1/benchmark-data/ic/cell"
  printf 'x\n' > "$1/benchmark-data/ic/cell/kept.txt"
  git init -q "$1"
  git -C "$1" config user.email t@t; git -C "$1" config user.name t
  git -C "$1" add -A; git -C "$1" commit -qm base
  printf 'import pathlib\np = pathlib.Path(%s) / "benchmark-data/ic/cell/stray.json"\np.write_text("leftover\\n")\nprint("wrote")\n' \
    "\"$1\"" > "$1/w.py"
  printf 'print("read nothing")\n' > "$1/r.py"
}
cat > "$T/corpuswrite.sh" <<'EOF'
set -euo pipefail
. "${HERE:?}/_gate_dispatch.sh"
gate_dispatch_init "$@"
run "a corpus writer" "${CORPUS_REPO:?}" python3 "${CORPUS_REPO}/w.py"
run "a corpus reader" "${CORPUS_REPO:?}" python3 "${CORPUS_REPO}/r.py"
gate_dispatch_finish
EOF
export CORPUS_REPO="$T/corpusrepo"
fresh_corpus "$CORPUS_REPO"
DRIVE_CORPUS_ROOT="$CORPUS_REPO" drive cwseq 1 "$T/corpuswrite.sh"; RC_CWSEQ=$?
fresh_corpus "$CORPUS_REPO"
DRIVE_CORPUS_ROOT="$CORPUS_REPO" drive cwpar 8 "$T/corpuswrite.sh"; RC_CWPAR=$?

if diff <(pairs "$T/cwseq.json") <(pairs "$T/cwpar.json") > "$T/cw.diff" 2>&1; then
  ok "a corpus write is recorded against the SAME gate in both arms"
else
  bad "the concurrent arm attributed the corpus write differently — a gate that
     wrote nothing is being named as a writer" "$(cat "$T/cw.diff")"
fi
# ...AND THE PAIR IS THE RIGHT ONE. Two arms can agree by being wrong the same
# way (both marking every gate WROTE_CORPUS), which the diff above cannot see.
for arm in cwseq cwpar; do
  got="$(pairs "$T/$arm.json")"
  if [ "$got" = "$(printf 'WROTE_CORPUS\ta corpus writer\nPASS\ta corpus reader')" ]
  then
    ok "[$arm] the writer is named and the reader is still a PASS"
  else
    bad "[$arm] the corpus-write verdicts are wrong" "$got"
  fi
done
if [ "$RC_CWSEQ" -eq "$RC_CWPAR" ] && [ "$RC_CWSEQ" -ne 0 ]; then
  ok "a corpus write fails the run in both arms (rc $RC_CWSEQ)"
else
  bad "a corpus write did not fail both arms identically" \
      "sequential rc $RC_CWSEQ, concurrent rc $RC_CWPAR"
fi
if grep -q "run ONE AT A TIME" "$T/cwpar.err"; then
  ok "the run SAYS it dropped to one gate at a time, rather than merely doing it"
else
  bad "the exclusive window was taken silently — a run that took six times as
     long for a reason nobody printed is its own defect" "$(cat "$T/cwpar.err")"
fi

# ── 21. THE TWO ZERO-POPULATION STATES ARE TWO ROWS, IN BOTH ARMS ───────────
#    THE CASE THIS HARNESS WAS MISSING, and it was missing in the same shape as
#    the defect it now guards. Case 19 drives `gate_dispatch_over ... true` — a
#    producer that exits 0 having printed nothing, i.e. A CORPUS THAT WAS READ
#    AND HOLDS NONE. That is one of the dispatcher's two zero-population states
#    and until now it was the only one this file had ever seen. The other — a
#    producer that resolved no corpus at all and exits `GATE_DISPATCH_ABSENT_RC`
#    — reached `_gate_dispatch.sh` for the first time in vibe-ic#1764 and no
#    case here drove it, so the paired guard for this file was blind to half of
#    what the file decides.
#
#    WHY IT BELONGS IN THE CONCURRENCY HARNESS SPECIFICALLY. Both rows are
#    synthesised at DECLARATION time by `gate_dispatch_over`, which is exactly
#    the moment case 19 exists to police: it speaks while earlier gates are
#    still running. A second synthetic row is a second chance for the buffering
#    to attach a verdict to the wrong corpus, and "0 items" reads identically on
#    both rows, so a swap between them would be invisible in the counts.
#
#    RED WITHOUT THE FIX, and the honest reading of that red. Measured on
#    `origin/main` with `_gate_dispatch.sh` and `routed_def_corpus.py` reverted
#    to `81cd5321b`: the absent corpus records `expansion PRODUCER_FAILED` and
#    NO GATE ROW AT ALL — one corpus, zero verdicts — so this case fails there.
#    It fails because the state did not exist to be recorded, not because the
#    old dispatcher mis-recorded it: rc 3 meant nothing to it. This is a pin on
#    the new invariant, not evidence of an old defect, and §10 of the #1764
#    record draws the same distinction about its pytest sibling.
cat > "$T/twostate.sh" <<'EOF'
set -euo pipefail
. "${HERE:?}/_gate_dispatch.sh"
gate_dispatch_init "$@"
_body() { run "per-item ($1)" "$PWD" true; }
run "slow-before-the-corpora" "$PWD" bash -c 'sleep 1; echo "SLOW body"; exit 1'
gate_dispatch_over "a toy corpus read and holding none" _body true
gate_dispatch_over "a toy corpus that could not be found" _body bash -c 'exit 3'
gate_dispatch_finish
EOF
drive twoseq 1 "$T/twostate.sh"
drive twopar 4 "$T/twostate.sh"

expansions() { python3 - "$1" <<'PYX'
import json, sys
for c in json.load(open(sys.argv[1]))["corpora"]:
    print(f'{c["name"]}\t{c["items"]}\t{c.get("expansion")}')
PYX
}

WANT_TWO=$(printf 'a toy corpus read and holding none\t0\tEXPANDED\na toy corpus that could not be found\t0\tNO_CORPUS')
for arm in twoseq twopar; do
  got="$(expansions "$T/$arm.json")"
  if [ "$got" = "$WANT_TWO" ]; then
    ok "[$arm] a READ-EMPTY corpus and an ABSENT one keep separate expansion states"
  else
    bad "[$arm] the two zero-population states did not stay apart — an absent
     corpus wearing the read-empty row claims a measurement nobody took
     (vibe-ic#1764)" "$got"
  fi
  rows=$(pairs "$T/$arm.json" | grep -c 'corpus "a toy corpus' || true)
  if [ "$rows" -eq 2 ]; then
    ok "[$arm] each of the two corpora carries its own verdict row"
  else
    bad "[$arm] expected one verdict row per corpus, got $rows — a corpus with
     no verdict at all is worse than a corpus with a wrong one" \
        "$(pairs "$T/$arm.json")"
  fi
done

if diff <(pairs "$T/twoseq.json") <(pairs "$T/twopar.json") > "$T/two.diff" 2>&1; then
  ok "the two synthetic corpus rows are recorded identically under concurrency"
else
  bad "the read-empty and the absent row differ between arms — a
     declaration-time verdict landed on the wrong corpus" "$(cat "$T/two.diff")"
fi
if diff <(norm "$T/twoseq.err") <(norm "$T/twopar.err") > "$T/twoerr.diff" 2>&1; then
  ok "both corpus notes keep their declared place in stderr under concurrency"
else
  bad "a corpus note jumped over a running gate's diagnostics" \
      "$(cat "$T/twoerr.diff")"
fi

printf '\n  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
