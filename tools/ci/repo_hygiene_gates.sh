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
# THE EXEMPTION BELOW WAS FALSE, AND THIS IS THE CORRECTION (2026-08-22).
# It said "the corpus carries none yet (#1121's first head-to-head has not
# run)". SEVENTEEN have run and are committed to this repository:
# `ppa-crosslayer/records/h2h_A..O.json` (15) and `ppa-e2e/records/*.json` (2).
# The gate was not waiting for a record. It was aimed at `benchmark-data`, which
# left this repository in v1.10.56, and nobody re-aimed it. A dated exemption
# over a population that already exists is a promise nothing was ever going to
# keep, because the day it came due nothing would have changed.
#
# THREE LINES, NOT ONE, and each has a DIFFERENT subject:
#   - the published corpus in the other repository, reachable only through
#     $VIBE_IC_BENCHMARK_DATA. Genuinely uncheckable here, and now says so for
#     the true reason instead of a false one.
#   - the cross-layer campaign, in tree.
#   - the end-to-end campaign, in tree.
# One `--corpus` takes one directory and the two campaigns have no common
# parent but the repository root; pointing this at `$ROOT` would sweep every
# test fixture in the tree into the population, which is the corpus-by-accident
# this gate exists to refuse.
uncheckable_until 2027-02-28 "the PUBLISHED corpus lives in another repository since v1.10.56, so this row can only be checked on a host that points VIBE_IC_BENCHMARK_DATA at a clone of it; rc 2 means the pointer is unset or unreadable, and it is NOT a claim that no record exists — seventeen are committed here and are checked by the two rows below"
run_tolerating_uncheckable "PPA head-to-head records" "$ROOT" \
    python3 "$PG/ppa_head_to_head_check.py" --corpus "$ROOT/benchmark-data"
# MEASURED 2026-08-22 on a00f53f20: 15 record(s), 1 refused, 2 undetermined,
# 12 accepted -> rc=1. The refusal is `h2h_F`, `BASELINE_TUNED_BY_US`: the
# record behind the lane's headline number declares `tuned_by_this_project:
# true` on its own BASELINE, and a comparison against a baseline this project
# tuned cannot carry the claim printed on it. That red is REAL, it is a finding
# about a published comparison, and it is acknowledged with a deadline in
# tools/ci/gate_red_since.json rather than wired around. `ppa-gate-audit/RESULT.md`
# is the whole measurement.
uncheckable_until 2027-02-28 "rc 2 here is a CONTENT verdict over a NON-EMPTY population, not a missing prerequisite: a record whose axis scope is incomplete or carries a null sentinel cannot be decided either way, and two nulls comparing EQUAL would otherwise pass two numbers taken under unrecorded conditions as taken under the same ones. A record that CAN be decided and fails is rc 1. THE DATE ON THIS EXEMPTION IS UNTOUCHED and no leniency changed; only a sentence of FACT did. It used to end 'and this corpus produces one today', naming h2h_F -- which was not a head-to-head at all but a within-project ablation mis-filed under this document kind, and has been re-filed as vibeic.ppa.ablation.v1 with every number byte-identical and the refusal that caused it kept beside it. The corpus is 14 records, 0 refused, and the 2 that remain undecidable are h2h_A and h2h_B. THEIR REASON IS NOT THE UNRECORDED-FIELD DEFECT THIS TEXT PREDICTED, and the sentence is corrected rather than left: both refuse at FEASIBILITY_NOT_CHECKED, naming 'feasibility.checks.drv.status' on BOTH arms, which check_feasibility reaches BEFORE check_scope_parity -- so the rc_corner sentinel h2h_A also carries is never the verdict. NAMED MISSING INPUT: a decided CLEAN/VIOLATIONS status on the drv axis. PRODUCER: none -- ppa-crosslayer/RESULT.md 8.4 measured that nothing in programs/ produces drv, which is why it was the last axis standing there too. Until this batch these two were rc 1 STAGE_CONTRADICTS_BASIS: each cited a stage='synth' power number under measurement_basis='post_route_sta'. Their power axis has been re-filed from the labelled post-route diagnostic the same trial already measured, so what is left is a stated gap and not a false claim"
run_tolerating_uncheckable "PPA head-to-head records (cross-layer campaign)" "$ROOT" \
    python3 "$PG/ppa_head_to_head_check.py" --corpus "$ROOT/ppa-crosslayer"
# MEASURED: 2 record(s), 0 refused, 2 undetermined -> rc=2. That is a
# content-earned NOT_CHECKED over a NAMED population of two, which is a
# different fact from the zero-second no-op this row used to be.
#
# THE COUNT WAS PREDICTED CORRECTLY AND THE REASON WAS NOT, so the reason is
# corrected here. This comment said both records were `SCOPE_SENTINEL` on the
# `rc_corner` key. They are not: both refuse at `FEASIBILITY_NOT_CHECKED`,
# naming `feasibility.checks.drv.status` -- and `setup` and `hold` besides --
# because `check_feasibility` runs BEFORE `check_scope_parity`, so the scope
# sentinel these records also carry is never the verdict a reader is given.
# The rc_corner gap is real and is still described in the exemption below; it
# is simply not what stops these two.
uncheckable_until 2027-02-28 "rc 2 here is a CONTENT verdict over a NON-EMPTY population of two. THE VERDICT BOTH RECORDS ACTUALLY RETURN is FEASIBILITY_NOT_CHECKED, naming 'feasibility.checks.drv.status', 'feasibility.checks.setup.status' and 'feasibility.checks.hold.status'; check_feasibility runs before check_scope_parity, so the rc_corner gap described below is real but is not what stops them. Until this batch the first of the two was rc 1 STAGE_CONTRADICTS_BASIS -- a stage='synth' power number cited under measurement_basis='post_route_sta' -- and its power axis has been re-filed from the post-route diagnostic this campaign had already measured and published beside it in head_to_head_diagnostic_power.json. THE SECOND, PRE-EXISTING GAP, still true: both published records declare a timing rc_corner key with no value, so on that axis too neither comparison can be decided. It is NOT a claim that the corpus is empty — the count is printed on every run — and a record that CAN be decided and fails is rc 1. THE PRODUCER-SIDE CAUSE, MEASURED 2026-08-22 over every scope/source pair in ppa-e2e: the timing axis of both records is taken from sta_spef_based.rpt, and that report names no RC corner anywhere in this corpus — 490 of 490 metric rows sourced from it carry rc_corner null. The only source that DOES name one is sta_spef_multicorner.rpt (549 max / 544 min), which is what the cross-layer records use and why they are decided. Re-filing the axis from it is not a repair anyone can make here: its rows sit at a different process corner than the tt/1.6V/100C these records publish, and its own wns_ns is null. NAMED MISSING INPUT: a setup WNS for these two arms, at the corner they publish, from an STA run that records its RC corner. PRODUCER: the end-to-end campaign runner. Stating the field from anything in the tree today would be composing the condition after the measurement"
run_tolerating_uncheckable "PPA head-to-head records (end-to-end campaign)" "$ROOT" \
    python3 "$PG/ppa_head_to_head_check.py" --corpus "$ROOT/ppa-e2e"

# THE ABLATION KIND, WHICH UNTIL NOW HAD A SCHEMA AND NO GATE.
#
# `schemas/ppa/ablation.v1.schema.json` exists because a WITHIN-PROJECT
# comparison was filed as `vibeic.ppa.comparison.v2` and `ppa_head_to_head_check`
# refused it BASELINE_TUNED_BY_US. The record was honest; the document kind was
# the lie. The new kind was the right repair -- and nothing that RUNS ever read
# it. Measured on a4caccefe (v1.11.69): one pytest driving one hardcoded path,
# and in this file the word `ablation` appeared in a comment and nowhere else.
#
# WHY THAT IS NOT A COSMETIC GAP. The three rows above refuse a comparison whose
# baseline this project tuned. This kind is where such a document legitimately
# goes -- and with no gate behind it, it is also where an ILLEGITIMATE one could
# go to escape those same conditions. The schema closes that from the other side
# (`tuned_by_this_project: const true` on EVERY arm, so a real head-to-head
# cannot satisfy it), but a schema nothing applies refuses nothing.
#
# THE WRAPPER, AND IT WAS CHOSEN THE SECOND TIME BY MEASUREMENT RATHER THAN BY
# TASTE. The gate PASSES today: 633 JSON file(s) opened under ppa-crosslayer,
# 1 ablation record selected, 0 refused, 0 undetermined, 1 accepted -> rc=0. So
# plain `run` looked right and was written first. It is WRONG, and here is the
# measurement that says so:
#
#   $ GATEKEEPER_BENCHMARK_DATA_SHA=... VIBE_IC_BENCHMARK_DATA=<clone> \
#       ppa_ablation_check --corpus <repo>/ppa-crosslayer
#   note: GATEKEEPER_BENCHMARK_DATA_SHA binds the landing corpus; forcing
#         VIBE_IC_BENCHMARK_DATA=<clone> and refusing any candidate-local
#         .../ppa-crosslayer shadow.
#   VACUOUS: ... 0 ablation record(s) selected ... rc=2
#
# A BOUND LANDING REDIRECTS THIS ROW AWAY FROM THE NAMED ROOT. That is
# `_corpus_location.resolve`'s bound branch working exactly as designed -- one
# byte-attested external checkout, no candidate-local shadow -- and it means an
# rc 2 here can be a fact about the LANDING ENVIRONMENT rather than about any
# record. Failing a landing for that would be a gate answering a question
# nobody asked, so rc 2 arrives as NOT CHECKED. rc 1 -- a record that WAS read
# and does not hold -- still fails, which is the half that matters.
#
# AND THE EXEMPTION IS DECLARED, because the dispatcher refuses to let it be
# defaulted into. Written first with no `uncheckable_until` -- on the reasoning
# that rc 2 is not EXPECTED here and an undeclared row stays louder -- and
# `_gate_dispatch.sh` rejected the whole run for it:
#
#   gate_dispatch: WIRING ERROR -- "PPA ablation records (within-project)" is
#   wired with run_tolerating_uncheckable, so it can report NOT_CHECKED, but no
#   `uncheckable_until <YYYY-MM-DD> <why>` line precedes it -- tolerance has to
#   be bought, not defaulted into
#   ... the set was not correctly declared, so this run certifies NOTHING
#
# That is the correct ruling and it cost nine test reds to learn. The routed-DEF
# row that reports "BLOCKING; no exemption" is NOT a counter-example: it uses
# the structural-refusal wrapper, a different mode, whose rc 2 is the only
# truthful outcome it has.
#
# AIMED AT ppa-crosslayer AND NOT AT benchmark-data, deliberately: this is where
# the kind lives (`records/ablations/`), and it is the directory a SECOND
# ablation would be filed into tomorrow -- the case that was validated by
# nothing before this row existed.
uncheckable_until 2027-02-28 "rc 2 here is NOTHING OPENED or nothing of this kind found -- never a verdict about a record. Over THIS repository the gate DECIDES and PASSES today: 633 JSON file(s) opened under ppa-crosslayer, 1 ablation record selected, 0 refused, 0 undetermined, 1 accepted, rc 0. The reachable rc 2 is environmental and was MEASURED, not guessed: a landing that binds a corpus (GATEKEEPER_BENCHMARK_DATA_SHA) forces VIBE_IC_BENCHMARK_DATA and refuses the candidate-local ppa-crosslayer shadow, so this row then reads a clone that carries no ablation record and answers VACUOUS rc 2. A record that IS read and does not hold is rc 1 and still fails this row. WHAT THE REVIEW DATE IS FOR: if the corpus this repository carries ever stops holding an ablation record, this row goes NOT CHECKED and the exemption above becomes a false sentence -- that is the state to look for, not the date"
run_tolerating_uncheckable "PPA ablation records (within-project)" "$ROOT" \
    python3 "$PG/ppa_ablation_check.py" --corpus "$ROOT/ppa-crosslayer"

