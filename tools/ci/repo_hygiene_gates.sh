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
RUNTIME_ROOT="$(cd "$HERE/../.." && pwd)"
ROOT="${VIBEIC_SUBJECT_ROOT:-$RUNTIME_ROOT}"
case "$ROOT" in /*) ;; *)
  echo "repo_hygiene_gates: VIBEIC_SUBJECT_ROOT must be absolute" >&2
  exit 2 ;;
esac
[ -d "$ROOT" ] || {
  echo "repo_hygiene_gates: subject root is not a directory: $ROOT" >&2
  exit 2
}
PLUGIN="$ROOT/vibe-ic-marketplace/plugins/vibe-ic"
PG="$RUNTIME_ROOT/vibe-ic-marketplace/plugins/vibe-ic/programs"
cd "$ROOT"

# One machine record per completed gate.  When the caller supplies a path it
# remains available as a progress/attestation channel; otherwise this run owns
# a private temporary file and embeds its records into --summary-json before
# removing it.
_GATE_ATTESTATION_OWNED=0
if [ -z "${GATE_DISPATCH_ATTESTATION_FILE:-}" ]; then
  GATE_DISPATCH_ATTESTATION_FILE="$(mktemp -t repo-hygiene-attest.XXXXXX)"
  _GATE_ATTESTATION_OWNED=1
fi
GATE_DISPATCH_ATTESTATION_HELPER="$PG/gate_process_attestation.py"
export GATE_DISPATCH_ATTESTATION_FILE GATE_DISPATCH_ATTESTATION_HELPER
_gate_attestation_cleanup() {
  # `.lock` is the flock target the concurrent workers serialise their appends on
  # (see `_gate_attest_locked`). It is swept with the file it guards.
  [ "$_GATE_ATTESTATION_OWNED" -eq 0 ] \
    || rm -f -- "$GATE_DISPATCH_ATTESTATION_FILE" \
                "$GATE_DISPATCH_ATTESTATION_FILE.lock"
}
trap _gate_attestation_cleanup EXIT

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
# vibe-ic#1241 — this checker was reachable only from its own test. It validates
# a RECORD rather than a design, and the corpus carries none yet (#1121's first
# head-to-head has not run), so it is wired through the uncheckable channel: it
# exits 2 and says so, rather than printing PASS over an empty population.
#
# THE CORPUS MOVED AND THIS LINE DID NOT FOLLOW IT. `benchmark-data` went to its
# own repository in v1.10.56, so `$ROOT/benchmark-data` has not existed here
# since — and `Path.glob` yields nothing for a missing directory, so this gate
# printed `0 head-to-head record(s) found` and exited 2 exactly as a clean empty
# corpus would. MEASURED: the two were byte-identical, which is a denominator
# asserted over a population nobody searched.
#
# The checker now resolves its corpus through `_corpus_location` — the same seam
# `L-doc field producer` and the two `tracked-symlink` gates use for the same
# v1.10.56 breakage (vibe-ic#1710) — so $VIBE_IC_BENCHMARK_DATA now actually
# aims this gate at a clone, and a pointer that is SET AND WRONG is UNDETERMINED
# rather than laundered into an empty corpus.
#
# DELIBERATELY *NOT* `--corpus-may-be-absent`. That flag's outcome is rc 0
# NO_CORPUS, and rc 0 here would be this gate printing a PASS over a population
# it never opened — the one thing #1241 wired it through this channel to avoid.
# Absent stays rc 2, which is what the declaration below already promises.
uncheckable_until 2026-11-30 "validates a RECORD rather than a design, and the corpus carries none yet (#1121's first head-to-head has not run), so rc 2 says the population is empty instead of printing PASS over it. Goes live by itself on the first head-to-head committed"
run_tolerating_uncheckable "PPA head-to-head records" "$ROOT" \
    python3 "$PG/ppa_head_to_head_check.py" --corpus "$ROOT/benchmark-data"

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
# Its SIBLING, and it had shipped with exactly the defect the comment above
# describes. `container_login_banner_parse_check` finds the OTHER half of the
# same hazard — a `docker exec ... bash -lc` whose captured stdout is then read
# as a value, when a login shell prepends two `[INFO]` lines to it — and nothing
# but its own unit test ever ran it, so `checker_execution_wiring_audit` counted
# it as zero coverage of real inputs. Its population is this plugin's own
# `programs/` tree, which is a repo-wide invariant needing no PR context: the
# thing this script is for.
#
# BLOCKING, and it can afford to be. Measured on 221689eb: rc 0 in 4.6s over 25
# login-shell callers and zero banner-fragile consumers, so unlike the gate
# above there is no pre-existing pile to bless and no reason to run advisory.
#
# `run_tolerating_uncheckable` because the checker's own rc 2 does not mean
# clean: it means NO caller passes a login shell any more, i.e. either the
# hazard is gone or the detector stopped matching the call sites, and the
# checker says in its own words that neither is a PASS. NOT_CHECKED carries that
# to the roll-up instead of folding "I could not look" into "I looked".
uncheckable_until 2026-11-30 "rc 2 here is NOT a missing prerequisite: it means NO caller passes a login shell any more, i.e. either the hazard is gone or the detector stopped matching the call sites, and the checker says neither is a PASS"
run_tolerating_uncheckable "container login-banner parses" "$ROOT" python3 "$PG/container_login_banner_parse_check.py"
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

# A disposition in the P0 registers can assert a home ("driven at the final
# acceptance gate") in the same present tense the one true claim above uses
# ("READY -- wired into tools/ci/repo_hygiene_gates.sh"), and nothing could tell
# them apart. Re-derived at b85d68ac (the tree carrying #804): over the 36 gates
# the invocability ratchet pins UNION every gate the registers write a
# disposition about, 3 claim a home that is real, 19 claim none, and 14 claim
# one that no flow step, runner, CI script or workflow backs.
#
# It is a RATCHET, not a wiring: it does not fail the 14 -- turning them red
# today would block every landing on prose, and each needs its own engineering.
# It stops a 15th arriving unnoticed and prints the residual on every run.
#
# Wired HERE and not in the P0 umbrella for the same reason as the two above:
# it takes no project, so the per-project umbrella cannot invoke it and it would
# run nowhere at all -- which is the exact condition it exists to detect.
run "P0 disposition backing"        "$ROOT" python3 "$PG/p0_disposition_backing_check.py" --repo-root "$ROOT"

# vibe-ic#215/#566 — the image-version gate is BLOCKING, and what it blocks on
# is now exactly the half this repo owns: every live pointer equals the anchor,
# and the anchor has not been rolled below what this repo already committed.
# Both are read from the tree and from git, so the verdict has a fixed point.
#
# vibe-ic#927 — it used to ALSO block on `--require-remote`, comparing the
# anchor against `:latest` and against the newest tag on ghcr. Those are names
# another org re-points on its own cadence: the gate went red when the fork
# published (0.2.75 -> .81 -> .82 -> .83 in about twelve hours), green again
# when they were quiet, and could not tell "we are behind" from "the registry
# moved under us". Bumping the anchor each time closed the instance and left
# the mechanism. The comparison still HAPPENS — it moved to the report on the
# next line — it just no longer decides whether anyone can land.
#
# vibe-ic#539, now RESOLVED as a side effect: this gate was the one declared
# out of the host-independence comparison, because that probe runs every gate
# TWICE and requires the verdicts to match, and a network round-trip can differ
# between invocations for a reason that is not in the commit (v1.7.92 went RED
# then GREEN on an identical commit). --check makes no network call at all now,
# so the EXCLUDE directive is GONE and the gate is probed like every other one.
run "image-version pins are internally consistent" "$ROOT" python3 "$ROOT/tools/vibeic-eda/sync_image_version.py" --check

# The other half of #927, deliberately NOT a verdict. "Has upstream published
# something newer?" is real and worth knowing, so it is asked on every run and
# the answer is RECORDED with the instant it was taken — a reading with no
# timestamp cannot be told from a current one by a later reader. It exits 0 when
# it got an answer (agreeing or not) and 2 when the registry did not respond, so
# it can never be the reason a landing fails. Adopting a newer image is this
# repo's call, made deliberately with `sync_image_version.py --set X.Y.Z`, which
# is where the #354 "the tag must actually resolve" check now lives.
uncheckable_until 2027-02-28 "needs a REACHABLE ghcr registry: --report-upstream asks the registry what it has published, and rc 2 means it did not respond (an answer that disagrees is rc 0 by design -- this gate can never fail a landing)"
# host-independence: EXCLUDE — resolves a tag on a remote registry, so two invocations can differ for a reason that is not in the commit
run_tolerating_uncheckable "upstream image currency (report-only)" "$ROOT" python3 "$ROOT/tools/vibeic-eda/sync_image_version.py" --report-upstream --require-remote

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
uncheckable_until 2027-02-28 "needs an AUTHENTICATED gh + network: it lists the org's repos live, and rc 2 means the org could not be asked (a duplicate it CAN see is rc 1)"
# host-independence: EXCLUDE — reads live org state over the network, so two invocations can differ for a reason that is not in the commit
run_tolerating_uncheckable "no upstream forked twice" "$PLUGIN" python3 programs/org_duplicate_fork_check.py vibeic

# vibe-ic#1364 — a PR whose base belongs to a CLOSED-unmerged PR, or whose
# branch merely CARRIES that PR's commits, reports `mergeable=CLEAN`, because
# `mergeable` is computed against the PR's OWN base and not against `main`.
# Measured 2026-08-13 over 218 open / 760 closed (485 unmerged, 87 branches
# still live): EIGHT open PRs are affected, and the two detection passes are
# INDEPENDENT — four are visible only to the commit-graph pass and declare
# `base=main`; one is visible only to the declared-base pass. Two of the eight
# are named landing blockers.
#
# `--repo-dir "$ROOT"` is what enables the commit-graph pass. Without it the
# check prints `CARRIED pass NOT ESTABLISHED` and scopes its own PASS line to
# the half it did run, rather than printing a clean bill over a question it
# never asked.
#
# `--advisory`, deliberately, and NOT because the finding is soft. It is eight
# real ones. The remedy is per-PR and belongs to each PR's author — rebase the
# rejected parent out, or adopt it openly and have it reviewed — so no single
# commit can clear this, and a blocking gate would leave main red on eight
# other people's branches until they act, which is how a gate gets switched
# off. `--advisory` lowers the exit code and nothing else: every finding is
# still printed and the verdict line still says FAIL. There is no baseline and
# no waiver file, so the only thing that can make this print zero is the
# branches being fixed. It does NOT lower a REFUSAL.
#
# `run_tolerating_uncheckable`: it asks the GitHub API, and rc 2 — "I could not
# look" — must never share an exit code with "I looked and it was clean".
#
# `"$ROOT"` + `"$PG/..."`, not `"$PLUGIN"` + `programs/...`. Both shapes are in
# this file (46 and 25), and only the first is actually PROBED: the denominator
# probe runs every gate from a scratch tree, so a path relative to `$PLUGIN`
# cannot be opened from there and the gate is recorded `[NOT DRIVEN]`. Measured
# both ways here — the relative form was reported as NOT DRIVEN and the absolute
# form is probed — so the gate is now subject to the same denominator-disclosure
# rule as the rest. The checker takes `--repo-dir` explicitly and passes `--repo`
# to `gh`, so it reads nothing from its cwd and the change is behaviour-neutral.
#
# ONE LINE, no `\` continuation — the denominator probe and the host-independence
# probe both parse this file with a single-line `run(?:_\w+)?\s+"label"...` regex.
uncheckable_until 2027-02-28 "needs an AUTHENTICATED gh + network: it reads live queue state over the network, and rc 2 means the queue could not be asked at all (a base that genuinely does not reach main is rc 1)"
# host-independence: EXCLUDE — reads live queue state over the network, so two invocations can differ for a reason that is not in the commit
run_tolerating_uncheckable "PR bases reach main" "$ROOT" python3 "$PG/pr_base_reachability_check.py" --repo-dir "$ROOT" --advisory

# vibe-ic#306/#316 — the audit that measures which gates can actually stop a
# run was itself wired into nothing while exiting 1. Recorded debt does not
# fail; anything NEW does.
run "flow-gate enforcement audit"       "$ROOT" python3 "$PG/flow_gate_enforcement_audit.py"

# vibe-ic#923 — the flow declared stage membership TWICE (a per-stage roster
# `stages[].steps` and a per-step `stage:` field), nothing derived either from
# the other, and they had drifted apart for 12 of the 63 steps: 4 outright
# contradictions and 8 steps the roster had never been told about. The roster
# was deleted because no shipped program read it for membership. This gate is
# what makes a second declaration impossible rather than merely noisy, and it
# also refuses the degenerate repair of deleting the surviving one.
run "stage membership declared once"    "$ROOT" python3 "$PG/flow_stage_membership_single_declaration_check.py"

# vibe-ic#312 family — a checker that reads a field NO document populates sees
# an empty value, and an empty value is indistinguishable from a clean one.
# Measured five times in one campaign; three were "the producer never existed".
#
# `--corpus-may-be-absent` (vibe-ic#1710's treatment): the L-docs this gate
# counts producers over moved to `vibeic/benchmark-data` in v1.10.56, so the
# hardcoded `benchmark-data/ic` is gone from this repo and the gate refused
# (rc 2 -> FAIL) on every landing. THE FLAG DOES NOT SILENCE IT. It only says
# "this repo need not carry a corpus", turning nothing-anywhere into NO_CORPUS
# which STATES that 0 documents were examined; a $VIBE_IC_BENCHMARK_DATA that is
# set and broken is still UNDETERMINED, a corpus that IS supplied is still fully
# adjudicated, and a corpus present but holding no L-doc is UNDETERMINED rather
# than a comparison against zero.
run "L-doc field producer"              "$ROOT" python3 "$PG/l_doc_field_producer_check.py" --corpus-may-be-absent

# vibe-ic#371 — a tracked symlink recorded with an ABSOLUTE target resolves
# only on the machine that wrote it. 159 of 172 were in that state and it made
# the evidence-citation verdict differ between local and CI on the same commit.
#
# `--corpus-may-be-absent` (vibe-ic#1710's treatment): the published corpus
# moved to `vibeic/benchmark-data` in v1.10.56, so the hardcoded scan root is
# gone from this repo and the gate refused (rc 2 -> FAIL) on every landing.
# THE FLAG DOES NOT SILENCE IT. It only says "this repo need not carry a
# corpus", turning nothing-anywhere into NO_CORPUS which STATES that nothing
# was scanned; a $VIBE_IC_BENCHMARK_DATA that is set and broken is still
# UNDETERMINED, and a corpus that IS supplied is still fully adjudicated.
run "tracked-symlink portability"       "$ROOT" python3 "$PG/tracked_symlink_portability_check.py" --corpus-may-be-absent
# The defect the line above deliberately declines. Its subject is whether a
# pointer is relative and stays inside the repo; a target that exists nowhere
# is a missing FILE, which its own comment says is different — and for months
# the count was reported on every run with nothing failing on it (#555, #556).
run "tracked-symlink target present"    "$ROOT" python3 "$PG/tracked_symlink_target_present_check.py" --root "$ROOT" --corpus-may-be-absent
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
uncheckable_until 2027-02-28 "needs the vibeic-eda CONTAINER IMAGE on the host: it invokes both STA engines inside it, and rc 2 means neither could be started (an engine that answers and disagrees is rc 1)"
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
#
# `--corpus-may-be-absent` (vibe-ic#1710's treatment): the sign-off documents AND
# the debt register that describes them both left with the corpus in v1.10.56 —
# the baseline lives beside the data (`root.parent/`), so they moved together.
# The flag turns nothing-anywhere into NO_CORPUS, which STATES that 0 documents
# were enumerated; a pointer that is set and broken stays UNDETERMINED, a corpus
# that is present but NOT a git checkout stays UNDETERMINED (this gate reads the
# INDEX, and over a loose directory an untracked local artefact would satisfy a
# citation the published tree does not ship), and a supplied corpus is still
# fully adjudicated against the register that travelled with it.
run "evidence citation resolves"        "$ROOT" python3 "$PG/evidence_citation_resolves_check.py" --corpus-may-be-absent
# The record the gate above now TRUSTS for its disclosures. It may only say
# a citation resolves when it does — verified against the cell as committed,
# because the publisher computes the decision against the tree it had and
# nothing re-derived it afterwards (8 false RESOLVES rows, measured).
#
# `--corpus-may-be-absent`: this gate's SUBJECT left with the corpus. A
# CITATION_ROUTING.txt ships inside a published cell, and the four that existed
# were deleted by the same commits that moved the cells out, so there is nothing
# in this repo for it to read. The pointer ADDS the corpus rather than replacing
# this repo (a record that comes home is still judged), a pointer set and broken
# or aimed at a non-checkout stays UNDETERMINED, and a supplied corpus carrying a
# false RESOLVES row still FAILs.
run "citation routing is true"          "$ROOT" python3 "$PG/citation_routing_is_true_check.py" --root "$ROOT" --corpus-may-be-absent

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
# The same shape one layer down: a program that parses N sources into records
# and folds them with `dict.update` lets a source that says NOTHING about a key
# overwrite one that said something — and which one wins is decided by the order
# the files sorted in. Measured: six LEFs declared one macro, five with 61-65
# obstruction rectangles and one with none; `sorted()` put the empty one last,
# so it won, and a BLOCKING gate passed a layout with 28 real crossings.
# Renaming a file flipped the verdict. This finds the next one.
#
# KNOWN AND DECLARED: this exits 1 on `macro_obs_geometry_intersect_check.py`
# until the PR that fixes that ORIGINAL instance lands. It is a real defect, so
# the guard is right to fire; it is not an exception and there is no list to add
# it to. When that PR merges this goes green with nothing else changed.
run "per-source record merges"          "$ROOT" python3 "$PG/per_source_record_merge_check.py"
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
#
# AND THE DENOMINATOR IS NOW PRINTED (vibe-ic#957). The corpus this loop
# selects is ONE published cell — `git ls-files` over the glob below returns a
# single routed DEF — so three gates run, once, over one item. Every one of the
# three is honest about which cell it examined; the ROLL-UP that counted them
# among ~74 green gates was not, and a reader took from it that post-route
# geometry is checked across the published corpus. The count was true and the
# impression was false.
#
# The iteration therefore goes through `gate_dispatch_over`, which measures the
# expansion and states it — including at 1, and especially at 0, where the loop
# declares no gate at all and there is nothing else left to notice its absence.
# Nothing here types the number: a `for` that hand-quoted "1" would be the next
# hand-maintained fact to drift, and drift is what this file exists to prevent.
#
# WHAT THIS DELIBERATELY DOES NOT DO: it does not change the corpus and does
# not change which gates run. Whether more published cells should carry a
# `phase3/stage3/pnr/routed.def` is a PUBLISHING decision with a real
# repository-size cost, and that decision is not a side effect of making the
# roll-up honest.
_per_published_cell_gates() {
  local _def="$1" _cell
  # `routed_def_corpus.py` emits ABSOLUTE DEF paths -- its own docstring says
  # "one absolute DEF path per line" -- and the published corpus may sit
  # OUTSIDE this repository entirely, because $VIBE_IC_BENCHMARK_DATA names a
  # clone whose root is the published tree. So $ROOT is not this path's parent
  # and must not be prefixed to it.
  #
  # v1.10.69 replaced this loop's producer with that program. The one it
  # replaced was `git -C "$ROOT" ls-files`, whose output IS repo-relative, so
  # the prefix below was correct for it and was carried over unchanged. The
  # result was "$ROOT/$ABSOLUTE" -- a path that cannot exist. Every per-cell
  # gate then answered rc 2 "I could not look", and `run_tolerating_uncheckable`
  # absorbed all four under exemptions whose stated reason is FALSE ("this cell
  # ships no readable macro/OBS geometry", "no parseable layout", "no step
  # reports", "NO_BASELINE"). The corpus read as CHECKED while nothing in it was
  # ever opened -- the empty-population refusal above cannot see this, because
  # the population is 1, not 0.
  _cell="${_def%/phase3/stage3/pnr/routed.def}"
  uncheckable_until 2027-02-28 "per published cell: rc 2 when this cell ships no readable macro/OBS geometry, so the intersection has no population -- an intersection it CAN compute and finds is rc 1"
  run_tolerating_uncheckable "macro OBS not crossed ($(basename "$(dirname "$_cell")"))" \
    "$PLUGIN" python3 programs/macro_obs_geometry_intersect_check.py "$_cell"
  # vibe-ic#693 — one of the 35 gates nothing invoked. A "0 DRC violations"
  # certificate over an empty layout is the strongest form of an absence
  # rendering as a pass, and the gate written for it was reachable only if an
  # agent read a skill and remembered to run it. MEASURED on the published
  # cells: it parses real geometry (8290 shapes, 35 violations) — a live
  # verdict, not a shape that can only ever say "nothing to look at".
  uncheckable_until 2027-02-28 "per published cell: rc 2 when this cell ships no parseable layout to judge the DRC certificate against, which is the state the gate exists to refuse to call a PASS"
  run_tolerating_uncheckable "DRC PASS is not vacuous ($(basename "$(dirname "$_cell")"))" \
    "$ROOT" python3 "$PG/drc_vacuous_pass_check.py" "$_cell"
  # Another of the 35. Its subject is an inner FAIL that never reaches the outer
  # verdict, and nothing ran it. It also had the defect: "nothing to examine"
  # exited 0 printing VACUOUS_PASS, one branch above a test in its own file
  # stating that "I could not look" must never share an exit code with "I looked
  # and it was clean". MEASURED on the published cells: 67-68 reports examined
  # each, so this is a live verdict over a real denominator.
  uncheckable_until 2027-02-28 "per published cell: rc 2 when this cell ships no step reports to examine, which the gate refuses to score as clean rather than exiting 0 on an empty population"
  run_tolerating_uncheckable "inner FAILs reach the verdict ($(basename "$(dirname "$_cell")"))" \
    "$ROOT" python3 "$PG/step_internal_fail_bubble_up_check.py" "$_cell"
  # vibe-ic#1241 — this gate was run by NOTHING but its own test, which proves
  # the logic against a fixture the author wrote and never against an artefact.
  # Wired here rather than into a flow step because its argument IS a published
  # cell, so this loop is the one place the flow already hands it its subject.
  #
  # `run_tolerating_uncheckable` is not a softening: the gate's own documented
  # contract is rc 2 = NO_BASELINE, "no previous run; nothing compared", and on
  # this corpus that is EVERY cell — no design carries two cells of the same
  # PDK, so `find_previous` has nothing to compare against. rc 2 is therefore
  # the expected answer today and must be LOUD and non-fatal; rc 1, a genuinely
  # new diagnostic id, still fails the suite. The day a second same-PDK cell is
  # published the comparison path becomes live without this line changing.
  uncheckable_until 2027-02-28 "per published cell: the gate's own documented contract is rc 2 = NO_BASELINE, 'no previous run; nothing compared', and on this corpus that is EVERY cell — no design carries two cells of the same PDK, so find_previous has nothing to compare against. A genuinely new diagnostic id is still rc 1"
  run_tolerating_uncheckable "new tool diagnostic id ($(basename "$(dirname "$_cell")"))" \
    "$PLUGIN" python3 programs/tool_diagnostic_id_gate.py "$_cell"
}
# NO `|| true` ANY MORE, and that is a repair rather than an omission: it used
# to turn "git could not look" into an empty corpus, which is the vacuous pass
# this repo removes from gates one at a time. `gate_dispatch_over` keeps the
# producer's exit status and says so; an empty result is still not an error and
# still does not abort the ~70 gates that have nothing to do with this corpus.
GATE_DISPATCH_ATTEST_POPULATION=1 gate_dispatch_over \
  "published cells carrying a routed DEF" \
  _per_published_cell_gates \
  python3 "$HERE/routed_def_corpus.py" --repo "$ROOT"
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

# vibe-ic#1241 — this gate existed and NOTHING but its own unit test ran it. A
# checker exercised only by a fixture its author wrote is verified against the
# author's MODEL of the artefacts, never against the artefacts: it can be
# perfectly correct about a world that does not exist, while contributing a
# green square to every count we publish.
#
# It sits here because it is the same population as the NDA scan above — the
# TRACKED tree, read for what shipping it obliges us to carry.
#
# MEASURED on this branch before wiring, so CI does not learn about a finding
# by turning red: 17217 tracked file(s) under benchmark-data, 525 declaring an
# SPDX licence, 11 attribution record(s), rc=0 PASS.
run "vendored attribution retained"     "$ROOT" python3 "$PG/vendored_attribution_retained_check.py"

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
uncheckable_until 2027-02-28 "needs the vibeic-eda CONTAINER IMAGE on the host: --from-image reads the PDK layer tables out of it, and rc 2 means the PDKs could not be read at all"
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
# SCOPE: its own --corpus argument names benchmark-data/ic and nothing else.
#        Read from the command line below, not from where the program lives:
#        `gen_programs_index.py` sits in tools/ yet reads the marketplace,
#        so "where it is" is the wrong question and this scope answers
#        "what it reads".
# NO gate_scope HERE, DELIBERATELY, AND THE MEASUREMENT IS WHY.
#
# This gate carried `gate_scope benchmark-data/ic/` from v1.10.53 until it was
# withdrawn. The scope was WRONG in the one direction that matters: it excludes
# the checker's own body and its own ratchet register.
#
#   cross_layer_reference_check.py reads programs/cross_layer_reference_baseline.json
#   -- its debt register, whose header says a findings count may SHRINK freely and
#   any INCREASE fails CI. Under that scope, a commit that only widens the register
#   touches nothing in benchmark-data/ic/, so the one gate guarding it does not run.
#
# The general rule this is an instance of: a scope that excludes the gate's own
# executable body makes the gate unable to fail on a change to ITSELF, and
# "edit the checker instead of the artefact" is precisely the change most likely
# to be an attempt to silence it. Measured across the 48 scopes proposed in the
# same sweep: 13 of them had this shape, and 5 of those 13 guard something that
# is RED on this tree today.
#
# `--corpus-may-be-absent` (vibe-ic#1710's treatment): the published corpus
# moved to `vibeic/benchmark-data` in v1.10.56, so `$ROOT/benchmark-data/ic`
# is gone from this repo and the sweep refused on every landing. THE FLAG DOES
# NOT SILENCE THE GATE. It converts nothing-discoverable-anywhere into
# NO_CORPUS (rc 0) which STATES that 0 cells were swept; a
# $VIBE_IC_BENCHMARK_DATA that is set and broken is still UNDETERMINED (rc 2),
# a pointer-supplied tree that is not a git checkout is UNDETERMINED, and a
# corpus that IS resolvable is swept and can still FAIL.
#
# AND IT DOES NOT EXCUSE THE REGISTER. `cross_layer_reference_baseline.json`
# lives in THIS repo and did not move; under NO_CORPUS the gate still opens it
# and FAILs (rc 1) if its `seal` does not match the counts beside it. That is
# what keeps the withdrawn `gate_scope` above from being reintroduced as an
# rc 0 that never read the file.
run "cross-layer reference regression"  "$ROOT" python3 "$PG/cross_layer_reference_check.py" --corpus "$ROOT/benchmark-data/ic" --corpus-may-be-absent

# vibe-ic#693 — `flow_compliance_check` classifies a project from each step's
# `pass.flag` and never walks the per-step report JSON, so a step can ship
# pass.flag while one of its own sub-reports declares verdict=FAIL. This walks
# them and requires each FAIL/MISSING to be ACKNOWLEDGED — by a waivers.json
# entry naming the report, or by an orchestrator/audit record naming it.
#
# NON-BLOCKING BY RATCHET, not by being toothless. Measured over the 46 run
# trees on a working checkout, `--strict` reddens 16 of them on 33 findings the
# gate did not create; landing that blocking is an outage. The corpus mode
# instead sweeps the PUBLISHED (git-tracked) run trees and ratchets the count
# recorded in `step_internal_fail_bubble_up_baseline.json`. The count may shrink
# freely; a NEW unacknowledged step-internal FAIL is red.
# Published, not on-disk, on purpose: 46 vs the tracked population is exactly
# the host-dependence `_published_tree` exists to remove from a baseline.
#
# A RUN TREE IS ONE THAT OWNS A TRACKED reports/ TREE, not one whose directory
# NAME matches a convention (vibe-ic#1223). It used to be `clean_run_*`, which
# on v1.10.42 reached 3 of the 16 published run trees under this root and
# reported 5 of the 22 unacknowledged findings they carry. The numbers are NOT
# repeated here: the baseline records `findings_total` and `corpus_population`,
# and `test_the_recorded_population_is_the_one_the_ci_gate_sweeps` asserts the
# root named on the line below is the one that record was measured over — so
# this comment cannot drift out of agreement with the gate again.
# SCOPE: its own --corpus argument names benchmark-data/ic and nothing else.
#        Read from the command line below, not from where the program lives:
#        `gen_programs_index.py` sits in tools/ yet reads the marketplace,
#        so "where it is" is the wrong question and this scope answers
#        "what it reads".
# NO gate_scope HERE, DELIBERATELY, AND THE MEASUREMENT IS WHY.
#
# This gate carried `gate_scope benchmark-data/ic/` from v1.10.53 until it was
# withdrawn. The scope was WRONG in the one direction that matters: it excludes
# the checker's own body and its own ratchet register.
#
#   cross_layer_reference_check.py reads programs/cross_layer_reference_baseline.json
#   -- its debt register, whose header says a findings count may SHRINK freely and
#   any INCREASE fails CI. Under that scope, a commit that only widens the register
#   touches nothing in benchmark-data/ic/, so the one gate guarding it does not run.
#
# The general rule this is an instance of: a scope that excludes the gate's own
# executable body makes the gate unable to fail on a change to ITSELF, and
# "edit the checker instead of the artefact" is precisely the change most likely
# to be an attempt to silence it. Measured across the 48 scopes proposed in the
# same sweep: 13 of them had this shape, and 5 of those 13 guard something that
# is RED on this tree today.
#
# `--corpus-may-be-absent`, same treatment and same limits as the gate above:
# NO_CORPUS states that 0 published run trees were swept, a set-and-broken
# pointer is still UNDETERMINED, and a resolvable corpus still ratchets. The
# baseline register did not move with the corpus either, so a corpus-less run
# still checks that `findings_total` equals the sum of `per_run` — a ceiling
# raised by hand to buy headroom is rc 1 with or without a corpus.
#
# AND A CEILING LOWERED BY HAND IS TOO (vibe-ic#1704). The register records the
# counts it moved FROM beside the counts it holds, plus the reason it was
# allowed to fall; a corpus-less run re-checks that pairing exactly as it
# re-checks the sum. `--write-baseline` — the command this gate tells an
# operator to run on a shrink — refuses to lower any of `findings_total`,
# `runs_swept` or `runs_with_reports` without `--shrink-reason '<why>'`.
# Nothing on the line below writes anything, so this gate is read-only as
# before.
run "step FAIL bubbles up"              "$ROOT" python3 "$PG/step_internal_fail_bubble_up_check.py" --corpus "$ROOT/benchmark-data/ic" --corpus-may-be-absent
# Its neighbour one artefact over: `flow_compliance_check` now emits a CLASSIFIED
# BLOCKER LIST beside the tally, and `blocker_classification_check` is the guard
# on that list's contract — complete over the non-PASS steps, inventing none,
# and no class without a rule named in `basis`. It too shipped with nothing but
# its own unit test running it.
#
# READ-ONLY over the corpus, so NOT `run_writing_the_corpus`: measured across a
# full suite run, `wrote_corpus` is 0 with this gate declared — the dispatcher's
# own `git status --porcelain --ignored=traditional -- benchmark-data` bracket
# is unchanged by it.
#
# IT REPORTS NOT_CHECKED TODAY, ON PURPOSE. All 5 compliance reports the corpus
# carries predate the `blockers` key, so every rule in the guard takes the
# pre-contract early return and an rc 0 here would mean "no rule executed" while
# reading exactly like "the reports are clean" — the vacuous sweep this repo
# keeps removing one gate at a time, and the one PR #858's own review caught.
# The checker now refuses to call that state a PASS (rc 2 with the count), so
# this line cannot go green until a contract-carrying report is committed, and
# it goes green by itself on the first one that is.
uncheckable_until 2026-11-30 "KNOWN DEBT, not a missing prerequisite: all committed compliance reports predate the blockers key, so every rule takes the pre-contract early return and rc 2 says so rather than reporting an unexercised guard as clean. Goes green by itself on the first contract-carrying report committed"
run_tolerating_uncheckable "blocker list contract on committed reports" "$ROOT" \
    python3 "$PG/blocker_classification_check.py" --dir "$ROOT/benchmark-data"

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
#
# `--corpus-may-be-absent` (vibe-ic#1710's treatment): all 199 tracked
# `L4_REGMAP.json` lived under `benchmark-data/` and left with it in v1.10.56,
# so `--root "$ROOT"` now finds none and the gate refused (rc 2 -> FAIL) on every
# landing. The flag turns nothing-anywhere into NO_CORPUS, which STATES that 0
# documents were parsed and the disposition table was not exercised.
# $VIBE_IC_BENCHMARK_DATA is ADDED to "$ROOT" rather than replacing it — an L4
# document that comes home to this repo keeps being audited — a pointer set and
# broken stays UNDETERMINED, and a corpus whose documents are all unreadable is
# UNDETERMINED rather than the PASS-over-nothing this program shipped once
# before ("audit-corpus found 0 of 201 documents -> PASS").
run "L4 -> SystemRDL disposition"       "$ROOT" python3 "$PG/l4_systemrdl_export.py" audit-corpus --root "$ROOT" --corpus-may-be-absent

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
#
# `--corpus-may-be-absent` is passed because the corpus MOVED to its own
# repository (v1.10.56), so this repo genuinely need not carry one — the same
# opt-in `gatekeeper-land.sh` passes to `benchmark_evidence_structure_check`
# after #1710, and for the same reason. It is opt-in HERE, at the call site,
# rather than a default in the program: the flag only converts "no corpus
# discoverable ANYWHERE" into NO_CORPUS (rc=0, generating and comparing
# nothing, and SAYING so). It does not touch the two outcomes that matter —
# a $VIBE_IC_BENCHMARK_DATA that is set and broken is still UNDETERMINED
# (rc=2), and a corpus that IS resolvable is still walked and can still FAIL
# on a stale index.
run "published-evidence index honest"   "$ROOT" python3 "$PG/benchmark_evidence_index.py" --check --root "$ROOT" --corpus-may-be-absent

# vibe-ic#459 follow-up — the PROGRAMS index, alongside the evidence index above.
# MAIN WENT RED TWICE (v1.7.40, v1.7.41) because a new program landed and
# INDEX.md was never regenerated. The freshness test EXISTS and is correct; it
# lives in the plugin pytest suite, which this lane does not run, so a green
# hygiene run was true and carried no information about it. The generator
# already ships `--check` (exit 1 if the index would change) — the repair was
# never missing, only unwired. One `git ls-files` + one walk; measured
# discriminating: injecting a throwaway program makes it rc 1, removing it rc 0.
run "programs index fresh"              "$ROOT" python3 "$ROOT/tools/gen_programs_index.py" --check

# vibe-ic#1120 — the four PUBLISHED dimensions (Engineering Velocity,
# Autonomous Improvement, Adversarial Verification, Silicon Proof). Same shape
# as the two indexes above: the page is generated, `--check` re-derives it and
# exits 1 if it disagrees, so a figure cannot be talked upward by editing the
# page. It re-derives at the page's own stated ANCHOR rather than at HEAD, so a
# landing does not redden it — a freshness gate that fires on every commit is a
# bypassed gate.
#
# `run_tolerating_uncheckable`, and the reason is MEASURED rather than
# defensive: every velocity figure is history-derived, and on a SHALLOW clone
# the generator's own first run produced `86 of 89 commits` where the remote
# `main` carries 2007 — wrong by ~22x and entirely plausible. It now REFUSES
# (rc 2) on a shallow clone instead of reporting the smaller number. rc 2 is
# therefore "this clone cannot answer", which is the normal state for a
# developer's `--depth` checkout and must be LOUD and non-fatal; CI checks out
# complete and genuinely checks. rc 1 (a hand-edited figure) still fails.
uncheckable_until 2027-02-28 "needs a COMPLETE clone: it REFUSES (rc 2) on a shallow --depth checkout rather than reporting the smaller, entirely plausible figure that state produces; CI checks out complete and genuinely checks. A hand-edited figure is still rc 1"
run_tolerating_uncheckable "engineering evidence fresh" \
    "$ROOT" python3 "$ROOT/tools/gen_engineering_evidence.py" --check

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
run "gates disclose their denominator" "$ROOT" python3 "$PG/gate_discloses_denominator_check.py" "$ROOT" --skip-host-excluded

# The THIRD member of the disclosure family, one level up from the two above.
# Those ask what a gate's OUTPUT said about how much it looked at. This one asks
# what a gate's DOCSTRING says about how much its own predicate selected — the
# funnel a scope decision is argued from ("N syntactic matches down to M"). A
# figure a reader cannot reproduce is not evidence, even when the conclusion it
# supports is correct, so those numbers must be derived by the program rather
# than typed into prose. Blocking clauses only; the advisory tier is printed and
# never changes the exit code. ~25s, dominated by evaluating the bindings.
run "stated corpus figures are derived, not typed" "$ROOT" python3 "$PG/derived_corpus_figure_check.py"

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
# vibe-ic batch R1 — the flow declaration and the d3 evidence manifest must move
# TOGETHER. A path added to a step's required_outputs without re-measuring the
# manifest reddens that step's dimension-3 cell, and when the step is a mutation
# WITNESS (matrix_mutation_ledger declares witness="D1" for D3-UNDECLARED-ARTEFACT)
# it also disables the proof that the mutation is still caught — LOCK 2 requires
# the unmutated cell to PASS. BLOCKING: measured 0 uncovered on main, and 2 on
# each of #1131/#1170, which are exactly the branches that redden D1.
run "d3 declaration/manifest parity" "$ROOT" \
    python3 "$PG/d3_manifest_declaration_parity_check.py" "$PLUGIN"

run "gate skips reach the vacuous tier" "$ROOT" python3 "$PG/gate_skip_routing_check.py" "$PLUGIN"


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
# `pytest.ini` sets `testpaths = programs/tests`, and nothing in this file or in
# any workflow named the tools tree — so `tools/test_liar_census.py` ran only
# when a human typed its path. That file is the liar census's CALIBRATION: the
# planted gate per probe that is the only reason a sweep reporting zero can be
# believed. An uncadenced control is the #1019 shape one level up, and it is a
# particularly bad one here, because what rots silently is the instrument that
# decides whether everything else is honest. 95 tests; measured twice at
# this consolidation at 25 s and 137 s on the same tree -- the mutation
# probes dominate and vary with machine load, so budget for the high one.
# Every subprocess this file starts is bounded at 55 s or less, and that is now
# the ONLY bound: the `-p pytest_timeout --timeout=180 --timeout-method=thread`
# session bound this line used to carry is gone. It was the LAST SURVIVING USE
# in this repo of an idiom the repo has already retired, and it made this gate
# unrunnable on the runtime the repo anchors.
#
#   CAPABILITY, measured: `-p pytest_timeout` is a hard import, and
#   `pytest-timeout` is absent from `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2`
#   (the image named by `protected_landing_transition.json` .runner.image) and
#   from every 0.2.x/0.3.x tag of it on this host. There, this exact line did
#   not run 108 tests and report zero failures — it exited before collection
#   with `ImportError: Error importing plugin "pytest_timeout"`. The only lane
#   that ever installed the plugin was `.github/workflows`, and those files now
#   live under `.github/workflows-disabled`; the pass this gate used to record
#   depended on an ambient host pip package that nothing in this tree declares.
#
#   DOCTRINE, already settled: `tools/gatekeeper-land.sh` dropped this idiom at
#   v1.10.69 and TWO live tests forbid its return
#   (`tools/ci/test_phase_b_activated_parity.py::test_the_activated_runtime_no_
#   longer_uses_a_wall_clock_pytest_timeout` and
#   `tools/ci/test_repo_tools_tests_gate.py::test_pytest_is_progress_supervised
#   _without_an_elapsed_verdict`), `ci_harness_timeout_ceiling_check.py` reports
#   it there as "reintroduces a fixed pytest elapsed-time verdict", and
#   `programs/pytest_per_file_junit.py` carries the measurement behind that
#   retirement: `--timeout-method=thread` kills the SESSION, so the run that
#   trips it loses every result it had already earned. This script is invoked
#   BY `gatekeeper-land.sh`, so it is on that same landing path.
#
# NOTHING IS LEFT UNBOUNDED THAT WAS BOUNDED: the 180 s session bound sat above
# per-subprocess bounds of 55 s or less, so by this file's own design it could
# only ever fire after the inner bounds had already failed a test — and when it
# did fire it destroyed the other 107 results. Its removal deletes a backstop
# whose only reachable behaviour was the destructive one.
run "liar census controls still fire"   "$ROOT" env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    python3 -m pytest -q \
    "$ROOT/tools/test_liar_census.py"
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
# vibe-ic#1241 — `bundled_attribution_notice_check` was authored, tested and
# merged with NOTHING but its own unit test invoking it: a fixture the author
# wrote proves the logic and proves nothing about what this repo ships.
#
# The population is THE REPOSITORY, not a per-cell loop, and that is the gate's
# own stated scope rather than a convenience: Apache-2.0 §4(d) attaches to
# distributing the WORK, so the subject is the whole distributed tree and the
# root `NOTICE` that must account for it. A per-published-cell dispatcher would
# have wired an obligation about the repository to a sample of run artefacts.
#
# `run`, not `run_tolerating_uncheckable`: this gate has a REFUSE path (rc=2,
# "no SPDX-headered source found") that exists precisely so an empty scan
# cannot read as a pass, and on this tree it does not fire — MEASURED, 513
# SPDX-headered files under 7 holders, all named in NOTICE, rc=0. A tolerated
# rc=2 here would re-admit the vacuous pass the refusal was written to block.
run "bundled work is named in NOTICE"   "$ROOT" python3 "$PG/bundled_attribution_notice_check.py" "$ROOT"
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
#
# `--corpus-may-be-absent` (vibe-ic#1710's treatment). Before it this gate did
# not refuse, it CRASHED — `ERROR: not a directory: <repo>/benchmark-data` at
# rc 1, which in this program means "a published record carries a verdict its
# gate would not issue today". It reported a finding against records it never
# opened. The flag converts nothing-anywhere into NO_CORPUS (rc 0) stating 0
# records were adjudicated; a set-and-broken $VIBE_IC_BENCHMARK_DATA is still
# UNDETERMINED (rc 2), and the debt register is STILL put through the #922
# may-only-shrink checks, which need no corpus to ask.
run "published records not superseded" "$ROOT" python3 "$PG/published_record_staleness_check.py" --corpus-may-be-absent

# vibe-ic#904 — a design-input document made a CHECKABLE factual claim about the
# installed PDK, the claim was false, and nothing in the flow noticed. The
# disclosure it mandated ("label every corner result a LEVEL=1 standin") then
# propagated into published output, so the false claim was not inert: it made the
# results UNDERSTATE themselves, which is the direction nobody watches for.
#
# WHY IT WAS NOT WIRED WHEN IT LANDED, and why that changed. #949 shipped this
# gate deliberately unwired, and the reason was sound at the time: wiring it
# blocking would have turned main red on the very design-input document #904
# forbade anyone to edit, i.e. it would have "closed" the issue by breaking the
# flow. The owner then ruled option A and the documents were corrected in #958,
# so the reason has expired. Leaving it unwired now costs two OTHER hygiene gates
# — `checker_execution_wiring_audit` named it as a checker nothing but its own
# test runs, and the unwired-gate census went 60 -> 61 — which is the same defect
# this file exists to remove, one level up.
#
# `run_tolerating_uncheckable`, and the choice is load-bearing. The gate needs an
# installed PDK tree to decide anything; on a host without one it exits 2 and
# says `[VACUOUS] ... examined nothing (reason: installed_pdk_root_unreadable);
# this is NOT a pass over the design`. NOT_CHECKED carries exactly that to the
# roll-up, instead of folding "I could not look" into "I looked and it was
# clean". Plain `run` would make every PDK-less host red for a reason that is
# about the host; treating rc 2 as PASS would be the lie.
#
# MEASURED when wired, on the corrected tree: 134 design-input documents, 8
# candidate claims, 4 CONTRADICTED / 1 CORROBORATED / 3 UNDECIDED before #958, 0
# false positives. The CORROBORATED one is a claim of identical grammar about a
# different installed PDK that happens to be TRUE — a real repository document
# rather than a synthetic fixture, which is what keeps this from being a gate
# that only ever says no.
#
# THAT MEASUREMENT WAS TAKEN OVER FOUR OF THE SIX INSTALLED PDKs (#964). The
# container backend listed with `ls -1p`, which marks REAL directories only, so
# the two PDKs the image installs as links into its package store were outside
# the population entirely — no decision and no refusal on either. Re-measured on
# the same image with the listing dereferencing, and with a lookup miss no
# longer defaulting to agreement (#965): 134 design-input documents, 6 -> 7
# candidate claims, 2 CONTRADICTED / 1 CORROBORATED / 3 -> 4 UNDECIDED, still 0
# false positives, verdict unchanged at FAIL. The seventh claim is about one of
# the two PDKs that could not be seen before, and it is UNDECIDED — which is the
# point: it is now REFUSED out loud instead of dropped in silence.
#
# THE WIRED PATH BELOW HAS NEVER EXERCISED ANY OF THAT (vibe-ic#981). It passes
# no `--container`, and no host that runs this script has a local `/foss/pdks`,
# so the run bails at `installed_pdk_root_unreadable` with 0 documents scanned:
# not one claim adjudicated, the walker never called, and `docker_backends` —
# the `-L` dereference #964 exists for — not executed at all. Every measurement
# quoted above was taken BY HAND with `--container`; none of them was taken by
# this line. The gate's own report now NAMES the backend that never ran, so the
# rc-2 says "I could not look, and here is the half of me that never ran"
# instead of leaving that for a reviewer to notice.
#
# WHY THE DISCLOSURE AND NOT ONE OF THE OTHER TWO REPAIRS, measured 2026-08-11:
#
#   a container in CI — REJECTED, and not because it is slow. It is not: the
#     gate answers in 2.2s against a live EDA container over all six installed
#     PDKs. It is rejected because it comes back rc 1: 134 documents, 7
#     candidate claims, 2 CONTRADICTED / 1 CORROBORATED / 4 UNDECIDED. Those
#     two contradictions are TRUE — the documents really do deny a corner
#     library the image really does ship — and both live under
#     benchmark-data/**/input/, which #904 forbade editing and which this
#     campaign forbids editing. Wiring it blocking would turn main red on files
#     nobody is permitted to correct, which is the exact bind #949 shipped this
#     gate unwired to avoid. It is reported as a FINDING in the PR instead of
#     being made green by widening anything.
#
#   a fixture PDK tree — REJECTED as theatre. This file's own line above says
#     it: "a checker only its own unit test ever runs has zero coverage of real
#     inputs: the fixture proves the logic, never the artefacts." pytest
#     already drives this gate over 41 synthetic PDK fixtures, including the
#     container backend's REAL command strings with `docker exec` swapped for a
#     local shell. A fixture run wired here would be that same suite wearing a
#     CI hat, and it would make the roll-up read PASS for a gate that still has
#     not seen one installed artefact.
#
# So the honest state WAS: the LOGIC is covered by pytest, the ARTEFACTS are
# covered by nothing automatic, and the gate now says so in the same document
# that carries its verdict. NOT_CHECKED in the roll-up is the correct state and
# is deliberately left in place.
#
# THAT CONCLUSION IS SUPERSEDED — see the #1076 paragraph at the bottom of this
# block. Its second premise was false: the artefacts ARE reachable, by a
# mechanism this same file already accepted for a sibling gate, and repair (a)
# above was rejected on a BLOCKING-vs-nothing choice that had a third option in
# it. The rejection of the FIXTURE repair still stands unchanged.
#
# THE DISCLOSURE ABOVE WAS ITSELF WRONG IN ONE ARM (vibe-ic#1491). Repair (a) —
# "pass --container here" — could have been applied, been entirely inert, and
# reported itself as done: `docker_backends` turned every backend failure
# (container down, container misnamed, docker absent, deadline expired) into an
# empty listing, `run` read that empty listing as an unreadable PDK ROOT, and
# the report then printed `backend_not_exercised: []`, i.e. asserted that the
# container backend HAD run. Measured on 8HD-7 at 3d13e2c59, exit codes taken
# from python directly rather than through a pipe:
#
#   no --container                    rc 2  installed_pdk_root_unreadable
#   --container <a live one>          rc 1  134 documents, 7 claims, 2 CONTRADICTED
#   --container <a name with no container>
#                                     rc 2  installed_pdk_root_unreadable,
#                                           backend_not_exercised: []
#
# Row 3 is the trap under row 1's own advice. The gate now PROBES the root
# instead of inferring it from an empty list, so those four environments carry
# four distinct reason tokens; `backend_not_exercised` is computed from what
# actually ran; and a backend the caller NAMED but could not reach is rc 1
# (`failure_kind: environment`) rather than a quiet rc 2 — the call `cvdp_gate`
# made for an absent iverilog in #1345. Every run, pass or not, now prints an
# `[ENVIRONMENT]` line naming the root, the backend and the state it read, so
# two verdicts at the same commit can be compared at all.
#
# THE INVOCATION IS DELIBERATELY UNCHANGED, AND SO IS THE EXEMPTION BELOW. It
# passes no `--container`, so it keeps taking the rc-2 tier for a reason that is
# genuinely about the host, and main stays exactly as green as it was. What
# #1491 changed is that the rc-2 now names WHICH host reason it is, and that the
# one non-host reason — a backend the caller named and could not reach — has
# left the rc-2 tier altogether, so it can no longer hide inside the exemption.
#
# Wiring `--container` here is now SAFE to do — a wrong name announces itself
# instead of reading as NOT_CHECKED. What it was NOT was sufficient: `--container`
# needs a container SOMEBODY ELSE started, and nobody starts one here, so the
# flag alone left the gate exactly as blind. That is why the paragraph above
# ends in an owner decision rather than a wiring.
#
# IT IS WIRED NOW, AND THE OWNER DECISION IS SIDESTEPPED RATHER THAN GUESSED
# (vibe-ic#1076). Two things changed:
#
#   * the checker grew `--from-image`, which starts ONE ephemeral container
#     from the image `tools/vibeic-eda/VERSION` anchors and hands it to the
#     already-tested `docker_backends`. This is not a second access path — it
#     is the `--container` path with the "somebody else starts it" precondition
#     removed. The MECHANISM was already accepted in this very file: the
#     sibling ~450 lines above (`PDK via patch vs layer min width`) reaches the
#     installed PDKs from CI with a flag of the same name and passes in the
#     same run. So "the ARTEFACTS are covered by nothing automatic" was a fact
#     about this checker's missing flag, never about the artefacts;
#
#   * it runs `--advisory`, which is the SAME disposition that sibling already
#     carries, for the same reason and with the same shape: the exit code
#     changes and NOTHING else. The verdict word stays FAIL, both
#     contradictions stay printed in full, and the checker prints
#     "(--advisory: returning 0. The verdict above is FAIL.)" underneath them,
#     so a tolerated finding cannot be read as an absent one.
#
# WHY ADVISORY AND NOT BLOCKING, stated rather than defaulted. The two live
# contradictions are in PUBLISHED RUN INPUT under benchmark-data/**/input/,
# which #904 forbids editing. Blocking would turn main red on files nobody is
# permitted to correct, and a blocking gate whose repair lives somewhere nobody
# may go is the gate that gets switched off. Advisory does not ask the owner
# question at all: it neither blesses those documents nor blocks on them, it
# PUBLISHES them every run so the count cannot drift unseen. Flip to blocking
# by deleting one word once the two documents are dispositioned.
#
# `--advisory` DELIBERATELY DOES NOT DOWNGRADE rc 2. rc 1 is "I looked and found
# something"; rc 2 is "I could not look". A host that cannot start the pinned
# image still reports NOT_CHECKED through the exemption below — which is why
# that exemption stays, with its reason rewritten to the one that can now
# actually occur. Laundering rc 2 into 0 would recreate #1076 through the flag
# that fixes it.
#
# MEASURED on 8HD-7 at 2efa6af35, exit codes taken from python directly:
#
#   as wired before                    rc 2  0 documents, 0 claims (NOT_CHECKED)
#   --from-image                       rc 1  134 documents, 7 claims,
#                                            2 CONTRADICTED / 1 CORROBORATED /
#                                            4 UNDECIDED
#   --from-image --advisory            rc 0  same report, verdict still FAIL
#   --from-image --advisory, no image  rc 2  the WARN names the image it could
#                                            not start; still NOT_CHECKED
#
# The image is READ from `tools/vibeic-eda/VERSION` rather than restated in the
# checker, and that was exercised rather than asserted: the anchor moved
# 0.2.98 -> 0.2.99 between v1.10.42 and v1.10.43 while this change was being
# measured, and the checker followed with no edit. The sibling carries the tag
# as a literal and needs `sync_image_version.py` to rewrite it.
uncheckable_until 2026-11-30 "needs the ANCHORED vibeic-eda IMAGE on the host: --from-image starts an ephemeral container from it to read the installed PDK, and rc 2 means no PDK could be read at all (a claim the installed tree contradicts is rc 1, and --advisory does not touch rc 2)"
run_tolerating_uncheckable "input-doc claims vs installed PDK" "$ROOT" \
  python3 "$PG/input_doc_pdk_claim_vs_installed_pdk_check.py" "$ROOT" --from-image --advisory

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

