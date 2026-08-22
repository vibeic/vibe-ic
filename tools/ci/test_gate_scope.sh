#!/usr/bin/env bash
# test_gate_scope.sh — the paired guard for change-aware gate selection (#P3).
#
# A feature whose whole job is to NOT RUN THINGS is one assertion away from being
# a way to turn the suite off. So every case here comes in two directions: the
# gate must skip when it genuinely has nothing to read, AND it must run when it
# does. A test that only proved the first would pass against a dispatcher that
# skips everything.
#
# The three properties, each with its own paired case:
#
#   narrowing is opt-in     no gate_scope line  -> ALWAYS runs
#   unknown means run       no change set       -> runs even with a scope
#   a skip is on the record -> state OUT_OF_SCOPE, printed, scope attached
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n     %s\n' "$1" "${2:-}"; }

# One dispatcher run in a subshell, so state cannot leak between cases.
#
# PINNED TO JOBS=1 (#P4), and the reason is not that scope and concurrency
# interact — they do not. Scope is decided at DECLARATION time, on the main
# shell, before any gate is queued, so its answer is the same at any job count.
# What differs is DELIVERY: with a pool, the SKIP line is buffered so it appears
# in declaration order, and it is `gate_dispatch_finish` that flushes it — which
# these cases deliberately never call, because they read the dispatcher's arrays
# directly rather than running a whole script. Pinning is therefore honest about
# what this file tests. That the SKIP still prints, in order, WITH a pool is
# asserted in `test_gate_concurrency.sh`, which drives complete scripts.
drive() {                       # drive <changed-paths-file|""> <body> -> stdout
  local changed="$1" body="$2"
  ( set +u
    export GATEKEEPER_CHANGED_PATHS="$changed"
    export GATEKEEPER_HYGIENE_JOBS=1
    . "$HERE/_gate_dispatch.sh" >/dev/null 2>&1
    gate_dispatch_init >/dev/null 2>&1
    eval "$body"
  ) 2>&1
}

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
printf 'vibe-ic-marketplace/plugins/vibe-ic/programs/x.py\n' > "$T/mp_only.txt"
printf 'tools/ci/repo_hygiene_gates.sh\n'                    > "$T/tools_only.txt"
: > "$T/empty.txt"

# ── 1. skips when the change touches nothing it reads ────────────────────────
out=$(drive "$T/mp_only.txt" 'gate_scope tools/; run "t" "." true')
case "$out" in
  *"SKIP"*"reads [tools/]"*) ok "scoped to tools/, change is marketplace-only -> SKIP" ;;
  *) bad "should have skipped" "$out" ;;
esac

# ── 2. …AND RUNS when it does. The half that makes case 1 mean something. ─────
out=$(drive "$T/tools_only.txt" 'gate_scope tools/; run "t" "." true')
case "$out" in
  *SKIP*) bad "scoped to tools/, change IS in tools/ -> must RUN, not skip" "$out" ;;
  *)      ok "scoped to tools/, change is in tools/ -> runs" ;;
esac

# ── 3. narrowing is OPT-IN: no scope declared -> always runs ─────────────────
out=$(drive "$T/mp_only.txt" 'run "t" "." true')
case "$out" in
  *SKIP*) bad "a gate with NO gate_scope was skipped — narrowing must be opt-in" "$out" ;;
  *)      ok "no gate_scope -> runs regardless of the change set" ;;
esac

# ── 4. an UNKNOWN change set runs everything ────────────────────────────────
out=$(drive "" 'gate_scope tools/; run "t" "." true')
case "$out" in
  *SKIP*) bad "no change set known, yet the gate was skipped — 'I could not find out
     what changed' must never read as 'nothing relevant changed'" "$out" ;;
  *)      ok "change set unknown -> scope ignored, gate runs" ;;
esac

# ── 5. an EMPTY change-set file is 'unknown', not 'nothing changed' ──────────
#    A produced-but-empty file is the classic empty-result-is-not-a-zero trap: a
#    failed `git diff` writes exactly this.
out=$(drive "$T/empty.txt" 'gate_scope tools/; run "t" "." true')
case "$out" in
  *SKIP*) bad "an EMPTY change-set file skipped the gate — an empty result is not a zero" "$out" ;;
  *)      ok "empty change-set file -> treated as unknown, gate runs" ;;
esac

# ── 6. the prefix match reaches into subdirectories ──────────────────────────
out=$(drive "$T/tools_only.txt" 'gate_scope tools/ci/; run "t" "." true')
case "$out" in
  *SKIP*) bad "tools/ci/ scope did not match tools/ci/repo_hygiene_gates.sh" "$out" ;;
  *)      ok "scope is a path prefix, so it reaches subdirectories" ;;
esac

# ── 7. a scope declared and never attached is a WIRING ERROR ─────────────────
#    Same rule as the exemption (#584): a pending declaration left armed would
#    silence the NEXT gate, which is a skip nobody wrote.
out=$(drive "$T/mp_only.txt" 'gate_scope tools/; gate_scope docs/; run "t" "." true')
case "$out" in
  *"never attached"*) ok "two scopes in a row -> wiring error, not a silent overwrite" ;;
  *) bad "a dangling scope was accepted" "$out" ;;
esac

# ── 8. an EMPTY scope is refused ────────────────────────────────────────────
out=$(drive "$T/mp_only.txt" 'gate_scope; run "t" "." true')
case "$out" in
  *"names nothing"*) ok "gate_scope with no path -> refused" ;;
  *) bad "an empty scope was accepted; it would skip on every change" "$out" ;;
esac

# ── 9. the skip is RECORDED, not merely printed ─────────────────────────────
out=$(drive "$T/mp_only.txt" 'gate_scope tools/; run "t" "." true; echo "STATE=${GATE_STATES[0]:-none} SCOPE=${GATE_SCOPES[0]:-none}"')
case "$out" in
  *"STATE=OUT_OF_SCOPE"*"SCOPE=tools/"*) ok "recorded as OUT_OF_SCOPE with its scope attached" ;;
  *) bad "the skip did not reach the record" "$out" ;;
esac

# ── 10. OUT_OF_SCOPE is NOT a pass ──────────────────────────────────────────
out=$(drive "$T/mp_only.txt" 'gate_scope tools/; run "t" "." true; echo "S=${GATE_STATES[0]:-none}"')
case "$out" in
  *"S=PASS"*) bad "a skipped gate was recorded as PASS — a shrinking denominator
     reading as a clean sheet is the defect this whole feature must not become" "$out" ;;
  *) ok "OUT_OF_SCOPE is its own state, not folded into PASS" ;;
esac

printf '\n  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