# THE REST OF THE PPA RECORD FAMILY, wired on the ruling three lines above.
#
# The v1.11.19..v1.11.32 PPA stack landed five more gates over PPA campaign
# DOCUMENTS, and `checker_execution_wiring_audit` / `gate_is_wired_check` both
# reported all five as consulted by no automatic verdict — the same finding
# #1241 made about `ppa_head_to_head_check`, which is why that gate is on the
# line above. The lanes could not wire them: this file and the flow YAML are
# single-writer surfaces they were forbidden to touch, so the wiring is the
# lander's step and this is it.
#
# WHY HERE AND NOT THE FLOW YAML, DECIDED PER PROGRAM AND MEASURED.
# Each of these validates a RECORD, not a design — a contract, a candidate set,
# a published frontier, a coverage bundle, a pair of contracts — and no flow
# step produces any of them. A flow clause would therefore have to name a path
# nothing writes, and `test_matrix_d2_falsifiable` demands that every BLOCKING
# clause reach a content-earned FAIL: MEASURED with two of them wired at step
# 36, `test_d2_gate_has_a_reachable_fail[step36]` goes red with both clauses at
# VACUOUS_PASS, because d2 materialises an unmet `condition_files_exist` as `{}`
# and `{}` is rc 2 to every one of these gates. Paying that with an UNREDDENED
# registration would be recording a gap this lander created, which is the one
# thing the register is not for. The record gates belong beside the record gate
# that is already here; promoting them into the flow is a flow-owner change with
# its own fixtures, and it is written up as a request rather than done quietly.
#
# rc 2 ON EVERY ONE OF THEM, MEASURED 2026-08-21 AGAINST AN ABSENT RECORD, which
# is what chooses the wrapper rather than a guess:
#   ppa_contract_check           rc 2  [CANNOT CHECK] ... contract.json: absent
#   ppa_measurement_check        rc 2  [CANNOT CHECK] INPUT_ABSENT: no such bundle
#   ppa_feasibility_check        rc 2  [CANNOT CHECK] candidates not found
#   ppa_pareto_check             rc 2  [CANNOT CHECK] candidates not found
#   ppa_problem_integrity_check  rc 2  [CANNOT CHECK] baseline ...: absent
# Not one of them exits 0 on an input it never opened, and each NAMES the file
# it looked for — so `run_tolerating_uncheckable` carries "I could not look" to
# the roll-up as NOT_CHECKED instead of folding it into "I looked and it was
# clean". `run` would be wrong here for the same reason it is right for the two
# flow-document gates further down: those have a subject in this repository.
#
# LIMIT, STATED RATHER THAN LEFT TO BE FOUND. These five take an EXACT path,
# not a corpus walk, so unlike the head-to-head gate above they do not follow
# `$VIBE_IC_BENCHMARK_DATA` and a record filed under another name is not judged.
# The refusal is at least self-describing — it prints the path it opened — but
# the honest fix is a `--corpus` mode resolved through `_corpus_location`, which
# is lane-owned code this landing may not edit. Recorded as a request.
# THE OTHER FIVE, RE-AIMED AT THE RECORDS THIS REPOSITORY HOLDS (2026-08-22).
#
# All five said "no run in this repository has filed one yet". Measured against
# the tree on the day that sentence was reviewed:
#
#   contract documents  (vibeic.ppa.contract.v1)     82 committed
#   candidate sets      (vibeic.ppa.candidates.v1)   21 committed
#   contract PAIRS the two campaigns compared        80 committed
#   coverage bundles with a declared denominator      0  <- genuinely absent
#   objectives / published frontier                   0  <- genuinely absent
#
# So three of the five were not waiting for a record: they were pointed at
# `benchmark-data`, which left this repository in v1.10.56, and each took an
# EXACT path rather than a corpus, so even a re-aimed path could have judged
# only one document. The `--corpus` mode this file's own note asked for
# ("the honest fix is a `--corpus` mode resolved through `_corpus_location`")
# is now implemented on the two gates that walk a population.
#
# The remaining two are STILL uncheckable, and their declarations below now name
# the exact missing artefact and who would produce it, instead of a date. That
# is the difference between an exemption resting on evidence and one resting on
# a deadline somebody typed. `ppa-gate-audit/RESULT.md` is the measurement.

# MEASURED 2026-08-22: 21 contract(s), 0 refused, 0 undetermined, 21 accepted.
uncheckable_until 2027-02-28 "PASSES today over 21 contracts; rc 2 is reachable and must stay non-fatal because it means a document in the corpus could not be READ — an unparseable contract that was named one is kept in the population deliberately rather than dropped, and 'I could not open it' is not a finding against the run it describes. A contract that IS read and does not hold is rc 1"
run_tolerating_uncheckable "PPA measurement contract (cross-layer campaign)" "$ROOT" \
    python3 "$PG/ppa_contract_check.py" --corpus "$ROOT/ppa-crosslayer"
# MEASURED 2026-08-22: 61 contract(s), 0 refused, 0 undetermined, 61 accepted.
uncheckable_until 2027-02-28 "PASSES today over 61 contracts; rc 2 is reachable only through an unreadable document kept in the population on purpose, and that is not a finding against the run it describes. A contract that IS read and does not hold is rc 1"
run_tolerating_uncheckable "PPA measurement contract (end-to-end campaign)" "$ROOT" \
    python3 "$PG/ppa_contract_check.py" --corpus "$ROOT/ppa-e2e"
# The published corpus in the other repository, unchanged in subject and
# corrected in wording. It is the one contract row that genuinely cannot run here.
uncheckable_until 2027-02-28 "the PUBLISHED corpus lives in another repository since v1.10.56; rc 2 means VIBE_IC_BENCHMARK_DATA is unset or unreadable. It is NOT a claim that no contract exists — 82 are committed here and are validated by the two rows above"
run_tolerating_uncheckable "PPA measurement contract" "$ROOT" python3 "$PG/ppa_contract_check.py" --corpus "$ROOT/benchmark-data"

# STILL CANNOT CHECK, AND NOW FOR A REASON THAT NAMES AN ARTEFACT.
# The record half exists: `ppa-crosslayer/records/trials/b000/records_flat.json`
# carries 148 `vibeic.ppa.metric.v1` rows and is what this row is now aimed at.
# The DENOMINATOR half does not exist anywhere in this repository — measured,
# `grep -rl '"expected"' ppa-e2e ppa-crosslayer` returns nothing and all 82
# contracts carry `"metrics": []`. So the refusal changes from INPUT_ABSENT ("I
# could not find the file") to NO_EXPECTATION_SET ("I read the records and
# nothing declares what should have been measured"), which is a fact about the
# campaign rather than about the wiring. Both are rc 2 and neither is a pass.
uncheckable_until 2027-02-28 "MISSING ARTEFACT, NAMED: a document with a non-empty expected list — the (metric, scope) pairs a PPA run is REQUIRED to produce, declared before the run. Nothing in this repository declares one; the record sets it would be measured against are committed and this row now reads one, so rc 2 is NO_EXPECTATION_SET and not INPUT_ABSENT. PRODUCER: ppa_contract_build.py, which already writes the metrics key it leaves empty; the denominator belongs beside required_views_by_axis, declared from L19_CONSTRAINTS_PDK rather than inferred from whatever the run happened to emit. Writing one HERE would be composing the answer key after the exam"
run_tolerating_uncheckable "PPA measurement coverage" "$ROOT" python3 "$PG/ppa_measurement_check.py" --coverage "$ROOT/ppa-crosslayer/records/trials/b000/records_flat.json"

# MEASURED 2026-08-22: 21 set(s), 0 infeasible, 21 undetermined, 0 feasible.
# Every one is `em:FEAS_NOT_MEASURED` and `equivalence:FEAS_NOT_MEASURED`, which
# reproduces the campaign's OWN published verdict — `ppa-crosslayer/records/summary.json`
# records `feasibility_verdict: UNDETERMINED` with those two axes undetermined for
# every trial. The gate agrees with the record set and refuses to call any
# published candidate promotable, which is the honest answer.
#
# NOTE THE MISSING `--contract`, AND IT IS DELIBERATE. The shipped line passed
# one, and two different documents in this codebase are called "contract": the
# `vibeic.ppa.contract.v1` this file validates two rows up (identities and
# evidence), and the feasibility/pareto contract (required_views / limits /
# objectives), of which this repository holds ZERO. Handing this gate the first
# shape overrides the `required_views_by_axis` the candidate sets already
# declare and loses all nine axes to FEAS_VIEWS_NOT_DECLARED — measured. A
# candidates document declares its own views; that is the input to use.
uncheckable_until 2027-02-28 "rc 2 here is a CONTENT verdict over 21 adjudicated candidate sets, not an absent input: seven of nine feasibility axes are SATISFIED on every one and two (em, equivalence) carry no measurement at all, so no candidate may be called promotable. That reproduces the campaign's own published summary.json verdict. A candidate that IS measured and VIOLATES an axis is rc 1"
run_tolerating_uncheckable "PPA promotion feasibility (cross-layer campaign)" "$ROOT" \
    python3 "$PG/ppa_feasibility_check.py" --corpus "$ROOT/ppa-crosslayer"

# STILL CANNOT CHECK, AND THE SECOND MISSING ARTEFACT IS WHY IT STAYS THAT WAY.
# `objectives` could be DERIVED here: each trial's `objective.json` names the
# search's single objective (`area.design_report.um2` at a stated scope) and
# `summary.json` records the direction. What cannot be derived is a PUBLISHED
# frontier for the gate to be under test against — and without one this gate
# would recompute a frontier and then check it against itself. A gate marking
# its own paper is not a gate, so this row is left refusing.
uncheckable_until 2027-02-28 "TWO MISSING ARTEFACTS, NAMED: (1) an objectives list [{key, metric, sense, scope}] — no contract, candidates document or any other file in this repository carries that key, measured; (2) a PUBLISHED frontier.json to be the thing under test. (1) alone is derivable from each trial's objective.json + summary.json, but deriving BOTH would have this gate recompute a frontier and check it against itself, which is a manufactured pass. PRODUCER: the search runner — ppa-crosslayer/tools/summarize.py already computes the ranking RESULT.md publishes as a Pareto set and emits it as prose and tables, never as a frontier.json. Making it write one, beside the objectives it is already optimising against, takes this gate live"
run_tolerating_uncheckable "PPA frontier recomputes" "$ROOT" python3 "$PG/ppa_pareto_check.py" --candidates "$ROOT/ppa-crosslayer/records/trials/z23/candidates.json"

