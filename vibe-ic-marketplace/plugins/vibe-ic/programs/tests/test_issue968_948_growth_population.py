#!/usr/bin/env python3
"""vibe-ic#968 + #948 — the rationale is held to one standard, and growth is a
population rather than a difference of two counts.

#968 REFUTES the commit that closed #922's second half. That commit's headline
is "AND THE OLD SENTENCE CANNOT SIT STILL"; the sentence could sit still. Its
decision read::

    growth_justified = rationale_substantive and (
        scope_ok or (covers_current and not rationale_unrenewed)
    )

``scope_ok`` short-circuits the new guard: only the COUNT arm carries
``and not rationale_unrenewed``, while the comment above it claims the list
spelling is held to "the same standard the count is held to". And satisfying
``scope_ok`` is a PURE FUNCTION of waivers.json — :func:`_derive_scope` below
never opens the baseline and never reads ``growth_rationale``, which is exactly
what the count arm's own failure message told the operator to do. The gate
printed the recipe for its own bypass. Before the scope work the list spelling
was rejected outright, so this path was NEW: a stale rationale could authorise
growth where before it could not.

#948 is the same defect one level up. The gate consulted the rationale only
when NET growth passed tolerance, and net is a difference of counts: delete one
waiver, add another, and the population changed completely while the number did
not move — not renewed, not scope-checked, not read. And where the baseline
carries no rationale the gate cannot decide renewal at all, which is the state
every tracked waivers.json in this repo is in today; it used to pass there in
silence, which is how "0 files affected" comes to read as safety when it is a
statement about reach.

THREE ARMS, and all three are required.

  * The FAILURE arm proves each bypass is closed. Every test in it exits 0
    against the unfixed program.
  * The PAIRED arm proves the fix was not bought by turning the gate into a
    ban: a rationale that genuinely covers its waivers stays green, a
    legitimate shrink is not blocked, and #945's count-equality memory is
    untouched. Those tests pass against BOTH programs, deliberately.
  * The CONTRACT-CHANGE arm asserts, rather than describes, the one thing this
    fix makes stricter for documents that do not exist yet: closing a waiver no
    longer pays for opening a different one.

The program is driven as a subprocess — the shipped entry point, argv and exit
code included. A test that re-states the rule in Python proves the re-statement.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
PROG = PROGRAMS / "waiver_growth_check.py"

sys.path.insert(0, str(PROGRAMS))
import waiver_growth_check as wgc  # noqa: E402  (after sys.path bootstrap)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


def _run(project: Path, *extra: str):
    """``(returncode, report)`` from one real invocation of the gate."""
    proc = _pr.run(
        [sys.executable, str(PROG), str(project), "--json", *extra],
        capture_output=True, text=True)
    assert proc.stdout.strip(), (
        f"the gate emitted no JSON (rc={proc.returncode}): {proc.stderr}")
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


def _attestations(*tickets) -> dict:
    return {"waivers": [{"step": t, "phase": "3", "ticket": t} for t in tickets]}


def _categories(report) -> set:
    return {f["category"] for f in report["findings"]}


#: The sentence under test, and the one the baseline freezes. Long enough to
#: clear the substantive-prose bar so every case turns on RENEWAL, not length.
_REASON = ("Deferred because the extraction flow is not yet wired into CI; "
           "signoff engineer will run the deck offline before tapeout release.")

#: A genuinely different reason, for the renewal arm.
_RENEWED = ("The second deferral is an extraction gap of the same kind, "
            "re-reviewed and accepted for this release by sign-off.")

_GROWTH_FINDINGS = {"UNJUSTIFIED_WAIVER_GROWTH",
                    "GROWTH_RATIONALE_WITHOUT_MEMORY",
                    "GROWTH_RATIONALE_STALE",
                    "GROWTH_RATIONALE_UNRENEWED",
                    "GROWTH_RATIONALE_SCOPE_MISMATCH"}


# --------------------------------------------------------------- the adversary

def _derive_scope(doc: dict) -> list:
    """The bypass, reproduced as the gate's own failure message described it.

    THIS FUNCTION NEVER READS ``growth_rationale`` AND NEVER OPENS THE
    BASELINE. It is handed the current document and returns a scope list that
    satisfies ``scope_ok`` — every root named exactly once, by a value the
    entry itself publishes. That is the whole argument of #968: if a machine
    with no access to the reason can produce the field, the field cannot be the
    author saying the reason is about these waivers.

    The name vocabulary is SCRAPED from the program (``_PUBLISHED_NAME_FIELDS``)
    rather than typed here, so a field added to the contract is a field this
    adversary immediately exploits — a typed list would be a promise nobody
    will add the next case."""
    entries = [e for key in ("waivers", "waived_steps")
               for e in (doc.get(key) or []) if isinstance(e, dict)]

    def names(entry):
        out = []
        for field in wgc._PUBLISHED_NAME_FIELDS:
            rendered = wgc._render_name(entry.get(field))
            if rendered and rendered not in out:
                out.append(rendered)
        return out

    owners = collections.Counter(n for e in entries for n in names(e))
    # Prefer a name unique to the entry: the ambiguity guard fires on a naive
    # ticket-first derivation when two entries share a ticket, and preferring
    # a unique name is still a pure function of the document.
    return [next(n for n in names(e) if owners[n] == 1) for e in entries]


def test_the_adversary_is_a_pure_function_of_the_document(tmp_path):
    """PREMISE CHECK, asserted rather than assumed. If the derivation above
    stopped satisfying the scope check, every #968 test below would pass for
    the wrong reason — the bypass would be gone by accident and this file would
    be testing nothing."""
    doc = dict(_attestations("alpha", "beta", "gamma"),
               growth_rationale=_REASON)
    doc["growth_rationale_covers"] = _derive_scope(doc)
    proj = _project(tmp_path, doc, baseline=_attestations("alpha"))
    _rc, report = _run(proj)

    assert report["summary"]["growth_rationale_scope"] == {
        "unnamed": [], "unmatched": [], "ambiguous": []}, (
        "the derived scope no longer satisfies the scope check, so these "
        "tests would no longer exercise the bypass they were written for")


# ------------------------------------------------------- #968, the failure arm

def test_the_derived_scope_does_not_launder_an_unrenewed_rationale(tmp_path):
    """THE ISSUE'S REPRODUCTION. The baseline holds `alpha` beside this
    rationale; the current document holds three roots and repeats that
    rationale WORD FOR WORD. The count spelling is refused. The list spelling —
    derived by a script that never read the sentence — used to exit 0 with the
    reason byte-identical to the frozen one."""
    current = dict(_attestations("alpha", "beta", "gamma"),
                   growth_rationale=_REASON)
    current["growth_rationale_covers"] = _derive_scope(current)
    baseline = dict(_attestations("alpha"),
                    growth_rationale=_REASON, growth_rationale_covers=1)

    rc, report = _run(_project(tmp_path, current, baseline))

    assert current["growth_rationale"] == baseline["growth_rationale"], (
        "premise: the sentence is unchanged, byte for byte")
    assert report["summary"]["growth_rationale_scope"] == {
        "unnamed": [], "unmatched": [], "ambiguous": []}
    assert report["summary"]["growth_rationale_unrenewed"] is True
    assert report["summary"]["growth_justified"] is False
    assert "GROWTH_RATIONALE_UNRENEWED" in _categories(report)
    assert rc == 1


@pytest.mark.parametrize("spelling", ["count", "list"])
def test_both_spellings_of_the_memory_are_held_to_one_standard(tmp_path,
                                                               spelling):
    """The property, stated once for each spelling: a rationale that has not
    been renewed cannot authorise growth by EITHER route. This is what the
    comment beside the decision already claimed, asserted."""
    current = dict(_steps("alpha", "beta"), growth_rationale=_REASON)
    current["growth_rationale_covers"] = (
        2 if spelling == "count" else _derive_scope(current))
    baseline = dict(_steps("alpha"),
                    growth_rationale=_REASON, growth_rationale_covers=1)

    rc, report = _run(_project(tmp_path, current, baseline))

    assert report["summary"]["growth_justified"] is False
    assert "GROWTH_RATIONALE_UNRENEWED" in _categories(report)
    assert rc == 1


def test_the_failure_message_no_longer_prints_a_way_around_itself(tmp_path):
    """CLOSED LOOP. Take the gate's own rejection of the count spelling, follow
    its instruction MECHANICALLY, and re-run: the verdict must not flip.

    The old text ended "replace `growth_rationale_covers: 3` with the list of
    the 3 root waiver(s) it covers", and doing exactly that turned rc 1 into
    rc 0 with nothing else changed. A failure message that names an escape the
    gate cannot check is a recipe, not a repair."""
    doc = dict(_attestations("alpha", "beta", "gamma"),
               growth_rationale=_REASON, growth_rationale_covers=3)
    baseline = dict(_attestations("alpha"),
                    growth_rationale=_REASON, growth_rationale_covers=1)
    proj = _project(tmp_path, doc, baseline)

    rc_count, report_count = _run(proj)
    assert rc_count == 1
    assert "GROWTH_RATIONALE_UNRENEWED" in _categories(report_count)

    # Follow the instruction, without reading the rationale.
    doc["growth_rationale_covers"] = _derive_scope(doc)
    (proj / "waivers.json").write_text(json.dumps(doc, indent=2))
    rc_list, report_list = _run(proj)

    assert rc_list == 1, (
        "the documented repair for one spelling is a bypass of the other")
    assert "GROWTH_RATIONALE_UNRENEWED" in _categories(report_list)

    message = [f["message"] for f in report_count["findings"]
               if f["category"] == "GROWTH_RATIONALE_UNRENEWED"][0]
    assert "not a renewal" in message, (
        "the failure text still offers re-declaring the population as a way "
        "out: %s" % message)


def test_a_broken_scope_and_an_old_sentence_are_reported_separately(tmp_path):
    """Two defects, two findings. Chaining them behind one `elif` means the
    author fixes the scope, re-runs, and meets a second refusal they were never
    told about — and it is what made the renewal check unreachable for the
    whole population spelling in the first place."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta"), growth_rationale=_REASON,
                     growth_rationale_covers=["alpha"]),
        baseline=dict(_steps("alpha"),
                      growth_rationale=_REASON, growth_rationale_covers=1),
    )
    rc, report = _run(proj)

    assert {"GROWTH_RATIONALE_SCOPE_MISMATCH",
            "GROWTH_RATIONALE_UNRENEWED"} <= _categories(report)
    assert rc == 1


