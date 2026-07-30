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

# Resolved to an ABSOLUTE path BEFORE the `cd` below: `${BASH_SOURCE[0]}` may
# be relative to the invoking cwd, and after `cd "$ROOT"` a relative dirname
# would resolve somewhere else — which would silently fail to find the sourced
# dispatch library for any caller that does not happen to start at the root.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PLUGIN="$ROOT/vibe-ic-marketplace/plugins/vibe-ic"
PG="$PLUGIN/programs"
cd "$ROOT"

# --- WHAT RAN, REPORTED FROM HERE (vibe-ic#538) -----------------------------
# `gatekeeper_review` — the gate a maintainer runs before every push, whose
# MERGE_OK reads as "this will land green" — carried its own list of FIVE of
# the gates below and answered MERGE_OK without consulting the other 29.
# Twice in one day that verdict was wrong: v1.7.89 landed red on
# `published_record_staleness_check`, and v1.7.92 was refused only because the
# maintainer had by then taken to running THIS script by hand.
#
# The repair is that the merge gate INVOKES this script instead of re-listing
# it, so the argument setup and the exit-code interpretation below are the ones
# that actually run — a caller that re-derived `prog .` from the gate NAMES
# would lose `--recent 60`, `--corpus`, `--check`, `audit-corpus`, `"$PLUGIN"`,
# the plugin-relative cwd and the rc-2 tolerance, and would be a second list
# besides.
#
# `run` / `run_tolerating_uncheckable` and the coverage record they produce now
# live in `_gate_dispatch.sh`, sourced below, so that the merge gate's report of
# what ran comes from the single place each gate is DECLARED. See that file for
# the state model and the `--list` / `--summary-json` contract; both flags are
# additive, and with neither this script behaves exactly as it did before, which
# is how both CI workflows still call it.
. "$HERE/_gate_dispatch.sh"
gate_dispatch_init "$@"

# --- repo-root scoped ------------------------------------------------------
run "chip-AGNOSTIC source guard"        "$ROOT" python3 "$PG/source_chip_agnostic_check.py" "$PLUGIN"
# Its PORTABILITY twin. Wired here because `gatekeeper_review` — the only
# other place that runs it — is invoked on PRs, and this repo lands most work
# by DIRECT PUSH, so the guard had never run on any of it. Measured when first
# wired: 4 non-portable paths, all in a test fixture committed the day before.
run "shipped-path portability" "$ROOT" python3 "$PG/shipped_path_portability_check.py" "$PLUGIN"
# vibe-ic#552 — a warning our EDA fork substitutes for an upstream abort must
# still be visible to the gate that needs it. Every downgrade moves a
# condition out of the error-matching sets BY CONSTRUCTION, so the
# registry has to be checked rather than trusted.
run "fork downgrades stay visible" "$PLUGIN" python3 programs/fork_downgrade_visibility_check.py .

# Three more of `gatekeeper_review`'s own gates, copied INTO this lane when it
# was the only direction available. Since #538 the traffic runs the other way
# as well — that program now invokes THIS script — so these three are executed
# twice on a landing. That is deliberate and it is not redundancy: this lane
# runs them against the repo it lives in, and the merge gate runs its own
# copies against whatever `--plugin-root` it was given, which is not always the
# same tree. Measured: 6s, 0s, 52s; the overlap is the cheap end of the set.
#
# (The count this comment used to carry — "9 of its 11 gates" — was wrong by
# the time anyone read it: `review()` had grown to 17. Counts of the other
# side's gate list are exactly what #538 is about, so this one no longer
# states a number it cannot keep true.)
run "watchdog compliance"           "$PLUGIN" python3 programs/loop_watchdog_compliance_check.py
run "marketplace version sync"      "$PLUGIN" python3 programs/marketplace_version_sync_check.py
run "plugin full audit"             "$PLUGIN" python3 programs/plugin_full_audit.py

