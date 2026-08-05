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
# vibe-ic#621 — the JSON manifests were guarded and the PROSE was not: the three
# READMEs a reader meets first advertised v1.5.12 / v1.4.72 / v1.4.61 against a
# shipped 1.9.36. Same drift `marketplace_version_sync_check` exists for, one
# file type over. Narrow by construction — only the forms that assert THIS
# plugin's version, so the MCP-EDA badge and the EDA image tag are untouched.
run "plugin version stated in prose" "$ROOT" python3 "$PG/plugin_version_prose_sync_check.py" "$ROOT"
# vibe-ic#585 — `docker exec ... timeout=N` bounds the local CLIENT; the tool
# inside the container keeps running as an orphan. The checker that finds those
# call sites shipped with nothing but its own test running it, which
# `checker_execution_wiring_audit` reports as zero coverage of real inputs — a
# checker cited as a fix that never sees a production file. Wired here, over the
# whole shipped plugin, which is the input it is about.
#
# NOT `--strict`: 54 findings stand today and failing a pre-existing pile on day
# one makes a gate people route around. It runs ADVISORY (rc 0) so the count is
# published every run and cannot drift unseen.
run "container exec deadlines"  "$ROOT" python3 "$PG/container_exec_deadline_check.py" "$PLUGIN"
# vibe-ic#552 — a warning our EDA fork substitutes for an upstream abort must
# still be visible to the gate that needs it. Every downgrade moves a
# condition out of the error-matching sets BY CONSTRUCTION, so the
# registry has to be checked rather than trusted.
run "fork downgrades stay visible" "$PLUGIN" python3 programs/fork_downgrade_visibility_check.py .
# A diagnostic emitted at severity=ERROR must be consumed by SOME verdict. The
# sibling of `fork_downgrade_visibility_check` one step further along: that one
# keeps a condition visible to the gate that needs it, this one proves a gate
# needs it at all. Measured when first wired: 443 severity=ERROR emissions,
# 380 distinct tokens, 1 inert.
#
# BLOCKING, with the one standing finding named rather than hidden. The
# precedent two gates up runs ADVISORY because 54 findings stood on day one and
# failing a pre-existing pile makes a gate people route around; that reasoning
# does not transfer to a pile of one. Naming it keeps the gate blocking for
# anything NEW from the first run, which is the property worth having.
#
# MACRO_STAGED_UNUSABLE: emitted by the synth front-end when a staged vendor
# macro is instantiated under no define-world, so synthesis substitutes the
# behavioural arm — its own reason says "a BEHAVIOURAL model of a cell that was
# staged as a real macro". The emitter is a library with no exit status and no
# runner branches on the verdict. Removing this entry is the fix; it is left
# out of THIS change because wiring a verdict to it alters flow outcomes and
# belongs in its own reviewable diff, not smuggled into the gate that found it.
run "severity=ERROR is consumed" "$PLUGIN" python3 programs/error_diagnostic_consumed_check.py . \
    --allow MACRO_STAGED_UNUSABLE

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

