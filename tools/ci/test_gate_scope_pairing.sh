#!/usr/bin/env bash
# test_gate_scope_pairing.sh — the harness `_gate_dispatch.sh` already claimed to have.
#
# WHAT WAS MISSING
# ================
# `_gate_dispatch.sh` states:
#
#     a scope that is too narrow silently stops guarding, which is why the pairing
#     test asserts a real change inside each declared scope still runs its gate
#
# No such assertion existed (vibe-ic#1729). Every case in `test_gate_scope.sh` drives
# a synthetic `run "t" "." true`, and `test_gate_concurrency.sh` drives scripts it
# writes itself. Neither ever runs a REAL gate program, so neither could tell a scope
# that guards from one that merely looks like it does — which is how thirteen scopes
# excluding their own checker got as far as review.
#
# WHAT THIS ADDS
# ==============
# A gate that is a real program reading a real file, driven through the real
# dispatcher, with the change set varied underneath it:
#
#     change INSIDE the declared scope   -> the gate RUNS      (the guarding half)
#     change OUTSIDE it                  -> the gate SKIPS     (the narrowing half)
#     the scope reaches --summary-json    -> the skip is CHECKABLE, not just printed
#
# The first is the one that was absent, and it is the one that matters: a test proving
# only that a scope skips would pass against a scope that skips everything.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s\n     %s\n' "$1" "${2:-}"; }

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

# A REAL gate: a program that reads a file and fails when its content is wrong.
# Not `true` — the whole point is that something is actually guarded.
mkdir -p "$T/guarded" "$T/elsewhere"
printf 'expected\n' > "$T/guarded/subject.txt"
printf 'unrelated\n' > "$T/elsewhere/other.txt"
cat > "$T/real_gate.sh" <<'GATE'
#!/usr/bin/env bash
# Fails if the guarded subject is not what it should be. A gate with a real verdict.
[ "$(cat "$1" 2>/dev/null)" = "expected" ] || { echo "SUBJECT CHANGED"; exit 1; }
echo "subject intact"
GATE
chmod +x "$T/real_gate.sh"

drive() {                      # drive <changed-paths-file> <scope> [--json OUT]
  local changed="$1" scope="$2" jsonout="${3:-}"
  ( set +u
    export GATEKEEPER_CHANGED_PATHS="$changed"
    # JOBS=1 DELIBERATELY. Under concurrency `run` returns while the gate is still
    # QUEUED and `GATE_STATES[i]` is not yet its verdict — measured here: case 2
    # read `STATE=QUEUED` and reported a false failure. Scope semantics are what
    # this harness is about, and they are identical in both arms; the concurrent
    # path has its own harness (`test_gate_concurrency.sh`).
    #
    # NOTE for whoever reads this next: `test_gate_scope.sh` case 9 asserts on
    # `GATE_STATES[0]` the same way. It passes today because its gate is `true`
    # and finishes first, which is luck rather than a guarantee.
    export GATEKEEPER_HYGIENE_JOBS=1
    . "$HERE/_gate_dispatch.sh" >/dev/null 2>&1
    gate_dispatch_init >/dev/null 2>&1
    [ -z "$scope" ] || gate_scope "$scope"
    run "guarded subject" "$T" bash "$T/real_gate.sh" "$T/guarded/subject.txt"
    [ -z "$jsonout" ] || _gate_dispatch_emit "$jsonout" >/dev/null 2>&1
    printf 'STATE=%s\n' "${GATE_STATES[0]:-none}"
  ) 2>&1
}

printf 'guarded/subject.txt\n' > "$T/inside.txt"
printf 'elsewhere/other.txt\n'  > "$T/outside.txt"

# ── 1. THE HALF THAT WAS MISSING ─────────────────────────────────────────────
#    A real change inside the declared scope must RUN the gate.
out="$(drive "$T/inside.txt" "guarded/")"
case "$out" in
  *"STATE=OUT_OF_SCOPE"*) bad "a change INSIDE the scope skipped the gate — the scope
     stopped guarding the thing it named" "$out" ;;
  *) ok "change inside the declared scope -> the gate runs" ;;