# vibe-ic#354 — the image-version gate is BLOCKING. It failed loudly on main
# for six versions (0.2.29 pinned in 13 places, never published) while nothing
# enforced it. --require-remote: the pinned tag must actually RESOLVE on ghcr;
# an unreachable registry is a FAIL here, not an UNVERIFIED shrug.
#
# vibe-ic#539 — and that remote call is why this gate, alone in the set, is
# declared out of the host-independence comparison below. That probe runs every
# gate TWICE and requires the two verdicts to match; a verdict that depends on
# a network round-trip can differ between the invocations for a reason that is
# not in the commit. v1.7.92 went RED on this gate, whose code is perfectly
# host-independent, and GREEN on the identical commit when re-run. The choice
# is between excluding it deliberately and excluding it by luck. The directive
# below is read by `gate_host_independence_check` — it must stay on the line
# IMMEDIATELY above the gate, and if it drifts the gate is probed again (a
# visible returning flake) rather than silently dropped.
# host-independence: EXCLUDE — resolves a tag on a remote registry (--require-remote), so two invocations can differ for a reason that is not in the commit
run_tolerating_uncheckable "image-version pins resolve" "$ROOT" python3 "$ROOT/tools/vibeic-eda/sync_image_version.py" --check --require-remote

# On 2026-07-28 a retried `gh repo fork` created 25 forks of one upstream in six
# minutes — the command is not idempotent and invents a numbered name instead of
# failing. Two days later GitHub flagged the account as spammy, and the org's
# issues and pull requests left the search index, which is what renders the
# `/issues` and `/pulls` pages. A repo with 205 issues and 353 PRs displayed as
# empty to every visitor, and Actions began returning 422.
#
# Cheap when clean: one `gh repo list`, and the per-branch comparison only runs
# for an upstream that actually appears twice. rc 2 when it cannot ask, so an
# offline run is NOT_CHECKED rather than a verdict.
# host-independence: EXCLUDE — reads live org state over the network, so two invocations can differ for a reason that is not in the commit
run_tolerating_uncheckable "no upstream forked twice" "$PLUGIN" python3 programs/org_duplicate_fork_check.py vibeic

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
# The defect the line above deliberately declines. Its subject is whether a
# pointer is relative and stays inside the repo; a target that exists nowhere
# is a missing FILE, which its own comment says is different — and for months
# the count was reported on every run with nothing failing on it (#555, #556).
run "tracked-symlink target present"    "$ROOT" python3 "$PG/tracked_symlink_target_present_check.py" --root "$ROOT"

# `ci.yml` and `gatekeeper-ci.yml` both ran "Validate all JSON + YAML". When
# Actions was disabled in v1.8.40 and gatekeeper-land.sh took over, that step
# was not carried across — and nothing noticed, because the tree was clean and
# a check that does not exist looks exactly like one that passes. Measured
# 2026-07-30: CAPTURE_ROUTING.json truncated mid-string, all eight cheap-tier
# gates PASS. The flow dispatcher's routing table could land unparseable.
# vibeic-eda#8 — the image ships two ways to run STA and they disagree about
# what the toolchain can do. `openroad`'s built-in engine carries our
# timing-ECO superset (10/10 commands); the standalone `sta` is the base
# image's June binary and has none of them, because no COPY line ever names it.
# Nothing errors when a flow step shells out to the wrong one — an absent Tcl
# command in a script that does not call it looks like a working install.
#
# FIXED in vibeic-eda 0.2.46: the build now builds `//src/sta:opensta` and the
# composing image copies it over the base image's binary. Verified against the
# published digest — sta went 8934800 bytes/Jun 22 with 0/10 superset commands
# to 12304560/Jul 30 with 10/10.
#
# The baseline register that carried those ten is DELETED rather than emptied.
# Kept, it passed the OLD image too — measured: `--image :0.2.45 --baseline …`
# returned rc 0 on a `sta` with 0 of 10 commands. A register describing a debt
# that no longer exists is not conservative, it is a blind spot the exact size
# of the bug it used to describe.
# host-independence: EXCLUDE — probes a container, so a host without the image gets NOT_CHECKED rather than the same verdict

run_tolerating_uncheckable "STA engines agree" "$PLUGIN" python3 programs/sta_engine_parity_check.py

# vibe-ic#559 — 33 of the P0 umbrella's 243 registered gates reject the argv it
# builds, so they return no verdict, and `_p0_buckets_from_records` folds
# NOT_INVOCABLE in with SKIP while the umbrella's pass flag is `len(fails) == 0`
# — P0 reports PASS over 33 checks that never ran. Fixing that is blocked on
# triaging the 33 (only 8 carry a recorded decision). This stops a 34th arriving
# while that happens: the predicate is `measured ⊆ recorded`, so a fix passes and
# a new silent gate does not. ~4s.
run "P0 gate invocability drift"        "$PLUGIN" python3 programs/p0_gate_invocability_drift_check.py