# vibe-ic#559 — two PLUGIN-scoped self-checks that were registered in the
# per-project P0 umbrella, which cannot invoke them: they take no project, so
# they returned NOT_INVOCABLE on all 107 corpus projects and therefore ran
# nowhere at all. Driving a plugin-wide check per project would have produced
# 107 identical answers; this is where one answer belongs.
#
# Both were checked for an honest denominator before being wired, because a
# gate that cannot distinguish a clean scan from a scan of nothing is worse
# here than absent — it would report green hardest when pointed somewhere
# wrong. `openroad_tcl_deprecation_check` now states `examined N file(s)` and
# exits 1 on zero (v1.8.80); `practical_notes_specificity_check` already
# refused an empty path set with rc=2.
#
# A third, `phase1_gate_contract_check`, is deliberately NOT here. Its
# docstring binds every Phase 1 gate under programs/, its DEFAULT_GATES names
# 7 from v0.74, and stage1 of the flow now references 29 — running the contract
# over all 29 gives 22 errors. Wiring it at the current scope buys a green over
# 7 of 29; widening it reddens every landing. See `_NOT_A_PROJECT_GATE` in
# flow_compliance_check.py for the measurement.
run "openroad TCL deprecations"     "$PLUGIN" python3 programs/openroad_tcl_deprecation_check.py
run "practical notes specificity"   "$PLUGIN" python3 programs/practical_notes_specificity_check.py

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
# vibe-ic#794 — thirteen ORGANIC backlog items were WRITTEN into
# `community/backlogs/` between 2026-06-14 and 2026-07-12 and never committed,
# beside twenty-five siblings that were. Both populations look identical in
# `ls`, so a reader could not tell a live backlog item from a dropped one, and
# a fresh clone silently received only the tracked half. The write path
# (`skills/community-backlog-submit` Step 3) creates the file, Step 4
# sanitizes it and Step 5 optionally opens an issue — NOTHING commits it, and
# until now nothing asked. Committing from the write path is not available
# (the filing agent is often a benchmark-agent, which `agent_checkin_scope_
# guard` bars from this zone) and failing at write time is wrong (the file is
# legitimately untracked the moment it is written), so the repair is the third
# option: OBSERVED by a gate that runs on every landing.
#
# `--audit tracked` and NOT the default content audit: measured 2026-08-04, the
# CONTENT scan over the same 25 files is rc 1 with 18 pre-existing ERRORs, and
# failing a legacy pile on day one is how a gate becomes one people route
# around (the same reasoning as "container exec deadlines" above). The
# trackedness lane is green today, so it is BLOCKING from its first run.
#
# ONE line, no `\` continuation: `gate_discloses_denominator_check.parse_gates`
# is line-anchored, so a wrapped argv would reach its probe with the tail
# silently missing — the gate it drove would not be the gate that runs here.
run "backlog items are tracked" "$ROOT" python3 "$PG/backlog_sanitize_check.py" --dir "$ROOT/vibe-ic-marketplace/community/backlogs" --audit tracked

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

# vibe-ic#559 — 36 of the P0 umbrella's 246 registered gates reject the argv it
# builds, so they return no verdict, and `_p0_buckets_from_records` folds
# NOT_INVOCABLE in with SKIP while the umbrella's pass flag is `len(fails) == 0`
# — P0 reports PASS over 36 checks that never ran, i.e. its true coverage is 210
# of 246. Fixing that is blocked on triaging the 36, each of which now carries a
# recorded decision. This stops a 37th arriving while that happens: the predicate
# is `measured ⊆ recorded`, so a fix passes and a new silent gate does not.
#
# The counts above were 33/243 and then 32/246 until round 7, and the second pair
# was WRONG rather than stale: this program re-typed `_gate_invocation`'s Rule A
# and never had Rule B, so four gates that hand-roll their required-argument
# check were invisible to it while the umbrella counted them. A count written
# into prose stops tracking what it counts; a count re-typed into a second
# predicate stops tracking it AND looks authoritative. ~4s.
run "P0 gate invocability drift"        "$PLUGIN" python3 programs/p0_gate_invocability_drift_check.py

run "tracked JSON/YAML parses"          "$ROOT" python3 "$PG/tracked_json_yaml_parses_check.py" --root "$ROOT"

# vibe-ic#361 — an evidence document that cites `foo.log` and ships no foo.log
# is unverifiable, and the failure is silent.
run "evidence citation resolves"        "$ROOT" python3 "$PG/evidence_citation_resolves_check.py"
# The record the gate above now TRUSTS for its disclosures. It may only say
# a citation resolves when it does — verified against the cell as committed,
# because the publisher computes the decision against the tree it had and
# nothing re-derived it afterwards (8 false RESOLVES rows, measured).
run "citation routing is true"          "$ROOT" python3 "$PG/citation_routing_is_true_check.py" --root "$ROOT"

