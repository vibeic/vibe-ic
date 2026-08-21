#!/usr/bin/env bash
# BLOCKING landing lane owned by vibeic/benchmark-data.
#
# The programs live in vibeic/vibe-ic; the evidence and its publishing decision
# live in vibeic/benchmark-data.  This runner is the single hand-off point.  It
# requires the exact top level of a clean canonical checkout and then runs every
# data-owned gate against that checkout.  There is deliberately no absent-corpus
# success path: no argument/environment pointer is rc 2, and a bad pointer is rc 1.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$HERE/../.." && pwd)"
PG="$PLUGIN_ROOT/vibe-ic-marketplace/plugins/vibe-ic/programs"
CORPUS="${VIBE_IC_BENCHMARK_DATA:-}"
if [ "$#" -gt 0 ] && [[ "$1" != --* ]]; then
  CORPUS="$1"
  shift
fi

if [ -z "$CORPUS" ]; then
  echo "[NOT CHECKED] benchmark-data hygiene: pass the exact checkout root or set VIBE_IC_BENCHMARK_DATA; no corpus was examined" >&2
  exit 2
fi
CORPUS="$(cd "$CORPUS" 2>/dev/null && pwd)" || {
  echo "[FAIL] benchmark-data hygiene: corpus pointer is not a readable directory: $CORPUS" >&2
  exit 1
}

# Preflight OWNS the next step: no gate runs against an unverified loose tree,
# fork, partial checkout, or dirty checkout.
python3 "$HERE/benchmark_data_contract_check.py" \
  --plugin-root "$PLUGIN_ROOT" --corpus "$CORPUS"

ROOT="$CORPUS"
GATE_DISPATCH_CORPUS_ROOT="$CORPUS"
GATE_DISPATCH_CORPUS_REL="."
GATE_DISPATCH_ATTESTATION_OWNED=0
if [ -z "${GATE_DISPATCH_ATTESTATION_FILE:-}" ]; then
  GATE_DISPATCH_ATTESTATION_FILE="$(mktemp -t benchmark-data-hygiene-attest.XXXXXX)"
  GATE_DISPATCH_ATTESTATION_OWNED=1
fi
GATE_DISPATCH_ATTESTATION_HELPER="$PG/gate_process_attestation.py"
export GATE_DISPATCH_CORPUS_ROOT GATE_DISPATCH_CORPUS_REL
export GATE_DISPATCH_ATTESTATION_FILE GATE_DISPATCH_ATTESTATION_HELPER
_cleanup() {
  [ "$GATE_DISPATCH_ATTESTATION_OWNED" -eq 0 ] \
    || rm -f -- "$GATE_DISPATCH_ATTESTATION_FILE"
}
trap _cleanup EXIT

. "$HERE/_gate_dispatch.sh"
gate_dispatch_init "$@"

# All ten are BLOCKING.  A program's rc 2 is a failed landing here: the corpus
# checkout passed preflight, so inability to examine it is a broken contract,
# not an environment exemption.
run "L-doc field producer"              "$CORPUS" python3 "$PG/l_doc_field_producer_check.py" "$CORPUS/ic" --baseline "$CORPUS/ci/baselines/l_doc_field_producer_baseline.json"
run "tracked-symlink portability"       "$CORPUS" python3 "$PG/tracked_symlink_portability_check.py" "$CORPUS"
run "tracked-symlink target present"    "$CORPUS" python3 "$PG/tracked_symlink_target_present_check.py" --root "$CORPUS" --subdir .
run "evidence citation resolves"        "$CORPUS" python3 "$PG/evidence_citation_resolves_check.py" "$CORPUS/ic" --baseline "$CORPUS/evidence_citation_baseline.json"
run "citation routing is true"          "$CORPUS" python3 "$PG/citation_routing_is_true_check.py" --root "$CORPUS"
run "cross-layer reference regression"  "$CORPUS" python3 "$PG/cross_layer_reference_check.py" --corpus "$CORPUS/ic" --baseline "$CORPUS/ci/baselines/cross_layer_reference_baseline.json"
run "step FAIL bubbles up"               "$CORPUS" python3 "$PG/step_internal_fail_bubble_up_check.py" --corpus "$CORPUS/ic" --baseline "$CORPUS/ci/baselines/step_internal_fail_bubble_up_baseline.json"
run "L4 -> SystemRDL disposition"        "$CORPUS" python3 "$PG/l4_systemrdl_export.py" audit-corpus --root "$CORPUS"
run "published-evidence index honest"    "$CORPUS" python3 "$PG/benchmark_evidence_index.py" --check --data-root "$CORPUS"
run "published records not superseded"   "$CORPUS" python3 "$PG/published_record_staleness_check.py" "$CORPUS"

gate_dispatch_finish