run "tracked JSON/YAML parses"          "$ROOT" python3 "$PG/tracked_json_yaml_parses_check.py" --root "$ROOT"

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

# vibe-ic#459 follow-up — the PROGRAMS index, alongside the evidence index above.
# MAIN WENT RED TWICE (v1.7.40, v1.7.41) because a new program landed and
# INDEX.md was never regenerated. The freshness test EXISTS and is correct; it
# lives in the plugin pytest suite, which this lane does not run, so a green
# hygiene run was true and carried no information about it. The generator
# already ships `--check` (exit 1 if the index would change) — the repair was
# never missing, only unwired. One `git ls-files` + one walk; measured
# discriminating: injecting a throwaway program makes it rc 1, removing it rc 0.
run "programs index fresh"              "$ROOT" python3 "$ROOT/tools/gen_programs_index.py" --check

# vibe-ic#542 — a test whose own subprocess timeout is at or above the pytest
# harness bound cannot fail as a TEST. `--timeout-method=thread` takes the
# whole SESSION down instead: `--maxfail` stops applying, no per-test
# diagnostic is printed, and every other file in the subset loses its verdict.
# That is how v1.7.92 went red — the session died at file 18 of 53 and the
# twelve after it were never run. `run`, not `run_tolerating_uncheckable`: this
# check reads only the checkout (no network, no container, no clean tree), so
# its rc 2 means the workflow or the test tree could not be found, which is a
# broken repo rather than an environment a developer can be forgiven for — and
# a gate that cannot locate the bound it judges against must not read as clean.
# Measured at wiring time: 230 bounds above the ceiling in 2010 files, one of
# them a `_SUBPROCESS_TIMEOUT_S = 900` module constant that the report's own
# grep could not see.
run "inner timeouts fit the harness"    "$ROOT" python3 "$PG/ci_harness_timeout_ceiling_check.py" "$ROOT"

# --- plugin scoped ---------------------------------------------------------
# Each of these was, until this file existed, run by NOTHING but its own unit
# test — it had never judged the tree it was written to judge. They are wired
# here because they are repo-hygiene: they need no design, no PDK and no run
# directory, only the plugin source itself.
# A PASS must say how much it looked at (vibe-ic#447). Runs every gate above
# against a scratch EMPTY tree and requires that a PASS there DISCLOSE it
# examined nothing. Placed LAST so it probes the full list; ~40s.
run "gates disclose their denominator" "$ROOT" python3 "$PG/gate_discloses_denominator_check.py" "$ROOT"

# vibe-ic#528 — the OTHER half of the disclosure question, and the reason both
# are wired: the check above asks whether a HUMAN READER can see that a gate
# examined nothing, judged from output text. This one asks whether the MACHINE
# that assigns the verdict tier can, judged from the exit code and the one
# stdout token `flow_compliance_check._stdout_signals_vacuous` matches. The
# first passing does not imply the second — `otp_image_nonzero_check` prints a
# perfectly clear "[SKIP] ... no L11/L4 OTP layout declares payload-class
# regions" and is invisible to the consumer. Static (it enumerates every
# module in programs/ and never invokes one), so its denominator is the file
# list rather than the set of gates a probe happened to be able to drive —
# which is what #515's and #521's behavioural sweeps could not reach. ~4s.
run "gate skips reach the vacuous tier" "$ROOT" python3 "$PG/gate_skip_routing_check.py" "$PLUGIN"


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

# vibe-ic#510 — a landed gate rule changes what the plugin certifies FROM NOW
# ON and does nothing to the records already published. v1.7.73 landed #502
# (an SI sign-off that re-derived zero coupling folds is VACUOUS_PASS, not
# PASS) and two of the seven tracked si_mcf_sta_check records still said PASS
# beside coupling_pairs: 0 — one of them the artefact #502 was filed about.
# Nothing measured the gap. Re-adjudicates every published record against its
# own gate's CURRENT rules, decided FROM THE RECORD (the inputs are gone —
# #506), and REPORTS: correcting a published record is the benchmark-agent's
# commit under NO-MIX, so the two are a recorded debt here and anything NEW —
# or a gate whose rules changed without re-review — fails.
run "published records not superseded" "$ROOT" python3 "$PG/published_record_staleness_check.py"

# Writes the coverage record (when asked), prints the roll-up WITH its own
# denominator, and exits 0 / 1 / 2. See `_gate_dispatch.sh`.
gate_dispatch_finish