# vibe-ic#381 — a checker only its own unit test ever runs has zero coverage of
# real inputs: the fixture proves the logic, never the artefacts.
run "checker execution wiring"          "$ROOT" python3 "$PG/checker_execution_wiring_audit.py"
# vibe-ic#693 — and the question NOTHING was asking: is a gate CONSULTED AT ALL?
# `gate_skip_routing_check` reports "98 unrouted skip path(s) in 53 gate(s);
# published inventory holds 98 in 53" — balanced, over a 53-gate population that
# contains none of the 35 gates no automatic verdict invokes. Its scope is its
# coverage. A gate nothing runs produces no verdict, and the tree looks the same
# either way.
run "gates are wired to something"      "$ROOT" python3 "$PG/gate_is_wired_check.py"
# vibe-ic#712 — a prose extractor that reads a value out of a sentence without
# asking whether the sentence DENIES it publishes a denied value as a
# declaration. Twice in one day, in two fields, and each fix grew its OWN copy
# of the negation vocabulary — which is how the second field learned it only
# after already publishing a wrong value. One vocabulary now (`_prose_polarity`),
# and this finds the next extractor that does not consult it.
run "prose extractors read polarity"    "$ROOT" python3 "$PG/prose_polarity_consulted_check.py"
# vibe-ic#731 — `// This module controls ...` matches `module\s+(\w+)` and mints
# a module that does not exist: 24 of them, measured, in #729. It is a DATAFLOW
# question, not a presence one — the defect function CALLS the stripper, for a
# SIBLING variable, and scans the raw one. Three detectors were built and
# retracted on that basis; this one carries the known instance as a test.
run "declaration scans strip comments"  "$ROOT" python3 "$PG/hdl_declaration_scan_strips_comments_check.py"
# ORGANIC #686 — a macro OBS is the vendor's statement of where the integrator
# may not put metal. It is not in the PDK deck, so sign-off DRC cannot see a
# crossing; and the wire is on the right net, so a connectivity audit cannot
# either. Runs over every published cell that has both a routed DEF and a
# macro LEF; rc=2 (nothing to look at) is tolerated, rc=1 is not.
#
# THE CELL LIST IS THE PUBLISHED ONE, NOT WHAT IS ON THIS DISK (2026-08-04).
# It used to be `for _cell in "$ROOT"/benchmark-data/ic/*/*/` with an `[ -f
# routed.def ]` filter, i.e. a glob over the working directory. A checkout that
# has been used carries run leftovers, and each leftover that happens to hold a
# routed DEF adds THREE gate invocations. Measured on the main checkout: 1078
# leftovers took this script's declared-gate count from 68 to 169 and produced
# 13 FAILs that were about the leftovers and not about the commit — reproduced
# identically on two unrelated PRs, which is how the tree rather than the PRs
# was identified, after hours of looking at the wrong thing.
#
# `git ls-files` makes the denominator a property of the COMMIT: the same 68
# gates in a working checkout, a fresh clone and a scratch worktree. Same
# `_published_tree` reasoning as the corpus gate at line 408 ("46 vs 17 is
# exactly the host-dependence `_published_tree` exists to remove from a
# baseline"), applied to the loop that decides how many gates there ARE.
while IFS= read -r _def; do
  [ -n "$_def" ] || continue
  _cell="$ROOT/${_def%/phase3/stage3/pnr/routed.def}"
  run_tolerating_uncheckable "macro OBS not crossed ($(basename "$(dirname "$_cell")"))" \
    "$PLUGIN" python3 programs/macro_obs_geometry_intersect_check.py "$_cell"
  # vibe-ic#693 — one of the 35 gates nothing invoked. A "0 DRC violations"
  # certificate over an empty layout is the strongest form of an absence
  # rendering as a pass, and the gate written for it was reachable only if an
  # agent read a skill and remembered to run it. MEASURED on the published
  # cells: it parses real geometry (8290 shapes, 35 violations) — a live
  # verdict, not a shape that can only ever say "nothing to look at".
  run_tolerating_uncheckable "DRC PASS is not vacuous ($(basename "$(dirname "$_cell")"))" \
    "$ROOT" python3 "$PG/drc_vacuous_pass_check.py" "$_cell"
  # Another of the 35. Its subject is an inner FAIL that never reaches the outer
  # verdict, and nothing ran it. It also had the defect: "nothing to examine"
  # exited 0 printing VACUOUS_PASS, one branch above a test in its own file
  # stating that "I could not look" must never share an exit code with "I looked
  # and it was clean". MEASURED on the published cells: 67-68 reports examined
  # each, so this is a live verdict over a real denominator.
  run_tolerating_uncheckable "inner FAILs reach the verdict ($(basename "$(dirname "$_cell")"))" \
    "$ROOT" python3 "$PG/step_internal_fail_bubble_up_check.py" "$_cell"