# EVERY PUBLISHED PAIR, NOT THE HEADLINE PAIR. This row first re-aimed at the
# one comparison each campaign quotes — cross-layer `b000` vs `z23`, end-to-end
# `baseline` vs `t028`. That decided something, and it decided about TWO pairs
# while EIGHTY sit committed here. A gate examining 2 of 80 available
# comparisons is under-aimed by exactly the argument that re-aimed it: a
# contract that drifts in trial 37 is a comparison nobody may quote, and nothing
# would have said so. `--corpus` compares the campaign baseline against every
# other contract in its tree.
#
# MEASURED 2026-08-22:
#   cross-layer  b000     vs 20 trials  ->  20 comparable, rc 0
#   end-to-end   baseline vs 60 trials  ->  60 comparable, rc 0
uncheckable_until 2027-02-28 "PASSES today over 210 pairs — 21 contracts in 1 problem group, every pair inside the group compared. It was 20 while this row ran baseline-against-each; grouping is the stronger question and the declaration has to say which one it bought. rc 2 means a contract in the corpus could not be READ — an unparseable one that was NAMED a contract is kept in the population deliberately so the pair it would have formed is reported rather than dropped, and a comparison never attempted is not a finding about either design. Two contracts that ARE read and disagree on the problem, analysis or toolchain identity are rc 1"
# `--baseline` IS GONE, and dropping it is what makes this row decide anything.
# MEASURED on a758f4adc, exactly as the line below was written:
#
#   [ppa_problem_integrity_check] REFUSE (bad invocation): --baseline/--candidate
#   and --corpus were both given. ... Give exactly one. rc=3.
#
# So both of these rows had stopped examining ANY pair. `--corpus` mode was
# rewritten to GROUP contracts by their problem identity and pair within each
# group, which needs no baseline, and the refusal of the two-flag form is
# deliberate and argued in the program. The wiring was not updated with it.
# rc 3 is a bad invocation: the row decided nothing, and it is a different and
# quieter failure than the rc 2 the rest of this block is about, because nothing
# in the roll-up distinguishes a gate the caller mis-invoked from one that ran.
#
# MEASURED with the flag removed:
#   cross-layer  21 contract(s), 1 problem group,  210 pair(s)  -> rc 0
#   end-to-end   61 contract(s), 1 problem group, 1830 pair(s)  -> rc 0
# The audit's Part 7 recorded 20 and 60 pairs for the baseline-against-each form;
# grouping compares every pair inside the group, which is the stronger question.
run_tolerating_uncheckable "PPA arms solved one problem (cross-layer campaign)" "$ROOT" \
    python3 "$PG/ppa_problem_integrity_check.py" \
    --corpus "$ROOT/ppa-crosslayer"
uncheckable_until 2027-02-28 "PASSES today over 1830 pairs — 61 contracts in 1 problem group, every pair inside the group compared. It was 60 while this row ran baseline-against-each; grouping is the stronger question and the declaration has to say which one it bought. rc 2 means a contract in the corpus could not be read, which is not a finding about either design. Two contracts that ARE read and disagree on the problem, analysis or toolchain identity are rc 1"
run_tolerating_uncheckable "PPA arms solved one problem (end-to-end campaign)" "$ROOT" \
    python3 "$PG/ppa_problem_integrity_check.py" \
    --corpus "$ROOT/ppa-e2e"

# THE PUBLISHED SENTENCE, not the record behind it. Every gate above this line
# asks whether an artefact is internally honest; none of them asks what the
# repository SAYS about it in a document a reader will quote. That gap is the
# measurement `ppa_page_claim_check` was written from: on 2026-08-21 three
# present-tense sentences on the published PPA page were true when written and
# false one landing later, and nothing could go red because they named no
# revision. This row runs the check over the report the end-to-end campaign
# publishes AS its result, together with the `claims.json` that report emits
# beside itself — the only page/claims pair in this tree where every row is
# cited by construction, which is what `--cite-numbers` requires.
#
# WHY THIS PAGE AND NOT `report/default-run/`. Both are the same generated
# document; `winner` is the arm the campaign publishes and `default-run` is the
# untuned arm kept beside it for comparison. Aiming at the published one is the
# claim a reader actually meets. MEASURED today: 35 sentence(s), 139 claim(s),
# 9 banned form(s) enforced, rc 0 — a real population, not an empty corpus.
#
# A plain `run`: rc 2 here is `[CANNOT CHECK]` (the page or the claims file
# could not be read), which is a missing prerequisite and must stay blocking
# rather than buy an exemption. rc 1 is a finding about a sentence.
run "PPA published page claims" "$ROOT" \
    python3 "$PG/ppa_page_claim_check.py" "$ROOT/ppa-e2e/report/winner/report.md" \
    --claims "$ROOT/ppa-e2e/report/winner/claims.json" --cite-numbers

# THE AUTHORISATION, checked against the tree it authorises. The actuator
# registry is what decides which programs a closure controller MAY run; an entry
# that claims `binding: EXECUTABLE` and names a program that is not in
# `programs/` is a permission granted over nothing, and it fails at the moment
# something finally tries to close a loop rather than at the moment it is
# written. `--verify-registry` resolves every EXECUTABLE claim and prints the
# population it resolved (actuators / domains / controllers) so the count is
# visible beside the verdict.
#
# NOT `--list-edges`, deliberately. That mode is the closed-loop CENSUS and it
# exits 2 by design while every declared edge is DECLARED_ONLY — which is the
# true state today and is `closed_loop_edge_check`'s question, already wired.
# Wiring the census here would be a permanently-red row reporting a fact another
# gate owns. MEASURED today: 6 actuators (1 EXECUTABLE), 9 domains
# (2 EXECUTABLE), 1 controller, every EXECUTABLE claim resolves, rc 0.
run "PPA actuator registry bindings" "$ROOT" \
    python3 "$PG/ppa_closure_run.py" --verify-registry \
    --registry "$PLUGIN/config/ppa_actuator_registry.yaml"

run "plugin version stated in prose" "$ROOT" python3 "$PG/plugin_version_prose_sync_check.py" "$ROOT"
# Its BLIND SPOT, and they are not the same question. The gate above asks whether
# a stated version AGREES with the shipped one; a claim inserted in the WRONG
# PLACE still agrees. MEASURED 2026-08-21 by replaying this rule over 400 commits
# of `origin/main`: 1370 distinct tracked markdown blobs, 25 of them carrying a
# `| Plugin version | **1.11.NN** |` fragment at `vibe-ic-marketplace/README.md`
# line 43 with no delimiter row above or below it, the number advancing release
# by release inside a "table" that never rendered as one. Every version gate
# looked at those numbers and found them correct. The sentence the fragment
# replaced was nobody's denominator, so nothing missed it.
run "table rows belong to tables" "$ROOT" python3 "$PG/doc_table_row_placement_check.py" --repo "$ROOT"
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

# vibe-ic#215/#566/#927 — THE IMAGE-VERSION GATE IS GONE, with the version it
# gated. `tools/vibeic-eda/VERSION` held vibeic-eda's version number inside THIS
# repo, so every image release needed a PR here; `sync_image_version.py --check`
# was the blocking gate that kept the install docs in step with it, and
# `--report-upstream` was the non-blocking half that asked the registry.
#
# Removed rather than fixed, because measured 2026-08-21 the mechanism had
# stopped paying for itself in both directions:
#
#   * `--check` was RED on main. Its one live pointer was
#     `crosslayer_rewrite_equivalence.py:379`, a comment recording WHICH image a
#     yosys measurement was taken on. The gate was demanding that a measurement
#     record be falsified to match an anchor;
#   * of 11 registered install docs only ONE still carried an X.Y.Z pin at all.
#     The documentation had already decoupled itself; the anchor reached almost
#     nothing;
#   * the anchor said 0.3.16 while the host running the gates had 0.3.13, so the
#     two gates that judge the IMAGE were judging one this machine does not have
#     — a multi-gigabyte pull inside a hygiene run, or a timeout reported as
#     "could not check".
#
# What the anchor was standing in for is REPRODUCIBILITY AND ATTRIBUTION, and a
# DIGEST gives that without anyone's cooperation: `_eda_image.judged_image()`
# names the image this host actually holds by the bytes it is made of, and every
# verdict-bearing report now carries that digest (`_eda_image.verdict_report`
# REFUSES to write one that does not).
#
# The one property `--check` had that is worth keeping — nothing in the tree may
# PIN an image version — moved to a shipped test that runs everywhere the plugin
# runs, instead of a repo-root tool that only runs here:
#   programs/tests/test_the_eda_image_is_resolved_not_remembered.py
#     ::test_no_shipped_file_reads_a_vibeic_eda_version_from_our_source_tree

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

# vibe-ic#1121 family, landed in the v1.11.19..v1.11.32 PPA stack and wired
# here by the lander because `flow/` and `tools/ci/` are single-writer surfaces
# the lane could not touch.
#
# ITS SUBJECT IS THE SHIPPED FLOW DOCUMENT, which is what puts it in this file
# rather than in a flow clause: a repo-wide invariant needing no PR context and
# no design run, sitting beside the two gates above that read the same document.
# It asks a question `closed_loop_edge_check` explicitly stops short of — that
# check proves a declared `closed_loop` edge is WELL-FORMED and says in its own
# words that nothing executes one — namely, for each declared edge, is there
# CODE that can take it, and what does that code prove? It refuses to let an
# edge nothing can take be reported as a closed-loop success.
#
# PLAIN `run`, and the wrapper was measured before it was chosen. On the shipped
# tree, 2026-08-21: rc 0, "22 declared closed_loop edge(s) over 69 step(s);
# DECLARED_ONLY=18, EXECUTABLE=1, REMEASURED=3, ROLLBACK_PROVEN=0". It has a
# real subject in this repository and a real denominator that it prints, so
# there is no "I could not look" state for `run_tolerating_uncheckable` to
# carry, and using that wrapper would give an rc 2 somewhere to hide.
#
# BLOCKING FROM ITS FIRST RUN IS AFFORDABLE, MEASURED: the census is green today
# and 18 DECLARED_ONLY edges are REPORTED, not failed — the tier a declaration
# gets by having no registry entry is a state the gate publishes, not a finding.
# What it fails is a citation that does not verify against the tree, so nothing
# pre-existing is being blessed and nothing pre-existing turns red.
#
# ONE LINE, no `\` continuation — `gate_discloses_denominator_check.parse_gates`
# is line-anchored, so a wrapped argv reaches its probe with the tail missing.
# THE FLOW IS NAMED FROM $ROOT, NOT LEFT TO THE PROGRAM'S OWN LOCATION.
# Both of these default to `Path(__file__).parent.parent / flow/...`, i.e. the
# tree the GATE lives in rather than the tree under test. In production those
# are the same file and the verdict is identical either way -- MEASURED, both
# gates, before and after this line: same rc, same counts. What changes is that
# a gate whose input is fixed to its own location cannot be shown to fail:
# `gate_mutation_fixtures.invoke` redirects $ROOT and nothing else, so no
# fixture could ever hand either of them a mutant flow, and both sat in
# `gate_mutation_fixture_check`'s NEW-OR-UNEXCUSED set with no way out of it.
# Naming the input is what makes the CAN-FAIL direction reachable.
run "closed-loop executable census" "$ROOT" python3 "$PG/closed_loop_executable_coverage_check.py" --flow "$ROOT/vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml"

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
uncheckable_until 2027-02-28 "SUBJECT ABSENT BY OWNER INSTRUCTION, not pointer broken. This reads an L-doc carrying a populated `fields` object, which exists only inside a published converged cell; benchmark-data has held ZERO since bcf2f94 (2026-08-20 -- none of the four withdrawn cells was a pass). rc 2 is a MEASURED zero over a corpus that WAS read, and it is NOT a claim the rule holds. The INSTRUMENT is proven separately and continuously by tools/ci/gate_fixtures/l_doc_field_producer.py, which drives it over a known-good L-doc and over one reader-without-producer. Closes on the first converged cell benchmark_evidence_publish stages; NOTHING IN THIS REPOSITORY CAN CLOSE IT, which is why it is here and not in a code change. rc 1 is UNAFFECTED and still blocks: an exemption converts only rc 2, so this gate looking and finding a defect still refuses the landing."
run_tolerating_uncheckable "L-doc field producer" "$ROOT" python3 "$PG/l_doc_field_producer_check.py" --corpus-may-be-absent

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
uncheckable_until 2027-02-28 "needs a vibeic-eda CONTAINER IMAGE on the host: it invokes both STA engines inside the digest this host resolves, and rc 2 means neither could be started (an engine that answers and disagrees is rc 1). It does NOT pull -- pass --allow-pull if that is what you mean"
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
uncheckable_until 2027-02-28 "SUBJECT ABSENT BY OWNER INSTRUCTION. CITATION_ROUTING.txt is emitted by exactly one program (benchmark_evidence_publish), only for a converged (IC x PDK) cell, and that program REFUSES a non-converged run; the corpus tracks zero of them, and zero GDS_MANIFEST.txt and zero LAYOUT_ROUTING.txt with it, so no tree anywhere was staged by that publisher. This gate is NOT path-wired to ic/ -- it reads the whole index -- so there is no pointer to repair. Closes on the first converged cell benchmark_evidence_publish stages; NOTHING IN THIS REPOSITORY CAN CLOSE IT, which is why it is here and not in a code change. rc 1 is UNAFFECTED and still blocks: an exemption converts only rc 2, so this gate looking and finding a defect still refuses the landing. NO SAMPLE PAIRS THIS ONE and that is deliberate: unlike its three neighbours it asks whether a SHIPPED FILE tells the truth about the tree it ships in, which is a question about published evidence and not about this plugin."
run_tolerating_uncheckable "citation routing is true" "$ROOT" python3 "$PG/citation_routing_is_true_check.py" --root "$ROOT" --corpus-may-be-absent

