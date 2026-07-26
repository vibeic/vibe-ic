#!/usr/bin/env bash
# tools/ci/repo_hygiene_gates.sh — the repo-wide invariant gates, in ONE place.
#
# WHY THIS FILE EXISTS (vibe-ic#381 sweep)
# ----------------------------------------
# These gates were listed inline in `.github/workflows/ci.yml` and were
# absent from `.github/workflows/gatekeeper-ci.yml`. That difference is not
# cosmetic: gatekeeper-ci is the ONLY workflow that fires on `merge_group`,
# so the native merge queue — the last thing that runs before a change
# lands — was executing a strictly WEAKER gate set than the PR check it
# supersedes. #394 had already found and hand-fixed one instance of exactly
# this (the merge gate carried only the message half of the NDA guard).
#
# A second hand-sync would drift again, because keeping two lists equal
# depends on remembering. One list invoked by both workflows makes the
# drift impossible instead of merely unlikely.
#
# WHAT BELONGS HERE: gates over repo-wide invariants that need no PR
# context. What does NOT: anything needing a commit RANGE or a base SHA
# (the NDA scanners, the version-monotonic and scope guards) — those are
# event-shaped and stay inline in the workflow that has the context.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLUGIN="$ROOT/vibe-ic-marketplace/plugins/vibe-ic"
PG="$PLUGIN/programs"
cd "$ROOT"

fail=0
run() {                                   # run <label> <cwd> <cmd...>
  local label="$1" wd="$2"; shift 2
  echo "── $label"
  if ( cd "$wd" && "$@" ); then :; else
    echo "   ^^ FAILED: $label" >&2; fail=1
  fi
}

# --- repo-root scoped ------------------------------------------------------
run "chip-AGNOSTIC source guard"        "$ROOT" python3 "$PG/source_chip_agnostic_check.py" "$PLUGIN"

# vibe-ic#354 — the image-version gate is BLOCKING. It failed loudly on main
# for six versions (0.2.29 pinned in 13 places, never published) while nothing
# enforced it. --require-remote: the pinned tag must actually RESOLVE on ghcr;
# an unreachable registry is a FAIL here, not an UNVERIFIED shrug.
run "image-version pins resolve"        "$ROOT" python3 "$ROOT/tools/vibeic-eda/sync_image_version.py" --check --require-remote

# vibe-ic#306/#316 — the audit that measures which gates can actually stop a
# run was itself wired into nothing while exiting 1. Recorded debt does not
# fail; anything NEW does.
run "flow-gate enforcement audit"       "$ROOT" python3 "$PG/flow_gate_enforcement_audit.py"

# vibe-ic#312 family — a checker that reads a field NO document populates sees
# an empty value, and an empty value is indistinguishable from a clean one.
# Measured five times in one campaign; three were "the producer never existed".
run "L-doc field producer"              "$ROOT" python3 "$PG/l_doc_field_producer_check.py"

# vibe-ic#371 — a tracked symlink recorded with an ABSOLUTE target resolves
# only on the machine that wrote it. 159 of 172 were in that state and it made
# the evidence-citation verdict differ between local and CI on the same commit.
run "tracked-symlink portability"       "$ROOT" python3 "$PG/tracked_symlink_portability_check.py"

# vibe-ic#361 — an evidence document that cites `foo.log` and ships no foo.log
# is unverifiable, and the failure is silent.
run "evidence citation resolves"        "$ROOT" python3 "$PG/evidence_citation_resolves_check.py"

# vibe-ic#381 — a checker only its own unit test ever runs has zero coverage of
# real inputs: the fixture proves the logic, never the artefacts.
run "checker execution wiring"          "$ROOT" python3 "$PG/checker_execution_wiring_audit.py"

# --- plugin scoped ---------------------------------------------------------
# Each of these was, until this file existed, run by NOTHING but its own unit
# test — it had never judged the tree it was written to judge. They are wired
# here because they are repo-hygiene: they need no design, no PDK and no run
# directory, only the plugin source itself.
run "argparse help format"              "$PLUGIN" python3 programs/argparse_help_format_check.py
run "dead plugin path"                  "$PLUGIN" python3 programs/dead_plugin_path_check.py
run "ic_expert_db health"               "$PLUGIN" python3 programs/ic_expert_db_health_audit.py
run "verdict token propagation"         "$PLUGIN" python3 programs/verdict_token_propagation_check.py
run "signoff gate self-skip"            "$PLUGIN" python3 programs/signoff_gate_self_skip_consistency_check.py
run "waveform artifact hygiene"         "$PLUGIN" python3 programs/waveform_artifact_hygiene_check.py

if [ "$fail" -ne 0 ]; then
  echo "repo_hygiene_gates: at least one gate FAILED" >&2
  exit 1
fi
echo "repo_hygiene_gates: all gates passed"