# The census the two gates above feed into, and the one thing in this family that
# a HUMAN had to remember to run.
#
# WHY THIS LINE EXISTS. `matrix_63x8/README.md` publishes the campaign's headline
# figure — "504 cells: N ENFORCED, N CONTRADICTED, N WAIVED, N NA" — and it has
# gone stale TWICE, in two different ways, and neither time did anything notice.
#
#   * First it was hand-written. `origin/main` at dee025059 published 483/9/12
#     while the live suite counted 481/11/12, four rows adrift, with the command
#     that disproves the table printed two lines underneath it. #898 made the
#     block GENERATED, which is the right repair and is not this one.
#   * Then it was generated at the wrong VINTAGE. #929 gave step P0 a `blocks_on`
#     key, self-invalidating d5's NA for that step — correctly, and loudly, with
#     the owning module emitting "the NA has self-invalidated". #928's block had
#     been generated BEFORE #929 existed and was merged two commits later without
#     regeneration, so main published 28 CONTRADICTED / 12 NA while its own live
#     join produced 29 / 11. Repaired in the tree; the ENFORCEMENT gap was left
#     open deliberately, with the reason written down: "a generated artefact whose
#     freshness check runs in no merge path will go stale again, and next time it
#     may not be a number anyone re-derives."
#
# That gap is what this line closes. Measured at the time and re-measured today:
# there is no `.github/workflows` directory in this repository, and before this
# line THIS script contained zero references to `63x8`, `matrix` or `census` —
# and #929 edited this very file, adding a gate one line away. The only automated
# consumer was `test_matrix_63x8_census_freshness.py`, which runs when a human
# selects it. So the guard shipped by #928 was real, was correct, and was enforced
# by nothing that fires on a merge. Six PRs landed on 2026-08-11 alone.
#
# BLOCKING, and it is green on day one — which is the condition under which
# blocking is honest. Measured at 6a61dbf2c: `[PASS] 63x8 census fresh: 504 cells
# over 8 dimensions; ENFORCED own=16 substituted=45 undeclared=397; WAIVED=11
# NA=11.`
#
# It can FAIL, proven rather than assumed: mutating one figure in the published
# block (458 -> 457 ENFORCED) gives rc 1 and names the file and the command that
# repairs it. A freshness gate that has never been shown to go red is the same
# defect one level up.
#
# host-independence: it is re-run by `gate_host_independence_check` above, so
# this was checked BEFORE wiring rather than discovered afterwards — two fresh
# worktrees at the same commit, output byte-identical, rc 0 both.
#
# COST: 2m07s measured (`real 2m7.492s`, user 2m46.939s), and the host-independence
# probe re-runs it, so ~6 min of added
# CI in total. Disclosed rather than buried: that is real, it is the second most
# expensive line in this file after the pytest-driven pin below, and it is the
# price of a headline figure that cannot drift unseen. The cheaper option — trust
# whoever lands the change to remember — is the option that already failed twice.
#
# WHAT THIS GATE COVERS, CORRECTED (vibe-ic#961). The paragraph above said "a
# headline figure that cannot drift unseen". `--check` compared the MARKED BLOCK
# only — 36 lines of a 501-line README — and five live-derived figures outside it
# were stale on origin/main, one of them invalidated by #929, the very commit
# cited nine lines above as the reason this gate exists. `--check` now also
# re-derives every ANCHORED figure in the 63x8 corpus and PRINTS ITS OWN
# COVERAGE on every verdict: how many figures it guards and how many stated
# population figures in the same files it does not. That remainder is large and
# is meant to be read, not celebrated — this gate is not, and does not claim to
# be, a guarantee about every number on the page.
#
# IT IS NOW HANDED "$ROOT", like every other gate on this page (vibe-ic#972).
# This line used to pass NO subject, so the program resolved every path off its
# own `__file__` and answered for its own checkout whatever tree it was asked
# about. `gate_discloses_denominator_check` drives this exact declaration
# against a scratch EMPTY repository, and MEASURED at 6525cf05 it printed
# `[PASS] 63x8 census fresh: 504 cells over 8 dimensions` — over a directory
# holding one file — in 1m50.203s, i.e. 8% under the 120s bound that would have
# reported it as unrunnable. Handed the scratch root it now refuses it as a
# ZERO DENOMINATOR in 0.03s, which is what that probe was asking for.
# MOVED OUT OF THE LANDING PATH (owner decision, 2026-08-16).
#
# `63x8 census freshness` asks whether the campaign's published matrix figures are
# still true. That is a QUALITY question about the 63x9 campaign, and it was the
# only 63x8 gate in this file. Landing asks a different question -- does this change
# break anything -- and a stale census breaks nothing: it makes one published number
# out of date, which blocks the campaign, not the push.
#
# The two tiers are now separate by construction. Run it where it belongs:
#     python3 tools/gen_matrix_63x8_census.py <root> --check
# and `test_matrix_63x8_census_freshness.py` still enforces it in the suite, so the
# figure cannot drift unnoticed -- it simply no longer sits between a fix and main.
#
# NOT REMOVED FOR SPEED. Measured on the trimmed tree it is 64s, which is not what
# made landing slow; the earlier 110s+ readings were taken before benchmark-data was
# split out and while five shard runs were saturating the host. The reason is
# layering, and stating the cost honestly matters because a wrong reason survives
# into the next decision.