# `|| true` on the producer: `git ls-files` over a path that matches nothing is
# not an error here, and under `pipefail` an empty result must not abort a
# script whose remaining 60 gates have nothing to do with this corpus.
done < <(git -C "$ROOT" ls-files -- \
  'benchmark-data/ic/*/*/phase3/stage3/pnr/routed.def' 2>/dev/null || true)
# The baseline the gate above maintains records WHY each entry is still there.
# 24 of 31 notes said the checker "skips without its input" about an input a
# real run always has — a reason whose premise is false, standing in for the
# real one (nothing calls it). vibe-ic#659.
run "triage notes state a true reason"  "$ROOT" python3 "$PG/triage_note_answers_the_question_check.py"

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

# vibe-ic#768 — a tech LEF that declares a routing layer's minimum width and,
# in the same file, gives its own vias a NARROWER patch on that layer. Every
# place a wire ENDS on such a via is a sign-off min-width violation, and the
# router's in-loop DRC reports 0 for it. MEASURED on the image this repo pins:
# 192 across 19 tech LEFs and 2 of the 3 PDK families it ships, in both the
# `VIA ... RECT` and the `VIARULE ... GENERATE ... ENCLOSURE` form.
#
# `--advisory`, deliberately, and NOT because the finding is soft. It is 192
# real ones. The fix lives in the EDA fork's PDK layer, in another repo — this
# repo cannot land it, so a blocking gate here would leave main red on someone
# else's change and get switched off, which is the failure this repo has
# already measured with `container_exec_deadline_check`. `--advisory` lowers
# the exit code and nothing else: every finding is still printed, and the line
# under them says the verdict is FAIL. There is no baseline and no waiver file,
# so the only thing that can make this print zero is the PDK being fixed.
#
# `run_tolerating_uncheckable`: reading the PDKs needs the image, and rc 2 —
# "I could not look" — must never share an exit code with "I looked and it was
# clean". Same shape as the asset half of the gate above.
#
# ONE LINE, no `\` continuation. Two OTHER gates PARSE this file — the
# denominator probe and the host-independence probe — with a single-line
# `^\s*run(?:_\w+)?\s+"label"\s+"$ROOT"\s+(.+)$`, so a continuation hands them
# a command consisting of the backslash alone. Both reported GATE_UNRUNNABLE
# (`No such file or directory: '\'`), which is not a failure of this gate but
# of the script's readability by its own readers.
run_tolerating_uncheckable "PDK via patch vs layer min width" "$ROOT" python3 "$PG/pdk_via_patch_meets_layer_min_width_check.py" --from-image --advisory

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

