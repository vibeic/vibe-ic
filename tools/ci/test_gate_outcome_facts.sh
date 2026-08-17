#!/usr/bin/env bash
# test_gate_outcome_facts.sh — the paired guard for `_gate_outcome_facts`.
#
# THE FIXTURE LIVES BESIDE THE CHECK, deliberately: this file sources the REAL
# `_gate_dispatch.sh` and drives the REAL `run` wrapper, so it cannot drift from
# what CI executes. That is the same reason `_gate_dispatch.sh`'s own header
# gives for the recording living there rather than inline in the gate script.
#
# BOTH DIRECTIONS FOR EVERY CASE. A renderer of failure facts is one `printf`
# away from printing the same string for every failure, which is exactly the
# defect it was written to remove — so each case asserts the fact that must be
# PRESENT and, where they are confusable, the fact that must be ABSENT.
#
#   ordinary failure   exit 1        named; must NOT claim a signal
#   killed by a signal exit 137      names SIGKILL *and* keeps the raw 137
#   missing command    exit 127      says so, rather than leaving 127 to be
#                                    read as an ordinary defect count
#   a PASS             unchanged     no facts line at all
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s\n     %s\n' "$1" "${2:-}"; }

# One dispatcher run per case in a subshell, jobs=1, so no state leaks between
# cases and the FAIL line is emitted inline rather than through the pool.
drive() {                                   # drive <body> -> merged stdout+stderr
  ( set +u
    export GATEKEEPER_HYGIENE_JOBS=1
    unset GATE_DISPATCH_ATTESTATION_FILE
    . "$HERE/_gate_dispatch.sh" >/dev/null 2>&1
    gate_dispatch_init >/dev/null 2>&1
    eval "$1"
  ) 2>&1
}

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

# ── 0. the renderer, called directly, on every branch ────────────────────────
direct() { ( . "$HERE/_gate_dispatch.sh" >/dev/null 2>&1; _gate_outcome_facts "$1" ); }

[ "$(direct 1)" = "exit 1" ] \
  && ok "rc 1 renders as 'exit 1'" \
  || bad "rc 1" "$(direct 1)"

case "$(direct 137)" in
  *"exit 137"*"SIGKILL"*) ok "rc 137 keeps the raw status AND names SIGKILL" ;;
  *) bad "rc 137 must carry both facts" "$(direct 137)" ;;
esac

case "$(direct 143)" in
  *"exit 143"*"SIGTERM"*) ok "rc 143 keeps the raw status AND names SIGTERM" ;;
  *) bad "rc 143 must carry both facts" "$(direct 143)" ;;
esac

case "$(direct 127)" in
  *"command not found"*) ok "rc 127 is named as a missing command" ;;
  *) bad "rc 127" "$(direct 127)" ;;
esac

# THE FALLBACK IS NOT AN EMPTY STRING. A renderer that prints nothing when it
# knows nothing turns "unobserved" into "nothing to report".
case "$(direct "")" in
  *"no exit code or signal"*) ok "an unobservable status SAYS it is unobservable" ;;
  *) bad "empty rc must not render as an empty string" "[$(direct "")]" ;;
esac

# ── 1. an ordinary failing gate names its exit status ────────────────────────
out=$(drive 'run "a-failure" "." sh -c "exit 1"')
case "$out" in
  *"FAILED: a-failure"*"exit 1"*) ok "a gate that exits 1 reports 'exit 1'" ;;
  *) bad "the exit status did not reach the FAIL line" "$out" ;;
esac
# …AND DOES NOT INVENT ONE. The half that makes the case above mean something:
# without it, a renderer that always appended 'signal SIGKILL' would pass.
case "$out" in
  *signal*) bad "an ordinary rc 1 must not claim a signal" "$out" ;;
  *)        ok "an ordinary rc 1 claims no signal" ;;
esac

# ── 2. a gate the machine KILLED is distinguishable from one that FAILED ─────
out_killed=$(drive 'run "a-kill" "." sh -c "kill -KILL \$\$"')
case "$out_killed" in
  *"FAILED: a-kill"*"SIGKILL"*) ok "a killed gate names SIGKILL on its FAIL line" ;;
  *) bad "a killed gate is indistinguishable from an ordinary failure" "$out_killed" ;;
esac
# The two lines must not be the same line. This is the whole point: before this
# change both rendered `^^ FAILED: <label> [0s]` and differed only in the label.
f1=$(printf '%s\n' "$out"        | grep -a 'FAILED:' | sed 's/^.*\]//')
f2=$(printf '%s\n' "$out_killed" | grep -a 'FAILED:' | sed 's/^.*\]//')
[ -n "$f1" ] && [ "$f1" != "$f2" ] \
  && ok "an OOM-killed gate and a defect-finding gate no longer read alike" \
  || bad "both failures rendered the same facts" "[$f1] vs [$f2]"

# ── 3. a missing command is named as such ────────────────────────────────────
out=$(drive 'run "a-missing" "." this-command-does-not-exist-9f3c')
case "$out" in
  *"FAILED: a-missing"*"command not found"*) ok "a missing command says so" ;;
  *) bad "rc 127 reached the reader as an ordinary failure" "$out" ;;
esac

# ── 4. a PASS is UNCHANGED. The facts line is diagnostic, never a new verdict
#       and never new noise on the green path. ────────────────────────────────
out=$(drive 'run "a-pass" "." true')
case "$out" in
  *FAILED*|*"exit "*) bad "a passing gate must print no outcome facts" "$out" ;;
  *)                  ok "a passing gate prints exactly what it always did" ;;
esac

printf '\n%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
