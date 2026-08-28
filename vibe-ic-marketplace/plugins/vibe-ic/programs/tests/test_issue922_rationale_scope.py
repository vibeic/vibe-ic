#!/usr/bin/env python3
"""vibe-ic#922, second half — a `growth_rationale` must say what it is FOR.

#945 gave the ratchet a memory: `growth_rationale_covers` records the root
waiver count the rationale was written beside, compared for EQUALITY. That made
the POPULATION CHANGING loud. It left the sentence itself unscoped, and its own
docstring said so: "a renewed count with the old sentence left standing is still
prose about the wrong waivers".

A count says HOW MANY, never WHICH, and two states follow from that:

  * SWAP — the file holds `alpha, beta, gamma` with `covers: 3`; a later edit
    closes `gamma` and opens `delta`. The count is still 3, the growth against
    the frozen baseline is still +2, and NO field in the document moved. A
    sentence written about `gamma` now authorises `delta`.
  * DRIFT — growth past the recorded count sends the author back to the
    integer and to nothing else. Bumping 3 to 4 renews the memory without
    renewing the reason.

Both arms are here and both are required. The FAILURE arm proves an old
sentence stops covering waivers it was not written about. The PAIRED arm proves
a rationale that genuinely DOES cover its waivers stays green, that a
legitimate shrink is never asked to renew anything, and that the count contract
#945 shipped is untouched wherever the gate has no earlier sentence on record.
A gate that only ever says no would satisfy the first arm alone, and a ban is
easy to mistake for rigour.

The program is driven as a subprocess — the shipped entry point, argv and exit
code included. A test that re-states the rule in Python proves the re-statement.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = Path(__file__).resolve().parent.parent / "waiver_growth_check.py"

def _run(project: Path):
    """``(returncode, report)`` from one real invocation of the gate."""
    proc = _pr.run(
        [sys.executable, str(PROG), str(project), "--json"],
        capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


def _project(tmp_path: Path, current: dict, baseline: dict | None = None) -> Path:
    proj = tmp_path / "proj"
    (proj / ".vibe-ic-state").mkdir(parents=True, exist_ok=True)
    (proj / "waivers.json").write_text(json.dumps(current, indent=2))
    if baseline is not None:
        (proj / ".vibe-ic-state" / "waivers_baseline.json").write_text(
            json.dumps(baseline, indent=2))
    return proj


def _steps(*names) -> dict:
    return {"waived_steps": [{"id": n} for n in names]}


def _categories(report) -> set:
    return {f["category"] for f in report["findings"]}


#: The sentence under test. Long enough to clear the substantive-prose bar, so
#: every case below turns on SCOPE rather than on length. It names no waiver —
#: which is the whole point: this is what a document-level rationale looks
#: like, and it is why one cannot be trusted to have been written about the
#: waivers standing next to it today.
_REASON = ("Device-level extraction is scheduled for the next release; "
           "deferral accepted by sign-off.")

#: A genuinely different reason, for the renewal arm.
_RENEWED = ("The added deferral is a second extraction gap of the same kind, "
            "re-reviewed and accepted for this release.")

_GROWTH_FINDINGS = {"UNJUSTIFIED_WAIVER_GROWTH",
                    "GROWTH_RATIONALE_WITHOUT_MEMORY",
                    "GROWTH_RATIONALE_STALE",
                    "GROWTH_RATIONALE_UNRENEWED",
                    "GROWTH_RATIONALE_SCOPE_MISMATCH"}


# ---------------------------------------------------------------- failure arm

def test_the_sentence_frozen_in_the_baseline_does_not_cover_what_came_after(
        tmp_path):
    """DRIFT, minimal. The baseline — a frozen waivers.json — carries this
    exact rationale beside one waiver. The current document carries the same
    sentence word for word, a dutifully renewed count, and a second waiver the
    sentence has never seen.

    Against the unfixed program this is `growth_justified: true`, rc 0: the
    count equals the current count, and nothing asks whether the reason moved.
    """
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta"),
                     growth_rationale=_REASON, growth_rationale_covers=2),
        baseline=dict(_steps("alpha"),
                      growth_rationale=_REASON, growth_rationale_covers=1),
    )
    rc, report = _run(proj)

    assert report["summary"]["net_growth"] == 1
    assert report["summary"]["growth_rationale_covers"] == 2
    assert report["summary"]["growth_rationale_unrenewed"] is True
    assert report["summary"]["growth_justified"] is False
    assert "GROWTH_RATIONALE_UNRENEWED" in _categories(report)
    assert rc == 1


def test_a_swap_that_keeps_the_count_moves_no_field_at_all(tmp_path):
    """SWAP — the state the count-memory cannot see.

    Release 1 froze `alpha` beside this rationale. Release 2 grew to
    `alpha, beta, gamma` and recorded `covers: 3`. Release 3 closed `gamma`,
    opened `delta`, and touched neither the rationale nor the count, because
    neither had to move: three roots before, three roots after.

    The gate sees only the frozen baseline and the current file, and against
    the unfixed program it sees a satisfied memory — `covers: 3` equals three
    current roots — and passes. `delta` is authorised by a sentence written
    two releases before it existed."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta", "delta"),
                     growth_rationale=_REASON, growth_rationale_covers=3),
        baseline=dict(_steps("alpha"),
                      growth_rationale=_REASON, growth_rationale_covers=1),
    )
    rc, report = _run(proj)

    assert report["summary"]["current_root_waivers"] == 3
    assert report["summary"]["growth_rationale_covers"] == 3
    assert report["summary"]["growth_justified"] is False
    assert "GROWTH_RATIONALE_UNRENEWED" in _categories(report)
    assert rc == 1