# A call site writes a literal into a parameter that picks between named
# alternatives, prose argues WHICH WAY, and no test can see the difference.
# MEASURED on review: flipping one such word — `on_conflict="richer"` to
# `"sparser"` — left all 25 tests of the PR that introduced it green, including
# a test named for the policy, because that test drove the HELPER under both
# values instead of the CALL SITE under one. A helper test gets greener the more
# thorough it is and never dies under the flip.
#
# This gate performs the flip and runs the tests, because there is no static
# form of the question: "a test mentions the value" is satisfied by a test that
# asserts nothing about it.
#
# COST: it runs pytest, so it is the slow one here — ~4 min on a quiet host for
# this corpus (one argued site, 32 candidate test files, two flips plus a
# baseline narrowed to the file that died). That is disclosed rather than hidden
# because it is the reason to keep the ARGUED population small and honest.
#
# rc=2 (a site it could not decide) BLOCKS, deliberately: this gate exists
# against checks that go green by declining to look, and that includes itself.
# vibe-ic#1128 — A SKIP IS GREEN, and thirteen of them are a coverage hole.
# 107 test files gate on the EDA image being reachable. Measured on a clean
# detached origin/main at v1.10.33, same files, two arms (arm 2 puts an
# `exit 127` shim ahead of `docker` on PATH):
#
#     image reachable     19 failed, 1419 passed, 44 skipped
#     image unreachable   24 failed, 1401 passed, 57 skipped
#
# 1419 -> 1401 is 18 passes lost: THIRTEEN became SKIP. The per-test messages are
# already honest ("this half was NOT checked"); the defect is one level up, where
# `1401 passed` is all a reader sees. And the trigger is an ANCHOR BUMP, not
# flakiness — coverage follows the anchor, so every bump removes these
# verifications on every host until that host pulls. With six machines landing in
# parallel that is exactly when a false green costs most.
#
# WIRED `run_tolerating_uncheckable` DELIBERATELY, and the choice is the point.
# The check exits 2 when the image is unreachable, which this wrapper records as
# NOT_CHECKED — a state that is never folded into `passed`. That is the mechanism
# `_gate_dispatch.sh` already gives GATES and the test tier lacks, which is #1128's
# own diagnosis. Promoting it to `run` (blocking) is a policy call with a measured
# blast radius: ZERO on a host carrying the anchored image, and every landing
# refused on a host without it. One word changes it when that is wanted.
# WHY TOLERATING: the anchored EDA image may legitimately be absent on a host
# that has not pulled it. The hole is REPORTED as NOT_CHECKED rather than
# blocking, until the owner rules on refusing landings from such a host.
# (#1072's `uncheckable_until` directive HAS since landed, so the disclosure this
# comment carried in prose is now stated in the form the dispatcher can read.)
uncheckable_until 2027-02-28 "needs the vibeic-eda CONTAINER IMAGE on the host: the check exits 2 when the image is unreachable, which a host that has not pulled it legitimately is. Refusing landings from such a host is a policy call with a measured blast radius — zero on a host carrying the anchored image — and one word changes it when that is wanted"
run_tolerating_uncheckable "image-gated verifications are not silently skipped" "$PLUGIN" \
  python3 programs/image_gated_verification_check.py

