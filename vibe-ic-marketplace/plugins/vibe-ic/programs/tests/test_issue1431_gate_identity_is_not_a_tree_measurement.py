"""A landing gate refused the shape this repo asks for: a fix that arrives with a test.

vibe-ic#1431 measured 67 verified-LAND, mergeable PRs against a `main` that had
not moved, and named the merge step as the constraint. This file gates one
mechanical reason that step refuses.

THE DEFECT
==========
`tools/gatekeeper-verify-merge.sh` runs `gatekeeper-land.sh` twice — arm A2 on
the untouched base, arm B on the candidate — and `landing_merge_verdict.decide`
subtracts one gate log from the other so that a gate already red on the base is
not charged to the branch. The subtraction matched gates BY THEIR PRINTED LABEL.

One gate bakes a per-tree measurement into its label::

    tools/gatekeeper-land.sh:381
        printf '  PASS  repo tools tests (%s file(s))\\n' "${#files[@]}"

`${#files[@]}` is a DISCOVERY count over `tools/` — deliberately so, because a
hardcoded roster goes stale silently. So any branch that adds or removes a test
file under `tools/` renames the gate, and the two arms compare two names:

    base       FAIL  repo tools tests (28 file(s))
    candidate  PASS  repo tools tests (29 file(s))      <- fixed it, plus a test

Before this file's fix the verdict read that as a gate that failed on the base
and "is no longer asked here" — a REFUSAL, for a branch that repaired the gate.
With the tier red on both arms it read it as a NEW failure the branch owns as
well: two refusals, neither of which describes anything that happened.

The test tier is already exempt for exactly this reason (`_TEST_TIER` drops
`targeted tests (21 file(s))` from the comparison). This is the same hazard in
the tier that exemption does not cover.

WHAT THIS FILE REFUSES
======================
1. **The ban.** A count-only difference must not manufacture a refusal — and
   the paired controls hold the count fixed, so the count is the only variable.
2. **A green bought by weakening.** Every genuine gate refusal still fires
   ACROSS a count change: a gate the branch reddens, a gate it stops asking, a
   gate it moves to SKIP.
3. **A normaliser that erases too much.** `gate_key` strips a per-tree count and
   nothing else, and never merges two different gates.
4. **The next one.** A structural guard over `gatekeeper-land.sh` itself: every
   gate label whose text varies with the tree must be either normalised out of
   the comparison or DECLARED as varying only in the strict direction. A new
   counted label added later turns this red instead of quietly re-banning.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import landing_merge_verdict as V  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO_ROOT = _PROGRAMS.parents[3]
_LAND_SH = _REPO_ROOT / "tools" / "gatekeeper-land.sh"

TREE = "a" * 40
SHA = "c" * 40


def _log(tools_line):
    """A `gatekeeper-land.sh` transcript whose ONLY variable is the tools tier."""
    body = [
        "=== gatekeeper landing gates — base=origin/main ===",
        "--- cheap tier (also enforced by the pre-push hook) ---",
        "  PASS  NDA — commit messages",
        "  PASS  version monotonic (assigned at merge — deferred)",
        "--- full tier (minutes; stamps the tree on success) ---",
        "  PASS  targeted tests (21 file(s))",
    ]
    if tools_line is not None:
        body.append("  " + tools_line)
    body.append("  PASS  repo hygiene gates")
    body.append("=== ALL GATES PASS — stamped %s ===" % SHA[:9])
    return "\n".join(body) + "\n"


def _decide(base_log, cand_log):
    """Everything except the two gate logs is held identical and clean."""
    # This unit fixture varies gate-label counts, not hygiene findings. Supply
    # the complete comparator input for its one clean synthetic hygiene gate;
    # absence now correctly means INCOMPLETE, never a measured empty delta.
    hygiene = {"status": "CLEAN", "introduced": [], "carried": [],
               "cleared": [], "candidate_findings": 0,
               "base_findings": 0, "declared": 1}
    return V.decide(
        rebase_status="ok", expected_tree=TREE, verified_tree=TREE,
        github_tree=TREE, land=V.parse_land_log(cand_log),
        base_land=V.parse_land_log(base_log),
        delta=V.Delta(base_total=10, candidate_total=10, overlap=10),
        verified_sha=SHA, truncated=False, dropped_files=(), selection_size=21,
        hygiene=hygiene)


# ====================================================== 1. THE BAN, AND ITS CONTROL


def test_a_fix_that_also_adds_a_tools_test_is_not_read_as_silencing_the_gate():
    """The reported defect. The branch REPAIRS the red tier and adds one test
    file, so the count moves 28 -> 29. Before the fix this refused with
    'A FAILING GATE WAS SILENCED RATHER THAN FIXED'."""
    v = _decide(_log("FAIL  repo tools tests (28 file(s))"),
                _log("PASS  repo tools tests (29 file(s))"))
    assert v.ok is True, v.reasons
    assert not any("SILENCED" in r for r in v.reasons), v.reasons
    assert any("now passes" in n for n in v.notes), v.notes


def test_the_same_repair_without_a_new_tools_test_is_the_control():
    """PAIRED CONTROL. Identical to the test above except the count does not
    move — so the count is the only thing the assertion above is about."""
    v = _decide(_log("FAIL  repo tools tests (28 file(s))"),
                _log("PASS  repo tools tests (28 file(s))"))
    assert v.ok is True, v.reasons
    assert any("now passes" in n for n in v.notes), v.notes


def test_a_tier_red_on_both_arms_is_not_read_as_a_failure_the_branch_owns():
    """The second half of the defect: with the tier red on both sides, a count
    change also invented a NEW failure. A gate red on the base is nobody's."""
    v = _decide(_log("FAIL  repo tools tests (28 file(s))"),
                _log("FAIL  repo tools tests (29 file(s))"))
    assert v.ok is True, v.reasons
    assert not any("PASSED ON THE BASE" in r for r in v.reasons), v.reasons
    assert any("fails on the base too" in n for n in v.notes), v.notes


