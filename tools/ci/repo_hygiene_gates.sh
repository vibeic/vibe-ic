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

# Same as `run`, but rc 2 means "could not check" rather than "found a defect".
# A probe that needs a CLEAN tree cannot fail the suite for a developer whose
# tree has untracked scratch in it — that is how a check becomes permanently
# red and then ignored. rc 1 (a real finding) still fails; rc 2 is LOUD and
# non-fatal, and CI checks out clean so it genuinely runs there.
run_tolerating_uncheckable() {            # <label> <cwd> <cmd...>
  local label="$1" wd="$2"; shift 2
  echo "── $label"
  local rc=0
  # `|| rc=$?` and NOT a bare `( ... ); rc=$?` — this script runs under
  # `set -e`, where a failing subshell aborts before the next line and the
  # disclosure below would never print.
  ( cd "$wd" && "$@" ) || rc=$?
  if [ "$rc" -eq 0 ]; then :
  elif [ "$rc" -eq 2 ]; then
    echo "   ^^ NOT CHECKED (rc 2, non-fatal): $label" >&2
  else
    echo "   ^^ FAILED: $label" >&2; fail=1
  fi
}

# --- repo-root scoped ------------------------------------------------------
run "chip-AGNOSTIC source guard"        "$ROOT" python3 "$PG/source_chip_agnostic_check.py" "$PLUGIN"
# Its PORTABILITY twin. Wired here because `gatekeeper_review` — the only
# other place that runs it — is invoked on PRs, and this repo lands most work
# by DIRECT PUSH, so the guard had never run on any of it. Measured when first
# wired: 4 non-portable paths, all in a test fixture committed the day before.
run "shipped-path portability" "$ROOT" python3 "$PG/shipped_path_portability_check.py" "$PLUGIN"

# Three more of `gatekeeper_review`'s gates. That program is the PR merge gate
# and is in NO CI workflow, while this repo lands most work by DIRECT PUSH — so
# 9 of its 11 gates had never run on a landing. These three are repo-STATE
# checks (no base/head needed), so they belong here. Measured: 6s, 0s, 52s.
run "watchdog compliance"           "$PLUGIN" python3 programs/loop_watchdog_compliance_check.py
run "marketplace version sync"      "$PLUGIN" python3 programs/marketplace_version_sync_check.py
run "plugin full audit"             "$PLUGIN" python3 programs/plugin_full_audit.py

# vibe-ic#354 — the image-version gate is BLOCKING. It failed loudly on main
# for six versions (0.2.29 pinned in 13 places, never published) while nothing
# enforced it. --require-remote: the pinned tag must actually RESOLVE on ghcr;
# an unreachable registry is a FAIL here, not an UNVERIFIED shrug.
run_tolerating_uncheckable "image-version pins resolve" "$ROOT" python3 "$ROOT/tools/vibeic-eda/sync_image_version.py" --check --require-remote

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

# The three NDA guards all scan a DELTA (commit messages, an added diff, the
# plugin source). None can see a token that is ALREADY tracked, so one that
# landed before a guard existed stays served by the repo forever while every
# guard reports clean. SKIPs (rc=2) when no token store is configured — which
# is the normal state for an outside contributor and is NOT a clean result.
run "NDA scan of the TRACKED tree"      "$ROOT" python3 "$PG/nda_tracked_tree_scan.py"

# vibe-ic#408/#389 — a PDK the image ships must be SELECTABLE by the name
# `--pdk` matches, and every asset the registry DECLARES must resolve. The
# name half is pure registry data and runs everywhere; the asset half needs
# the image and reports SKIPPED (never folded into the PASS) when no
# container is reachable, which is the normal CI state.
run "PDK registry selectable"           "$ROOT" python3 "$PG/pdk_registry_selectable_check.py"

# vibe-ic#419 — the size guard `.gitignore` promised in a comment and nobody
# ever wrote. Ten untracked *.gds under benchmark-data/ic are 74–105 MB and
# ACCEPTED by that file's negations; two are over GitHub's 100 MB hard limit,
# where a push is rejected after the objects are already in local history.
run "tracked blob size ceiling"         "$ROOT" python3 "$PG/tracked_blob_size_guard.py"

# vibe-ic#419 — five mechanisms held an opinion about which layout artefacts
# ship and no two agreed. Each was edited alone and stayed true to what its
# author knew; nothing could notice the set had stopped being consistent.
run "layout-artefact size policy"       "$ROOT" python3 "$PG/size_policy_drift_check.py"

# vibe-ic#413 — a correction note that claims a repair its row never received
# is a fabricated citation inside the artefact whose job is to prevent one.
# 50 of 54 noted rows carried a one-size-fits-all note asserting BOTH repairs
# when each row had received only one.
run "provenance correction notes"       "$ROOT" python3 "$PG/provenance_correction_note_check.py"

# vibe-ic#414 — a ledger's job is that a reader can take a declared output
# path, open the file, and check its hash. 102 of 156 declared outputs across
# 21 tracked ledgers could not be followed; 12 shipped under a name the ledger
# never mentioned and 90 shipped nowhere at all.
run "declared outputs are findable"     "$ROOT" python3 "$PG/provenance_declared_output_check.py"

# vibe-ic#381 — an issue reporting a DEFECTIVE ARTEFACT was twice closed by a
# change that only added or fixed the CHECKER, leaving the published data
# byte-identical and still reproducible on main. The prose rule for this lives
# in core-agent-loop 5a-i and did not stop the close it was written for.
# Sweep mode needs no PR context: it derives each closed issue's range from the
# commits whose message references it. A labelled `artefact-defect` close whose
# artefact never changed FAILS; everything else is ADVISORY (measured: 0 of 100
# attributable closes fire). Without a reachable issue API it prints SKIPPED
# and exits 0 — SKIPPED is not a PASS, and the log says so.
run "artefact-defect close discipline" "$ROOT" python3 "$PG/artefact_defect_close_check.py" --recent 60