# ------------------------------------------------------- #948, the failure arm

def test_a_swap_at_constant_count_is_a_change(tmp_path):
    """Delete one, add one. The count does not move, the population is
    different, and against the unfixed program the gate never looked: net 0 is
    not greater than tolerance 0, so the rationale was not consulted, not
    scope-checked and not read."""
    proj = _project(
        tmp_path,
        current=_attestations("alpha", "delta"),
        baseline=_attestations("alpha", "gamma"),
    )
    rc, report = _run(proj)

    summary = report["summary"]
    assert summary["net_growth"] == 0, "premise: the count did not move"
    assert summary["added_root_waivers"] == 1
    assert summary["removed_root_waivers"] == 1
    assert summary["retained_root_waivers"] == 1
    assert "UNJUSTIFIED_WAIVER_GROWTH" in _categories(report)
    assert rc == 1


def test_a_swap_gets_no_free_pass_from_the_sentence_it_predates(tmp_path):
    """The swap the #946 docstring described and could not see: `gamma` closes,
    `delta` opens, the count stays 3, and no field in the document moves. The
    sentence written about `gamma` was authorising `delta`."""
    proj = _project(
        tmp_path,
        current=dict(_attestations("alpha", "beta", "delta"),
                     growth_rationale=_REASON, growth_rationale_covers=3),
        baseline=dict(_attestations("alpha", "beta", "gamma"),
                      growth_rationale=_REASON, growth_rationale_covers=3),
    )
    rc, report = _run(proj)

    assert report["summary"]["net_growth"] == 0
    assert report["summary"]["growth_rationale_unrenewed"] is True
    assert "GROWTH_RATIONALE_UNRENEWED" in _categories(report)
    assert rc == 1


