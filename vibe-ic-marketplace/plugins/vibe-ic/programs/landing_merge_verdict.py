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

So a PR is judged on WHAT IT BREAKS:

    base            candidate         decision
    ----            ---------         --------
    RED             RED               pre-existing — not this PR's
    RED             PASSED            FIXED (reported, never required)
    not-RED         RED               NEW FAILURE            -> REFUSE
    RED             SKIPPED / ABSENT  SILENCED               -> REFUSE
    PASSED          SKIPPED / ABSENT  WEAKENED (reported)

The SILENCED row is the one that has to be there. Without it the differential
rewards exactly the cheat it is supposed to catch: delete or skip a red test and
the failed set shrinks, so "what did this PR break" answers nothing while the
suite quietly stops asking. **FAILED -> SKIPPED is never an improvement.**

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
        [--verification-tier merge-tree|rebase-replay] [--git-version <v>]
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
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

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

# `run()` in gatekeeper-land.sh prints exactly two leading spaces, the word, two
# more spaces, then the label. `report()` prints REPORT and is NOT a gate.
_LAND_LINE = re.compile(r"^ {2}(PASS|FAIL|SKIP|REPORT) {2}(.+?)\s*$")
_LAND_SENTINEL = "=== gatekeeper landing gates"
# `printf '  FAIL  targeted tests (%s file(s))\n'` — the test tier, whose verdict
# this program overrides with the differential. NOT `targeted test selection
# produced no files`, which is a selection failure and stays a hard refusal.
_TEST_TIER = re.compile(r"^targeted tests(?:\s|\(|$)")
_STAMPED = re.compile(r"===\s*ALL GATES PASS\s*[—-]\s*stamped\s+(\S+)")

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