def test_re_wrapping_and_re_casing_a_paragraph_is_not_renewing_it(tmp_path):
    """The comparison is on what the sentence SAYS. Re-flowing the line breaks
    and shouting one word is the same reason, and an author who wanted the
    escape hatch to be a formatting change would have found one otherwise."""
    reflowed = ("Device-level    EXTRACTION is scheduled for the\n\t"
                "next release;  deferral accepted by Sign-off.")
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta"),
                     growth_rationale=reflowed, growth_rationale_covers=2),
        baseline=dict(_steps("alpha"),
                      growth_rationale=_REASON, growth_rationale_covers=1),
    )
    rc, report = _run(proj)

    assert report["summary"]["growth_rationale_unrenewed"] is True
    assert "GROWTH_RATIONALE_UNRENEWED" in _categories(report)
    assert rc == 1


def test_a_scope_that_omits_a_waiver_is_silent_about_it(tmp_path):
    """The population spelling has to BE the population. A list naming only
    the waiver that was already there says nothing about the one that arrived,
    and the report has to name which one it means."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta"),
                     growth_rationale=_REASON,
                     growth_rationale_covers=["alpha"]),
        baseline=_steps("alpha"),
    )
    rc, report = _run(proj)

    assert report["summary"]["growth_rationale_scope"]["unnamed"] == ["'beta'"]
    assert report["summary"]["growth_justified"] is False
    assert "GROWTH_RATIONALE_SCOPE_MISMATCH" in _categories(report)
    assert rc == 1


def test_a_scope_may_not_name_a_waiver_that_is_not_there(tmp_path):
    """The population spelling inherits #945's refusal of headroom. Listing a
    ticket for a waiver nobody has opened yet would pre-authorise it, which is
    exactly what `covers >= current` was rejected for."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta"),
                     growth_rationale=_REASON,
                     growth_rationale_covers=["alpha", "beta", "not-yet"]),
        baseline=_steps("alpha"),
    )
    rc, report = _run(proj)

    assert report["summary"]["growth_rationale_scope"]["unmatched"] == \
        ["'not-yet'"]
    assert "GROWTH_RATIONALE_SCOPE_MISMATCH" in _categories(report)
    assert rc == 1