# The THIRD record in this family, and the one nothing was reading. A Phase-1
# protocol-parity sweep publishes ONE parity number over N protocols whose input
# documents are NOT of one kind -- some are the issuing body's specification,
# some an encyclopedia article, some a vendor app note. The tier is recorded as
# data in `protocol_parity/source_tier.json`, the sweep's RESULT markdown
# PUBLISHES the per-tier counts, and until this line nothing checked that the
# published counts were the counts in the data. A number that drifts from its own
# record still reads as a measurement.
#
# It asks three things of the record, and the second is the one only a gate can
# hold: (1) every protocol directory is tiered and the tier file's own `counts`
# block agrees with its `protocols` block; (2) every RESULT markdown carrying the
# `<!-- source-tier-counts -->` marker publishes counts that MATCH; (3) every
# `input/docs/<doc>` an L-doc cites either resolves in the tree or is accounted
# for by the tier record -- the same citation-followability question its two
# neighbours above ask of the published cells, asked of the parity sweep instead.
#
# THE PARITY ROOT IS RELATIVE, resolved against the cwd this gate is dispatched
# with. That is what makes the CAN-FAIL direction reachable: the engine redirects
# $ROOT and nothing else, so a root spelled from the program's own location could
# never be handed a mutant record.
uncheckable_until 2027-02-28 "SUBJECT ABSENT: protocol_parity/ is a PUBLISHED SWEEP TREE and left this repository with the rest of the corpus in v1.10.56. rc 2 here is the program's own not-a-directory refusal, which NAMES the path it looked for -- it is not a claim that any record is honest. The INSTRUMENT is proved continuously by tools/ci/gate_fixtures/phase1_parity_source_tier_record.py, which drives it over a two-protocol record whose RESULT markdown agrees with its data and over the same record with ONE published count moved. Closes the day a parity sweep is published in-tree. rc 1 is UNAFFECTED and still blocks: an exemption converts only rc 2, so this gate reading a record and finding it dishonest still refuses the landing."
run_tolerating_uncheckable "phase1 parity source-tier record" "$ROOT" python3 "$PG/phase1_parity_source_tier_check.py" protocol_parity

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

# --- the upstream-parity family (vibe-ic#1082 compose step) -----------------
# Three checkers landed together and NOTHING but their own unit tests ran any
# of them: `checker_execution_wiring_audit` named all three, and
# `gate_is_wired_check` named the two below that are gate-shaped. A checker a
# fixture proves and no tree ever exercises is verified against its author's
# MODEL of the artefacts, never against the artefacts.
#
# They sit together and next to the attribution gate above because they are the
# same population and the same question: what this repository BORROWED from an
# upstream flow, and whether the borrowing is still maintained rather than
# merely once true.
#
# THE SUBJECT IS PASSED EXPLICITLY, not defaulted. Each of the three defaults to
# the directory it is installed in, and a gate that reads its own installation
# cannot be shown a mutated input — so the declaration names `$PLUGIN`, which
# is the same tree in production and is what makes the two-fixture pair
# (tools/ci/gate_fixtures/) able to drive the real declared command.

# The register half: every upstream name inside a registered entry is in exactly
# one class. rc 2 if the register cannot be read — an empty register passes
# every property it states, which is the one verdict it must never return.
run "upstream contract parity"          "$ROOT" python3 "$PG/upstream_contract_parity_check.py" \
    --register "$PLUGIN/programs/upstream_contract_parity.json"

# The declaration half: a module that says it mirrors upstream must name a test
# that READS upstream. rc 2 on zero declared mirrors — that is a question with
# no subject, not a clean answer to it.
run "declared upstream mirrors are pinned" "$ROOT" python3 "$PG/upstream_mirror_is_pinned_check.py" \
    --programs-dir "$PLUGIN/programs"

# The anchor half, and the only one of the three whose input is HOST-dependent:
# it opens the upstream file each pin names and looks for the anchor text in it.
# `--upstream-root "$ROOT"` says an upstream tree VENDORED INSIDE THE CHECKOUT
# also counts; nothing vendors one today, so on a bare host every pin resolves
# to NOT_ON_HOST and the gate refuses rather than reporting agreement it never
# measured.
uncheckable_until 2027-02-28 "needs an INSTALLED upstream tool tree on the host for ONE of its two legs. The STRUCTURAL leg needs no tree and runs everywhere: it evaluates each UPSTREAM_PINS declaration and requires every pin to carry both an upstream key and an anchor key. MEASURED on a bare checkout, 5 of 5 declared pin(s) pass it, and it discriminates rather than merely passing -- drop one pin's anchor and the count goes to 4 with rc 1 PIN_INCOMPLETE; make the declaration non-literal and it goes to 0 with rc 1 PIN_UNREADABLE, both on a host with no upstream tree anywhere. The COMPARISON leg is what rc 2 declines: it opens the file each pin names and looks for the anchor text, and on a bare checkout none of the declared upstream files resolves under any probed root. The refusal PRINTS both halves -- how many pins were structurally validated, and every root probed with whether the directory exists and how many declared upstream files were found under it -- so this row can never read as a gate that checked nothing. rc 2 is NOT 'the re-implementations agree' and the gate says so in those words. An anchor ABSENT from a file it DID read is rc 1 and still fails this row"
run_tolerating_uncheckable "upstream pins still resolve" "$ROOT" python3 "$PG/upstream_reimplementation_pin_check.py" \
    --programs-dir "$PLUGIN/programs" --upstream-root "$ROOT"

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
uncheckable_until 2027-02-28 "needs a vibeic-eda CONTAINER IMAGE on the host: --from-image reads the PDK layer tables out of the digest this host resolves, and rc 2 means the PDKs could not be read at all. It does NOT pull -- pass --allow-pull if that is what you mean"
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
uncheckable_until 2027-02-28 "SUBJECT ABSENT BY OWNER INSTRUCTION. This sweeps producer records carrying a declared reference inside a published cell; the corpus holds zero such cells since bcf2f94. MEASURED, so the alternatives are closed rather than untried: repointing --corpus at protocol_parity gives 87 cells and 0 producer records and refuses as LOST REACH (examined 9 -> 0); widening to the corpus root gives the same line. Re-sealing the register would need --write-baseline, which this repo forbids. The INSTRUMENT is proven by tools/ci/gate_fixtures/cross_layer_reference_regression.py at the recorded denominator of 9. Closes on the first converged cell benchmark_evidence_publish stages; NOTHING IN THIS REPOSITORY CAN CLOSE IT, which is why it is here and not in a code change. rc 1 is UNAFFECTED and still blocks: an exemption converts only rc 2, so this gate looking and finding a defect still refuses the landing."
run_tolerating_uncheckable "cross-layer reference regression" "$ROOT" python3 "$PG/cross_layer_reference_check.py" --corpus "$ROOT/benchmark-data/ic" --corpus-may-be-absent

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
uncheckable_until 2027-02-28 "SUBJECT ABSENT BY OWNER INSTRUCTION. This sweeps published run trees for a reports/ directory carrying step verdicts; the corpus holds zero published run trees since bcf2f94, so the sweep examines nothing and says VACUOUS_PASS rather than passing. The INSTRUMENT is proven by tools/ci/gate_fixtures/step_fail_bubbles_up.py over two run trees with four readable verdicts, two of them FAIL. Closes on the first converged cell benchmark_evidence_publish stages; NOTHING IN THIS REPOSITORY CAN CLOSE IT, which is why it is here and not in a code change. rc 1 is UNAFFECTED and still blocks: an exemption converts only rc 2, so this gate looking and finding a defect still refuses the landing. The per-cell invocation earlier in this file is unaffected and still blocks."
run_tolerating_uncheckable "step FAIL bubbles up" "$ROOT" python3 "$PG/step_internal_fail_bubble_up_check.py" --corpus "$ROOT/benchmark-data/ic" --corpus-may-be-absent
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
uncheckable_until 2026-11-30 "IT IS A MISSING PREREQUISITE, AND THIS DECLARATION USED TO DENY BEING ONE. Measured 2026-08-22: the gate prints '--dir <ROOT>/benchmark-data is not a directory' — it opens NO report. The previous wording said \"KNOWN DEBT, not a missing prerequisite: all committed compliance reports predate the blockers key\", which is a claim about the CONTENT of reports nothing read; it was plausibly true before v1.10.56 moved benchmark-data to its own repository, and has been a statement about an absent tree ever since. It also promised to go \"green by itself on the first contract-carrying report committed\" — it cannot, because no report committed HERE is in the directory it opens. MISSING INPUT, NAMED: a readable benchmark-data corpus, i.e. VIBE_IC_BENCHMARK_DATA pointed at a clone of the published-corpus repository. NOT given --corpus-may-be-absent deliberately: that flag returns rc 0 NO_CORPUS, which is a pass printed over a population nobody opened. THE REVIEW DATE IS DELIBERATELY UNCHANGED at 2026-11-30 even though the mechanism it was defending turned out to be false: re-dating an exemption is forbidden outright, and the argument for moving it here — that a date guarding a false reason means something different from one guarding a named absence — is exactly the kind of reasoning an author uses to widen his own deadline. The text is corrected; the clock is not touched"
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
# THE OTHER DERIVED INVENTORY, and it had no landing check at all.
# `SKILL_INVENTORY.json` is the AUTHORITATIVE skill count — its own `_comment`
# says the website must read `total` from it — and it is generated from the
# `skills/*/SKILL.md` folders. Its generator shipped with `--check` and the
# instruction "wire into CI", and nothing wired it: the only thing running it
# was `tests/test_skill_inventory_no_drift.py`, so the freshness of a published
# number depended on that one test file continuing to exist. The hand-maintained
# figure this replaced had already drifted (the site said 55 with 57 on disk),
# which is the drift the artefact exists to make impossible.
#
# SAME SHAPE AS `programs index fresh` ABOVE: a committed derived file, a
# generator that regenerates it, and `--check` as the landing question.
run "skill inventory fresh"              "$ROOT" python3 "$PG/gen_skill_inventory.py" --check --plugin "$PLUGIN"

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
uncheckable_until 2027-02-28 "needs a COMPLETE clone AND the artefact to have been generated, and only the first half used to be stated. It REFUSES (rc 2) on a shallow --depth checkout rather than reporting the smaller, entirely plausible figure that state produces; a hand-edited figure is still rc 1. MEASURED 2026-08-22 on a COMPLETE checkout (git rev-parse --is-shallow-repository = false): rc 2 anyway, and the reason is not depth — 'docs/ENGINEERING_EVIDENCE.md does not exist'. That file is NOT tracked (git ls-files finds none), so on any clean checkout it is absent until the generator this very row invokes has run. Blaming shallowness alone sends a reader to check their clone depth when the answer is that nothing generated the file yet"
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