def test_the_undecidable_state_is_disclosed_rather_than_passed_in_silence(
        tmp_path):
    """Where the baseline carries no rationale, renewal is not decidable — and
    that is a different fact from "renewal was checked and the sentence is
    fresh". The document still PASSES on the count contract, which is #945's
    reach and this fix does not re-price it; what changes is that the report
    now says which of the two happened.

    This is the state of every tracked waivers.json in this repo, and it is why
    the scope work's contract impact was 0 files: 0 is a statement about reach,
    not about safety."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta"),
                     growth_rationale=_REASON, growth_rationale_covers=2),
        baseline=_steps("alpha"),
    )
    rc, report = _run(proj)

    assert report["summary"]["growth_rationale_renewal"] == "undecided"
    assert "GROWTH_RATIONALE_RENEWAL_UNDECIDED" in _categories(report)
    # It is a DISCLOSURE, not a new block: the verdict is unchanged.
    assert report["summary"]["growth_justified"] is True
    assert not _categories(report) & _GROWTH_FINDINGS
    assert rc == 0


def test_the_disclosure_is_not_raised_where_the_gate_can_decide(tmp_path):
    """A disclosure printed on every run is noise, and noise is how a real one
    gets skipped. Where the baseline HAS a sentence on record the gate decided,
    and says so."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta"),
                     growth_rationale=_RENEWED, growth_rationale_covers=2),
        baseline=dict(_steps("alpha"),
                      growth_rationale=_REASON, growth_rationale_covers=1),
    )
    rc, report = _run(proj)

    assert report["summary"]["growth_rationale_renewal"] == "renewed"
    assert "GROWTH_RATIONALE_RENEWAL_UNDECIDED" not in _categories(report)
    assert rc == 0