def test_a_name_two_waivers_publish_identifies_neither(tmp_path):
    """A step ROLE is not unique — a project may defer the same role twice
    under two tickets, which is the corpus shape this gate already refuses to
    guess about for cascades. A scope entry of `lvs` there could mean either
    obligation, so it covers neither and both are reported unnamed."""
    proj = _project(
        tmp_path,
        current={"waivers": [{"step": "lvs", "phase": "3", "ticket": "T-1"},
                             {"step": "lvs", "phase": "3", "ticket": "T-2"}],
                 "growth_rationale": _REASON,
                 "growth_rationale_covers": ["lvs"]},
        baseline={},
    )
    rc, report = _run(proj)

    scope = report["summary"]["growth_rationale_scope"]
    assert scope["ambiguous"] == ["'lvs'"]
    assert len(scope["unnamed"]) == 2
    assert "GROWTH_RATIONALE_SCOPE_MISMATCH" in _categories(report)
    assert rc == 1


# ----------------------------------------------------------------- paired arm

def test_rewriting_the_reason_renews_it(tmp_path):
    """THE PAIRED ARM. The author re-read the rationale, found it no longer
    described the file, and wrote what does. That is the decision the gate is
    asking for, and it passes."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta"),
                     growth_rationale=_RENEWED, growth_rationale_covers=2),
        baseline=dict(_steps("alpha"),
                      growth_rationale=_REASON, growth_rationale_covers=1),
    )
    rc, report = _run(proj)

    assert report["summary"]["growth_rationale_unrenewed"] is False
    assert report["summary"]["growth_justified"] is True
    assert not _categories(report) & _GROWTH_FINDINGS
    assert rc == 0


def test_naming_the_population_does_not_make_an_old_sentence_new(tmp_path):
    """INVERTED BY vibe-ic#968, deliberately and on the record.

    This test shipped with #946 asserting the opposite — `growth_justified` is
    True, rc 0 — under the reasoning that "keeping the words and re-declaring
    which waivers they cover is a decision the author made in the data". It is
    not a decision. The scope list is a PURE FUNCTION of waivers.json: the
    twenty lines of `_derive_scope` in `test_issue968_948_growth_population.py`
    produce it from the entries' own published names, never opening the
    baseline and never reading `growth_rationale`. The identical argument that
    retired the count as a binding of prose to a population (#945) retires the
    list.

    So the same fixture is kept, byte for byte, and the assertions are turned
    over: an unrenewed sentence is refused through BOTH spellings. What the
    list still buys is asserted in its own tests — it is the only thing that
    says WHICH waivers a reason covers, and it is what a document should carry
    where renewal is undecidable."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta"),
                     growth_rationale=_REASON,
                     growth_rationale_covers=["alpha", "beta"]),
        baseline=dict(_steps("alpha"),
                      growth_rationale=_REASON, growth_rationale_covers=1),
    )
    rc, report = _run(proj)

    # The scope itself is perfect — that is the point. It is not the defect.
    assert report["summary"]["growth_rationale_covers"] == ["alpha", "beta"]
    assert report["summary"]["growth_rationale_scope"] == {
        "unnamed": [], "unmatched": [], "ambiguous": []}
    # And the sentence beside it still predates the waiver it authorises.
    assert report["summary"]["growth_rationale_unrenewed"] is True
    assert report["summary"]["growth_justified"] is False
    assert "GROWTH_RATIONALE_UNRENEWED" in _categories(report)
    assert "GROWTH_RATIONALE_SCOPE_MISMATCH" not in _categories(report)
    assert rc == 1