# THE THIRD MEMBER OF THAT FAMILY, and the one the two above cannot reach. They
# ask what a gate SAYS about its own reach. This one asks whether a population an
# emitter PRINTS still equals the population it counts, and whether the test
# pinning that number still names a value the emitter can produce. MEASURED
# 2026-08-21: a lane added a third repair to a post-route block, moved the
# emitter's printed denominator from two to three, and left the test asserting
# the old ratio — so the test failed for the right reason with the wrong message.
# Reach is small and PRINTED on every run (a handful of denominators and pins);
# a verdict that did not state it would overstate itself.
run "a printed population agrees with its pin" "$PLUGIN" python3 programs/emitter_population_pin_check.py

# vibe-ic#564 — the SIBLING property. The gate above requires a PASS to say how
# much it looked at; this one requires a gate that looked at NOTHING to refuse.
# Both are needed: the P0 umbrella reads exit codes, so a gate that discloses
# `0` in prose and returns `0` in rc is a silent pass, and the disclosure gate
# passes it correctly.
run "a zero denominator refuses" "$ROOT" python3 "$PG/gate_zero_denominator_refuses_check.py"

# THE OTHER HALF OF THE DENOMINATOR QUESTION, and the one the three above cannot
# reach. They ask what a PASS disclosed about its reach. This asks what a
# REFUSAL disclosed about its reach: an absence verdict — a `*_NOT_FOUND` /
# `*_ABSENT` / `*_MISSING` refusal — must name WHERE it looked, or a reader
# cannot tell "it is in neither of the two places it is declared" from "I opened
# one of them". Landed with nothing but its own unit test running it.
# `--programs-dir` names the subject for the same reason the upstream family
# above does: the default is this gate's own installation.
run "absence verdicts name where they looked" "$ROOT" python3 "$PG/absence_verdict_names_its_search_space_check.py" \
    --programs-dir "$PLUGIN/programs"

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
# session bound this line used to carry is gone.
#
# THE CLAIM THAT USED TO STAND HERE -- "it was the LAST SURVIVING USE in this
# repo of an idiom the repo has already retired" -- WAS FALSE, and stayed false
# for three versions. MEASURED 2026-08-20 at 9cc09b863 (v1.11.5), FOUR live
# requests remained: `programs/tests/test_pytest_per_file_junit.py:389`, two in
# `programs/tests/test_issue1181_probe_budget_and_summary.py`, and the DEFAULT
# RUNNER of `tools/core_agent/covered_by.py`. They cost 28 red cells on the
# landing gate in the anchored image that vanished on any host with an ambient
# pip install -- a set difference of 28 whose entire content was the runtime,
# not the code under test. The claim was true of every file anybody had
# PINNED, and each of the five pins was scoped to one named file, so none of
# them could see the sixth. `retired_pytest_plugin_request_check.py` below is
# the tree-wide form, and it is what makes a claim like this one checkable
# instead of merely asserted in a comment.
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
# ptmo/2026-08-20 — the tree-wide form of a retirement that had been enforced
# five times, each time in ONE named file, and had therefore leaked into four
# files nobody pinned. `-p <name>` is a hard import: pytest dies in its
# pre-parse when the module is absent, and `pytest-timeout` is absent from the
# anchored runner image AND from its newest tag. MEASURED, same 90 cases, same
# tree: 30 red in the image, 3 on a host, 28-test set difference, all of it
# this cause. BLOCKING: `run` fails the suite on any non-zero rc, and the gate
# returns 2 rather than 0 when it could not read a file or examined none.
run "no retired pytest plugin request" "$ROOT" python3 "$PG/retired_pytest_plugin_request_check.py" "$ROOT"
# The other half of the same measurement. `retired_pytest_plugin_request_check`
# above refuses a SOURCE file that asks for a plugin the runtime may not carry;
# this one refuses a RESULT that does not say which runtime produced it. Both
# come out of the 28-of-127 set difference recorded in the paragraph above: those
# 28 failures were charged to the revision under test, and 26 of them vanished on
# a second runtime, because nothing on the aggregate named the runtime and so two
# aggregates from different runtimes subtracted cleanly and silently. Neither
# `retired_pytest_plugin_request_check` nor `landing_pytest_runtime_preflight`
# writes anything onto the RESULT, which is the gap this closes.
#
# The gate DECIDES per aggregate: an aggregate that carries {image, interpreter,
# unimportable_plugins} is rc 0, one that omits any of them -- or fills it with a
# placeholder like "unknown"/"n/a", which is how the first version of this rule
# passed an aggregate naming no runtime -- is rc 1 and FAILS this suite. Its
# `--diff A B` arm additionally REFUSES to subtract two aggregates whose runtime
# stamps disagree.
uncheckable_until 2027-02-28 "rc 2 here is NO TEST AGGREGATE IN THIS TREE, never a verdict about one, and it is this repository's normal state today -- MEASURED at the wiring commit: 'examined 0 test aggregate(s)', over a walk of every tracked .json. That is not an accident of a checkout: the rule's subject is the per-case record a TEST ARM writes, and this repository's only run summary is written by tools/ci/_gate_dispatch.sh into a temporary directory and let go -- and that document is a GATE PROFILE (it names benchmark_data_sha and corpus_inputs, i.e. the CORPUS) and not a test aggregate, so it is out of scope by the gate's own narrowing even if it were kept. The gate's discrimination is therefore proved by fixture rather than by this tree: tools/ci/gate_fixtures/a_test_aggregate_names_its_runtime.py drives both directions over the SAME one-aggregate corpus and the can-fail arm goes rc 1 on the placeholder-identity seam. WHAT THE REVIEW DATE IS FOR: the day any arm starts KEEPING its per-case aggregate in the tree, this row starts deciding and this exemption must go -- that is the state to look for, not the date. An aggregate that IS read and does not name its runtime is rc 1 and still fails this row."
run_tolerating_uncheckable "a test aggregate names its runtime" "$ROOT" \
    python3 "$PG/pytest_aggregate_carries_its_runtime_identity.py" "$ROOT"
run "argparse help format"              "$PLUGIN" python3 programs/argparse_help_format_check.py
run "dead plugin path"                  "$PLUGIN" python3 programs/dead_plugin_path_check.py
run "ic_expert_db health"               "$PLUGIN" python3 programs/ic_expert_db_health_audit.py
run "verdict token propagation"         "$PLUGIN" python3 programs/verdict_token_propagation_check.py
run "signoff gate self-skip"            "$PLUGIN" python3 programs/signoff_gate_self_skip_consistency_check.py
run "waveform artifact hygiene"         "$PLUGIN" python3 programs/waveform_artifact_hygiene_check.py
# TWO OF THE SIX ANTI-FABRICATION GATES, DECLARED INDIVIDUALLY. They were
# reachable only through `tools/ci/run_plugin_self_audit.sh`, which
# `.github/workflows/` used to run and nothing does since both workflows became
# `.disabled` — so every one of them read as wired and none of them ran.
#
# ONE `run` LINE EACH RATHER THAN ONE FOR THE SCRIPT, and that is what made them
# fixturable at all. Wiring the script means the fixture subject must carry the
# runner AND every gate AND enough of the plugin's import surface for six
# programs to load; three attempts failed exactly there. Declared individually,
# `$PG` keeps pointing at the real gate and the subject only has to be its
# INPUT — a CHANGELOG and one program. That is the same shape as the sixteen
# above, and it works for the same reason.
run "changelog metric reproducibility"  "$ROOT" python3 "$PG/changelog_metric_reproducibility_check.py" "$PLUGIN"
run "changelog command reproducibility" "$ROOT" python3 "$PG/changelog_command_reproducibility_check.py" "$PLUGIN"
run "literal verdict keyword"           "$ROOT" python3 "$PG/literal_verdict_keyword_check.py" "$PLUGIN"