def test_a_release_that_adds_nothing_is_not_asked_the_renewal_question(
        tmp_path):
    """`not_consulted` is its own state. A flat or shrinking release is not
    being authorised by a rationale, so reporting "undecided" there would be
    the gate disclosing a question it had no reason to ask."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha"),
                     growth_rationale=_REASON, growth_rationale_covers=1),
        baseline=_steps("alpha", "beta"),
    )
    rc, report = _run(proj)

    assert report["summary"]["growth_rationale_renewal"] == "not_consulted"
    assert "GROWTH_RATIONALE_RENEWAL_UNDECIDED" not in _categories(report)
    assert rc == 0


# ------------------------------------------------------- the contract-change arm

def test_closing_one_waiver_does_not_pay_for_opening_another(tmp_path):
    """STATED AS A CHANGE, not smuggled. Under net accounting a project could
    close three waivers, open one nobody has justified, and pass — the closures
    paid for it. Deferred work is not fungible by the count: the new obligation
    is new whatever else was retired in the same edit.

    This is the widening in this commit. It reaches no tracked document today
    (none carries a frozen baseline) and it is the first thing a maintainer
    will meet when one does, so it is asserted here rather than described."""
    proj = _project(
        tmp_path,
        current=_attestations("alpha", "delta"),
        baseline=_attestations("alpha", "beta", "gamma", "epsilon"),
    )
    rc, report = _run(proj)

    assert report["summary"]["net_growth"] == -2, "premise: this is a net shrink"
    assert report["summary"]["added_root_waivers"] == 1
    assert "UNJUSTIFIED_WAIVER_GROWTH" in _categories(report)
    assert rc == 1


def test_the_tolerance_operator_counts_additions_now(tmp_path):
    """The escape hatch moved with the trigger and is documented in --help: the
    number an operator sets is the number of root waivers that may be ADDED
    without a rationale, not a net figure that a closure can offset."""
    proj = _project(
        tmp_path,
        current=_attestations("alpha", "delta"),
        baseline=_attestations("alpha", "beta", "gamma", "epsilon"),
    )
    rc, report = _run(proj, "--tolerance", "1")

    assert report["summary"]["added_root_waivers"] == 1
    assert not _categories(report) & _GROWTH_FINDINGS
    assert rc == 0


# ----------------------------------------------------------------- paired arm
#
# These pass against BOTH the unfixed and the fixed program, on purpose. They
# are what stops the fix from being bought by turning the gate into a ban.

def test_a_rationale_that_genuinely_covers_its_waivers_stays_green(tmp_path):
    """The operator escape hatch, unchanged: a substantive reason, rewritten
    for the population it stands beside, authorises growth."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta", "gamma"),
                     growth_rationale=_RENEWED, growth_rationale_covers=3),
        baseline=dict(_steps("alpha"),
                      growth_rationale=_REASON, growth_rationale_covers=1),
    )
    rc, report = _run(proj)

    assert report["summary"]["growth_justified"] is True
    assert not _categories(report) & _GROWTH_FINDINGS
    assert rc == 0