def test_the_same_pre_existing_red_without_a_new_tools_test_is_the_control():
    """PAIRED CONTROL for the test above."""
    v = _decide(_log("FAIL  repo tools tests (28 file(s))"),
                _log("FAIL  repo tools tests (28 file(s))"))
    assert v.ok is True, v.reasons
    assert any("fails on the base too" in n for n in v.notes), v.notes


# ============================== 2. THE GATE MUST STILL REFUSE ACROSS A COUNT CHANGE
#
# Every one of these is the mutant the fix above could have been: a normaliser
# that stops the ban by also stopping the gate. Each holds the count DIFFERENT
# between the arms, so it is answered by the new code path and not the old one.


def test_a_gate_this_branch_reddens_is_still_refused_across_a_count_change():
    v = _decide(_log("PASS  repo tools tests (28 file(s))"),
                _log("FAIL  repo tools tests (29 file(s))"))
    assert v.ok is False
    assert any("PASSED ON THE BASE" in r and "repo tools tests" in r
               for r in v.reasons), v.reasons


def test_a_failing_gate_that_stops_being_asked_is_still_refused():
    """`failed -> absent` is never an improvement. The candidate does not print
    the tier at all; deleting the red gate must not buy a landing."""
    v = _decide(_log("FAIL  repo tools tests (28 file(s))"), _log(None))
    assert v.ok is False
    assert any("SILENCED" in r for r in v.reasons), v.reasons


def test_a_failing_gate_moved_to_SKIP_is_still_refused_across_a_count_change():
    """`failed -> skipped` is never an improvement either, and a changed count
    must not let the SKIP through as 'a different gate that was never red'."""
    v = _decide(_log("FAIL  repo tools tests (28 file(s))"),
                _log("SKIP  repo tools tests (29 file(s))"))
    assert v.ok is False
    assert any("SILENCED" in r for r in v.reasons), v.reasons


def test_a_gate_with_no_count_at_all_is_unaffected():
    """The whole rest of the gate list is compared exactly as before."""
    base = _log("FAIL  repo tools tests (28 file(s))")
    cand = base.replace("  PASS  repo hygiene gates",
                        "  FAIL  repo hygiene gates")
    v = _decide(base, cand)
    assert v.ok is False
    assert any("PASSED ON THE BASE" in r and "repo hygiene gates" in r
               for r in v.reasons), v.reasons


# ================================================ 3. THE NORMALISER'S OWN BOUNDARY


@pytest.mark.parametrize("a,b", [
    ("repo tools tests (28 file(s))", "repo tools tests (29 file(s))"),
    ("repo tools tests (1 file(s))", "repo tools tests (10 file(s))"),
    ("targeted tests (21 file(s))", "targeted tests (145 file(s))"),
])
def test_the_same_gate_under_two_counts_is_one_identity(a, b):
    assert V.gate_key(a) == V.gate_key(b)


@pytest.mark.parametrize("a,b", [
    # Two DIFFERENT gates must never collapse into one identity.
    ("repo tools tests (28 file(s))", "targeted tests (28 file(s))"),
    ("repo tools tests (28 file(s))", "repo hygiene gates"),
    # Not a per-tree count: an rc is an OUTCOME, and merging two outcomes would
    # let 'I could not look' (rc=2) be waived by 'I looked and it wrote' (rc=1).
    ("repo tools tests wrote to the tree (write-guard rc=1)",
     "repo tools tests wrote to the tree (write-guard rc=2)"),
    # A count that is not the trailing group is part of the name, not a measurement.
    ("gate (2 file(s)) suffix", "gate (3 file(s)) suffix"),
])
def test_two_different_identities_are_never_merged(a, b):
    assert V.gate_key(a) != V.gate_key(b)


