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
GATES=(
    "emitter_failure_mode_check"
    "literal_verdict_keyword_check"
    "source_chip_agnostic_check"
    "changelog_metric_reproducibility_check"
    "changelog_command_reproducibility_check"
    "self_audit_doc_claim_consistency_check"
    # Every code package declares its own invariants, next to the code
    # they bind, and the declaration is checked rather than believed: a
    # missing INVARIANTS.yaml, a stale one, a rule naming an enforcer
    # that is not there, or a local rule a file in the package violates.
    # Belongs in THIS lane because it audits the plugin's own source
    # shape, which is what this script is for. The gate that BLOCKS a
    # landing on it is programs/tests/test_package_invariants_check.py,
    # in the one tree the landing pytest actually runs.
    "package_invariants_check"
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

if [ "$fail" -gt 0 ]; then
    echo "==> $fail of ${#GATES[@]} gate(s) FAILed"
    exit 1
fi
echo "==> all ${#GATES[@]} self-audit gates PASS"