# SEVENTEEN DOCTRINE-RATCHET GATES, EACH WITH A FIXTURE THE EXERCISER
# ACCEPTED.
# Named after the rule each enforces, authored with committed baselines during a
# capture campaign, and then reachable from nothing. A regression guard nobody
# runs guards nothing — and these are the easiest in the tree to have missed,
# because each one PASSES. A failing gate gets noticed; a green gate nobody runs
# looks exactly like a green gate that ran.
#
# EACH CARRIES `tools/ci/gate_fixtures/<slug>.py` with can_pass AND can_fail, and
# each pair was driven through `test_gate_fixtures_discriminate` — a fixture that
# cannot make its gate go red proves nothing, which is what that bar is for.
#
# FIVE TAKE THE ROOT POSITIONALLY AND MUST NOT BE NORMALISED to `--root`: for
# `local clone`, `measurement only artefact`, `provenance value`, `prepared
# checkout` and `printed remedy` that flag is `unrecognized arguments` -> rc 3,
# a bad invocation on every arm. `only the declaring step` carries `--self-test` because that
# program's own header calls its negative control "part of the gate".
#
# FOUR SIBLINGS ARE ABSENT ON THEIR OWN WRITTEN INSTRUCTION.
# `checker_population_is_structural_not_filename_shaped_census` and
# `content_pinned_authority_verified_only_at_merge` reach a failing status only
# under `--strict`, and their docstrings say "THIS IS A CENSUS, NOT A GATE. IT
# MUST NOT BE WIRED AS A BLOCKING CHECK" and "VERDICT CLASS: ADVISORY ... it must
# stay advisory". Measured: `--strict` reddens this lane over 47 and 13
# PRE-EXISTING findings. Wiring a census over its author's objection to reach a
# number is the ritual this batch is against.
#
# `local_clone_does_not_borrow_objects_census` IS ALSO ABSENT, and its reason is
# NOT the same one — saying it is invites the next reader to wire it on the
# strength of a measurement nobody took. MEASURED on this tree: `--strict` is
# rc 0 (0 borrowing clones and 0 inventory rows over 1454 modules and 24 shell
# scripts), so it would not redden this lane at all.
#
# It stays out for two reasons that do not depend on today's count. Its header
# carries the same instruction — "THIS IS A CENSUS, NOT A GATE. IT MUST NOT BE
# WIRED AS A BLOCKING CHECK" — and the fixture bar cannot be met either way:
# declared non-strict, the only non-zero status it can reach is the rc-2
# empty-corpus path, which `gate_mutation_fixtures` refuses by name ("a can_fail
# that is red because the corpus went to zero proves the vacuity path and
# nothing about the predicate"); declared `--strict`, it is a blocking gate over
# its author's objection.
#
# AND IT IS NOT COVERAGE THIS LANE LOSES. Its refusing sibling
# `local_clone_does_not_borrow_objects` is wired above, on the same predicate,
# over a population that CONTAINS this one's. Driven on a tree seeded with two
# borrowing clones, one under `programs/` and one under `benchmark/`: the gate
# named BOTH and failed; the census named only the `programs/` one, because it
# walks `programs/` + `tools/` and the gate walks the repo. The census's one
# unique feature is `--inventory` grandfathering, and the gate's docstring says
# having no inventory is the point — it refuses where the census would record.
#
# `explicit_argument_outranks_the_environment_pointer_census` is the FOURTH, and
# it is recorded here (2026-08-25) so that its absence is a DECISION and not an
# omission the next orphan sweep re-litigates. It carries the same sentence
# verbatim — "THIS IS A CENSUS, NOT A GATE. IT MUST NOT BE WIRED AS A BLOCKING
# CHECK" — and adds "nothing in the flow should pass [--strict]".
# THE MEASUREMENT IS THE OPPOSITE OF THE OTHER THREE and is stated because it
# would otherwise look like the reason: `--strict` on this tree is rc 0 over a
# real population (1 site classified, 1 inventoried, 0 unrecorded, 0 stale), so
# wiring it would cost a landing NOTHING today. It stays out on the instruction,
# not on the cost. Without `--strict` its findings path returns 0 by design, so a
# `run` line would be a permanently green declaration whose only red is the
# rc-2 empty-population refusal — and `gate_mutation_fixtures` refuses a can_fail
# that reaches its refusal by emptying the corpus, so the pair could not be
# built honestly either.
# ITS RULE IS NOT UNGUARDED, BUT IT IS NOT FULLY GUARDED EITHER.
# `explicit_argument_outranks_the_environment_pointer` is wired below and
# refuses the half of the contract that is uncontested (a reader that can
# redirect its subject must SAY so). The census's half — the guard POLARITY,
# `if _env and args.tree: args.tree = _env` versus the absent form — is enforced
# by nothing, which is a debt this note records rather than hides.
#
# THE SEVENTEENTH, `printed remedy`, ARRIVED ON 2026-08-25 out of the same
# capture and was reachable from nothing but its own unit test. It asks whether
# a refusal that prints "run this to fix it" printed a line that RUNS: the
# composed EDA image parses the arguments after the image reference, so a
# printed `docker run ... <image> <command>` hands the command to the entry
# point, which answers `[ERROR] Unexpected option` and never runs it. Recorded
# verbatim in `container_image_provenance.py`, and the exit is NON-zero, so the
# reader's honest conclusion is that the refusal is broken rather than that its
# message is stale.
#
# RUN BEFORE WIRING, on this tree: `examined 100 printed string(s) naming docker`,
# rc 0 — a real population, not an empty scan, and rc 2 NOT CHECKED is what it
# returns when that population is empty. Its fixture moves TOKEN ORDER inside a
# single printed remedy, so both arms examine exactly one.
run "declaration searched only inside a truncated" "$ROOT" python3 "$PG/declaration_searched_only_inside_a_truncated_window.py" --root "$ROOT"
run "declared invocation accepted by its own pars" "$ROOT" python3 "$PG/declared_invocation_accepted_by_its_own_parser.py" --root "$ROOT"
run "denial that constitutes the value it appears" "$ROOT" python3 "$PG/denial_that_constitutes_the_value_it_appears_to_negate.py" --root "$ROOT"
run "invocation proved by parse not by text" "$ROOT" python3 "$PG/invocation_proved_by_parse_not_by_text.py" --root "$ROOT"
run "local clone does not borrow objects" "$ROOT" python3 "$PG/local_clone_does_not_borrow_objects.py" "$ROOT"
run "measurement only artefact is not a verdict s" "$ROOT" python3 "$PG/measurement_only_artefact_is_not_a_verdict_source.py" "$ROOT"
run "only the declaring step writes its output ce" "$ROOT" python3 "$PG/only_the_declaring_step_writes_its_output_census.py" --root "$ROOT" --self-test
run "population guard asserts equality not a floo" "$ROOT" python3 "$PG/population_guard_asserts_equality_not_a_floor.py" --root "$ROOT"
run "population pin without its member set" "$ROOT" python3 "$PG/population_pin_without_its_member_set.py" --root "$ROOT"
run "prepared checkout states the revision it hol" "$ROOT" python3 "$PG/prepared_checkout_states_the_revision_it_holds.py" "$ROOT"
run "printed remedy runs as printed" "$ROOT" python3 "$PG/printed_remedy_runs_as_printed.py" "$ROOT"
run "provenance value is resolved not constant" "$ROOT" python3 "$PG/provenance_value_is_resolved_not_constant.py" "$ROOT"
run "published absence claim is rechecked against" "$ROOT" python3 "$PG/published_absence_claim_is_rechecked_against_the_tree.py" --root "$ROOT"
run "reference control resolved through a mutable" "$ROOT" python3 "$PG/reference_control_resolved_through_a_mutable_ref.py" --root "$ROOT"
run "registry is the iteration domain" "$ROOT" python3 "$PG/registry_is_the_iteration_domain.py" --root "$ROOT"
run "spawned gate whose status is discarded" "$ROOT" python3 "$PG/spawned_gate_whose_status_is_discarded.py" --root "$ROOT"
run "two input selectors given together must refu" "$ROOT" python3 "$PG/two_input_selectors_given_together_must_refuse.py" --root "$ROOT"

# THE FIFTH SIBLING, ADMITTED 2026-08-25 AFTER ITS VERDICT WAS REPAIRED. This
# gate was on the excluded list below — "exit 1 on a GENUINE finding" — and the
# finding was NOT genuine. It reported the `drv` feasibility axis structurally
# unprovable, on a claim about the repository drawn from a directory: its scan
# root was `programs/`, and both producers that declare the four `timing.drv.*`
# keys as plain literals live outside it (`ppa-crosslayer/tools/drv_records.py`,
# `ppa-e2e/tools/signoff_records.py`). The same verdict was measured false from
# the other side by `every_required_metric_key_has_a_producer` — "That verdict
# was FALSE, and false in the blocking direction" — and recorded as F15 in
# docs/findings/2026-08-22-two-capture-distillation-branches-verified.md.
#
# THE REPAIR IS THE TWO-PART ONE F15 MEASURED, because widening alone leaves
# `timing.drv.violations` unresolved: the population was the relation "in the
# `_ppa` package or IMPORTS it", and one real producer names `_ppa` only in its
# prose. So the walk is now the whole repository and the producing side is also
# admitted by what a module EMITS — constructs a `"metric"` record, statuses it
# MEASURED / NOT_MEASURED, and WRITES it. The consumer does the first two and
# never the third, so the exclusion that makes this gate discriminate at all is
# preserved and was checked directly.
#
# MEASURED after the repair, at this tip: 10 axes, 40 -> 53 emitting modules,
# 146 -> 192 declared names, 1 -> 0 unprovable axes, rc 1 -> 0. Its own suite
# is 8/8 — THREE of those tests encoded the false verdict and were re-derived,
# one of which (`the consumer is excluded ...`) asserted the unprovable list was
# non-empty and so could not pass on ANY tree where the gate passes.
run "gate proof vocabulary has a producer" "$ROOT" python3 "$PG/gate_proof_vocabulary_has_a_producer.py" --root "$ROOT"

# The SEVENTEENTH of that family, wired separately because it did not land with
# the sixteen: when they were measured it exited 1 on a GENUINE finding and
# would have blocked a landing on debt that change did not own.
#
# THE DEBT IS PAID IN THIS CHANGE, so the exclusion no longer applies. Both
# findings were `phase3_one_shot_runner` reports that carried their basis in
# prose and never in the one spelling `_sta_basis.declared_basis` reads:
# `power.rpt` wrote `basis:` / `POWER_BASIS:` beside a `basis_stamp` it had
# already computed, and `si_crosstalk.rpt` (Step 27, on the routed design)
# wrote none at all. Both now stamp `STA_BASIS:`, so both rejoin the sign-off
# evidence set instead of being dropped as undeclared.
#
# RUN BEFORE WIRING, on this tree: rc 0, over 4 emitter(s) of 8 flow-declared
# timing/power reports plus 9 sibling reports in 1 module judged by the
# convention arm — not an empty scan, and rc 2 (no flow, no declaration, no
# identifiable emitter) is a REFUSAL here rather than a pass, so a subject that
# lost its corpus cannot read as green.
run "signoff report states its stage" "$ROOT" python3 "$PG/signoff_report_states_its_stage.py" "$ROOT"

# THREE MORE FROM THE SAME CAPTURE CAMPAIGN, AND THE SAME REASON THEY WERE
# MISSED: authored, tested, merged, and then invoked by nothing but their own
# test. Each PASSES on this tree today over a LIVE, NON-EMPTY denominator, which
# is exactly why nobody noticed — a failing gate gets noticed, a green gate
# nobody runs looks identical to a green gate that ran.
#
# EACH CARRIES `tools/ci/gate_fixtures/<slug>.py` with can_pass AND can_fail,
# driven through `test_gate_fixtures_discriminate`, and in every pair the
# mutation is the defect the gate's OWN docstring was written for, with the
# denominator held equal across the two arms.
#
# ALL THREE TAKE THE ROOT POSITIONALLY AND MUST NOT BE NORMALISED to `--root`:
# each parser declares `root` as `nargs="?"` (and `cross_design_identity_check`
# declares `projects` as `nargs="+"`), so `--root` is `unrecognized arguments`
# -> a bad invocation on every arm. Read from `--help`, not assumed.
#
# WHAT EACH ONE MEASURES HERE TODAY:
#
#   `declared_basis_matches_the_session_inputs` — 22 (session, report) pairs,
#   all 22 declaring a stage, 0 findings. Every one of the 22 is a POWER
#   analysis deck beside its own report (`ppa-crosslayer/records/trials/*/diag/
#   power_postroute.{tcl,rpt}` and two in `ppa-e2e/diag/`), which is precisely
#   the population the rule was measured on: a report headed post-layout whose
#   session loaded no extracted parasitics, publishing 0.306 mW against the
#   post-route session's 0.573 mW and a whole clock group at 0.000 mW.
#   NOT WIRED INTO FLOW STEP 33 (power analysis), and that was checked rather
#   than assumed: `phase3_one_shot_runner` writes the deck as
#   `power_<top>.tcl` beside `power.rpt`, and `_pairs()` matches on a SHARED
#   STEM, so a design run yields ZERO pairs and the clause would be rc 2 on
#   every run forever. The live corpus is here, so the gate is here.
#
#   `explicit_argument_outranks_the_environment_pointer` — 7 in-scope
#   corpus-pointer readers, 0 findings, plus 2 readers outside the scope
#   DISCLOSED by path on every run. It refuses only the half of the pointer
#   contract that is UNCONTESTED (a reader that can redirect its subject must
#   say so); the live split over whether the pointer may WIN is argued in the
#   program's own docstring and is deliberately not arbitrated here.
#
#   `cross_design_identity_check` — 2 project dirs, 7 report-class artefacts,
#   0 byte-identical pairs. It is the "exists, UNWIRED" row of the capture's
#   own already-program table, listed in `checker_execution_wiring_baseline
#   .json` with the note "unwired for lack of a CALLER, not for lack of an
#   input". THE SUBJECT IS SPELLED OUT rather than globbed because the fixture
#   engine substitutes `$ROOT` token-wise and can drive no shell expansion:
#   these two directories are this repository's ONLY tracked pair of DIFFERENT
#   designs each carrying its own `reports/` tree, which is the exact
#   population the rule needs (>= 2 designs, report-class artefacts). It runs
#   with the parser's default `--allow`, so `ir_drop.json` / `power.json`
#   wrappers keep their CONDITIONAL exemption; `--allow-honest-na` is NOT
#   passed, so no verdict-only shape is exempted here.
run "report basis matches its session inputs" "$ROOT" python3 "$PG/declared_basis_matches_the_session_inputs.py" "$ROOT"
run "explicit argument outranks the env pointer" "$ROOT" python3 "$PG/explicit_argument_outranks_the_environment_pointer.py" "$ROOT"
run "cross-design report identity" "$ROOT" python3 "$PG/cross_design_identity_check.py" \
  "$ROOT/docs/research/fleet_run_folder_triage_evidence/112/_gk198_gk/ibex" \
  "$ROOT/docs/research/fleet_run_folder_triage_evidence/112/_gk198_gk/opentitan_aes"