@dataclass
class Delta:
    """The failed-set difference. Every list holds junit keys."""

    new_failures: List[str] = field(default_factory=list)
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

    @property
    def blocking_failures(self) -> List[str]:
        """Every FAIL except the test tier, whose verdict the differential owns."""
        return [l for l in self.failed if not _TEST_TIER.match(l)]

    @property
    def test_tier_failed(self) -> bool:
        return any(_TEST_TIER.match(l) for l in self.failed)

    def as_dict(self) -> dict:
        return {
            "pass": self.passed,
            "fail": self.failed,
            "skip": self.skipped,
            "report": self.reported,
            "stamped_sha": self.stamped_sha,
            "blocking_failures": self.blocking_failures,
            "test_tier_failed": self.test_tier_failed,
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


# The verification TIERS. `merge-tree` is the strong path; `rebase-replay` is the
# fallback for a host whose git predates `merge-tree --write-tree` (>= 2.38), on
# which the strong path cannot start at all. Anything else is not a tier this
# program knows how to reason about, and it FAILS CLOSED on one — see `decide`.
TIER_MERGE_TREE = "merge-tree"
TIER_REBASE_REPLAY = "rebase-replay"
TIERS = (TIER_MERGE_TREE, TIER_REBASE_REPLAY)
MERGE_TREE_MIN_VERSION = "2.38"


# ---------------------------------------------------------------- junit reading


def _testcase_outcome(tc: ET.Element) -> str:
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
    out: Dict[str, str] = {}
    for tc in root.iter("testcase"):
        k = _key(tc)
        o = _testcase_outcome(tc)
        # A rerun/duplicate id keeps the WORST outcome. Two entries for one id
        # otherwise let an ordering accident decide whether a failure is seen.
        if k in out and out[k] in RED:
            continue
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


def junit_red_count(path: Path) -> int:
    root = ET.parse(str(path)).getroot()
    n = 0
    for tc in root.iter("testcase"):
        if _testcase_outcome(tc) in RED:
            n += 1
    return n


# ------------------------------------------------------------------- the delta


def failed_set_delta(base: Dict[str, str], cand: Dict[str, str]) -> Delta:
    d = Delta(base_total=len(base), candidate_total=len(cand),
              overlap=len(set(base) & set(cand)))
    for k in sorted(set(base) | set(cand)):
        b = base.get(k, ABSENT)
        c = cand.get(k, ABSENT)
        if c in RED:
            if b in RED:
                d.preexisting.append(k)
            else:
                d.new_failures.append(k)
        elif b in RED:
            if c in SILENT:
                # FAILED -> SKIPPED / ABSENT. Never an improvement: the failure
                # did not go away, the question did.
                d.silenced.append(k)
            else:
                d.fixed.append(k)
        elif b == PASSED and c in SILENT:
            d.weakened.append(k)
    return d


# --------------------------------------------------------------- land.sh log


def parse_land_log(text: str) -> LandLog:
    log = LandLog(sentinel_seen=_LAND_SENTINEL in text)
    for line in text.splitlines():
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


# ------------------------------------------------------------------- the gate
#
# EVERYTHING ABOVE MEASURES. THIS DECIDES. One function, one call site.


def decide(*, rebase_status: str, expected_tree: str, verified_tree: str,
           github_tree: Optional[str], land: LandLog, delta: Delta,
           verified_sha: str, truncated: bool, dropped_files: Sequence[str],
           selection_size: int, replayed_tree: str = "",
           base_dropped_files: Sequence[str] = (),
           base_selection_supplied: bool = True,
           base_land: Optional[LandLog] = None,
           verification_tier: str = TIER_MERGE_TREE,
           git_version: str = "", tier_reason: str = "") -> Verdict:
    reasons: List[str] = []
    notes: List[str] = []
    disclosures: List[str] = []

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

    if verification_tier == TIER_REBASE_REPLAY:
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
        notes.append(
            f"{len(delta.weakened)} passing test(s) became skipped/absent — "
            "read them: " + ", ".join(delta.weakened[:5])
            + ("…" if len(delta.weakened) > 5 else ""))
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
    return Verdict(not reasons, reasons, notes, disclosures=disclosures)


# --------------------------------------------------------------------- the CLI


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="the merge-path landing verdict (chip-AGNOSTIC)")
    ap.add_argument("--base-sha", required=True)
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
                         f"cross-check is not performed). Any other value "
                         f"refuses as unmeasurable")
    ap.add_argument("--git-version", default="",
                    help="the git version measured on this host, named in the "
                         "tier disclosure so the refusal is actionable")
    ap.add_argument("--merge-tree-min-version", default=MERGE_TREE_MIN_VERSION,
                    help="the git version the strong tier needs")
    ap.add_argument("--tier-reason", default="",
                    help="why this tier was selected, when it was not the "
                         "strong one")
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
            return read_junit(path, selection)
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
    if cand is not None:
        ran_files = junit_files(Path(a.candidate_junit), selection)
        dropped = sorted(set(selection) - ran_files)
        truncated = (bool(dropped)
                     and junit_red_count(Path(a.candidate_junit)) >= a.maxfail)
    # THE SAME QUESTION OF ARM A (vibe-ic#1443). The list is the base's OWN
    # selection, never `--selection`: a file the PR ADDS is legitimately absent
    # from the base report, and asking about it here would refuse every PR that
    # brings a new test file. A base arm that produced NO report at all while
    # having been asked for N files is the same defect at N — that is why the
    # `base_raw is None` arm names all of them rather than falling through to
    # the all-or-nothing note.
    base_dropped: List[str] = []
    if base_selection:
        if base_raw is None:
            base_dropped = sorted(base_selection)
        else:
            base_dropped = sorted(
                set(base_selection)
                - junit_files(Path(a.base_junit), base_selection))

    v = decide(rebase_status=a.rebase_status, expected_tree=a.expected_tree,
               verified_tree=a.verified_tree,
               github_tree=a.github_tree or None, land=land, delta=delta,
               verified_sha=a.verified_sha, truncated=truncated,
               dropped_files=dropped, selection_size=len(selection),
               base_dropped_files=base_dropped,
               base_selection_supplied=bool(base_selection),
               replayed_tree=a.replayed_tree, base_land=base_land,
               verification_tier=a.verification_tier,
               git_version=a.git_version, tier_reason=a.tier_reason)

    if a.gate_edited:
        v.notes.append("this branch edits the gate that judges it: "
                       + ", ".join(a.gate_edited))

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
            "base_land": base_land.as_dict() if base_land else None,
            "delta": delta.as_dict(),
            "selection_size": len(selection),
            "dropped_selected_files": dropped,
            "candidate_run_truncated": truncated,
            # ARM A's completeness, machine-readably (vibe-ic#1443).
            # `base_selection_size == 0` means the check could not fire — a
            # reader must be able to tell that from "it fired and found
            # nothing", which is why the size travels with the list.
            "base_selection_size": len(base_selection),
            "dropped_base_selected_files": base_dropped,
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
            "squash_vs_rebase_cross_check": (
                "PERFORMED" if a.verification_tier == TIER_MERGE_TREE
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