run "an argued direction is pinned" "$PLUGIN" python3 programs/policy_direction_pin_check.py programs --verify-pins --jobs 6

# vibe-ic#1241 — WIRED HERE, not left to its own test. The audit
# (`checker_execution_wiring_audit`) named this checker as one that nothing but
# its own fixture ever ran: "a fixture the author wrote proves the logic, never
# the artefacts."
#
# This surface and not the flow, because the subject is SHIPPED SOURCE, not a
# design's artefacts: it parses every program under `programs/` and asks whether
# a write to a declared report destination goes through `_atomic_artefact`. That
# is the same population and the same cadence as the pinned-direction gate
# directly above, which is why it sits beside it.
#
# MEASURED before wiring, so this adds a gate that passes rather than a new red:
#   1138 program(s) parsed; 565 non-atomic declared-report writes (residual
#   baseline 565); rc=0 "[PASS] no new non-atomic declared-report write."
# The 565 are a recorded residual, not a waiver — the gate fails on a NEW one.
run "declared reports are written atomically" "$PLUGIN" python3 programs/atomic_artifact_write_check.py programs

# The other half of #447: compare the checkout records every gate above has
# ALREADY produced with one fresh-worktree run.  This is deliberately LAST.
# The old placement launched Arm A again inside this gate, so every ordinary
# hygiene gate ran three times (outer + A + B), and a disagreement ran five.
# Reusing the exact argv-bound structured record makes the common path two
# executions without weakening the two-tree assertion. Missing/malformed
# records are rc 2 NOT CHECKED, never reconstructed from console prose.
uncheckable_until 2027-02-28 "needs a CLEAN checkout and a complete machine record from this enclosing hygiene run: rc 2 means tracked modifications or missing attestation made the comparison meaningless (a genuinely host-dependent gate is rc 1)"
# SERIAL, AND THE REASON IS THE WHOLE POINT OF THIS GATE.
#
# It compares each gate's record from THIS run against a fresh-worktree run, so it
# needs every other gate's process record to already exist. Under `--jobs 8` it is
# declared last and still starts while the slowest gates are in flight, so their
# records are not written yet and it reports:
#
#     [CHECKOUT_ATTESTATION_MISSING] an argued direction is pinned
#         the outer hygiene run supplied no complete process record for this
#         declared gate; the fresh arm was not run
#         checkout: NORECORD    worktree: NOT RUN
#
# Measured: the gates it named missing were exactly the slowest — "an argued
# direction is pinned" (150 s), "gates disclose their denominator" (47 s), "liar
# census controls still fire" (30 s). The attestation FILE was complete afterwards
# (79 declared, 79 records, 0 missing); what was incomplete was the file AT THE
# MOMENT THIS GATE READ IT.
#
# `gate_serial` drains the pool first, which restores the ordering the sequential
# run gave it for free. Declaration order was never the guarantee — completion
# order was, and concurrency separated the two.
gate_serial "it reads every other gate's process record, so all of them must have \
finished; under concurrency the slowest are still running when it starts"
run_tolerating_uncheckable "gates are host-independent" "$ROOT" \
  python3 "$PG/gate_host_independence_check.py" "$ROOT" \
  --jobs 8

# Writes the coverage record (when asked), prints the roll-up WITH its own
# denominator, and exits 0 / 1 / 2. See `_gate_dispatch.sh`.
gate_dispatch_finish