def test_the_label_is_reported_verbatim_even_though_the_key_is_stripped():
    """The denominator is evidence. A reader of a refusal must still see how
    many files the tier discovered."""
    v = _decide(_log("PASS  repo tools tests (28 file(s))"),
                _log("FAIL  repo tools tests (29 file(s))"))
    assert any("(29 file(s))" in r for r in v.reasons), v.reasons


# ========================================= 4. THE STRUCTURAL GUARD ON THE SCRIPT

# A gate label that varies with the tree is compared against a DIFFERENT tree's
# label, so it must be handled deliberately. Two dispositions are allowed:
#
#   NORMALISED      `gate_key` removes the varying part, so the two arms agree.
#   DECLARED-STRICT the variation can only ever produce a REFUSAL, never a
#                   waiver — so leaving it un-normalised is the safe direction
#                   and it is recorded here rather than left to be rediscovered.
#
# The second set holds the two write-guard verdicts, one per test stage that
# carries its own guard. Each is printed ONLY when that stage wrote into the
# tree, so a mismatch between the arms refuses in both directions, and refusing
# a landing whose two arms disagree about how the tree was written is correct.
#
# The rc is deliberately IN the label rather than normalised away: rc=1 is "this
# stage wrote" and rc=2 is "the guard could not look", and those are different
# findings. `test_two_different_identities_are_never_merged` pins that, so
# normalising here would contradict it.
#
# `unselectable tests …` joined the set when vibe-ic#1424 (PR #1530) added the
# stage that prints it. It was NOT declared at the time, which left this test
# red on clean main for the whole of v1.10.40 — a red every branch then
# inherited. Adding a stage with a write-guard means adding its verdict here.
_DECLARED_STRICT = {
    "repo tools tests wrote to the tree (write-guard rc=%s)",
    "unselectable tests wrote to the tree (write-guard rc=%s)",
}

_PRINTF_GATE = re.compile(
    r"""printf\s+'\s{2}(?:PASS|FAIL|SKIP)\s{2}(?P<label>.*?)\\n'"""
    r"""(?P<args>[^\n]*)""")
_ECHO_GATE = re.compile(
    r'echo\s+"\s{2}(?:PASS|FAIL|SKIP)\s{2}(?P<label>[^"]*)"')

#: The generic `run()` helper's argument. A `%s` fed from THIS is the unit's own
#: name, set as a literal at the call site — it is the same string on every tree.
_CALL_SITE_LABEL_ARG = '"$label"'


def _varies_with_the_tree(label: str, args: str) -> bool:
    """Does this printed line differ between two runs on two trees?

    THE FORMAT ALONE CANNOT ANSWER IT, and reading it as if it could is how
    this guard accused an honest landing. MEASURED (czmainred9, v1.19.60):
    `ca93e79dc` (#2142) added the census-freshness unit, whose two FAIL lines are

        printf '  FAIL  %s — no verdict was recorded for this unit\\n' "$label"
        printf '  FAIL  %s — the published census does not re-derive on this
                          tree\\n' "$label"

    with `label="63x8 census freshness"` three lines above — a constant. Both
    print the identical sentence on every tree in the world, and this scan
    called them tree-varying because the FORMAT holds a `%s`. The old filter
    had the right idea and stopped one step short: it excluded a BARE `%s`
    because "its label comes from the call site as a literal", which is a fact
    about the ARGUMENT and not about the format, so a fixed suffix after the
    same argument defeated it.

    So the argument decides. `"$label"` is the call site's literal; anything
    else — `"$(wc -l < "$sel")"`, `"${#files[@]}"`, `"$wrc"` — is a measurement
    of this tree, and those are exactly the labels this file exists to refuse.
    An `echo` line interpolates in place and carries no separate argument, so
    it is judged on its own text as before.
    """
    if "%s" not in label and "$" not in label:
        return False
    if args is None:                              # the `echo` form
        return True
    rest = args.strip()
    if not rest:
        return "$" in label                       # nothing substituted at all
    return set(rest.split()) != {_CALL_SITE_LABEL_ARG}


def _tree_varying_gate_labels():
    """Every gate label `gatekeeper-land.sh` prints that is not a constant."""
    src = _LAND_SH.read_text(encoding="utf-8")
    found = [(m.group("label"), m.group("args"))
             for m in _PRINTF_GATE.finditer(src)]
    found += [(m.group("label"), None) for m in _ECHO_GATE.finditer(src)]
    return sorted({l for l, a in found if _varies_with_the_tree(l, a)})