esac

# ── 2. …and the gate it ran actually REACHED ITS SUBJECT and can fail. ───────
#    Without this, case 1 passes against a gate that runs and checks nothing.
printf 'tampered\n' > "$T/guarded/subject.txt"
out="$(drive "$T/inside.txt" "guarded/")"
case "$out" in
  *"STATE=FAIL"*) ok "the gate that ran can still FAIL on its real subject" ;;
  *) bad "the subject was tampered with and the gate did not fail — it runs without
     reading anything, so case 1 proves nothing" "$out" ;;
esac
printf 'expected\n' > "$T/guarded/subject.txt"

# ── 3. THE NARROWING HALF: a change outside must skip. ──────────────────────
out="$(drive "$T/outside.txt" "guarded/")"
case "$out" in
  *"STATE=OUT_OF_SCOPE"*) ok "change outside the declared scope -> the gate skips" ;;
  *) bad "the scope narrowed nothing" "$out" ;;
esac

# ── 4. NO SCOPE -> ALWAYS RUNS, even for an unrelated change. ───────────────
out="$(drive "$T/outside.txt" "")"
case "$out" in
  *"STATE=OUT_OF_SCOPE"*) bad "an UNSCOPED gate was skipped — narrowing must be opt-in" "$out" ;;
  *) ok "no gate_scope -> runs whatever changed" ;;
esac

# ── 5. THE SKIP IS CHECKABLE. vibe-ic#1729: the scope must reach the RECORD, ─
#    not only the console. A reader must be able to check the claim rather than
#    inherit it — and every consumer reads --summary-json, not the log.
drive "$T/outside.txt" "guarded/" "$T/rec.json" >/dev/null
if [ ! -s "$T/rec.json" ]; then
  bad "no summary record was written at all" "$T/rec.json"
else
  got="$(python3 - "$T/rec.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
g = next((x for x in d.get("gates", []) if x.get("label") == "guarded subject"), None)
print("MISSING" if g is None else f'{g.get("state")}|{g.get("scope")!r}')
PY
)"
  case "$got" in
    OUT_OF_SCOPE\|*guarded/*) ok "the record carries the state AND the scope it claimed" ;;
    *MISSING*) bad "the gate is absent from the record" "$got" ;;
    *"|None"*) bad "the record says OUT_OF_SCOPE and does NOT say which paths were
     claimed — the skip is printed but not checkable, which is vibe-ic#1729" "$got" ;;
    *) bad "unexpected record" "$got" ;;
  esac
fi

# ── 6. AN UNSCOPED GATE RECORDS scope=None, not a stale neighbour's scope. ──
#    The arrays are read by index; a scope appended on only some paths would
#    attribute one gate's claim to another's verdict.
( set +u
  export GATEKEEPER_CHANGED_PATHS="$T/inside.txt"
  export GATEKEEPER_HYGIENE_JOBS=1
  . "$HERE/_gate_dispatch.sh" >/dev/null 2>&1
  gate_dispatch_init >/dev/null 2>&1
  gate_scope "guarded/"
  run "scoped one"   "$T" bash "$T/real_gate.sh" "$T/guarded/subject.txt"
  run "unscoped one" "$T" bash "$T/real_gate.sh" "$T/guarded/subject.txt"
  _gate_dispatch_emit "$T/rec2.json" >/dev/null 2>&1
) >/dev/null 2>&1
got="$(python3 - "$T/rec2.json" <<'PY'
import json, sys
try: d = json.load(open(sys.argv[1]))
except Exception as e: print(f"UNREADABLE {e}"); raise SystemExit
m = {g["label"]: g.get("scope") for g in d.get("gates", [])}
print(f'{m.get("scoped one")!r}|{m.get("unscoped one")!r}')
PY
)"
case "$got" in
  *guarded/*\|None) ok "scope is per gate: the unscoped one records None, not its neighbour's" ;;
  *) bad "a scope leaked between gates, or the record is unreadable" "$got" ;;
esac

printf '\n  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