def test_the_population_spelling_still_authorises_growth(tmp_path):
    """The list spelling is held to the renewal standard, not withdrawn. Naming
    the population beside a reason written for it passes — and it is the only
    spelling that says WHICH waivers the reason is about."""
    current = dict(_attestations("alpha", "beta"), growth_rationale=_RENEWED)
    current["growth_rationale_covers"] = _derive_scope(current)
    proj = _project(tmp_path, current,
                    baseline=dict(_attestations("alpha"),
                                  growth_rationale=_REASON,
                                  growth_rationale_covers=1))
    rc, report = _run(proj)

    assert report["summary"]["growth_rationale_covers"] == ["alpha", "beta"]
    assert report["summary"]["growth_justified"] is True
    assert rc == 0


def test_a_legitimate_shrink_is_not_blocked(tmp_path):
    """A project that only closes waivers adds nothing, is never asked to renew
    anything, and passes. A gate that penalised shrinking would teach operators
    not to shrink."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha"),
                     growth_rationale=_REASON, growth_rationale_covers=1),
        baseline=dict(_steps("alpha", "beta", "gamma"),
                      growth_rationale=_REASON, growth_rationale_covers=3),
    )
    rc, report = _run(proj)

    # Asserted on fields BOTH programs emit, so this guard is a real control:
    # it passes against the unfixed gate too, and a fix that bought its bite by
    # blocking shrinks would break it.
    assert report["summary"]["net_growth"] == -2
    assert report["summary"]["new_waivers"] == []
    assert not _categories(report) & _GROWTH_FINDINGS
    assert rc == 0


def test_a_flat_population_is_not_a_change(tmp_path):
    """The same waivers, the same reason: nothing was added, so nothing needs
    justifying. Set accounting must not turn a re-run into a change."""
    doc = dict(_attestations("alpha", "beta"),
               growth_rationale=_REASON, growth_rationale_covers=2)
    rc, report = _run(_project(tmp_path, doc, baseline=doc))

    assert report["summary"]["net_growth"] == 0
    assert report["summary"]["new_waivers"] == []
    assert report["summary"]["removed_waivers"] == []
    assert not _categories(report) & _GROWTH_FINDINGS
    assert rc == 0


def test_the_report_names_the_three_sets_a_population_actually_has(tmp_path):
    """Added, closed and retained are three facts; net is one digit that
    reports +1/-1 and 0/0 identically. The set the verdict turns on is now on
    the report, so a reader can see what the number was computed from."""
    proj = _project(
        tmp_path,
        current=dict(_attestations("alpha", "delta"),
                     growth_rationale=_RENEWED, growth_rationale_covers=2),
        baseline=dict(_attestations("alpha", "gamma"),
                      growth_rationale=_REASON, growth_rationale_covers=2),
    )
    _rc, report = _run(proj)
    summary = report["summary"]

    assert summary["added_root_waivers"] == 1
    assert summary["removed_root_waivers"] == 1
    assert summary["retained_root_waivers"] == 1
    assert summary["net_growth"] == 0
    assert summary["population_grew"] is True


def test_the_count_equality_memory_of_945_still_holds(tmp_path):
    """#945's contract, re-asserted here because this commit rewrites the
    decision it lives in: the recorded count is compared for EQUALITY, so a
    rationale cannot reserve headroom above the population beside it."""
    proj = _project(
        tmp_path,
        current=dict(_steps("alpha", "beta"),
                     growth_rationale=_REASON, growth_rationale_covers=51),
        baseline=_steps("alpha"),
    )
    rc, report = _run(proj)

    assert "GROWTH_RATIONALE_STALE" in _categories(report)
    assert rc == 1


def test_growth_with_no_rationale_keeps_its_original_category(tmp_path):
    """Callers matching on ``UNJUSTIFIED_WAIVER_GROWTH`` keep matching. The
    category is the contract; only the number quoted in its message moved,
    because a swap adds a waiver at net 0 and "net count grew by 0" would be
    the gate lying about its own trigger."""
    proj = _project(tmp_path, current=_steps("alpha", "beta"),
                    baseline=_steps("alpha"))
    rc, report = _run(proj)

    assert "UNJUSTIFIED_WAIVER_GROWTH" in _categories(report)
    assert rc == 1