# vibe-ic#693 — `flow_compliance_check` classifies a project from each step's
# `pass.flag` and never walks the per-step report JSON, so a step can ship
# pass.flag while one of its own sub-reports declares verdict=FAIL. This walks
# them and requires each FAIL/MISSING to be ACKNOWLEDGED — by a waivers.json
# entry naming the report, or by an orchestrator/audit record naming it.
#
# NON-BLOCKING BY RATCHET, not by being toothless. Measured over the 46 run
# trees on a working checkout, `--strict` reddens 16 of them on 33 findings the
# gate did not create; landing that blocking is an outage. The corpus mode
# instead sweeps the PUBLISHED (git-tracked) trees — 17 here, 5 of which ship a
# reports/ tree — and ratchets the recorded 7 findings across 4 runs
# (sha256/clean_run_v1422_20260715, sha256/clean_run_v1427_20260715,
# u_hawaii_adc/clean_run_v1422_20260715, u_hawaii_adc/clean_run_v1427_20260715).
# The count may shrink freely; a NEW unacknowledged step-internal FAIL is red.
# Published, not on-disk, on purpose: 46 vs 17 is exactly the host-dependence
# `_published_tree` exists to remove from a baseline.
run "step FAIL bubbles up"              "$ROOT" python3 "$PG/step_internal_fail_bubble_up_check.py" --corpus "$ROOT/benchmark-data/ic"

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

# vibe-ic#564 — the SIBLING property. The gate above requires a PASS to say how
# much it looked at; this one requires a gate that looked at NOTHING to refuse.
# Both are needed: the P0 umbrella reads exit codes, so a gate that discloses
# `0` in prose and returns `0` in rc is a silent pass, and the disclosure gate
# passes it correctly.
run "a zero denominator refuses" "$ROOT" python3 "$PG/gate_zero_denominator_refuses_check.py"

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
# 2026-08-04 — `gate_cli_mutation_probe` makes a gate unable to fail and then
# restores it in a `finally`. A `finally` does not run on SIGKILL, and twice in
# one parallel-agent session a killed run left `hold_area_budget_check.py` and
# `hold_corner_coverage_check.py` carrying an injected early return beside a
# `.probe-orig` sidecar. An injected early return exits 0, so the flow read
# those gates as PASS — the failure is silent, green, and affects every step the
# gate guards. Both were found by hand.
#
# The probe now mutates only a disposable copy, so nothing can create this state
# afresh. A checkout can still be IN it (an older build, a restored backup, a
# hand-edit), and until now nothing looked. ~2s over 3396 modules.
#
# host-independence: EXCLUDE — its subject is a fact about the CHECKOUT (what an interrupted probe left in it), which a fresh worktree by construction does not carry
run "no gate is left neutered"          "$PLUGIN" python3 programs/neutered_gate_tree_check.py "$PLUGIN"
run "argparse help format"              "$PLUGIN" python3 programs/argparse_help_format_check.py
run "dead plugin path"                  "$PLUGIN" python3 programs/dead_plugin_path_check.py
run "ic_expert_db health"               "$PLUGIN" python3 programs/ic_expert_db_health_audit.py
run "verdict token propagation"         "$PLUGIN" python3 programs/verdict_token_propagation_check.py
run "signoff gate self-skip"            "$PLUGIN" python3 programs/signoff_gate_self_skip_consistency_check.py
run "waveform artifact hygiene"         "$PLUGIN" python3 programs/waveform_artifact_hygiene_check.py