# THE TWELFTH CHIP-PATH RULE, RE-HOMED. `generated_values_state_whether_they_
# were_read_or_defaulted` is the last member of the family `test_chip_path_
# rules_rc_contract` pins as one rc contract; five of its siblings are declared
# above and this one was reachable from nothing but that contract test.
#
# WHAT IT IS ABOUT: a value that could have come from the design's own documents
# or from a generator's fallback is not self-describing. The measured instance
# signed a run off at a last-resort clock period of 20 where the documents
# declared 24 — a 20 % over-constraint nobody requested — and the artefact was
# byte-identical either way. `declared_clock_period` already returns the
# DISCLOSURE beside the value; what this rule adds is that a CALLER may not take
# the value and drop the disclosure, which re-creates the defect one layer up.
#
# IT TAKES THE ROOT POSITIONALLY, like the five named above: `--root` there is
# `unrecognized arguments` -> rc 3, a bad invocation on every arm.
#
# RUN BEFORE WIRING, on this tree: `examined 3 call site(s) of 2 read-or-default
# helper(s)`, rc 0. A real population, not an empty scan, and the rc-2 NOT
# CHECKED tier is what it returns when that population is empty.
run "generated values state read or defaulted" "$ROOT" python3 "$PG/generated_values_state_whether_they_were_read_or_defaulted.py" "$ROOT"

# THE PROTOCOL-DETECTOR CROSS-FIRE MATRIX, RE-HOMED (2026-08-25). Every
# module-level `is_<stem>` exported by a `<stem>_protocol_synth.py` is run
# against EVERY benchmark's content blob and must fire on its OWN and on no
# other, modulo the documented derived-sibling allowlist. Both directions fall
# out of the same matrix — a NEW detector firing on an existing benchmark, and
# an existing detector firing on a NEW one — which is why it is one program and
# not a per-protocol test. Promoted to a first-class program at v0.2.13 and then
# reachable from nothing: two pytest files import its HELPERS, and `main()` had
# no caller at all.
#
# `--blob superset` is the strictest of its four: the source spec plus ALL
# generated L-docs, which is the blob the paired pytest guard pins.
#
# `run_tolerating_uncheckable`, and the corpus is why. `benchmark-data/` moved
# to its own repository at v1.10.56, so `$ROOT/benchmark-data/...` is absent on
# an ordinary checkout and rc 2 — "I could not look" — must never share an exit
# code with "I looked and it was clean". The tree-local
# `programs/tests/fixtures/synthetic_benchmark_phase1/` was measured as an
# alternative and REJECTED: `.gitignore:127` ignores it and `git ls-files`
# returns 0 of the 56 files, so it is rebuilt by the test suite and absent from
# any fresh clone. Aiming a landing gate at it would make the verdict depend on
# whether the reader had run pytest — the exact host-dependence
# `gate_host_independence_check` exists to refuse.
#
# WHAT rc 2 CANNOT BE BOUGHT WITH, and this is the half that had to be built:
# until today `--benchmark-dir <EMPTY DIR>` printed `benchmarks=0` and then
# `ALL_PASS` at rc 0 (docs/findings/2026-08-22-a-zero-denominator-green-outside-
# the-gate-that-forbids-it.md — `gate_zero_denominator_refuses_check` forbids
# that shape and could not see this program, whose filename does not end in
# `_check.py`). Both arms of the matrix now return the NOT-CHECKED tier when
# either axis is empty, so the tolerated rc 2 cannot be reached by a corpus that
# exists and contains nothing.
#
# ITS FIXTURE RUNS IT FOR REAL. `tools/ci/gate_fixtures/` builds one benchmark
# under the subject's own `benchmark-data/evaluation/phase1_parity`, so both
# arms present 86 real detectors with one benchmark and differ only in whether
# that benchmark's documents carry a second protocol's signature: rc 0 / rc 1,
# same denominators.
#
# ONE LINE, no `\` continuation: the denominator probe and the host-independence
# probe both parse this file with a single-line `run(?:_\w+)?\s+"label"...` regex.
uncheckable_until 2027-02-28 "needs a clone of the published benchmark-data corpus: benchmark-data/ moved to its own repository at v1.10.56, so <root>/benchmark-data/evaluation/phase1_parity is absent on an ordinary checkout and rc 2 means no benchmark could be read at all -- a detector that genuinely fires outside its own benchmark is rc 1, and an EMPTY corpus is rc 2 as well rather than a green"
run_tolerating_uncheckable "protocol detector no-misfire matrix" "$ROOT" python3 "$PG/protocol_detector_no_misfire_matrix.py" --blob superset --benchmark-dir "$ROOT/benchmark-data/evaluation/phase1_parity"

# SEVENTEEN DOCTRINE-RATCHET GATES, EACH WITH A FIXTURE THE EXERCISER
# ACCEPTED.
# Named after the rule each enforces, authored with committed baselines during a
# capture campaign, and then reachable from nothing. A regression guard nobody
# runs guards nothing — and these are the easiest in the tree to have missed,
# because each one PASSES. A failing gate gets noticed; a green gate nobody runs
# looks exactly like a green gate that ran.
#
# EACH CARRIES `tools/ci/gate_fixtures/<slug>.py` with can_pass AND can_fail, and
# each pair was driven through `test_gate_fixtures_discriminate` — a fixture that
# cannot make its gate go red proves nothing, and the bar is there to refuse it.
#
# FIVE ARE NOT THE `--root "$ROOT"` TEMPLATE AND MUST NOT BE NORMALISED: `local
# clone`, `measurement only artefact`, `provenance value`, `prepared checkout`
# and `printed remedy` take the root POSITIONALLY, and `--root` there is
# `unrecognized arguments` -> rc 3, a bad invocation on every arm. `only the declaring step` carries
# `--self-test` because that program's own header calls its negative control
# "part of the gate".
#
# FOUR SIBLINGS ARE DELIBERATELY ABSENT, ON THEIR OWN WRITTEN INSTRUCTION.
# `checker_population_is_structural_not_filename_shaped_census` and
# `content_pinned_authority_verified_only_at_merge` only reach a failing status
# under `--strict`, and their docstrings say "THIS IS A CENSUS, NOT A GATE. IT
# MUST NOT BE WIRED AS A BLOCKING CHECK" and "VERDICT CLASS: ADVISORY ... it must
# stay advisory". Measured: `--strict` turns this lane red over 47 and 13
# PRE-EXISTING findings respectively. A census is not a gate, and wiring one over
# its author's objection to reach a number is the ritual this whole batch is
# against.
#
# `local_clone_does_not_borrow_objects_census` IS ALSO ABSENT, and its reason is
# NOT the same one — saying it is invites the next reader to wire it on the
# strength of a measurement nobody took. MEASURED on this tree: `--strict` is
# rc 0 (0 borrowing clones and 0 inventory rows over 1454 modules and 24 shell
# scripts), so it would not redden this lane at all.
#
# It stays out for two reasons that do not depend on today's count. Its header
# carries the same instruction — "THIS IS A CENSUS, NOT A GATE. IT MUST NOT BE
# WIRED AS A BLOCKING CHECK" — and the fixture bar cannot be met either way:
# declared non-strict, the only non-zero status it can reach is the rc-2
# empty-corpus path, which `gate_mutation_fixtures` refuses by name ("a can_fail
# that is red because the corpus went to zero proves the vacuity path and
# nothing about the predicate"); declared `--strict`, it is a blocking gate over
# its author's objection.
#
# AND IT IS NOT COVERAGE THIS LANE LOSES. Its refusing sibling
# `local_clone_does_not_borrow_objects` is wired above, on the same predicate,
# over a population that CONTAINS this one's. Driven on a tree seeded with two
# borrowing clones, one under `programs/` and one under `benchmark/`: the gate
# named BOTH and failed; the census named only the `programs/` one, because it
# walks `programs/` + `tools/` and the gate walks the repo. The census's one
# unique feature is `--inventory` grandfathering, and the gate's docstring says
# having no inventory is the point — it refuses where the census would record.
# `explicit_argument_outranks_the_environment_pointer_census` joined them on
# 2026-08-25 — the full reasoning, including the measurement that says wiring it
# would cost this lane nothing and why that is NOT the reason it stays out, is
# written once at the sibling block above.

# The six anti-fabrication gates in `tools/ci/run_plugin_self_audit.sh`, re-homed.
# They were wired to `.github/workflows/`, both of which are now `.disabled`, and
# nothing re-homed them — every remaining reference to that script in the tree is
# a comment or a docstring. `checker_execution_wiring_audit` scored all six as
# WIRED anyway, because it credited the script's `GATES=(...)` array as an entry
# path without asking whether anything runs the script; its own comment recorded
# that decision. So the audit that answers "did we forget to plug something in"
# was answering it wrong by six, in the direction of complacency. Both halves are
# fixed together: that audit now requires a dispatcher to be executed by
# something, and this line is what executes this one.
#
# BLOCKING, and green on this tree: all 6 gates PASS as of this change. Two did
# not before it — `changelog_metric_reproducibility_check` FAILed six README
# percentages that each sit beside the fraction they are computed from, and
# `changelog_command_reproducibility_check` FAILed four capture-document commands
# quoted exactly as they were run, from inside `programs/`. Both were defects in
# the CHECKERS, repaired in the same change; no published number was edited.
run "plugin self-audit"                 "$ROOT" bash "$ROOT/tools/ci/run_plugin_self_audit.sh" "$PLUGIN"

# THREE ORPHANED REPO-WIDE GATES, RE-HOMED. Each was authored, tested, merged and
# then reachable from nothing: no flow clause, no runner, no tools/ci line. Each
# was RUN before being wired here, because a gate that cannot pass on the tree it
# is about to gate is not a wiring job, and each one's measured verdict is:
#
#   flow_step_executor_coverage_check  steps=75 WIRED=59 ORPHANED=0 -> PASS
#   lessons_corpus_consistency_check   PASS, over the real lessons corpus
#   ip_catalog_upstream_audit          18/18 local PASS
#
# `--no-network` on the last one is deliberate and not a weakening: its upstream
# arm does `git ls-remote` and a shallow clone per IP, so wiring it without the
# flag makes this lane fail when github is unreachable — a red that says nothing
# about the tree. The local arm checks every manifest's files and license against
# what is actually vendored, which is the half a landing can be responsible for.
#
# NOT WIRED, and the reason is the point: `synth_wrapper_check` also exits 0 here,
# with `wrappers_checked: 0`. A gate that passes because it found nothing to look
# at is a green light for an empty scan, which is the defect this whole family of
# audits exists to catch. It needs a corpus before it needs a caller.
run "flow step-executor coverage"       "$PLUGIN" python3 programs/flow_step_executor_coverage_check.py
run "lessons corpus consistency"        "$PLUGIN" python3 programs/lessons_corpus_consistency_check.py
run "ip-catalog upstream (local arm)"   "$PLUGIN" python3 programs/ip_catalog_upstream_audit.py --no-network

