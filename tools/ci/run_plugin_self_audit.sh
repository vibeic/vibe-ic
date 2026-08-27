#!/bin/bash
# tools/ci/run_plugin_self_audit.sh — anti-fabrication self-audit
# (v1.6.45: added the v1.6.43 gates that v1.6.43 itself forgot to wire
# in, plus a meta-gate that catches the same class of doc-vs-runner
# drift in CHANGELOG / plugin.json.)
#
# Runs the plugin-source-auditing gates against the vibe-ic plugin tree
# itself. Intended as a pre-commit / pre-push CI step. Distinct from
# `flow_compliance_check.py` which audits a chip-design project tree;
# these gates audit the plugin's own source for the kinds of
# fabrication that the v1.6.37 release shipped (silent-PASS on tool
# failure, hardcoded sign-off numerics, chip-specific tokens, CHANGELOG
# metrics / quoted commands / pytest counts that don't trace back to
# source).
#
# Exit codes:
#   0  every gate PASSes
#   1  one or more gates FAIL — review output and fix
#   2  argument / IO error
#
# Usage:
#   bash tools/ci/run_plugin_self_audit.sh [<plugin_root>]
#
# Default <plugin_root> = vibe-ic-marketplace/plugins/vibe-ic relative
# to the repo root (auto-detected via git rev-parse).

set -e

if ! ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
    echo "error: not inside a git work tree" >&2
    exit 2
fi

PLUGIN_ROOT="${1:-$ROOT/vibe-ic-marketplace/plugins/vibe-ic}"
if [ ! -d "$PLUGIN_ROOT/programs" ]; then
    echo "error: plugin programs/ subdir not found at $PLUGIN_ROOT" >&2
    exit 2
fi

PROGRAMS="$PLUGIN_ROOT/programs"
# Gates that take the plugin root as a POSITIONAL argument.
GATES=(
    "emitter_failure_mode_check"
    "literal_verdict_keyword_check"
    "source_chip_agnostic_check"
    "changelog_metric_reproducibility_check"
    "changelog_command_reproducibility_check"
    "self_audit_doc_claim_consistency_check"
)

# Gates that take it as `--root`. A SECOND LIST rather than a rewritten CLI:
# the alternative was to give `unanchored_process_kill_check.py` a positional
# root so it could join the array above, and changing a shipped gate's
# interface to fit its runner is the tail wagging the dog — the runner is what
# has to accommodate, and one more `for` loop is the whole cost.
#
# WHY THIS FILE AND NOT `repo_hygiene_gates.sh`: both are machine runners the
# wiring audit counts, and this one is the stated home for exactly this class —
# its own header says it "runs the plugin-source-auditing gates against the
# vibe-ic plugin tree itself", which is what a pure source scan is. It is also
# not in the protected-landing tuple, so wiring here does not need a
# PREPARE/ACTIVATE pair to reach main.
GATES_ROOT_FLAG=(
    # vibe-ic#381: no shipped code may choose which process to KILL by matching
    # a command line. Landed by ea51511ef1 (v1.11.95) WITHOUT a runner, which
    # is what `checker_execution_wiring_audit` reports: "1 checker(s) that
    # NOTHING but their own test runs". Measured GREEN over `$PLUGIN_ROOT`
    # before being wired here (#1253: wiring a RED gate turns "unverified" into
    # "blocking", which is a different change and not this one).
    "unanchored_process_kill_check"
)

fail=0
for gate in "${GATES[@]}"; do
    echo "=== $gate ==="
    if python3 "$PROGRAMS/${gate}.py" "$PLUGIN_ROOT"; then
        echo
    else
        rc=$?
        echo "  -> FAIL (rc=$rc)"
        fail=$((fail + 1))
    fi
done

for gate in "${GATES_ROOT_FLAG[@]}"; do
    echo "=== $gate ==="
    if python3 "$PROGRAMS/${gate}.py" --root "$PLUGIN_ROOT"; then
        echo
    else
        rc=$?
        echo "  -> FAIL (rc=$rc)"
        fail=$((fail + 1))
    fi
done

if [ "$fail" -gt 0 ]; then
    echo "==> $fail of $(( ${#GATES[@]} + ${#GATES_ROOT_FLAG[@]} )) gate(s) FAILed"
    exit 1
fi
echo "==> all $(( ${#GATES[@]} + ${#GATES_ROOT_FLAG[@]} )) self-audit gates PASS"