def test_rewriting_the_reason_renews_the_population_spelling_too(tmp_path):
    """THE PAIRED ARM for the inversion above. The list spelling is not being
    banned — it is being held to the same standard as the count. The author who
    names the population AND writes the reason for it passes, and the finding
    text that used to recommend the list as an escape now recommends this."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta"),
                     growth_rationale=_RENEWED,
                     growth_rationale_covers=["alpha", "beta"]),
        baseline=dict(_steps("alpha"),
                      growth_rationale=_REASON, growth_rationale_covers=1),
    )
    rc, report = _run(proj)

    assert report["summary"]["growth_rationale_unrenewed"] is False
    assert report["summary"]["growth_rationale_renewal"] == "renewed"
    assert report["summary"]["growth_justified"] is True
    assert not _categories(report) & _GROWTH_FINDINGS
    assert rc == 0


def test_a_waiver_may_be_named_the_way_the_document_writes_it(tmp_path):
    """Names are the document's, not this gate's. The tracked corpus writes
    `waived_steps` ids as INTEGERS, so an author naming one reaches for `39`,
    not for this module's `repr(id)` growth key. Both spellings of the same
    scalar name the same waiver; neither requires knowing how the gate keys
    one."""
    proj = _project(
        tmp_path,
        current=dict(_steps(6, 39),
                     growth_rationale=_REASON,
                     growth_rationale_covers=[6, "39"]),
        baseline=_steps(6),
    )
    rc, report = _run(proj)

    assert report["summary"]["growth_justified"] is True
    assert not _categories(report) & _GROWTH_FINDINGS
    assert rc == 0


def test_the_population_spelling_works_in_the_other_dialect(tmp_path):
    """The attestation dialect is counted for growth (vibe-ic#525) and carries
    its own `ticket`, so it must be scopeable the same documented way — scope
    is a property of the document, not of one dialect."""
    proj = _project(
        tmp_path,
        current={"waivers": [{"step": "lvs", "phase": "3", "ticket": "T-1"},
                             {"step": "drc", "phase": "3", "ticket": "T-2"}],
                 "growth_rationale": _REASON,
                 "growth_rationale_covers": ["T-1", "T-2"]},
        baseline={},
    )
    rc, report = _run(proj)

    assert report["summary"]["current_root_waivers"] == 2
    assert report["summary"]["growth_justified"] is True
    assert rc == 0


def test_a_legitimate_shrink_is_never_asked_to_renew(tmp_path):
    """A project that CLOSES waivers must not be made to rewrite prose about
    the ones it just removed. The rationale is consulted only when the count
    grows past tolerance — a gate that penalises shrinking teaches operators
    not to shrink."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha"),
                     growth_rationale=_REASON, growth_rationale_covers=1),
        baseline=dict(_steps("alpha", "beta", "gamma"),
                      growth_rationale=_REASON, growth_rationale_covers=3),
    )
    rc, report = _run(proj)

    assert report["summary"]["net_growth"] == -2
    assert not _categories(report) & _GROWTH_FINDINGS
    assert rc == 0


def test_a_flat_population_is_never_asked_to_renew(tmp_path):
    """Nor is a release that added nothing. An unchanged rationale beside an
    unchanged population is a rationale that still covers exactly what it was
    written about — the state this fix exists to preserve, not to punish."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha"),
                     growth_rationale=_REASON, growth_rationale_covers=1),
        baseline=dict(_steps("alpha"),
                      growth_rationale=_REASON, growth_rationale_covers=1),
    )
    rc, report = _run(proj)

    assert report["summary"]["net_growth"] == 0
    assert report["summary"]["growth_rationale_unrenewed"] is False
    assert not _categories(report) & _GROWTH_FINDINGS
    assert rc == 0


# ------------------------------------------------- the #945 contract is intact

def test_a_baseline_with_no_rationale_leaves_the_count_contract_alone(tmp_path):
    """The bound on this fix, asserted rather than described.

    Where the baseline carries no rationale the gate has no earlier sentence to
    compare against, and it says nothing: #945's count-memory is the whole of
    what it can know, and a document that satisfies it passes exactly as
    before. This is the state EVERY tracked `waivers.json` is in today (9 of 9
    carry no `growth_rationale`, and 0 have a frozen baseline), so this fix
    invalidates none of them."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta"),
                     growth_rationale=_REASON, growth_rationale_covers=2),
        baseline=_steps("alpha"),
    )
    rc, report = _run(proj)

    assert report["summary"]["growth_rationale_unrenewed"] is False
    assert report["summary"]["growth_justified"] is True
    assert rc == 0


def test_a_baseline_rationale_below_the_prose_bar_is_not_a_prior_sentence(
        tmp_path):
    """A baseline carrying a stub too short to have been a rationale is not an
    earlier reason on record. Comparing against it would refuse a document for
    matching something the gate never accepted in the first place."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta"),
                     growth_rationale="short", growth_rationale_covers=2),
        baseline=dict(_steps("alpha"), growth_rationale="short"),
    )
    rc, report = _run(proj)

    assert report["summary"]["growth_rationale_unrenewed"] is False
    # It still fails — on the PROSE, which is where it always failed.
    assert "UNJUSTIFIED_WAIVER_GROWTH" in _categories(report)
    assert rc == 1