# ORGANIC #720 / #693 — the ONE gate in the repo-process family that really was
# wired to nothing. It was invisible to `checker_execution_wiring_audit` (wired
# at line 247) purely by FILENAME: that gate's population was `*_check.py` +
# `*_audit.py`, and `_guard.py` is neither, so it reported "[PASS] no NEW
# test-only checker" over a population that structurally could not contain it.
# The population is widened in the same change.
#
# ONLY THE COMMIT-DETERMINED HALF IS WIRED HERE, and the flag is load-bearing.
# Every gate in this script is re-run by `gate_host_independence_check` above
# against a fresh worktree at the same commit and must produce the same verdict
# line and rc. The guard's untracked-scratch scan is a fact about a CHECKOUT,
# so wiring it here would make this script's own host-independence probe go red
# the moment any agent left a scratch file in the tree — measured, with the
# probe output in the PR. That half runs report-only from `gatekeeper-land.sh`.
#
# BLAST RADIUS, measured 2026-08-03 over 250 checkouts of this repo on one
# host: 0 red. `rule_present` true in 250/250, `subdir_registry_ignored` false
# in 250/250 (with the `--no-index` fix that makes that assertion capable of
# firing at all), no tracked root `_*.js` anywhere.
run "gitignore scratch guard"           "$ROOT" python3 "$PG/gitignore_scratch_guard.py" --root "$ROOT"
# vibe-ic#693 (from #313 §6) — a remedy that silently declines is
# indistinguishable from a remedy that was never needed. Flags a remedy-named
# call assigned to a variable, guarded by `if <var>:` with no else and no
# disclosure on the decline path. It audits SOURCE, not runs, so it belongs
# beside the other plugin-scoped source gates.
#
# `--ratchet`, deliberately, and not `--strict`: measured at this commit,
# 1091 files scanned and 15 silent declines across 6 files
# (phase1_doc_one_shot_runner x6, cvdp_complete_extract x3, lec_run x2,
# phase3_one_shot_runner x2, cvdp_context_interface_recover x1,
# design_one_shot_runner x1). `--strict` reddens main today over a backlog this
# change does not triage; a bare run returns 0 unconditionally, which would wire
# a gate that cannot fail. The ratchet keeps the 15 visible, blesses none of
# them, and makes a SIXTEENTH red. `--strict` becomes correct once they are
# triaged.
run "silent remedy decline"             "$PLUGIN" python3 programs/silent_decline_audit.py programs --ratchet

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

# The flow-gate dashboard publishes a per-step dimension asking "can this step
# actually fail", and NOTHING recomputes it — the page's own generator says so in
# its docstring and carries the distribution forward. Recomputed from the flow
# yaml, EIGHT of 63 steps have no criterion that can fail on content: two have no
# blocking criterion at all (P0, 14) and six can fail only on a declared file
# being ABSENT (1, 12, 18, 27, 32, 35), never on it holding the wrong answer.
#
# Step 32 is the worked example: a run recorded `eco_needed=true,
# changes_count=0, re_verified=false` — an ECO raised, never applied, never
# re-verified — and the step passed because a file existed and its program
# criterion is optional.
#
# The eight are a baseline that MAY ONLY SHRINK, so this is blocking for anything
# NEW from its first run, and it fires again if a baseline step gains a real gate
# and the record is not shrunk to match.
run "a step whose gate cannot fail" "$PLUGIN" python3 programs/flow_step_can_fail_check.py

# The flow-gate dashboard's DEPENDENCY dimension, recomputed instead of assessed.
# Fully decidable from the flow yaml: every blocks_on target must exist, the
# graph must be acyclic, and a step with no dependencies must be a declared entry
# point. On its first run against the real tree it caught a baseline taken from a
# checkout 700 commits behind — which is the argument for recomputing.

# The flow-gate grid: recompute every dimension decidable from the flow source,
# and name the ones that are not. 315 of 504 cells are now recomputed; the other
# 189 are reported as NOT DERIVABLE with the reason, which is what stops the page
# claiming they are live. D3 in particular is a fact about a RUN — the page's
# framing is wrong for it, not merely stale.
run "flow-gate grid" "$PLUGIN" python3 programs/flow_gate_grid.py

run "flow dependency graph" "$PLUGIN" python3 programs/flow_dependency_graph_check.py

# Writes the coverage record (when asked), prints the roll-up WITH its own
# denominator, and exits 0 / 1 / 2. See `_gate_dispatch.sh`.
gate_dispatch_finish