# vibe-ic#376 — a value present in the layer that PRODUCES it and unreachable
# by the layer that CONSUMES it, while both layers pass their own gates. 23
# hand-written pairwise gates each cover one slice of that class. This is the
# general mechanism over declared cross-layer references; the corpus mode
# judges every published cell and compares against a recorded count, so the
# repo cannot grow a NEW instance of the class silently. The recorded breaks
# are real and their repair is open (layer-contract-doctrine §6); a count may
# shrink freely, any increase is red.
run "cross-layer reference regression"  "$ROOT" python3 "$PG/cross_layer_reference_check.py" --corpus "$ROOT/benchmark-data/ic"

# vibe-ic#410 — pdk_registry.json is not the only per-PDK table. Three others
# are keyed independently, and registering a PDK in the registry registers it
# in none of them. An IHP netlist was handed the SKY130A ATPG cell model while
# the artefact recorded `generic_unmapped`.
run "per-PDK table coverage"            "$ROOT" python3 "$PG/pdk_table_coverage_check.py"

# vibe-ic#377 (item B) — L4's register/field vocabulary is the one part of our
# schema whose domain is semantically CLOSED, and a ratified standard already
# enumerates it. This gate does not migrate anything: it asserts that every
# register/field key appearing in the published L4 corpus has a RECORDED answer
# to "what can SystemRDL 2.0 say about this" — NATIVE, UDP, LOSSY or DROPPED,
# each with a reason. A key with no answer would be dropped from every export
# in silence, and a .rdl that silently omits what it cannot express reads as a
# complete description of a register map it does not describe. Remedy when it
# fires: one row in DISPOSITION. Measured at wiring time: 201 documents, 41
# register keys, 18 field keys, all classified.
run "L4 -> SystemRDL disposition"       "$ROOT" python3 "$PG/l4_systemrdl_export.py" audit-corpus --root "$ROOT"

# vibe-ic#440 — benchmark-data/ic/ is what this project points at when it says
# a cell converged, and it also holds runs that did not. Measured: 28 published
# cells, 3 with an audit verdict of PASS_WITH_WAIVERS; two assert success in
# their RESULT.md while their own audit artefact reads FAIL, and one has an
# orchestrator report saying PASS_WITH_WAIVERS next to an audit saying FAIL.
# Deleting the failures (#421) was refused on measurement — that would make
# "we never ran this" and "we ran it, it failed, and we kept the record" the
# same state. The repair is to LABEL, and the label has to be gated: the
# hand-maintained BENCHMARK_IC_CAMPAIGN_STATUS.md is the version without a
# gate, and all three of its citations for the converged cells point at
# directories that no longer exist. INDEX.md is a pure function of the tracked
# artefacts, so a verdict that changes while its row does not is a FAIL here.
run "published-evidence index honest"   "$ROOT" python3 "$PG/benchmark_evidence_index.py" --check --root "$ROOT"

# --- plugin scoped ---------------------------------------------------------
# Each of these was, until this file existed, run by NOTHING but its own unit
# test — it had never judged the tree it was written to judge. They are wired
# here because they are repo-hygiene: they need no design, no PDK and no run
# directory, only the plugin source itself.
# A PASS must say how much it looked at (vibe-ic#447). Runs every gate above
# against a scratch EMPTY tree and requires that a PASS there DISCLOSE it
# examined nothing. Placed LAST so it probes the full list; ~40s.
run "gates disclose their denominator" "$ROOT" python3 "$PG/gate_discloses_denominator_check.py" "$ROOT"


# The other half of #447: a gate that reads the WRONG POPULATION and reports
# confidently about it. Runs every gate above twice at the same commit —
# working checkout vs a throwaway worktree — and requires the same verdict.
# COST: ~3m45s, roughly tripling this script's runtime. Accepted because the
# class has produced FIVE instances, two of them inside the fixes for the
# previous ones. Refuses (rc 2) on a dirty checkout rather than reporting the
# uncommitted work as findings.
run_tolerating_uncheckable "gates are host-independent" "$ROOT" python3 "$PG/gate_host_independence_check.py" "$ROOT"
run "argparse help format"              "$PLUGIN" python3 programs/argparse_help_format_check.py
run "dead plugin path"                  "$PLUGIN" python3 programs/dead_plugin_path_check.py
run "ic_expert_db health"               "$PLUGIN" python3 programs/ic_expert_db_health_audit.py
run "verdict token propagation"         "$PLUGIN" python3 programs/verdict_token_propagation_check.py
run "signoff gate self-skip"            "$PLUGIN" python3 programs/signoff_gate_self_skip_consistency_check.py
run "waveform artifact hygiene"         "$PLUGIN" python3 programs/waveform_artifact_hygiene_check.py

# vibe-ic#428 — final_summary.md printed TWO verdict roll-ups over the same 63
# steps and they disagreed on the BLOCKING-FAILURE count, with nothing marking
# either as counting a different thing. The cause was static and repo-shaped:
# the renderer's verdict-line parser enumerated only some step-id shapes, so
# the ids the flow had since grown (D1, FS1, DT1-3) were unreadable and each
# was silently booked as the compliance verdict MISSING. Repo mode asserts
# every id the flow declares is readable — it fires when the id shape is
# ADDED, not after a run has already published a wrong FAIL count.
run "final-summary roll-up consistency" "$PLUGIN" python3 programs/final_summary_rollup_consistency_check.py

if [ "$fail" -ne 0 ]; then
  echo "repo_hygiene_gates: at least one gate FAILED" >&2
  exit 1
fi
echo "repo_hygiene_gates: all gates passed"