# BACK, WITH THE FIXTURE THE BAR NOW ASKS FOR. `lessons_corpus_consistency_check`
# is named in the block above and its `run` line was taken out by "let the
# fixture bar decide what lands" — correctly, because it carried no fixture. It
# carries one now, `tools/ci/gate_fixtures/lessons_corpus_consistency.py`, and
# the pair was driven through `test_gate_fixtures_discriminate`: the can-fail arm
# strips the spec-deference clause off ONE directive sentence and the gate goes
# red naming `axis=read-timing genre=fifo`, over a corpus holding the same two
# sections as the green arm. The mutation moves the ANSWER, not the denominator.
#
# THE CORPUS PATH IS NAMED HERE, NOT DEFAULTED, and that is load-bearing.
# `_default_corpus()` resolves beside the program's own source file — under `$PG`
# that is the SHIPPED corpus whatever subject the gate is aimed at, so a fixture
# could never move its answer and the pair would certify nothing. Passing the
# path relative to the cwd this line names points it at the subject instead.
#
# WHAT IT PROTECTS: the digest a blind author is required to read. A `### Skill:`
# section that hard-codes one pole of a decision the SPEC owns steers a faithful
# author to the failing choice, and it reads like advice on the way past.
#
# RUN BEFORE WIRING, on this tree: 207 `### Skill:` sections parsed — 15 fifo and
# 7 shifter, the two genres the axes are bound to — 0 contradictions, rc 0.
run "lessons corpus consistency" "$PLUGIN" python3 "$PG/lessons_corpus_consistency_check.py" agents/ic-expert-agent.md

# CORRECTION, MEASURED 2026-08-25 — `ip_catalog_upstream_audit` DOES NOT BELONG
# ON THIS LANE, and the 18/18 above is why it looked as though it did. That run
# passed because this developer's HOME DIRECTORY holds the mirrors:
#     ip_catalog_pull.find_local_mirror('lfsr')
#         -> /home/reyerchu/ic_documents/open_ic/alexforencich-lfsr
#     IP_MIRROR_ROOT -> None      (`git ls-files | grep -c '^IP/'` -> 0)
# The subject it audits — the vendored tree the manifests describe — is not in
# this repository, so on any other checkout every IP returns
# `no local mirror found` and the lane would be red for a fact about the HOST.
# `gates are host-independent` exists to refuse exactly that. It is wired at its
# real caller instead: `ip_catalog_pull.pull_catalog_ip`, the one place that has
# a mirror in hand, checks the manifest's claim against it before the RTL enters
# a design.
#
# ITS SIBLING IS THE ONE THAT BELONGS HERE. `ip_catalog_validate` reads the
# MANIFESTS, which ARE tracked in this repository (18 of them), and nothing
# else: schema shape, a non-empty `matches_when`, an HTTP(S) canonical_url,
# port dicts that carry a name and a legal direction, and the license against
# the permissive whitelist. Its own header says "Run from CI / pre-commit hook
# to catch broken manifests early" and nothing ever did — the ip-catalog README
# names it as step 4 of adding an IP, which is a procedure and not a caller.
#
# MEASURED BEFORE WIRING: `PASS: 18  FAIL: 0` -> rc 0 over the shipped catalog.
# A zero-manifest catalog now exits 2 rather than printing `PASS: 0  FAIL: 0`
# and returning 0, so a catalog that MOVES cannot leave this row green over a
# directory nobody opened.
run "ip-catalog manifests validate" "$ROOT" python3 "$PG/ip_catalog_validate.py" --catalog-dir "$PLUGIN/ip-catalog"

# ORPHANED, RE-HOMED. `skill_doc_section_present_check` exists so a durably
# captured lesson cannot be silently dropped by a later edit: give it a document
# and the marker substrings that must survive, and a deletion becomes a red line
# instead of a thing nobody notices for a year. It had no caller, which means
# every doctrine section it was written to protect was unprotected.
#
# WHICH SECTIONS, AND WHY THESE. Each is a rule this repo learned by paying for
# it, and each is prose — the exact shape that goes missing:
#   RULE 0                       a benchmark enters through the general flow,
#                                never a benchmark-only harness
#   GENERAL-CORE / THIN-ADAPTER  a benchmark-named file may hold the IO shell
#                                and nothing else
#   IC-EXPERT OPERATING MAP      the phase -> program -> gate -> skill table the
#                                agent routes from
# Measured before wiring: all three present, `"missing": []`, rc=0.
#
# WHY `$PG/...` AND NOT `programs/...` (2026-08-25). These two lines run with
# cwd `$PLUGIN`, and the fixture engine substitutes `$PLUGIN` with the SUBJECT
# tree while leaving `$PG` pointing at the real programs directory. Spelled
# `programs/skill_doc_section_present_check.py`, the gate would resolve to a
# COPY of itself inside the fixture subject and measure that copy — the subject
# is the gate's INPUT, never its code.
run "benchmark doctrine sections kept" "$PLUGIN" python3 "$PG/skill_doc_section_present_check.py" \
    --doc skills/open-benchmark-methodology/SKILL.md \
    --marker "RULE 0" --marker "GENERAL-CORE / THIN-ADAPTER"
run "ic-expert operating map kept"     "$PLUGIN" python3 "$PG/skill_doc_section_present_check.py" \
    --doc agents/ic-expert-agent.md --marker "IC-EXPERT OPERATING MAP"

# THE DOCTRINE-RATCHET GATES, RE-HOMED (2026-08-25). Twenty-two AST gates named
# after the rule each enforces — "only the declaring step writes its output",
# "a population guard asserts equality not a floor" — authored with committed
# baselines during a capture campaign and then reachable from NOTHING. No flow
# clause, no runner, no tools/ci line. A regression guard nobody runs guards
# nothing; these are the cheapest wiring in the tree and the easiest to have
# missed, because each one passes and so nobody notices it never ran.
#
# ALL TWENTY-TWO WERE RUN FIRST and all exit 0 over REAL corpora — 1478, 1327,
# 4360, 2842 modules parsed, not an empty scan between them. They are green
# regression guards with no cadence: wiring them costs a landing nothing today
# and catches the NEXT instance, which is the only thing a ratchet is for.
#
# The eleven siblings NOT here are excluded on measurement, not oversight.
# Three exit 1 on a GENUINE finding and would block a landing on debt this
# change does not own:
#     every_required_metric_key_has_a_producer
#     layer_membership_is_declared_not_inferred_from_a_filename_prefix
#     metric_constant_across_differing_arms_is_not_measured
# `gate_proof_vocabulary_has_a_producer` was the fourth. Its red was measured
# FALSE (F15) and is repaired; it is DECLARED above, green, with a fixture.
# Seven exit 2 NOT CHECKED because they need an argument no "run" line can
# supply; those need a caller with project knowledge, not a cadence.

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
# ITS RUNTIME TWIN. `silent_decline_audit` reads SOURCE for a remedy that
# declines without saying so; `sweep_reach_survey` RUNS every sweep-shaped
# program in the tree against a POPULATED corpus none of their rules applies to,
# and asks whether the exit code and stdout can tell "I looked and found
# nothing" from "I never reached the check". Same disease, opposite instrument,
# and the survey was reachable from nothing but its own unit test — so the ratio
# it publishes was quoted in a change body and re-derivable by nobody.
#
# THE CORPUS IS POPULATED, NOT EMPTY, and that is the measurement. Three valid
# trivial Verilog modules every sweep can READ and essentially no sweep's rule
# JUDGES. An empty corpus would test "I was given nothing", which the shipped
# `_gate_denominator` work already made visible everywhere; this tests the
# quieter shape — a sweep that read 756 pairs in full, decided about none, and
# exited 0 clean.
#
# `--max-silent 27`, NOT a bare run and NOT `--strict`. MEASURED at this commit:
# 64 sweep-shaped programs discovered, 35 driven to a zero-reach run, 8 of the
# 35 DISCLOSE and 27 are SILENT (29 the generic probe corpus cannot drive are
# published as NOT_DRIVABLE rather than dropped, which is the survey refusing
# its own version of the defect). A bare run returns 0 unconditionally — a gate
# that cannot fail; failing on the whole 27 would wire a permanently red one.
# The ratchet holds today's 27 visible, blesses none of them, and makes a
# TWENTY-EIGHTH red. It is a number that may only shrink.
#
# `--programs-dir "$PLUGIN/programs"`, spelled out rather than left to the
# program's default (which is the directory the SURVEY lives in): the fixture
# engine substitutes the subject token-wise, and a gate that resolved its own
# corpus from `__file__` would read the real tree no matter what subject it was
# handed — an input no fixture can move is an input no fixture can prove
# anything about.
run "a sweep can say it judged nothing" "$ROOT" python3 "$PG/sweep_reach_survey.py" --programs-dir "$PLUGIN/programs" --max-silent 27

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
# The image is RESOLVED, not restated: `_eda_image.judged_image()` names the
# newest vibeic-eda image THIS HOST holds, by digest. That was exercised rather
# than asserted — the checker followed an anchor bump 0.2.98 -> 0.2.99 with no
# edit back when the answer came from `tools/vibeic-eda/VERSION`, and it follows
# a host's image with no edit now. What changed is that the answer is no longer
# a version number stored in this repo, so a vibeic-eda release no longer needs a
# PR here, and the report names the DIGEST it read rather than a tag.
uncheckable_until 2026-11-30 "needs a vibeic-eda IMAGE on the host: --from-image starts an ephemeral container from the digest this host resolves and reads the installed PDK, and rc 2 means no PDK could be read at all (a claim the installed tree contradicts is rc 1, and --advisory does not touch rc 2)"
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

# The same flow document's OTHER graph: the `closed_loop` edges. Wired here
# because it was the SEVENTH name that `checker_execution_wiring_audit` and
# `gate_is_wired_check` both reported, and the only reason both exited 1 —
# `closed_loop_edge_check` landed with no flow gate clause, and its one
# non-comment consumer was a file under `programs/tests/`, which is not a wiring
# surface. A gate reachable only from a test does not run on a design, so the
# check that made `closed_loop` declarations falsifiable was itself consulted by
# no automatic verdict (docs/PPA_CURRENT_STATE.md section 5).
#
# rc RE-MEASURED on this base before wiring, not carried over from another tree:
# rc 0, "checked 22 declared closed_loop edge(s) over 69 step(s); every edge
# resolves to a declared step, closes a loop, carries a trigger, and leaves a
# step whose gate can produce a verdict."
# THE FLOW IS NAMED FROM $ROOT, NOT LEFT TO THE PROGRAM'S OWN LOCATION.
# Both of these default to `Path(__file__).parent.parent / flow/...`, i.e. the
# tree the GATE lives in rather than the tree under test. In production those
# are the same file and the verdict is identical either way -- MEASURED, both
# gates, before and after this line: same rc, same counts. What changes is that
# a gate whose input is fixed to its own location cannot be shown to fail:
# `gate_mutation_fixtures.invoke` redirects $ROOT and nothing else, so no
# fixture could ever hand either of them a mutant flow, and both sat in
# `gate_mutation_fixture_check`'s NEW-OR-UNEXCUSED set with no way out of it.
# Naming the input is what makes the CAN-FAIL direction reachable.
run "closed-loop edges resolve" "$ROOT" python3 "$PG/closed_loop_edge_check.py" --flow "$ROOT/vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml"

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