def test_the_scan_actually_finds_the_labels_it_is_meant_to_judge():
    """An empty population is not a pass. This guard is worthless if the regex
    stops matching after someone reformats the script."""
    labels = _tree_varying_gate_labels()
    assert labels, (
        "no tree-varying gate label was found in %s — the scan is broken, not "
        "the script" % _LAND_SH)
    assert "repo tools tests (%s file(s))" in labels, (
        "the known counted label is missing from the scan: %r" % (labels,))


def test_every_tree_varying_gate_label_is_normalised_or_declared_strict():
    offenders = []
    for label in _tree_varying_gate_labels():
        if label in _DECLARED_STRICT:
            continue
        a, b = label.replace("%s", "28"), label.replace("%s", "29")
        if V._TEST_TIER.match(a) and V._TEST_TIER.match(b):
            continue                      # dropped from the comparison entirely
        if V.gate_key(a) == V.gate_key(b):
            continue                      # normalised to one identity
        offenders.append(label)
    assert not offenders, (
        "these gate labels change with the tree, so the base arm and the "
        "candidate arm compare two different names for one gate — a landing is "
        "refused for a difference nobody made: " + repr(offenders))


def test_at_least_one_label_is_carried_by_the_normaliser_and_not_the_declaration():
    """Keeps the guard above from being satisfied by declaring everything
    strict, which would restate the bug as policy."""
    normalised = [l for l in _tree_varying_gate_labels()
                  if l not in _DECLARED_STRICT
                  and not V._TEST_TIER.match(l.replace("%s", "28"))
                  and V.gate_key(l.replace("%s", "28"))
                  == V.gate_key(l.replace("%s", "29"))]
    assert normalised, (
        "every varying label is exempt by declaration — the normaliser is "
        "carrying nothing")


def test_the_strict_declaration_names_no_label_the_script_stopped_printing():
    """A roster that outlives what it names goes stale in the safe-looking
    direction: fewer entries still passes."""
    src = _LAND_SH.read_text(encoding="utf-8")
    stale = [l for l in _DECLARED_STRICT if l not in src]
    assert not stale, "declared strict but no longer printed: %r" % (stale,)


# ── the argument rule's own two directions (czmainred9) ───────────────────

def test_the_scan_still_catches_a_label_fed_from_a_tree_measurement():
    """MUTATION. The `"$label"` rule must not be a way to hide a real one.

    Six lines, one synthetic script, every shape the real file uses. The three
    fed from `"$label"` are the same sentence on every tree; the three fed from
    a count, an array length and an rc are not, and every one of those three is
    a label this file exists to refuse. Replace `_varies_with_the_tree` with
    `"%s" in label` and the first three come back; replace it with `False` and
    the last three go quiet.
    """
    script = (
        '''    printf '  PASS  %s\\n' "$label"\n'''
        '''    printf '  FAIL  %s — no verdict was recorded for this unit\\n' "$label"\n'''
        '''    printf '  SKIP  %s — nothing to do here\\n' "$label"\n'''
        '''    printf '  FAIL  targeted tests (%s file(s))\\n' "$(wc -l < "$sel")"\n'''
        '''    printf '  PASS  repo tools tests (%s file(s))\\n' "${#files[@]}"\n'''
        '''    printf '  FAIL  it wrote to the tree (write-guard rc=%s)\\n' "$wrc"\n''')
    varying = sorted({m.group("label") for m in _PRINTF_GATE.finditer(script)
                      if _varies_with_the_tree(m.group("label"),
                                               m.group("args"))})
    assert varying == [
        "it wrote to the tree (write-guard rc=%s)",
        "repo tools tests (%s file(s))",
        "targeted tests (%s file(s))",
    ], varying


def test_a_census_style_suffix_is_not_made_varying_by_its_suffix():
    """The exact pair #2142 added, and the exact pair that was accused.

    Asserted on the REAL script rather than on a copy of the strings, so it
    cannot pass by describing a file that has moved on.
    """
    src = _LAND_SH.read_text(encoding="utf-8")
    suffixed = [(m.group("label"), m.group("args"))
                for m in _PRINTF_GATE.finditer(src)
                if m.group("label").startswith("%s — ")]
    assert len(suffixed) >= 2, (
        "the `%s — <suffix>` shape is gone from the script, so this test now "
        "asks nothing — re-point it or delete it, do not leave it green: "
        f"{suffixed}")
    for label, args in suffixed:
        assert args.strip() == _CALL_SITE_LABEL_ARG, (
            "a `%s — <suffix>` line grew an argument that is NOT the call "
            f"site's own label, so it really does vary: {label!r} <- {args!r}")
        assert not _varies_with_the_tree(label, args), label
