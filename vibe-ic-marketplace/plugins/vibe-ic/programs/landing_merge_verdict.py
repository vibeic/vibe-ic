#!/usr/bin/env python3
"""landing_merge_verdict.py — the REFUSAL DECISION for the merge path, in one
function, because `gh pr merge` runs no gate at all.

THIS GATE BLOCKS (rc=1). rc=2 means the question could not be put, which also
refuses the landing — an unmeasurable landing is not a verified one.

THE DEFECT (vibe-ic#1019), measured
===================================
Three facts, each checked directly on 2026-08-12:

    Actions permissions   {"enabled": false}         account-level block
    branch protection     404 Branch not protected   no required check exists
    the only enforcement  tools/git-hooks/pre-push   refuses a push whose
                                                     commit has no matching
                                                     `.git/gatekeeper-stamp`

`tools/gatekeeper-land.sh` writes that stamp after running the tests and the
hygiene gates. So the enforcement is attached to `git push`.

**`gh pr merge --squash` creates the commit SERVER-SIDE. Nothing is pushed from
a local clone, so `pre-push` never fires and `gatekeeper-land.sh` never runs.**
Merging is not pushing. Every PR landed that way skipped the entire test tier —
which is how `programs/tests/test_matrix_d2_falsifiable.py` stayed RED on `main`
across five merges (#1006, #1007, #1008, #1009, #1013) with nobody noticing.

The test SELECTION was not a second hole. `ci_targeted_test_select.py` picked
that file for all seven merges examined in #1019. The suite was right, the
selection was right, and the thing that runs them was never invoked.

WHY THE DECISION LIVES HERE AND NOT IN THE SHELL SCRIPT
=======================================================
`tools/gatekeeper-verify-merge.sh` does the git work: fetch, rebase, two test
arms, invoke `gatekeeper-land.sh`. It forms NO opinion. Every reason a landing
may be refused is computed by :func:`decide` in this file, so:

  * the refusal has ONE site a mutant can neuter, and a mutant that neuters it
    has to be able to leave every other line standing — which is the only way
    to show the tests are reading the DECISION and not the plumbing;
  * the verdict is a value, not an exit status threaded through a pipeline.

WHY A DIFFERENTIAL FAILED-SET AND NOT "THE TREE MUST BE GREEN"
==============================================================
`main` is RED right now, and not because of anything in flight. Measured at
`e4880703b`, each side run in its own worktree off the same object store:

    programs/tests/test_ci_harness_timeout_ceiling_check.py   3 of 40 fail
    repo hygiene: flow_gate_enforcement_audit                 rc=1 (5 AUDIT_ONLY)
    repo hygiene: gen_matrix_63x8_census --check              rc=1
    repo hygiene: ci_harness_timeout_ceiling_check            rc=1 (7 bounds)

A gate that demands green would refuse EVERY landing today, and a gate that
refuses every landing is a ban. Worse, it is a ban that teaches the operator to
bypass it, which is how the repo arrived at a landing path with no gate in the
first place.

THE SAME RULE APPLIES TO BOTH TIERS, and the second half is not optional: two of
those three hygiene gates are red on the base, so an absolute "any gate FAIL
refuses" would have been exactly the ban described above. The candidate's failing
GATE LABELS are compared against the base's, just as its failing TEST IDS are.
When no base gate log is supplied the comparison falls back to absolute — the
strict direction — and says so.

AND THE LABEL IS TOO COARSE FOR ONE OF THE TIERS (vibe-ic#1498)
==============================================================
`gatekeeper-land.sh` runs the whole repo-hygiene suite — ~80 declared gates —
under ONE label, `repo hygiene gates`. The subtraction above is BY LABEL, so
that tier is judged at a granularity of one:

    the base's suite is red  -> the whole label is excused, and a finding this
                                branch INTRODUCED under it is invisible
    the base's suite is green -> the whole label blocks, which is right

The first row is the permissive half, and until this program was given the
comparison below nothing caught it. `hygiene_finding_delta.py` supplies the
granularity the label cannot: it differences the two arms' `--summary-json`
records and answers "which findings exist on the candidate that are not on the
base". Its answer is read here, and it is STRICTLY ADDITIVE — it can only add
refusal reasons to the label-level rule above, never remove one, so no landing
that refuses today lands because of it.

THE TWO ARMS' RECORDS ARE ASYMMETRIC ON PURPOSE, for #1443's reason:

    no BASE record       -> disclosed, degrades to the per-label comparison. The
                            branch does not control whether the base arm ran (a
                            `--base-gate-cache` hit skips it entirely), so a
                            missing baseline must not be a ban.
    no CANDIDATE record  -> REFUSE. The base measured its findings and the tree
                            under test did not, so the subset question cannot be
                            answered about the one side the branch owns.

So a PR is judged on WHAT IT BREAKS:

    base            candidate         decision
    ----            ---------         --------
    RED             RED               pre-existing — not this PR's
    RED             PASSED            FIXED (reported, never required)
    not-RED         RED               NEW FAILURE            -> REFUSE
    RED             SKIPPED / ABSENT  SILENCED               -> REFUSE
    PASSED          SKIPPED / ABSENT  WEAKENED               -> REFUSE

The SILENCED and WEAKENED rows have to be there. Without them the differential
rewards exactly the cheat it is supposed to catch: delete or skip a test and the
suite quietly stops asking. This is also what keeps a reusable green base record
fail-closed if an unobserved runtime drift would make that base test red today:
PASS -> SKIP still refuses instead of hiding the now-silenced question.

EVERY WAY THE DIFFERENTIAL CAN DEGRADE, DEGRADES TOWARD STRICTER
================================================================
  * empty base report  -> every candidate failure is new -> demand green
  * no overlapping ids -> same
  * candidate run truncated by `--maxfail` -> REFUSE, never a pass: the tests
    after the tenth failure did not run, so their absence is not a result
  * a selected test file that produced no test case at all -> REFUSE: a test
    file that was chosen and then contributed nothing is the hole this repo
    hunts, not a clean sheet
  * THE SAME QUESTION, ASKED OF THE BASE ARM (vibe-ic#1443) -> REFUSE. This was
    the one exception to the rule above, and it ran the WRONG WAY. `silenced`
    and `weakened` are read off what was RED (or passing) ON THE BASE, so a base
    failure that never got measured is a base failure the branch may delete for
    free. `base_total == 0` was the only guard and it is all-or-nothing — a base
    arm that ran three of its five files sits between the two and was subtracted
    as though whole. Measured on `3d13e2c59` with ONE selected file missing from
    the base report and every other input byte-identical, a candidate that turned
    a red test into a SKIP went from `REFUSE 1 FAILING TEST(S) WERE SILENCED` to
    `LAND OK`. The list arm A was asked for arrives as `--base-selection`;
    without it the check cannot fire and says so in the notes.

A PER-FILE NORECORD IS STRUCTURED EVIDENCE, NOT CONSOLE TEXT (vibe-ic#1709)
==========================================================================
`pytest_per_file_junit.py` keeps a file whose session died ABSENT from the
merged report and names it on stdout as `NORECORD`. Which arm of this program
reads that absence decided whether the refusal could say WHAT is missing.

Until #1709 the answer was: neither. `missing_process_files` and
`base_missing_process_files` were declared in :func:`decide`, initialised to
`[]` in :func:`main`, and never populated; `junit_per_file_process_files` had no
caller. The signal reached the verdict only through
`tools/gatekeeper-land.sh`'s

    grep -qa '^NORECORD' <driver combined stdout>

which prints a gate LABEL — over the mixed driver/subject channel this file
says everywhere else that it does not trust, because pytest can print
marker-looking text into it. MEASURED on 7c376e348, one candidate report,
aggregate suite intact, ONE selected file's per-file attestation removed, every
other input byte-identical:

    no label            LAND OK   rc=0   missing_candidate_process_files []
    label on candidate  REFUSE    rc=1   ...still []  — "LANDING GATE FAILED"
    label on BOTH arms  LAND OK   rc=0   ...still []

The middle row is the one #1709 reported: a refusal that cannot name the file
sends the next reader to the wrong place. The LAST row is worse and is the
reason the fix is a REASON and not a better label. A label goes through the
per-label gate differential, so the same NORECORD on both arms is scored
PRE-EXISTING and excused — and a hang that fires on both arms is precisely the
shape `pytest_per_file_junit.py` exists for; its own docstring rejects a
synthetic red testcase for exactly this reason and the label reintroduced it.

WHICH FILES THE QUESTION IS ASKED ABOUT is the part that must not be guessed.
Per-file sessions are diagnostic recovery, so a healthy landing has NO per-file
evidence and demanding one attestation per selected file unconditionally would
refuse every landing — the ban. `per_file_record_gaps` derives the population
from what the report claims instead: aggregate attested and no per-file
evidence is NOT ASKED and says so; any per-file attestation, or a missing
aggregate attestation, asks over the whole selection and NAMES every gap.

There is no argument this program accepts that makes it more permissive than
"demand green". That is the property that makes the relaxation safe. THE
VERIFICATION TIER BELOW IS NOT AN EXCEPTION TO IT: a degraded tier reports what
it could not check and softens nothing it did.

TWO TIERS, BECAUSE THE HOST THAT LANDS CODE CANNOT RUN THE STRONG ONE
=====================================================================
`git merge-tree --write-tree` requires git >= 2.38. Measured across this fleet
on 2026-08-12, FOUR OF SIX HOSTS RUN 2.34.1 — including the orchestrator, where
every `gh pr merge` is actually run:

    .102  orchestrator, lands every PR   2.34.1   no
    .105                                 2.34.1   no
    .112  where this was authored        2.43.0   yes
    .114                                 2.54.0   yes
    .120                                 2.34.1   no
    .121                                 2.34.1   no

On the four, the strong path does not fail — it never starts. `--write-tree` is
read as a REV (`fatal: unknown rev --write-tree`), the tree comes back empty and
this program refuses with THE MERGE TREE COULD NOT BE COMPUTED. As a refusal
that is exactly right and it is KEPT. As a gate it was a BAN: it refused every
landing on the only host that lands, which is the failure mode this file exists
to detect.

    TIER `merge-tree`     git >= 2.38. The tree under test is the 3-way merge;
                          the rebase replay is an independent second opinion and
                          a disagreement is a refusal.
    TIER `rebase-replay`  the fallback. The tree under test IS the rebase
                          replay, so THE SQUASH-VS-REBASE CROSS-CHECK IS NOT
                          PERFORMED — nothing is left to disagree with it. The
                          forge's `refs/pull/<n>/merge` still cross-checks it
                          whenever the forge merged this same base.
    TIER `direct-push`    the DIRECT-PUSH path (`git push origin main`), driven
                          by `tools/gatekeeper-land-differential.sh`. There is
                          no PR, no forge merge and no squash: the commit being
                          pushed IS the commit that lands and its tree IS the
                          tree that lands, so squash-vs-rebase is NOT
                          APPLICABLE rather than not performed — there are not
                          two computations of one tree for one to disagree
                          with. THAT DISTINCTION IS THE WHOLE POINT OF THE
                          SEPARATE CODE: `NOT_PERFORMED` names evidence that
                          was lost, `NOT_APPLICABLE` names evidence that never
                          existed, and a reader who cannot tell them apart
                          cannot tell a degraded run from a complete one.
                          The caller must therefore pass the SAME oid as
                          `--expected-tree` and `--verified-tree` (the pushed
                          commit's tree) and leave `--replayed-tree` and
                          `--github-tree` empty; the cross-tree refusals above
                          stay armed and fire if it does not.
                          THE FAST-FORWARD ASSERTION IS NOT WAIVED, it is
                          simply owned elsewhere: `gatekeeper-land.sh` runs
                          `gatekeeper_stale_branch_check` over the real range
                          on the candidate arm, where an empty base range makes
                          it range-scoped and therefore ABSOLUTE.

Everything else is identical: same squash commit built from the tree under test,
same `gatekeeper-land.sh`, same test and gate differentials, same fail-closed
behaviour when the replay conflicts. **A fallback that passed everything would
be worse than a gate that refused everything**, so the paired negative control —
an innocuous diff that leaves a test red — is asserted UNDER THE FALLBACK.

The loss is disclosed in the printed verdict AND machine-readably in the JSON
(`verification_tier`, `tier_degraded`, `squash_vs_rebase_cross_check`,
`disclosures`, `git_version`), because a disclosed weaker check is only better
than a refusal if the weakness is legible to whatever reads the record next. An
UNRECOGNISED tier refuses as unmeasurable rather than inheriting the strong
tier's silence.

Usage
-----
    landing_merge_verdict.py --base-sha <sha> --head-sha <sha>
        --verified-sha <sha> --rebase-status ok|conflict
        --expected-tree <oid> --verified-tree <oid>
        [--replayed-tree <oid>] [--github-tree <oid>]
        --land-log <path> [--base-land-log <path>] --selection <path>
        [--base-selection <path>]
        --base-junit <path> --candidate-junit <path>
        [--base-hygiene <path> --candidate-hygiene <path>
         --base-hygiene-host <name> --candidate-hygiene-host <name>]
        [--verification-tier merge-tree|rebase-replay|direct-push]
        [--git-version <v>]
        [--merge-tree-min-version <v>] [--tier-reason <text>]
        [--gate-edited <path>...] [--maxfail N] [--json <out>]

Exit codes
----------
    0   LAND OK   — the tree that would be merged was verified and broke nothing
    1   REFUSE    — at least one refusal reason; every reason is printed
    2   REFUSE (UNMEASURABLE) — the question could not be put

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

RC_OK = 0
RC_REFUSE = 1
RC_CANNOT_MEASURE = 2

# Outcome vocabulary. ABSENT is a first-class outcome, not a missing key: a test
# that stopped existing is a measurement, and on the RED side it is a refusal.
PASSED = "passed"
FAILED = "failed"
ERRORED = "errored"
SKIPPED = "skipped"
XFAILED = "xfailed"
ABSENT = "absent"
RED = frozenset({FAILED, ERRORED})
SILENT = frozenset({SKIPPED, XFAILED, ABSENT})
PROCESS_RC_PREFIX = "process_rc:"

# `run()` in gatekeeper-land.sh prints exactly two leading spaces, the word, two
# more spaces, then the label. `report()` prints REPORT and is NOT a gate.
_LAND_LINE = re.compile(r"^ {2}(PASS|FAIL|SKIP|REPORT) {2}(.+?)\s*$")
_LAND_SENTINEL = "=== gatekeeper landing gates"
# `printf '  FAIL  targeted tests (%s file(s))\n'` — the test tier, whose verdict
# this program overrides with the differential. NOT `targeted test selection
# produced no files`, which is a selection failure and stays a hard refusal.
_TEST_TIER = re.compile(r"^targeted tests(?:\s|\(|$)")
_PROCESS_VERDICT_MARKER = "targeted test process verdicts embedded in junit"
_AGGREGATE_COMPLETE_MARKER = "targeted aggregate session completed"
_AGGREGATE_INCOMPLETE_PREFIX = "targeted aggregate session produced no "
_PER_FILE_INCOMPLETE_PREFIX = "targeted per-file session produced no "
_PER_FILE_NOTRUN = "targeted per-file session was not run"
# `run "repo hygiene gates" bash tools/ci/repo_hygiene_gates.sh …` — the ONE
# label under which ~80 gates are judged, which is why it needs the finer
# comparison below (#1498). Unlike `_TEST_TIER` this label is NOT exempted from
# the per-label differential: the finding delta is added to that rule, not
# substituted for it.
_HYGIENE_TIER = re.compile(r"^repo hygiene gates(?:\s|\(|$)")
_STAMPED = re.compile(r"===\s*ALL GATES PASS\s*[—-]\s*stamped\s+(\S+)")
_NON_TARGET_COMPLETE = "=== ALL NON-TARGET GATES COMPLETE"
_FAILURES_TERMINAL = "=== FAILURES ABOVE"

# The three answers `hygiene_finding_delta.compare` can give. Named here so this
# program branches on a value rather than on the helper's exit status, and so a
# reader of this file can see the whole vocabulary without opening that one.
HYG_CLEAN = "CLEAN"
HYG_INTRODUCED = "INTRODUCED"
HYG_REFUSED = "REFUSED"

# A GATE'S LABEL IS ITS IDENTITY; A COUNT INSIDE IT IS A MEASUREMENT OF A TREE.
#
# The gate differential in `decide` matches the base arm's failing gates against
# the candidate arm's BY LABEL, and the two arms measure two different trees. One
# gate in `gatekeeper-land.sh` prints a per-tree count inside its label:
#
#     printf '  PASS  repo tools tests (%s file(s))\n' "${#files[@]}"
#
# — a DISCOVERY count over `tools/`, deliberately not a roster, so ANY branch
# that adds or removes a test file there renames the gate. Measured against the
# code before this normaliser existed (vibe-ic#1431): a branch that repairs the
# red repo-tools tier and adds one test file goes
#
#     base       FAIL  repo tools tests (28 file(s))
#     candidate  PASS  repo tools tests (29 file(s))
#
# and the differential reported two things that never happened — a gate that
# failed on the base and "is no longer asked here", and, with the tier red on
# both arms, a NEW failure the branch owns. Both refuse, and the shape they
# refuse is the one this repo asks for: a fix that arrives with a test.
#
# The test tier is already exempt for exactly this reason — `_TEST_TIER` above
# matches `targeted tests (21 file(s))` and drops it from the comparison. This
# is the same hazard in the tier that exemption does not cover, so the count is
# stripped from the KEY the comparison uses. Labels are still printed VERBATIM in
# every reason and note: the denominator is evidence and is never hidden.
#
# DELIBERATELY NARROW. `(<n> file(s))` at the end of a label is a pure per-tree
# count and nothing else. A parenthesised `rc=`, a version, or any other suffix
# is left alone — a normaliser that erases more than the tree-dependent part
# starts merging gates that are genuinely different, and merging outcomes would
# let "I could not look" be waived by "I looked". `programs/tests/
# test_issue1431_gate_identity_is_not_a_tree_measurement.py` holds that boundary
# in both directions and re-derives this population from the script itself.
_LABEL_TREE_COUNT = re.compile(r"\s*\(\d+ file\(s\)\)$")


def gate_key(label: str) -> str:
    """The identity of a gate, with any per-tree count removed.

    Compare gates with this; report them with the original label.
    """
    return _LABEL_TREE_COUNT.sub("", label)


def _fmt_hyg(finding: Sequence[str]) -> str:
    """One hygiene finding, printed the way `hygiene_finding_delta` prints it.

    `(kind, label, corpus)` — the KIND is never dropped: `FAIL`,
    `WROTE_CORPUS` and `EXEMPTION_EXPIRED` are three different things a reader
    has to do three different things about.
    """
    kind, label, corpus = (list(finding) + ["", "", ""])[:3]
    return f"[{kind}] {label}" + (f" [over {corpus}]" if corpus else "")


@dataclass
class Delta:
    """The failed-set difference. Every list holds junit keys."""

    new_failures: List[str] = field(default_factory=list)
    #: The SUBSET of `new_failures` whose id the base report does not contain at
    #: all — a test the change BRINGS, failing, rather than a behaviour it broke.
    #: Both block; `new_failures` is untouched and no verdict moves. This exists
    #: because the two are not the same finding and were reported as one.
    new_absent_on_base: List[str] = field(default_factory=list)
    silenced: List[str] = field(default_factory=list)
    fixed: List[str] = field(default_factory=list)
    weakened: List[str] = field(default_factory=list)
    preexisting: List[str] = field(default_factory=list)
    base_total: int = 0
    candidate_total: int = 0
    overlap: int = 0

    def as_dict(self) -> dict:
        return {
            "new_failures": self.new_failures,
            # MACHINE-READABLE TOO, not only in the prose: a downstream that
            # routes on the count is the reader most likely to overstate it.
            "new_absent_on_base": self.new_absent_on_base,
            "silenced": self.silenced,
            "fixed": self.fixed,
            "weakened": self.weakened,
            "preexisting": self.preexisting,
            "base_total": self.base_total,
            "candidate_total": self.candidate_total,
            "overlap": self.overlap,
        }


@dataclass
class LandLog:
    passed: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    reported: List[str] = field(default_factory=list)
    stamped_sha: Optional[str] = None
    sentinel_seen: bool = False
    non_target_complete: bool = False
    failure_terminal_seen: bool = False

    @property
    def blocking_failures(self) -> List[str]:
        """Every FAIL except the test tier, whose verdict the differential owns."""
        return [l for l in self.failed if not _TEST_TIER.match(l)]

    @property
    def test_tier_failed(self) -> bool:
        return any(_TEST_TIER.match(l) for l in self.failed)

    @property
    def process_verdicts_embedded(self) -> bool:
        return _PROCESS_VERDICT_MARKER in self.reported

    @property
    def aggregate_complete(self) -> bool:
        return _AGGREGATE_COMPLETE_MARKER in self.reported

    @property
    def aggregate_incomplete(self) -> bool:
        return any(label.startswith(_AGGREGATE_INCOMPLETE_PREFIX)
                   for label in self.failed)

    @property
    def per_file_incomplete(self) -> bool:
        return (any(label.startswith(_PER_FILE_INCOMPLETE_PREFIX)
                    for label in self.failed)
                or _PER_FILE_NOTRUN in self.failed)

    def as_dict(self) -> dict:
        return {
            "pass": self.passed,
            "fail": self.failed,
            "skip": self.skipped,
            "report": self.reported,
            "stamped_sha": self.stamped_sha,
            "non_target_complete": self.non_target_complete,
            "failure_terminal_seen": self.failure_terminal_seen,
            "blocking_failures": self.blocking_failures,
            "test_tier_failed": self.test_tier_failed,
            "process_verdicts_embedded": self.process_verdicts_embedded,
            "aggregate_complete": self.aggregate_complete,
            "aggregate_incomplete": self.aggregate_incomplete,
            "per_file_incomplete": self.per_file_incomplete,
        }


@dataclass
class Verdict:
    ok: bool
    reasons: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    unmeasurable: bool = False
    #: MACHINE-READABLE codes for what this verdict did and did not check, so a
    #: downstream reader can tell a strong verification from a degraded one
    #: without parsing prose. Prose lives in :attr:`notes`; these are the keys.
    disclosures: List[str] = field(default_factory=list)


def read_protected_transition_receipt(
        path: str, *, base_commit: str, candidate_commit: str,
        base_tree: str, candidate_tree: str
        ) -> tuple[Optional[dict], Optional[dict], str]:
    """Load and bind BASE-owned protected-source evidence.

    The validator is resolved by path from this verdict's own raw-attested
    BASE snapshot.  Importing a same-named candidate module would let the
    subject redefine the receipt it is meant to satisfy.
    """
    if not str(path).strip():
        return None, None, "no protected landing transition receipt was supplied"
    repo = Path(__file__).resolve().parents[4]
    validator_path = repo / "tools" / "ci" / "protected_landing_transition.py"
    try:
        spec = importlib.util.spec_from_file_location(
            "_trusted_protected_landing_transition", validator_path)
        if spec is None or spec.loader is None:
            raise ImportError("no loader")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        receipt = module.strict_load_receipt(
            Path(path), oid_len=len(base_commit))
        summary = module.validate_receipt_binding(
            receipt,
            base_commit=base_commit,
            candidate_commit=candidate_commit,
            base_tree=base_tree,
            candidate_tree=candidate_tree,
        )
    except (ImportError, OSError, RuntimeError, ValueError, TypeError) as exc:
        return None, None, str(exc)
    return receipt, summary, ""


# The verification TIERS. `merge-tree` is the strong path; `rebase-replay` is the
# fallback for a host whose git predates `merge-tree --write-tree` (>= 2.38), on
# which the strong path cannot start at all. Anything else is not a tier this
# program knows how to reason about, and it FAILS CLOSED on one — see `decide`.
TIER_MERGE_TREE = "merge-tree"
TIER_REBASE_REPLAY = "rebase-replay"
#: The DIRECT-PUSH path. Not a degradation of the merge path — a different
#: question with a different answer set. Nothing is squashed, so there is no
#: second computation of the landing tree to cross-check the first against, and
#: the honest disclosure is NOT_APPLICABLE rather than NOT_PERFORMED. Every
#: OTHER refusal in `decide` is computed exactly as the merge path computes it,
#: including the cross-tree checks, which the caller keeps armed by passing the
#: pushed commit's tree as BOTH `expected_tree` and `verified_tree`.
TIER_DIRECT_PUSH = "direct-push"
TIERS = (TIER_MERGE_TREE, TIER_REBASE_REPLAY, TIER_DIRECT_PUSH)
MERGE_TREE_MIN_VERSION = "2.38"


# ---------------------------------------------------------------- junit reading


def _testcase_outcome(tc: ET.Element, *, process_attested: bool = False) -> str:
    # A subject testcase can set its own junit classname and properties through
    # pytest's public record_xml_attribute/record_property fixtures. Therefore
    # those attributes authorize a process outcome ONLY when the parent suite
    # has independently passed the exact driver-attestation shape check.
    if process_attested and (tc.get("classname") or "") in {
            "pytest_per_file_process", "pytest_aggregate_process"}:
        for prop in tc.iter("property"):
            if prop.get("name") == "process_rc":
                return PROCESS_RC_PREFIX + str(prop.get("value"))
    for child in tc:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "failure":
            return FAILED
        if tag == "error":
            return ERRORED
        if tag == "skipped":
            if (child.get("type") or "").endswith("xfail"):
                return XFAILED
            return SKIPPED
    return PASSED


def _is_red(outcome: str) -> bool:
    if outcome.startswith(PROCESS_RC_PREFIX):
        return outcome != PROCESS_RC_PREFIX + "0"
    return outcome in RED


def _is_passed(outcome: str) -> bool:
    return outcome == PASSED or outcome == PROCESS_RC_PREFIX + "0"


def _same_red(base: str, candidate: str) -> bool:
    """Ordinary pytest reds are equivalent; process rc values are exact."""
    if (base.startswith(PROCESS_RC_PREFIX)
            or candidate.startswith(PROCESS_RC_PREFIX)):
        return base == candidate and _is_red(base)
    return base in RED and candidate in RED


def _key(tc: ET.Element) -> str:
    return f"{tc.get('classname') or ''}::{tc.get('name') or ''}"


def _file_of(tc: ET.Element, selection: Sequence[str]) -> Optional[str]:
    """The test FILE a junit case came from.

    `junit_family=xunit1` carries a ``file`` attribute and that is used when it
    is there. `xunit2` — the pytest default — drops it, so fall back to the
    dotted ``classname``: the module prefix is the longest prefix that names a
    file in the SELECTION. Matching against the selection rather than the
    filesystem keeps this honest about the question being asked ("did every
    file we chose actually run"), and works for class-based tests, whose
    classname carries a trailing component that is not a module.
    """
    f = tc.get("file")
    if f:
        return f
    parts = (tc.get("classname") or "").split(".")
    want = set(selection)
    for i in range(len(parts), 0, -1):
        cand = "/".join(parts[:i]) + ".py"
        if cand in want:
            return cand
    return None


def read_junit(path: Path, selection: Sequence[str] = ()) -> Dict[str, str]:
    """key -> outcome. A missing file raises; an unparseable one raises."""
    root = ET.parse(str(path)).getroot()
    process_cases = _trusted_process_case_ids(root)
    out: Dict[str, str] = {}
    for tc in root.iter("testcase"):
        k = _key(tc)
        o = _testcase_outcome(tc, process_attested=id(tc) in process_cases)
        # A rerun/duplicate id keeps the WORST outcome. Two entries for one id
        # otherwise let an ordering accident decide whether a failure is seen.
        if k in out and _is_red(out[k]):
            continue
        out[k] = o
    return out


def _aggregate_testcases(root: ET.Element):
    """Yield only testcase evidence emitted by the aggregate session.

    A NORECORD diagnostic may carry surviving per-file suites in the same XML.
    Those suites are useful to a human but cannot complete, excuse, or otherwise
    alter the authoritative whole-selection question.  The driver namespaces
    aggregate suites structurally; stdout and ordinary subject suites are never
    consulted here.
    """
    for suite in root.iter("testsuite"):
        if not (suite.get("name") or "").startswith("aggregate::"):
            continue
        for tc in suite.iter("testcase"):
            if (tc.get("classname") or "").startswith("pytest_aggregate."):
                yield tc


def read_aggregate_junit(path: Path,
                         selection: Sequence[str] = ()) -> Dict[str, str]:
    """Read the canonical aggregate testcase set plus its exact process rc."""
    root = ET.parse(str(path)).getroot()
    out: Dict[str, str] = {}
    for tc in _aggregate_testcases(root):
        k = _key(tc)
        o = _testcase_outcome(tc)
        if k in out and _is_red(out[k]):
            continue
        out[k] = o
    for suite in root.iter("testsuite"):
        if not _valid_process_case(
                suite, classname="pytest_aggregate_process",
                name="whole_selection::process_exit",
                file_name="<aggregate>"):
            continue
        tc = list(suite.iter("testcase"))[0]
        k = _key(tc)
        o = _testcase_outcome(tc, process_attested=True)
        if k not in out or not _is_red(out[k]):
            out[k] = o
    return out


def junit_files(path: Path, selection: Sequence[str]) -> set:
    root = ET.parse(str(path)).getroot()
    seen = set()
    for tc in root.iter("testcase"):
        f = _file_of(tc, selection)
        if f:
            seen.add(f)
    return seen


def junit_aggregate_files(path: Path, selection: Sequence[str]) -> set:
    """Selected files represented by aggregate testcase evidence only."""
    root = ET.parse(str(path)).getroot()
    seen = set()
    for tc in _aggregate_testcases(root):
        f = _file_of(tc, selection)
        if f:
            seen.add(f)
    return seen


def _valid_process_case(suite: ET.Element, *, classname: str,
                        name: str, file_name: str) -> bool:
    """Whether *suite* is one process attestation written by the driver.

    Subject pytest stdout shares a channel with the driver's human log and can
    therefore print any REPORT-looking text it wants.  The landing decision
    never trusts that channel.  It trusts only this exact, parent-appended XML
    shape.  In particular, the suite name matters: ordinary per-file suites
    are renamed to the selected ``*.py`` path, while process suites are named
    ``<path>::process_exit``.  A testcase changing its own junit classname
    cannot manufacture that parent suite.
    """
    cases = list(suite.iter("testcase"))
    if len(cases) != 1:
        return False
    tc = cases[0]
    if (suite.get("name") != name
            or tc.get("classname") != classname
            or tc.get("name") != name
            or tc.get("file") != file_name):
        return False
    values = [prop.get("value") for prop in tc.iter("property")
              if prop.get("name") == "process_rc"]
    # A complete pytest session has one of the two normal pytest outcomes.
    # Kills, signals and setup failures outside that contract are NORECORD and
    # the driver deliberately emits no process case for them.
    return len(values) == 1 and values[0] in {"0", "1"}


def _trusted_process_case_ids(root: ET.Element) -> set:
    """Object ids of cases whose parent suite authenticates their role."""
    trusted = set()
    for suite in root.iter("testsuite"):
        cases = list(suite.iter("testcase"))
        if len(cases) != 1:
            continue
        tc = cases[0]
        classname = tc.get("classname") or ""
        if classname == "pytest_per_file_process":
            file_name = tc.get("file") or ""
            name = f"{file_name}::process_exit"
        elif classname == "pytest_aggregate_process":
            file_name = "<aggregate>"
            name = "whole_selection::process_exit"
        else:
            continue
        if _valid_process_case(suite, classname=classname, name=name,
                               file_name=file_name):
            trusted.add(id(tc))
    return trusted


def junit_per_file_process_files(path: Path) -> set:
    """Selected file paths with exactly one valid per-file attestation."""
    root = ET.parse(str(path)).getroot()
    counts: Dict[str, int] = {}
    for suite in root.iter("testsuite"):
        cases = list(suite.iter("testcase"))
        if len(cases) != 1:
            continue
        tc = cases[0]
        if tc.get("classname") != "pytest_per_file_process":
            continue
        file_name = tc.get("file") or ""
        name = f"{file_name}::process_exit"
        if _valid_process_case(
                suite, classname="pytest_per_file_process", name=name,
                file_name=file_name):
            counts[file_name] = counts.get(file_name, 0) + 1
    # Duplicated attestations are malformed, not stronger evidence.
    return {file_name for file_name, count in counts.items() if count == 1}


def per_file_record_gaps(path: Path, selection: Sequence[str],
                         aggregate_present: bool) -> Optional[List[str]]:
    """Selected files with no valid per-file attestation — or ``None`` when the
    question was NOT PUT, which is a different answer from "none missing".

    WHEN THE QUESTION IS PUT (vibe-ic#1709)
    ---------------------------------------
    Per-file sessions are diagnostic recovery: `pytest_per_file_junit.py` runs
    them only after the aggregate record is lost, so a healthy landing carries
    an aggregate attestation and NO per-file evidence at all. Demanding one per
    selected file unconditionally would refuse every landing — the ban this
    whole program exists to avoid — so the population is derived from what the
    report itself claims:

      aggregate attested, no per-file evidence  -> NOT ASKED. The authoritative
                                                   whole-selection question was
                                                   answered and recovery never
                                                   ran; ``None``.
      any per-file attestation present          -> ASKED over the whole
                                                   selection. The report claims
                                                   per-file coverage, and a
                                                   selected file missing from
                                                   it is a session whose
                                                   record was LOST, not one
                                                   that was never needed.
      no aggregate attestation                  -> ASKED. The aggregate is
                                                   already an absolute refusal;
                                                   asking here is what NAMES
                                                   the file(s) behind it.

    Returning ``None`` rather than ``[]`` for the first row is the same law the
    rest of this file follows: a check that could not fire must be legible as
    such, never as a check that fired and found nothing.
    """
    attested = junit_per_file_process_files(path)
    if aggregate_present and not attested:
        return None
    return sorted(set(selection) - attested)


def junit_has_aggregate_process(path: Path) -> bool:
    """Whether the report has exactly one valid aggregate attestation."""
    root = ET.parse(str(path)).getroot()
    valid = 0
    for suite in root.iter("testsuite"):
        if _valid_process_case(
                suite, classname="pytest_aggregate_process",
                name="whole_selection::process_exit",
                file_name="<aggregate>"):
            valid += 1
    return valid == 1


def junit_red_count(path: Path) -> int:
    root = ET.parse(str(path)).getroot()
    process_cases = _trusted_process_case_ids(root)
    n = 0
    for tc in root.iter("testcase"):
        if _is_red(_testcase_outcome(
                tc, process_attested=id(tc) in process_cases)):
            n += 1
    return n


def junit_aggregate_red_count(path: Path) -> int:
    """Red outcomes in the authoritative aggregate channel only."""
    return sum(1 for outcome in read_aggregate_junit(path).values()
               if _is_red(outcome))


# ------------------------------------------------------------------- the delta


def failed_set_delta(base: Dict[str, str], cand: Dict[str, str]) -> Delta:
    d = Delta(base_total=len(base), candidate_total=len(cand),
              overlap=len(set(base) & set(cand)))
    for k in sorted(set(base) | set(cand)):
        b = base.get(k, ABSENT)
        c = cand.get(k, ABSENT)
        if _is_red(c):
            if _same_red(b, c):
                d.preexisting.append(k)
            else:
                d.new_failures.append(k)
                # NEW-BROKEN vs NEW-BROUGHT (vibe-ic#1417). `b` is ABSENT both
                # when the base RAN the test and it passed, and when the base
                # never had the test at all — and only the first is a behaviour
                # this change broke. The membership test, not the outcome, is
                # what separates them, so it is asked of `base` directly.
                #
                # Only meaningful when the base actually reported. With an empty
                # base every id is absent and the split would read as "nothing
                # was broken, it is all new", which is the flattering direction
                # and false. `decide` already discloses base_total == 0; this
                # stays silent there rather than adding a second wrong sentence.
                if base and k not in base:
                    d.new_absent_on_base.append(k)
        elif _is_red(b):
            if c in SILENT:
                # FAILED -> SKIPPED / ABSENT. Never an improvement: the failure
                # did not go away, the question did.
                d.silenced.append(k)
            else:
                d.fixed.append(k)
        elif _is_passed(b) and c in SILENT:
            d.weakened.append(k)
    return d


# --------------------------------------------------------------- land.sh log


def parse_land_log(text: str) -> LandLog:
    log = LandLog(sentinel_seen=_LAND_SENTINEL in text)
    for line in text.splitlines():
        if line.startswith(_NON_TARGET_COMPLETE):
            log.non_target_complete = True
        if line.startswith(_FAILURES_TERMINAL):
            log.failure_terminal_seen = True
        m = _LAND_LINE.match(line)
        if m:
            word, label = m.group(1), m.group(2)
            {"PASS": log.passed, "FAIL": log.failed,
             "SKIP": log.skipped, "REPORT": log.reported}[word].append(label)
            continue
        m = _STAMPED.search(line)
        if m:
            log.stamped_sha = m.group(1)
    return log


# ------------------------------------------------- the hygiene finding delta
#
# vibe-ic#1498. The comparison itself lives in `hygiene_finding_delta.py`, which
# is tested on its own; what lives here is only WHEN TO ASK IT and how a missing
# arm is read. Those two are the part that decides a landing, so they are in the
# file that decides landings.


def read_hygiene_delta(base_path: str, cand_path: str, base_host: str,
                       cand_host: str,
                       trusted_transition_evidence: str = ""
                       ) -> Optional[dict]:
    """The hygiene finding differential, or ``None`` when it was not asked for.

    ``None`` is NOT a clean result and `decide` never reads it as one — it is
    the disclosed degradation to the per-label comparison, taken when the BASE
    arm produced no record (a `--base-gate-cache` hit skips that arm entirely,
    and the branch under test does not control that).

    A base record WITHOUT a candidate record is the opposite case and is not
    ``None``: it is a REFUSAL, because the side that failed to measure is the
    tree being judged.
    """
    if not str(base_path).strip():
        return None
    if not str(cand_path).strip():
        return {"status": HYG_REFUSED, "refusal":
                "a BASE hygiene record was supplied and no CANDIDATE one was, "
                "so the arm that did not measure is the tree under test; its "
                "silence is not an empty finding set"}
    # Imported from THIS file's directory, so the comparison comes from the
    # verifier's tree alongside the verdict — see "WHERE EACH HALF COMES FROM"
    # in gatekeeper-verify-merge.sh. A tree under test must not be able to
    # supply the program that judges it.
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import hygiene_finding_delta as _H  # noqa: WPS433
    except Exception as exc:                # pragma: no cover - wiring failure
        return {"status": HYG_REFUSED, "refusal":
                f"the two arms' hygiene records were supplied but "
                f"`hygiene_finding_delta` could not be imported from {here} "
                f"({exc}), so nothing was differenced"}
    evidence = (Path(trusted_transition_evidence)
                if str(trusted_transition_evidence).strip() else None)
    return _H.compare(
        Path(base_path), Path(cand_path), base_host, cand_host,
        trusted_transition_evidence_path=evidence)


# ------------------------------------------------------------------- the gate
#
# EVERYTHING ABOVE MEASURES. THIS DECIDES. One function, one call site.


def _load_red_since():
    """`gate_red_since_check`, loaded by path at the moment it is needed.

    It owns the acknowledgement vocabulary and the deadline; this file owns the
    decision to consume it. Loading it lazily keeps this module's import graph
    exactly what it was.
    """
    import importlib.util
    path = Path(__file__).resolve().parent / "gate_red_since_check.py"
    spec = importlib.util.spec_from_file_location(
        "_lmv_gate_red_since_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def decide(*, rebase_status: str, expected_tree: str, verified_tree: str,
           github_tree: Optional[str], land: LandLog, delta: Delta,
           verified_sha: str, truncated: bool, dropped_files: Sequence[str],
           selection_size: int, replayed_tree: str = "",
           base_dropped_files: Sequence[str] = (),
           base_selection_supplied: bool = True,
           base_land: Optional[LandLog] = None,
           hygiene: Optional[dict] = None,
           red_since_ledger: Optional[Sequence[dict]] = None,
           commit_age: Optional[Callable[[str], Optional[int]]] = None,
           verification_tier: str = TIER_MERGE_TREE,
           git_version: str = "", tier_reason: str = "",
           missing_process_files: Sequence[str] = (),
           aggregate_process_present: bool = True,
           base_missing_process_files: Sequence[str] = (),
           base_aggregate_process_present: bool = True,
           candidate_gate_rc: int = 0,
           require_composite_gate_record: bool = False,
           candidate_test_worktree_status: str = "clean",
           base_test_worktree_status: str = "clean") -> Verdict:
    reasons: List[str] = []
    notes: List[str] = []
    disclosures: List[str] = []
    #: Set only by the hygiene finding differential, which is the one input that
    #: can be PRESENT and still unable to answer. Carried to the final Verdict
    #: instead of returning early, so the reasons found after it are not lost.
    unmeasurable = False

    # `reasons + [...]`, never a fresh list, and `disclosures` carried through.
    # An early return that drops what was already found makes the operator hunt:
    # a conflicting rebase and an uncomputable merge tree are the SAME event seen
    # twice, and printing only the second names the symptom while hiding the
    # cause. The same argument applies to the tier — a refusal that does not say
    # WHICH tier could not answer sends the reader to the wrong host.
    def _stop(reason: str) -> Verdict:
        return Verdict(False, reasons + [reason], notes, unmeasurable=True,
                       disclosures=disclosures)

    # ---- WHICH TIER ANSWERED, AND WHAT IT THEREFORE DID NOT CHECK ----
    # FAIL CLOSED ON AN UNKNOWN TIER, before anything else is read. A third tier
    # arriving by typo must not inherit the strong tier's silence: if the gate
    # cannot say what was verified, nothing was verified.
    if verification_tier not in TIERS:
        return Verdict(False, reasons + [
            f"UNKNOWN VERIFICATION TIER {verification_tier!r} — this program "
            f"knows {' and '.join(TIERS)} and cannot say what was checked, so "
            f"nothing was."], notes, unmeasurable=True,
            disclosures=["VERIFICATION_TIER_UNKNOWN"])

    if verification_tier == TIER_DIRECT_PUSH:
        # NOT a third degradation of the merge path. On `git push origin main`
        # the commit under gate IS the commit that lands, so there is no second
        # computation of one tree for a cross-check to compare — the check is
        # NOT APPLICABLE, and the code says so in its own word rather than
        # borrowing the fallback's, because borrowing it would tell a reader
        # that something was lost here.
        disclosures += ["VERIFICATION_TIER_DIRECT_PUSH",
                        "SQUASH_VS_REBASE_CROSS_CHECK_NOT_APPLICABLE"]
        notes.append(
            "DIRECT-PUSH TIER: nothing is squashed and no forge merge exists, "
            "so the tree measured is the tree that lands and the "
            "squash-vs-rebase cross-check is NOT APPLICABLE (not 'not "
            "performed' — there is no second tree it could disagree with). "
            "Every other refusal reason was computed exactly as the merge path "
            "computes it, including the cross-tree checks, which the caller "
            "keeps armed by passing the pushed commit's tree as both "
            "--expected-tree and --verified-tree."
            + (f" ({tier_reason})" if tier_reason else ""))
    elif verification_tier == TIER_REBASE_REPLAY:
        disclosures += ["VERIFICATION_TIER_REBASE_REPLAY",
                        "SQUASH_VS_REBASE_CROSS_CHECK_NOT_PERFORMED"]
        notes.append(
            "DEGRADED TIER: the tree under test is the REBASE REPLAY, not a "
            "`merge-tree --write-tree` 3-way merge, so the squash-vs-rebase "
            "cross-check WAS NOT PERFORMED — the phantom-revert shape, where "
            "replay and merge disagree, would not have been caught here"
            + (f" ({tier_reason})" if tier_reason else "")
            + f". git found: {git_version or 'unknown'}; needed for the strong "
              f"tier: >= {MERGE_TREE_MIN_VERSION}. Every OTHER refusal reason "
              f"was computed exactly as the strong tier computes it.")
    else:
        disclosures.append("VERIFICATION_TIER_MERGE_TREE")
        disclosures.append("SQUASH_VS_REBASE_CROSS_CHECK_PERFORMED")

    # The forge's own merge is an independent second opinion computed by a git
    # new enough to have the capability. Recorded either way, because under the
    # fallback its PRESENCE is the only cross-check left and its ABSENCE is
    # exactly how much was lost.
    disclosures.append("FORGE_CROSS_CHECK_PERFORMED" if github_tree
                       else "FORGE_CROSS_CHECK_ABSENT")
    if verification_tier == TIER_REBASE_REPLAY and github_tree:
        notes.append(
            "the forge published a merge for this same base, so the replayed "
            "tree still got one independent cross-check")

    if rebase_status != "ok":
        reasons.append(
            "REBASE CONFLICT — the PR does not apply to the current base, so "
            "no tree was verified. Rebase the branch and re-run.")

    if not expected_tree or not verified_tree:
        # UNDER THE FALLBACK this is still reachable and still refuses: the
        # replay is adopted as the tree under test ONLY when it succeeded, so a
        # conflicted rebase leaves it empty and lands here. The fallback trades
        # away a cross-check, never the fail-closed property.
        return _stop(
            "THE MERGE TREE COULD NOT BE COMPUTED — nothing was verified.")

    # Vacuous under the fallback — `expected_tree` IS `replayed_tree` there, and
    # that identity is the disclosed loss. Kept unconditional so a shell that
    # ever hands over an inconsistent pair is caught in either tier.
    if replayed_tree and replayed_tree != expected_tree:
        # REPLAY vs 3-WAY MERGE. Rebasing asks "does the branch's intent still
        # apply"; merging asks "does its text still combine". The phantom-revert
        # shape is where the two answers come apart, and only one of them is what
        # `gh pr merge` will create.
        reasons.append(
            f"THE REPLAY AND THE MERGE DISAGREE — rebasing the branch produces "
            f"tree {replayed_tree[:12]}, merging it produces "
            f"{expected_tree[:12]}. One of them is not what lands.")

    if expected_tree != verified_tree:
        reasons.append(
            f"VERIFIED THE WRONG TREE — the gates ran on {verified_tree[:12]} "
            f"but the merge would produce {expected_tree[:12]}. A verdict about "
            f"a tree that is not the tree that lands is worth nothing.")

    if github_tree and github_tree != expected_tree:
        reasons.append(
            f"THE FORGE DISAGREES — refs/pull/*/merge is tree "
            f"{github_tree[:12]}, locally the merge is {expected_tree[:12]}. "
            f"`gh pr merge` will create the FORGE's tree, which is not the one "
            f"measured here.")

    if not land.sentinel_seen or not (land.passed or land.failed):
        return _stop(
            "THE LANDING GATES DID NOT RUN — gatekeeper-land.sh produced no "
            "gate lines, so its silence is not a pass.")

    if require_composite_gate_record:
        if candidate_gate_rc not in (0, 1):
            return _stop(
                "THE NON-TARGET GATE ARM DID NOT EXIT NORMALLY — "
                f"gatekeeper-land.sh rc={candidate_gate_rc}; a partial log is "
                "not a completed gate record.")
        terminal_seen = (land.non_target_complete if candidate_gate_rc == 0
                         else land.failure_terminal_seen)
        if not terminal_seen:
            return _stop(
                "THE NON-TARGET GATE ARM PRODUCED NO COMPLETE TERMINAL RECORD "
                f"FOR rc={candidate_gate_rc} — some gate lines were printed, "
                "but the arm did not prove that it reached its normal end.")

    if candidate_test_worktree_status == "unknown":
        return _stop(
            "THE CANDIDATE TEST WORKTREE COULD NOT BE INSPECTED AFTER B1 — "
            "the verifier cannot prove the parallel test arm left its subject "
            "unchanged.")
    if candidate_test_worktree_status == "wrong-head":
        reasons.append(
            "THE CANDIDATE TEST ARM MOVED OFF THE VERIFIED COMMIT — B1's "
            "JUnit is about a different tree than the tree that would land.")
    elif candidate_test_worktree_status != "clean":
        reasons.append(
            "THE CANDIDATE TEST ARM WROTE INTO ITS WORKTREE — B1 did not "
            "measure an immutable candidate tree.")

    if base_selection_supplied and base_test_worktree_status == "unknown":
        return _stop(
            "THE BASE TEST WORKTREE COULD NOT BE INSPECTED AFTER A1 — the "
            "verifier cannot prove the baseline test arm left its subject "
            "unchanged.")
    if (base_selection_supplied
            and base_test_worktree_status == "wrong-head"):
        reasons.append(
            "THE BASE TEST ARM MOVED OFF THE BASE COMMIT — A1's JUnit is "
            "about a different baseline and cannot be subtracted.")
    elif base_selection_supplied and base_test_worktree_status != "clean":
        reasons.append(
            "THE BASE TEST ARM WROTE INTO ITS WORKTREE — A1 did not measure "
            "an immutable baseline tree.")

    # Runtime attestations are read from the report itself — never source text
    # and never the combined driver/subject stdout.  The aggregate session is
    # the original, authoritative whole-selection question.  Per-file sessions
    # are diagnostic recovery after aggregate NORECORD; requiring them on a
    # complete aggregate would repeat the suite on every successful landing.
    # `per_file_record_gaps` therefore decides WHETHER the per-file question is
    # put; this block decides what its answer means (vibe-ic#1709).
    #
    # BOTH LISTS ARE READ HERE AND NOWHERE ELSE. Until #1709 they were declared
    # in this signature, initialised to `[]` in `main`, and never populated, so
    # the only thing carrying a per-file NORECORD to this decision was
    # `tools/gatekeeper-land.sh`'s `grep -qa '^NORECORD'` over the driver's
    # COMBINED driver/subject stdout — a channel pytest can print into, and the
    # one input this file's own docstring says it does not trust. Measured on
    # 7c376e348 with a candidate report whose aggregate suite was intact and one
    # selected file's per-file attestation removed:
    #
    #     grep label absent               -> LAND OK          rc=0
    #     grep label on the candidate     -> REFUSE, generic  rc=1
    #     grep label on BOTH arms         -> LAND OK          rc=0
    #
    # The third row is the worse half and it is why this is a REASON rather than
    # a gate label: a label goes through the per-label base differential, so a
    # hang that fires on both arms — the exact shape `pytest_per_file_junit.py`
    # was written for — is scored PRE-EXISTING and excused. A reason is absolute
    # and NAMES the file, which is the difference between a refusal a reader can
    # act on and one that sends them looking in the wrong place.
    if missing_process_files:
        reasons.append(
            f"{len(missing_process_files)} SELECTED TEST FILE(S) HAVE NO "
            f"PER-FILE SESSION RECORD IN THE CANDIDATE REPORT — the per-file "
            f"question was put (see `candidate_aggregate_process_present` for "
            f"which of the two ways) and these files did not answer it, so "
            f"their sessions are UNKNOWN, not clean. This is an absolute "
            f"refusal and cannot be waived by the base gate log. Missing: "
            + ", ".join(missing_process_files[:5])
            + ("…" if len(missing_process_files) > 5 else ""))
    if not aggregate_process_present:
        reasons.append(
            "THE CANDIDATE AGGREGATE TEST SESSION PRODUCED NO COMPLETE RECORD "
            "— cross-file/order semantics are UNKNOWN, not clean. This is an "
            "absolute refusal and cannot be waived by the base gate log.")
    if (land.test_tier_failed and not delta.new_failures
            and not delta.preexisting):
        reasons.append(
            "THE TARGETED TEST TIER FAILED BUT THE CANDIDATE REPORT CONTAINS "
            "NO RED TESTCASE OR PROCESS VERDICT — the failure is unexplained "
            "by the machine record and cannot be treated as green.")
    # The base is the permissive arm of a differential, so its aggregate
    # attestation remains independently mandatory.  A complete candidate can
    # never compensate for an unknown baseline.  The per-file question is asked
    # of arm A on the same terms and for #1443's reason: what the baseline did
    # not measure is what the branch may delete for free.
    if base_missing_process_files:
        reasons.append(
            f"{len(base_missing_process_files)} SELECTED TEST FILE(S) HAVE NO "
            f"PER-FILE SESSION RECORD ON THE BASE — the per-file question was "
            f"put of arm A and these files did not answer it, so what they "
            f"would have shown is UNKNOWN and `silenced`/`weakened` were "
            f"computed over a SUBSET of the baseline. Missing: "
            + ", ".join(base_missing_process_files[:5])
            + ("…" if len(base_missing_process_files) > 5 else ""))
    if base_selection_supplied and not base_aggregate_process_present:
        reasons.append(
            "THE BASE AGGREGATE TEST SESSION PRODUCED NO COMPLETE RECORD — "
            "cross-file/order failures on the baseline are UNKNOWN. This is "
            "an absolute refusal, not a pre-existing failure to subtract.")

    # ---- the GATE differential, on exactly the rule the test tier uses ----
    # Not a nicety: measured 2026-08-12 at `e4880703b`, TWO of the repo-hygiene
    # gates (`flow_gate_enforcement_audit`, the 63x8 census freshness check) are
    # red on the base itself. An absolute "any gate FAIL refuses" would therefore
    # have refused every landing — the ban this whole program exists to avoid.
    if base_land is None or not base_land.sentinel_seen:
        notes.append("no base gate log was supplied, so every failing gate "
                     "counts against this branch — the comparison degraded to "
                     "'demand green', which is the strict direction")
        for label in land.blocking_failures:
            reasons.append(f"LANDING GATE FAILED — {label}")
    else:
        # KEYED BY `gate_key`, REPORTED BY LABEL — see the note on
        # `_LABEL_TREE_COUNT`. The arms measure two trees, so a label carrying a
        # per-tree count is not the same string on both sides even when it is
        # the same gate; every message below still prints the label verbatim.
        was_red = {gate_key(l): l for l in base_land.blocking_failures}
        now_red = {gate_key(l): l for l in land.blocking_failures}
        cand_skipped = {gate_key(l) for l in land.skipped}
        cand_passed = {gate_key(l): l for l in land.passed}
        cand_labels = set(cand_passed) | set(now_red) | cand_skipped
        for key in sorted(set(now_red) - set(was_red)):
            reasons.append(
                f"LANDING GATE FAILED, AND PASSED ON THE BASE — {now_red[key]}")
        # A gate that stopped being asked is not a gate that started passing —
        # the same rule as `failed -> skipped` for a test.
        for key in sorted(was_red):
            if key in cand_skipped or key not in cand_labels:
                reasons.append(
                    f"A FAILING GATE WAS SILENCED RATHER THAN FIXED — "
                    f"{was_red[key]} failed on the base and is no longer asked "
                    f"here")
        if any("range is empty" in l for l in base_land.skipped):
            # DISCLOSED, because it bounds what the base arm can excuse. Arm A2
            # measures the base over an EMPTY range on purpose, so the
            # range-scoped gates are not asked there — and a range-scoped gate
            # that answered VACUOUSLY would let a candidate's real violation be
            # waived as pre-existing. `landing is one commit` did exactly that
            # (it FAILs on `X..X` with "NOTHING to land") until it was made to
            # SKIP; the reader gets told the boundary rather than trusting it.
            notes.append("the base arm ran over an empty range, so the "
                         "range-scoped gates were not asked there — a failure "
                         "among them on this branch is necessarily new")
        for key in sorted(set(was_red) & set(now_red)):
            notes.append(f"gate fails on the base too, so it is not this "
                         f"branch's — {now_red[key]}")
        for key in sorted((set(was_red) - set(now_red)) & set(cand_passed)):
            notes.append("gate was failing on the base and now passes — "
                         f"{cand_passed[key]}")

    # ---- THE HYGIENE TIER, AT FINDING GRANULARITY (vibe-ic#1498) ----
    # The block above subtracted ONE label for a suite of ~80 gates. While the
    # base's suite is red — it has been, batch after batch — that label is
    # excused on the candidate too and a finding this branch INTRODUCED under it
    # is invisible. `hygiene_finding_delta` answers the finer question; the
    # answer is consumed here.
    #
    # STRICTLY ADDITIVE. Nothing below removes a reason the label-level rule
    # produced, so a landing that refuses without this input still refuses with
    # it. That is the property that makes reading a helper's verdict safe: the
    # worst a wrong CLEAN can do is leave the tier exactly as coarse as it was.
    hyg_status = (hygiene or {}).get("status")
    if hygiene is None:
        disclosures.append("HYGIENE_FINDING_DELTA_NOT_SUPPLIED")
        notes.append(
            "no hygiene finding differential was supplied, so the ~80-gate "
            "hygiene suite was judged by its ONE label only — a finding this "
            "branch introduced under a label the base already fails would not "
            "have been visible here (vibe-ic#1498)")
    elif hyg_status == HYG_REFUSED:
        # A REFUSAL BLOCKS, and it is UNMEASURABLE rather than merely refused:
        # the two records exist and cannot be differenced, which is not the same
        # event as a finding. `hygiene_finding_delta` returns this rather than
        # guessing, and a gate that cannot measure must never report that it
        # measured.
        disclosures.append("HYGIENE_FINDING_DELTA_REFUSED")
        unmeasurable = True
        reasons.append(
            "THE HYGIENE FINDING DIFFERENTIAL COULD NOT BE COMPUTED, so "
            "whether this branch introduced a hygiene finding is UNKNOWN — "
            f"{hygiene.get('refusal') or 'no reason given'}")
    elif hyg_status == HYG_INTRODUCED:
        disclosures.append("HYGIENE_FINDING_DELTA_INTRODUCED")
        intro = hygiene.get("introduced") or []
        reasons.append(
            f"{len(intro)} HYGIENE FINDING(S) INTRODUCED BY THIS BRANCH — "
            "present on the candidate and NOT on the base, under a suite label "
            "the per-label comparison excuses: "
            + "; ".join(_fmt_hyg(f) for f in intro[:8])
            + ("…" if len(intro) > 8 else ""))
    elif hyg_status == HYG_CLEAN:
        disclosures.append("HYGIENE_FINDING_DELTA_CLEAN")
        carried = hygiene.get("carried") or []
        notes.append(
            f"the hygiene suite introduced no finding: "
            f"{hygiene.get('candidate_findings')} on the candidate, "
            f"{hygiene.get('base_findings')} on the base, {len(carried)} "
            f"carried (which do NOT block), "
            f"{len(hygiene.get('cleared') or [])} cleared, over "
            f"{hygiene.get('declared')} declared gate(s)")
        for lbl in (hygiene.get("no_verdict_either_side") or [])[:8]:
            notes.append(f"hygiene gate reached no verdict on EITHER arm, so it "
                         f"excuses nothing — {lbl}")
        for name in (hygiene.get("empty_corpora") or [])[:8]:
            notes.append(f"hygiene loop corpus expanded over 0 item(s) on some "
                         f"arm — {name}")
        # vibe-ic#1764. A corpus nothing OPENED gets its own sentence: "it
        # expanded over 0 item(s)" says a population was measured, and none
        # was. `.get` so a record from an older dispatcher simply has none.
        for name in (hygiene.get("absent_corpora") or [])[:8]:
            notes.append(f"hygiene loop corpus was NOT FOUND on some arm, so "
                         f"nothing was opened and there is no population to "
                         f"report — this is not a corpus that was read and "
                         f"holds 0 item(s) — {name}")
        # THE CROSS-CHECK `hygiene_finding_delta`'s own docstring asks for: a
        # difference that explains nothing cannot excuse anything. If the suite
        # went from not-failing to failing and the finding list is empty, the
        # delta models fewer failure causes than the suite has, and the tier
        # must not be waved through on a list nobody could produce.
        cand_hyg_red = any(_HYGIENE_TIER.match(l) for l in land.failed)
        base_hyg_red = base_land is not None and any(
            _HYGIENE_TIER.match(l) for l in base_land.failed)
        if cand_hyg_red and not base_hyg_red:
            unmeasurable = True
            reasons.append(
                "THE HYGIENE SUITE FAILED HERE AND NOT ON THE BASE, YET THE "
                "FINDING DIFFERENTIAL NAMES NOTHING — the two disagree, so the "
                "finding list is incomplete and cannot account for the failure.")
    # ---- AN INHERITED RED IS NOT THIS BRANCH'S, AND IT IS STILL SOMEBODY'S ----
    #
    # The two tiers above both end the same way: a failure present on BOTH arms
    # is `notes` (`gate fails on the base too…`) or `carried (which do NOT
    # block)`. That subtraction is correct — an absolute "any FAIL refuses"
    # would refuse every landing, which is measured in the comment above the
    # gate differential — and it has no floor. MEASURED: `flow-gate enforcement
    # audit`, dispatched with a plain blocking `run`, was red on the base at
    # e4880703b on 2026-08-12 and still red at 752a8baa nine days, 704 commits
    # and 96 version-bearing landings later, and every one of those landings
    # was correct to allow it.
    #
    # The deadline that would end that already exists — `max_days` in
    # `tools/ci/gate_red_since.json`, read by `gate_red_since_check` — and
    # nothing ever opens it, because a row is voluntary and pure cost so no row
    # is ever written. This is the forcing function, and it has to be HERE:
    # a refusal wired inside the hygiene suite would be a gate in the suite, red
    # on both arms from its first landing, and subtracted by this very rule.
    #
    # STRICTLY ADDITIVE, like the tier above it: it only ever appends reasons.
    else:
        # A status this program does not know is not a pass. Reached only if the
        # helper grows a fourth answer without this branch being taught it.
        disclosures.append("HYGIENE_FINDING_DELTA_UNKNOWN_STATUS")
        unmeasurable = True
        reasons.append(
            f"THE HYGIENE FINDING DIFFERENTIAL RETURNED {hyg_status!r}, which "
            f"this program does not know how to read, so it read nothing.")

    # The rule itself runs AFTER the whole chain above, never inside it: it must
    # apply whatever status the differential returned, and it must not change
    # which branch of that chain is taken.
    if red_since_ledger is None or commit_age is None:
        # A RULE THAT DID NOT RUN MUST SAY SO. Without the ledger or without a
        # way to age a commit this cannot answer, and silence here would be
        # indistinguishable from "every inherited red is owned".
        disclosures.append("INHERITED_RED_DEADLINE_NOT_EVALUATED")
        notes.append(
            "the inherited-red deadline was NOT evaluated — no acknowledgement "
            "ledger and/or no row-age function was supplied, so whether a "
            "gate red on both arms is owned by a live deadline is UNKNOWN here")
    else:
        # IMPORTED HERE, NOT AT MODULE SCOPE. This file is executed by the
        # isolated trusted entry and its import graph is part of what the
        # protected runtime pins; a top-level `sys.path` insertion in an
        # authority file changes what every later import resolves to, and it
        # measurably broke two end-to-end cases when it was one.
        for reason in _load_red_since().inherited_red_reasons(
                list((hygiene or {}).get("carried") or []),
                list(red_since_ledger), commit_age):
            reasons.append(reason)

    if any("assigned at merge" in l for l in land.passed):
        # A DEFERRAL IS AN ACTION ITEM, NOT A CLEAN SHEET. Measured 2026-08-12:
        # the last twelve first-parent landings on `main` all carry the SAME
        # plugin version, and `version_bump_monotonic_check` returns rc=1 on each
        # of the last three under default semantics. Step 3.5 of the gatekeeper
        # loop assigns the version on the REBASED BRANCH — which a server-side
        # squash of the PR's remote head never sees. Same root cause as the test
        # tier, and it stays true until the assignment is pushed to the PR.
        notes.append("the version is DEFERRED to the merge: this PR does not "
                     "bump it, so assign it (gatekeeper_assign_version.py "
                     "--write, pushed to the PR branch) or the landing carries "
                     "the previous version")
    for label in land.skipped:
        notes.append(f"land.sh SKIP — {label}")
    for label in land.reported:
        notes.append(f"land.sh REPORT (never blocking) — {label}")

    if land.stamped_sha and not verified_sha.startswith(land.stamped_sha):
        reasons.append(
            f"THE STAMP NAMES ANOTHER COMMIT — stamped {land.stamped_sha}, "
            f"verified {verified_sha[:12]}.")

    if truncated:
        reasons.append(
            "THE CANDIDATE RUN WAS TRUNCATED — `--maxfail` stopped pytest, so "
            "the tests after it did not run and their absence is not a result. "
            "The differential cannot be computed against a partial run.")
    elif dropped_files:
        reasons.append(
            f"{len(dropped_files)} SELECTED TEST FILE(S) PRODUCED NO TEST CASE "
            f"— chosen and then never asked: "
            + ", ".join(sorted(dropped_files)[:5])
            + ("…" if len(dropped_files) > 5 else ""))

    # ---- THE SAME QUESTION, ASKED OF THE BASE ARM (vibe-ic#1443) ----
    # The completeness check above was asked only of the CANDIDATE, and the base
    # arm's only guard was `base_total == 0` — all-or-nothing, and a NOTE. A base
    # arm that ran SOME of its files lands between the two and was subtracted as
    # though it were whole.
    #
    # That direction is PERMISSIVE, which is why it is a refusal and not a note.
    # `silenced` and `weakened` are computed from what was RED (or PASSING) ON
    # THE BASE: a base failure that never got measured is a base failure the
    # branch is free to delete. Measured on 3d13e2c59 with one selected file
    # missing from the base report and every other input held identical, a
    # candidate that turned a red test into a SKIP went from
    #
    #     REFUSE  1 FAILING TEST(S) WERE SILENCED RATHER THAN FIXED
    # to
    #     LAND OK
    #
    # This is #1443's own law — "a two-arm comparison must assert that both arms
    # emitted a summary line before it subtracts anything" — applied to the arm
    # that did not have it. The junit form is the stronger one: it answers
    # per-FILE rather than per-run, so a base arm that died on its third file is
    # caught as well as one that never started.
    if base_dropped_files:
        reasons.append(
            f"{len(base_dropped_files)} SELECTED TEST FILE(S) PRODUCED NO TEST "
            f"CASE ON THE BASE — the base arm did not finish, so its failed set "
            f"is a SUBSET and a silenced failure in the missing files would not "
            f"be visible: "
            + ", ".join(sorted(base_dropped_files)[:5])
            + ("…" if len(base_dropped_files) > 5 else ""))
    elif not base_selection_supplied:
        # DEGRADE LOUDLY. A caller that does not say what the base arm was ASKED
        # to run leaves the check above unable to fire, and a check that cannot
        # fire must say so rather than read as a clean sheet.
        notes.append(
            "no base selection was supplied (--base-selection), so the base "
            "arm's completeness was NOT checked — a base arm that ran only "
            "some of its files would have been subtracted as though whole")

    if delta.candidate_total == 0:
        return _stop(
            "THE CANDIDATE RAN NO TESTS — a clean result over an empty run is "
            "not a clean result.")

    if delta.base_total == 0:
        notes.append(
            "the base report is empty, so every candidate failure counts as "
            "NEW — the differential degraded to 'demand green', which is the "
            "strict direction")
    elif delta.overlap == 0:
        notes.append(
            "no test id appears on both sides, so the differential degraded to "
            "'demand green'")

    if delta.new_failures:
        reasons.append(
            f"{len(delta.new_failures)} NEW FAILURE(S) THIS BRANCH OWNS: "
            + ", ".join(delta.new_failures[:8])
            + ("…" if len(delta.new_failures) > 8 else ""))
        # SPLIT THE COUNT, NEVER THE VERDICT (vibe-ic#1417). Both halves still
        # refuse — a test you bring, failing, is yours. What changes is that a
        # reviewer can see WHICH kind, because the two demand different work:
        # a broken behaviour is a bug to fix, a failing new assertion is a
        # reconciliation with whatever else is in the batch.
        #
        # MEASURED on a 141-PR batch composed on 3d13e2c59: 5 nodes reported as
        # NEW, of which FOUR do not exist on main at all and ONE is a real
        # regression. A reviewer sizing that batch off "5 NEW FAILURES" is
        # reading a 5x overstatement, and reads it consistently — which is
        # enough to reject every large batch forever.
        n_brought = len(delta.new_absent_on_base)
        if n_brought:
            notes.append(
                f"of those {len(delta.new_failures)}, {n_brought} do NOT exist "
                f"on the base at all — assertions this change BRINGS, failing, "
                f"rather than behaviour it broke; the other "
                f"{len(delta.new_failures) - n_brought} ran on the base and "
                f"passed. Both refuse. "
                + ", ".join(delta.new_absent_on_base[:5])
                + ("…" if n_brought > 5 else ""))
    if delta.silenced:
        reasons.append(
            f"{len(delta.silenced)} FAILING TEST(S) WERE SILENCED RATHER THAN "
            f"FIXED (failed -> skipped/absent): "
            + ", ".join(delta.silenced[:8])
            + ("…" if len(delta.silenced) > 8 else ""))

    if delta.preexisting:
        notes.append(
            f"{len(delta.preexisting)} failure(s) are pre-existing on the base "
            f"and are NOT this branch's: " + ", ".join(delta.preexisting[:5])
            + ("…" if len(delta.preexisting) > 5 else ""))
    if delta.fixed:
        notes.append(f"{len(delta.fixed)} base failure(s) now pass")
    if delta.weakened:
        reasons.append(
            f"{len(delta.weakened)} PASSING TEST(S) WERE WEAKENED "
            "(passed -> skipped/absent): " + ", ".join(delta.weakened[:8])
            + ("…" if len(delta.weakened) > 8 else ""))
    notes.append(f"{selection_size} test file(s) selected; "
                 f"{delta.candidate_total} test(s) ran on the candidate, "
                 f"{delta.base_total} on the base")

    # THE DECISION. Neutering this line — and only this line — is the mutant the
    # shipped tests are calibrated against. Everything above still measures and
    # still prints; only the answer changes.
    #
    # THE TIER IS NOT AN INPUT TO IT. `disclosures` rides alongside the answer
    # and never into it: the fallback reports what it could not check, it does
    # not get to excuse anything it did check. A tier that could soften a reason
    # would be the "fallback that passes everything" this design refuses.
    return Verdict(not reasons, reasons, notes, unmeasurable=unmeasurable,
                   disclosures=disclosures)


# --------------------------------------------------------------------- the CLI


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="the merge-path landing verdict (chip-AGNOSTIC)")
    ap.add_argument("--base-sha", required=True)
    ap.add_argument("--base-tree", required=True,
                    help="tree of the exact BASE commit owning the validator")
    ap.add_argument("--head-sha", required=True)
    ap.add_argument("--verified-sha", required=True,
                    help="the local stand-in for the squash commit whose "
                         "TREE is what would land")
    ap.add_argument("--rebase-status", required=True, choices=("ok", "conflict"))
    ap.add_argument("--expected-tree", default="")
    ap.add_argument("--verified-tree", default="")
    ap.add_argument("--github-tree", default="",
                    help="tree of refs/pull/<n>/merge, when the forge has one")
    ap.add_argument("--land-log", required=True)
    ap.add_argument("--base-land-log", default=None,
                    help="gatekeeper-land.sh's log for the UNTOUCHED base. "
                         "Without it every failing gate counts against the "
                         "branch, which is the strict direction")
    ap.add_argument("--replayed-tree", default="",
                    help="tree the rebase produced, cross-checked against the "
                         "merge tree")
    ap.add_argument("--selection", required=True)
    ap.add_argument("--base-selection", default="",
                    help="the file listing what ARM A actually asked pytest to "
                         "run on the base — the selection filtered to files "
                         "that exist there. Used to check the base arm FINISHED "
                         "(vibe-ic#1443); a base arm that ran only some of its "
                         "files hides `silenced`. Omitting it leaves the check "
                         "unable to fire, which is disclosed in the notes")
    ap.add_argument("--base-junit", required=True)
    ap.add_argument("--candidate-junit", required=True)
    # vibe-ic#1498 — the two arms' `repo_hygiene_gates.sh --summary-json`
    # records. OPTIONAL, and their absence degrades to the per-label comparison
    # with a disclosure; supplying the BASE one without the candidate's is a
    # refusal, because then the unmeasured side is the tree under test.
    ap.add_argument("--base-hygiene", default="",
                    help="`--summary-json` record from the BASE arm's hygiene "
                         "run (vibe-ic#1498)")
    ap.add_argument("--candidate-hygiene", default="",
                    help="`--summary-json` record from the CANDIDATE arm")
    ap.add_argument("--base-hygiene-host", default="",
                    help="the host the base record was measured on; REQUIRED "
                         "by the differential and never inferred — these "
                         "findings are host-dependent")
    ap.add_argument("--candidate-hygiene-host", default="",
                    help="the host the candidate record was measured on")
    ap.add_argument("--trusted-transition-evidence", default="",
                    help="parent-owned routed-corpus manifest and independent "
                         "execution receipts; required by the trusted hygiene "
                         "judge for an EMPTY-to-expanded transition")
    ap.add_argument("--protected-transition-receipt", default="",
                    help="BASE-validator pre/post-identical receipt binding the "
                         "atomic protected landing-runtime tuple")
    ap.add_argument("--maxfail", type=int, default=10,
                    help="the --maxfail gatekeeper-land.sh passes to pytest; "
                         "used only to tell truncation from a real absence")
    ap.add_argument("--gate-edited", action="append", default=[],
                    help="a path this branch changes that is part of the gate "
                         "judging it; disclosed, never blocking")
    ap.add_argument("--verification-tier", default=TIER_MERGE_TREE,
                    help="which tier computed the tree under test: "
                         f"{TIER_MERGE_TREE} (git >= {MERGE_TREE_MIN_VERSION}, "
                         f"the 3-way merge, cross-checked by the replay) or "
                         f"{TIER_REBASE_REPLAY} (the fallback: the replay IS "
                         f"the tree under test and the squash-vs-rebase "
                         f"cross-check is not performed) or "
                         f"{TIER_DIRECT_PUSH} (the direct-push path: no PR, no "
                         f"squash, no forge merge — the commit under gate IS "
                         f"the commit that lands, so the cross-check is NOT "
                         f"APPLICABLE rather than not performed). Any other "
                         f"value refuses as unmeasurable")
    ap.add_argument("--git-version", default="",
                    help="the git version measured on this host, named in the "
                         "tier disclosure so the refusal is actionable")
    ap.add_argument("--merge-tree-min-version", default=MERGE_TREE_MIN_VERSION,
                    help="the git version the strong tier needs")
    ap.add_argument("--tier-reason", default="",
                    help="why this tier was selected, when it was not the "
                         "strong one")
    ap.add_argument("--candidate-gate-rc", type=int, default=0,
                    help="OS exit status of the candidate non-target gate arm")
    ap.add_argument("--red-since-ledger", default="",
                    help="tools/ci/gate_red_since.json as the BASE commit "
                         "carries it. The acknowledgement policy is BASE-owned, "
                         "like the protected transition manifest: a candidate "
                         "must not be able to grant itself an amnesty. Absent "
                         "means the inherited-red deadline is NOT evaluated, "
                         "and that is DISCLOSED rather than assumed clean")
    ap.add_argument("--red-since-repo", default="",
                    help="a repository containing the commits the ledger's "
                         "`since` fields cite, used only to read their dates "
                         "and age each row in DAYS. Absent means the same "
                         "disclosure")
    ap.add_argument("--require-composite-gate-record", action="store_true",
                    help="require the B2 rc and matching terminal sentinel; "
                         "used when targeted evidence comes from parallel B1")
    ap.add_argument("--candidate-test-worktree-status", default="clean",
                    choices=("clean", "dirty", "wrong-head", "unknown"),
                    help="trusted post-B1 git-status result from its isolated "
                         "candidate-test worktree")
    ap.add_argument("--base-test-worktree-status", default="clean",
                    choices=("clean", "dirty", "wrong-head", "unknown"),
                    help="trusted post-A1 git-status result from its isolated "
                         "base-test worktree")
    ap.add_argument("--json", dest="json_out", default=None)
    a = ap.parse_args(argv)

    try:
        land = parse_land_log(Path(a.land_log).read_text(errors="replace"))
    except OSError:
        land = LandLog()

    base_land = None
    if a.base_land_log:
        try:
            base_land = parse_land_log(
                Path(a.base_land_log).read_text(errors="replace"))
        except OSError:
            base_land = None

    try:
        selection = [l.strip() for l in
                     Path(a.selection).read_text(errors="replace").splitlines()
                     if l.strip()]
    except OSError:
        selection = []

    def _load(p: str, label: str):
        path = Path(p)
        if not path.is_file():
            return None
        try:
            return read_aggregate_junit(path, selection)
        except ET.ParseError as exc:
            print(f"[SKIP] landing_merge_verdict: the {label} report at {p} is "
                  f"not parseable ({exc})", file=sys.stderr)
            return None

    base_selection: List[str] = []
    if a.base_selection:
        try:
            base_selection = [
                l.strip() for l in
                Path(a.base_selection).read_text(errors="replace").splitlines()
                if l.strip()]
        except OSError:
            base_selection = []

    cand = _load(a.candidate_junit, "candidate")
    # An unreadable BASE report is not a refusal to answer: it makes every
    # candidate failure NEW, which is STRICTER than the differential, and
    # `decide` discloses the degradation in its notes. An unreadable CANDIDATE
    # report is the opposite — nothing was measured about what this branch
    # breaks — and `decide` returns unmeasurable for it via candidate_total == 0.
    base_raw = _load(a.base_junit, "base")
    base = base_raw or {}
    delta = failed_set_delta(base, cand or {})
    dropped: List[str] = []
    truncated = False
    missing_process_files: List[str] = []
    #: Whether the per-file completeness question was PUT at all, which a reader
    #: has to be able to tell from an empty list of gaps (vibe-ic#1709).
    candidate_per_file_checked = False
    aggregate_process_present = False
    if cand is not None:
        candidate_path = Path(a.candidate_junit)
        ran_files = junit_aggregate_files(candidate_path, selection)
        dropped = sorted(set(selection) - ran_files)
        truncated = (bool(dropped) and
                     junit_aggregate_red_count(candidate_path) >= a.maxfail)
        aggregate_process_present = junit_has_aggregate_process(candidate_path)
        # THE STRUCTURED PATH, CONNECTED (vibe-ic#1709). An unreadable candidate
        # report is deliberately left out: `cand is None` already refuses via
        # `candidate_total == 0`, and naming every selected file there would
        # report a per-file gap for a report nobody could parse.
        gaps = per_file_record_gaps(
            candidate_path, selection, aggregate_process_present)
        candidate_per_file_checked = gaps is not None
        missing_process_files = gaps or []
    # THE SAME QUESTION OF ARM A (vibe-ic#1443). The list is the base's OWN
    # selection, never `--selection`: a file the PR ADDS is legitimately absent
    # from the base report, and asking about it here would refuse every PR that
    # brings a new test file. A base arm that produced NO report at all while
    # having been asked for N files is the same defect at N — that is why the
    # `base_raw is None` arm names all of them rather than falling through to
    # the all-or-nothing note.
    base_dropped: List[str] = []
    base_missing_process_files: List[str] = []
    base_per_file_checked = False
    base_aggregate_process_present = True
    if base_selection:
        if base_raw is None:
            base_dropped = sorted(base_selection)
            base_aggregate_process_present = False
        else:
            base_path = Path(a.base_junit)
            base_dropped = sorted(
                set(base_selection)
                - junit_aggregate_files(base_path, base_selection))
            base_aggregate_process_present = junit_has_aggregate_process(
                base_path)
            # Over the BASE's own selection, never `--selection` — same reason
            # as `base_dropped` above: a file the PR ADDS cannot have a record
            # on a base that does not contain it.
            base_gaps = per_file_record_gaps(
                base_path, base_selection, base_aggregate_process_present)
            base_per_file_checked = base_gaps is not None
            base_missing_process_files = base_gaps or []

    hygiene = read_hygiene_delta(
        a.base_hygiene, a.candidate_hygiene,
        a.base_hygiene_host, a.candidate_hygiene_host,
        a.trusted_transition_evidence)

    protected_receipt, protected_transition, protected_error = (
        read_protected_transition_receipt(
            a.protected_transition_receipt,
            base_commit=a.base_sha,
            candidate_commit=a.verified_sha,
            base_tree=a.base_tree,
            candidate_tree=a.verified_tree,
        ))

    v = decide(rebase_status=a.rebase_status, expected_tree=a.expected_tree,
               verified_tree=a.verified_tree,
               github_tree=a.github_tree or None, land=land, delta=delta,
               verified_sha=a.verified_sha, truncated=truncated,
               dropped_files=dropped, selection_size=len(selection),
               base_dropped_files=base_dropped,
               base_selection_supplied=bool(base_selection),
               replayed_tree=a.replayed_tree, base_land=base_land,
               hygiene=hygiene,
               red_since_ledger=(
                   _load_red_since().load_ledger(Path(a.red_since_ledger))
                   if a.red_since_ledger else None),
               commit_age=(
                   _load_red_since().git_age_days(Path(a.red_since_repo))
                   if a.red_since_repo else None),
               verification_tier=a.verification_tier,
               git_version=a.git_version, tier_reason=a.tier_reason,
               missing_process_files=missing_process_files,
               aggregate_process_present=aggregate_process_present,
               base_missing_process_files=base_missing_process_files,
               base_aggregate_process_present=(
                   base_aggregate_process_present),
               candidate_gate_rc=a.candidate_gate_rc,
               require_composite_gate_record=(
                   a.require_composite_gate_record),
               candidate_test_worktree_status=(
                   a.candidate_test_worktree_status),
               base_test_worktree_status=a.base_test_worktree_status)

    if a.gate_edited:
        v.notes.append("this branch edits the gate that judges it: "
                       + ", ".join(a.gate_edited))
    if protected_error:
        v.ok = False
        v.unmeasurable = True
        v.reasons.append(
            "PROTECTED LANDING SOURCE TRANSITION IS UNMEASURED: "
            + protected_error)

    head = ("[PASS] landing_merge_verdict: LAND OK" if v.ok
            else "[FAIL] landing_merge_verdict: REFUSE")
    print(f"{head} — base {a.base_sha[:12]} + head {a.head_sha[:12]} "
          f"=> verified commit {a.verified_sha[:12]} tree "
          f"{(a.verified_tree or '?')[:12]} [tier {a.verification_tier}]")
    for r in v.reasons:
        print(f"  REFUSE  {r}")
    # PRINTED AND MACHINE-READABLE. The codes go to stdout as well as to the
    # JSON so an operator reading a terminal and a program reading a record are
    # told the same thing — a tier reported only in prose is a tier a downstream
    # cannot act on.
    for d in v.disclosures:
        print(f"  DISCLOSE  {d}")
    for n in v.notes:
        print(f"  note    {n}")
    print(f"  stamp   {land.stamped_sha or 'NONE (gatekeeper-land.sh withheld it)'}")

    # ALWAYS, including on an unmeasurable refusal. The record is what the
    # gatekeeper reads and what `--reassert` re-checks later; a refusal that
    # leaves no record makes the operator re-derive the reason by hand, which is
    # the habit that ends in landing without looking.
    if a.json_out:
        Path(a.json_out).write_text(json.dumps({
            "verdict": "LAND_OK" if v.ok else "REFUSE",
            "unmeasurable": v.unmeasurable,
            "base_sha": a.base_sha,
            "base_tree": a.base_tree,
            "head_sha": a.head_sha,
            "verified_sha": a.verified_sha,
            "rebase_status": a.rebase_status,
            "expected_tree": a.expected_tree,
            "verified_tree": a.verified_tree,
            "github_tree": a.github_tree,
            "reasons": v.reasons,
            "notes": v.notes,
            "replayed_tree": a.replayed_tree,
            "land": land.as_dict(),
            "candidate_gate_rc": a.candidate_gate_rc,
            "composite_gate_record_required": (
                a.require_composite_gate_record),
            "candidate_test_worktree_status": (
                a.candidate_test_worktree_status),
            "base_test_worktree_status": a.base_test_worktree_status,
            "base_land": base_land.as_dict() if base_land else None,
            "delta": delta.as_dict(),
            # vibe-ic#1498, MACHINE-READABLY. `null` means the differential was
            # NOT ASKED FOR — which a reader must be able to tell apart from
            # "asked and found nothing", because only one of those two says
            # anything about what this branch did to the hygiene suite.
            "hygiene_finding_delta": hygiene,
            "protected_landing_transition": protected_transition,
            "protected_transition_receipt": protected_receipt,
            "selection_size": len(selection),
            "dropped_selected_files": dropped,
            "candidate_run_truncated": truncated,
            # ARM A's completeness, machine-readably (vibe-ic#1443).
            # `base_selection_size == 0` means the check could not fire — a
            # reader must be able to tell that from "it fired and found
            # nothing", which is why the size travels with the list.
            "base_selection_size": len(base_selection),
            "dropped_base_selected_files": base_dropped,
            # PER-FILE COMPLETENESS, FROM STRUCTURED JUNIT (vibe-ic#1709). The
            # `*_checked` flags travel with the lists for the reason
            # `base_selection_size` travels with `dropped_base_selected_files`:
            # an empty list means "asked and nothing missing" only when the
            # question was put, and "aggregate-only evidence, per-file recovery
            # never ran" otherwise. Two different facts, one shape.
            "missing_candidate_process_files": missing_process_files,
            "candidate_per_file_records_checked": candidate_per_file_checked,
            "candidate_aggregate_process_present": aggregate_process_present,
            "missing_base_process_files": base_missing_process_files,
            "base_per_file_records_checked": base_per_file_checked,
            "base_aggregate_process_present": (
                base_aggregate_process_present),
            "test_evidence_mode": ("aggregate+per-file"
                                   if candidate_per_file_checked
                                   else "aggregate"),
            "gate_edited": a.gate_edited,
            # ---- WHAT THIS VERDICT DID NOT CHECK, MACHINE-READABLY ----
            # A disclosed weaker check beats a universal refusal ONLY if the
            # weakness is legible to whatever reads the record next. These four
            # keys are that contract: `verification_tier` names the tier,
            # `tier_degraded` is the one-bit answer, `squash_vs_rebase_cross_
            # check` names the specific check that was skipped, and
            # `disclosures` is the stable code list to key on.
            "verification_tier": a.verification_tier,
            "tier_degraded": a.verification_tier != TIER_MERGE_TREE,
            # THREE VALUES, NOT TWO. `NOT_APPLICABLE` is the direct-push
            # answer and it is NOT a synonym for `NOT_PERFORMED`: one says the
            # cross-check was skipped, the other says there was never a second
            # tree to cross-check. Collapsing them would make a complete
            # direct-push verdict indistinguishable from a degraded merge one.
            "squash_vs_rebase_cross_check": (
                "PERFORMED" if a.verification_tier == TIER_MERGE_TREE
                else "NOT_APPLICABLE"
                if a.verification_tier == TIER_DIRECT_PUSH
                else "NOT_PERFORMED"),
            "tier_reason": a.tier_reason,
            "disclosures": v.disclosures,
            "git_version": a.git_version,
            "git_version_required_for_merge_tree": a.merge_tree_min_version,
        }, indent=2) + "\n")

    if v.unmeasurable:
        return RC_CANNOT_MEASURE
    return RC_OK if v.ok else RC_REFUSE


if __name__ == "__main__":
    raise SystemExit(main())
