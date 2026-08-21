#!/usr/bin/env python3
"""`ppa_page_claim_check.py` — the gate that refuses a sentence bigger than its evidence.

PPA_INTERFACES.md §7: positive, negative, vacuous, mutation.

The negative corpus in this file is not invented. Every banned sentence below was
MEASURED on the live published page on 2026-08-21, and three of them had already
gone FALSE by then: step 9 had acquired an area `closed_loop` and an area budget
gate, and step 33 a power `closed_loop` and a power budget gate, one day after
the page was published. That is the failure this gate exists to make impossible
to repeat — not a style preference.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import ppa_page_claim_check as chk  # noqa: E402

#: Spec §3.3, as the brief states them. This list is duplicated here ON PURPOSE:
#: if it were imported from the program, deleting a form from the program would
#: delete it from its own test, and the suite would stay green while the gate
#: stopped enforcing it.
FORBIDDEN_SENTENCES = (
    "This axis genuinely converges.",
    "The loop runs until nothing violates.",
    "Step 33 measures total power and feeds it to nothing.",
    "It does not measure area at all.",
    "Nineteen steps declare a closed_loop with a real fallback edge.",
    "Keep the two anti-cheating terms verbatim.",
    "This is the gap nobody is standing in.",
    "No open flow searches across layers.",
    "Every rewrite is checked, so the search stays honest.",
)


def _claims(*claims):
    return {"schema": chk.CLAIMS_SCHEMA, "generated_by": "test",
            "claims": list(claims)}


def _write(tmp_path, name, obj):
    path = tmp_path / name
    path.write_text(json.dumps(obj) if not isinstance(obj, str) else obj,
                    encoding="utf-8")
    return path


def _run(tmp_path, page_text, claims_doc, **kw):
    page = _write(tmp_path, "page.md", page_text)
    claims = _write(tmp_path, "claims.json", claims_doc)
    return chk.evaluate(page, claims, **kw)


# ---------------------------------------------------------------- positive

def test_positive_a_qualified_page_passes(tmp_path):
    doc = _claims({
        "id": "flow.area.v1-11-7",
        "text": "at v1.11.7 no flow step declared an area metric",
        "status": "MEASURED",
        "scope": {"base": "v1.11.7 (41bfd8a12~1)"},
        "evidence": [{"path": "flow/phase1_phase2_phase3.yaml",
                      "status": "MEASURED"}],
    })
    page = ("Measured at v1.11.7, the flow does not measure area at all "
            "`[claim:flow.area.v1-11-7]`.")
    rc, report = _run(tmp_path, page, doc)
    assert rc == chk.RC_OK, report["findings"]


def test_positive_a_page_with_no_banned_form_and_sound_claims_passes(tmp_path):
    doc = _claims({
        "id": "t.wns", "text": "setup WNS is -0.124 ns", "status": "MEASURED",
        "evidence": [{"path": "sta.rpt", "status": "MEASURED"}],
    })
    rc, report = _run(tmp_path, "Setup slack is negative `[claim:t.wns]`.", doc)
    assert rc == chk.RC_OK, report["findings"]


def test_positive_a_not_measured_claim_may_cite_nothing(tmp_path):
    """The one legitimate uncited claim: the absence of the artefact IS the
    fact. This is the row a report must print rather than drop."""
    doc = _claims({"id": "p.total", "text": "power was not measured",
                   "status": "NOT_MEASURED",
                   "reason": "no activity basis was recorded"})
    rc, report = _run(tmp_path, "Power was not measured `[claim:p.total]`.", doc)
    assert rc == chk.RC_OK, report["findings"]


# ---------------------------------------------------------------- negative

@pytest.mark.parametrize("sentence", FORBIDDEN_SENTENCES)
def test_negative_every_forbidden_form_makes_the_page_red(tmp_path, sentence):
    """The gate takes a page and a claims file and refuses the banned forms.
    A page containing ONE of them is enough."""
    rc, report = _run(tmp_path, f"Intro text.\n\n{sentence}\n", _claims())
    assert rc == chk.RC_REFUSED, (sentence, report)
    assert report["marker"] == "[REFUSE]"
    assert report["findings"], sentence


def test_negative_the_live_page_shapes_all_fire_together(tmp_path):
    page = "\n\n".join(FORBIDDEN_SENTENCES)
    rc, report = _run(tmp_path, page, _claims())
    assert rc == chk.RC_REFUSED
    codes = {f["code"] for f in report["findings"]}
    enforced = {f["code"] for f in chk.BANNED_FORMS}
    assert codes == enforced, (
        f"forms declared but not fired: {sorted(enforced - codes)}; "
        f"fired but not declared: {sorted(codes - enforced)}")


def test_negative_an_unfalsifiable_form_cannot_be_bought_off_with_a_citation(
        tmp_path):
    """`genuinely` states no criterion, so no claim can supply the missing
    qualification. This form has to be rewritten, and the gate says so."""
    doc = _claims({
        "id": "everything", "text": "the axis converges", "status": "MEASURED",
        "criterion": "WNS >= 0 at every declared corner",
        "scope": {"base": "v1.11.18", "reviewed": "all open flows, 2026-08"},
        "definitions": {"executable": "a step that runs the edge"},
        "evidence": [{"path": "sta.rpt", "status": "MEASURED"}],
    })
    rc, report = _run(tmp_path,
                      "This axis genuinely converges `[claim:everything]`.", doc)
    assert rc == chk.RC_REFUSED
    assert {f["code"] for f in report["findings"]} == {"GENUINELY_CONVERGES"}


@pytest.mark.parametrize("form", [f for f in chk.BANNED_FORMS
                                  if f["requires"] != chk.REQUIREMENT_NEVER])
def test_negative_a_citation_WITHOUT_the_qualification_does_not_lift_it(
        tmp_path, form):
    """A citation is not a password. The claim has to actually supply the
    specific thing the sentence was missing."""
    doc = _claims({"id": "bare", "text": "something", "status": "NOT_MEASURED",
                   "reason": "no evidence"})
    # A LITERAL sentence per form, never the regex source: a test that fed the
    # pattern back to the matcher would pass for any pattern, including one
    # that matches nothing a human would ever write.
    literal = {
        "UNTIL_NOTHING_VIOLATES": "It runs until nothing violates.",
        "FEEDS_IT_TO_NOTHING": "Step 33 feeds it to nothing.",
        "DOES_NOT_MEASURE_AREA": "It does not measure area at all.",
        "REAL_FALLBACK_EDGE": "It has a real fallback edge.",
        "ANTI_CHEATING_VERBATIM": "Keep the two anti-cheating terms verbatim.",
        "UNBOUNDED_NOBODY": "This is where nobody is standing.",
        "UNBOUNDED_NO_OPEN_FLOW": "No open flow does this.",
        "SEARCH_STAYS_HONEST": "So the search stays honest.",
    }[form["code"]]
    page = f"{literal[:-1]} `[claim:bare]`."
    rc, report = _run(tmp_path, page, doc)
    assert rc == chk.RC_REFUSED, (form["code"], report)
    assert form["code"] in {f["code"] for f in report["findings"]}


def test_negative_a_claim_may_not_outrun_its_evidence(tmp_path):
    doc = _claims({
        "id": "over", "text": "area is 1234 um2", "status": "MEASURED",
        "evidence": [{"path": "synth/stats.json", "status": "NOT_MEASURED"}],
    })
    rc, report = _run(tmp_path, "Area is known `[claim:over]`.", doc)
    assert rc == chk.RC_REFUSED
    assert {f["code"] for f in report["findings"]} == {"CLAIM_OUTRUNS_EVIDENCE"}


def test_negative_the_weakest_evidence_governs(tmp_path):
    """Adding a strong record beside a weak one does not upgrade the claim."""
    doc = _claims({
        "id": "mixed", "text": "x", "status": "MEASURED",
        "evidence": [{"path": "a", "status": "MEASURED"},
                     {"path": "b", "status": "INVALID"}],
    })
    rc, report = _run(tmp_path, "A claim `[claim:mixed]`.", doc)
    assert rc == chk.RC_REFUSED
    assert {f["code"] for f in report["findings"]} == {"CLAIM_OUTRUNS_EVIDENCE"}


def test_negative_a_measured_claim_citing_nothing_is_an_assertion(tmp_path):
    doc = _claims({"id": "bare", "text": "x", "status": "MEASURED"})
    rc, report = _run(tmp_path, "Stated `[claim:bare]`.", doc)
    assert {f["code"] for f in report["findings"]} == {"UNCITED_CLAIM"}
    assert rc == chk.RC_REFUSED


def test_negative_not_measured_without_a_reason_is_a_hole_with_a_label(tmp_path):
    doc = _claims({"id": "hole", "text": "x", "status": "NOT_MEASURED"})
    rc, report = _run(tmp_path, "Nothing `[claim:hole]`.", doc)
    assert rc == chk.RC_REFUSED
    assert {f["code"] for f in report["findings"]} == \
        {"NOT_MEASURED_WITHOUT_REASON"}


def test_negative_a_dangling_citation_is_caught(tmp_path):
    """A citation that resolves to nothing reads to a reader exactly like one
    that resolves to evidence."""
    rc, report = _run(tmp_path, "Proven `[claim:nowhere]`.", _claims())
    assert rc == chk.RC_REFUSED
    assert {f["code"] for f in report["findings"]} == {"DANGLING_CITATION"}


@pytest.mark.parametrize("field", chk.COLLAPSED_SCALAR_FIELDS)
def test_negative_a_collapsed_scalar_in_the_claims_is_refused(tmp_path, field):
    doc = _claims({"id": "s", "text": "x", "status": "NOT_MEASURED",
                   "reason": "none", field: 0.9})
    rc, report = _run(tmp_path, "Text `[claim:s]`.", doc)
    assert rc == chk.RC_REFUSED
    assert "COLLAPSED_SCALAR" in {f["code"] for f in report["findings"]}


def test_negative_a_banned_form_hidden_in_markup_is_still_caught(tmp_path):
    """A sentence broken across spans is the same sentence to a reader."""
    page = ("<p>This axis <span class='x'>genuinely</span> converges.</p>")
    page_file = tmp_path / "page.html"
    page_file.write_text(page, encoding="utf-8")
    claims = _write(tmp_path, "claims.json", _claims())
    rc, report = chk.evaluate(page_file, claims)
    assert rc == chk.RC_REFUSED
    assert {f["code"] for f in report["findings"]} == {"GENUINELY_CONVERGES"}


def test_a_phrase_inside_a_style_block_is_not_a_claim(tmp_path):
    page_file = tmp_path / "page.html"
    page_file.write_text(
        "<style>.nobody{color:red}</style><p>Some prose here.</p>",
        encoding="utf-8")
    claims = _write(tmp_path, "claims.json", _claims())
    rc, report = chk.evaluate(page_file, claims)
    assert rc == chk.RC_OK, report["findings"]


def test_cite_numbers_is_off_by_default_and_red_when_asked(tmp_path):
    page = "The flow has 44 steps."
    rc_default, _ = _run(tmp_path, page, _claims())
    assert rc_default == chk.RC_OK
    rc_strict, report = _run(tmp_path, page, _claims(), cite_numbers=True)
    assert rc_strict == chk.RC_REFUSED
    assert {f["code"] for f in report["findings"]} == {"UNCITED_NUMBER"}


def test_cite_numbers_ignores_code_spans_and_fences(tmp_path):
    page = ("A path `/var/run-1000` is not a claim.\n"
            "```\n"
            "run --top 12\n"
            "```\n")
    rc, report = _run(tmp_path, page, _claims(), cite_numbers=True)
    assert rc == chk.RC_OK, report["findings"]


# ---------------------------------------------------------------- vacuous

def test_vacuous_a_missing_page_is_rc2_with_a_marker(tmp_path):
    claims = _write(tmp_path, "claims.json", _claims())
    rc, report = chk.evaluate(tmp_path / "gone.md", claims)
    assert rc == chk.RC_UNDETERMINED
    assert report["code"] == "PAGE_MISSING"
    assert report["marker"] == "[CANNOT CHECK]"


def test_vacuous_a_missing_claims_file_is_rc2_not_a_clean_page(tmp_path):
    """Without the claims file no citation resolves, so a page full of banned
    forms would otherwise look qualified — or a clean page would look checked
    when nothing was."""
    page = _write(tmp_path, "page.md", "Some prose.")
    rc, report = chk.evaluate(page, tmp_path / "gone.json")
    assert rc == chk.RC_UNDETERMINED
    assert report["code"] == "CLAIMS_MISSING"


def test_vacuous_an_unparseable_claims_file_is_rc2(tmp_path):
    page = _write(tmp_path, "page.md", "Some prose.")
    claims = _write(tmp_path, "claims.json", "{not json")
    rc, report = chk.evaluate(page, claims)
    assert (rc, report["code"]) == (chk.RC_UNDETERMINED, "CLAIMS_UNREADABLE")


def test_vacuous_a_foreign_json_is_not_silently_accepted_as_claims(tmp_path):
    page = _write(tmp_path, "page.md", "Some prose.")
    claims = _write(tmp_path, "claims.json", {"schema": "something.else.v1"})
    rc, report = chk.evaluate(page, claims)
    assert (rc, report["code"]) == (chk.RC_UNDETERMINED,
                                    "CLAIMS_NOT_A_CLAIMS_DOC")


def test_vacuous_an_empty_page_is_rc2_not_rc0(tmp_path):
    """"I read it and it was empty" is not "I read it and it was clean"."""
    page = _write(tmp_path, "page.md", "   \n\n  ")
    claims = _write(tmp_path, "claims.json", _claims())
    rc, report = chk.evaluate(page, claims)
    assert (rc, report["code"]) == (chk.RC_UNDETERMINED, "EMPTY_PAGE")


def test_vacuous_arms_are_never_rc0_or_rc1(tmp_path):
    """The shape PPA_INTERFACES.md §1 names: a gate that exits 2 on absent
    input can never fail, and a gate that exits 1 reports a finding about the
    design when it never looked."""
    claims = _write(tmp_path, "claims.json", _claims())
    page = _write(tmp_path, "page.md", "Prose.")
    for args in ((tmp_path / "gone.md", claims),
                 (page, tmp_path / "gone.json")):
        rc, _ = chk.evaluate(*args)
        assert rc == chk.RC_UNDETERMINED
        assert rc not in (chk.RC_OK, chk.RC_REFUSED)


def test_bad_invocation_is_not_a_design_finding():
    # PPA_INTERFACES §1: 3 is BAD INVOCATION; 2 is UNDETERMINED ("I could not
    # look") and must never be mapped to PASS by a flow gate -- which is how a
    # caller that treats 2 as "nothing to check here" swallows a typo'd flag
    # and carries on green. This test previously asserted argparse's own 2,
    # which satisfied its stated intent (never 1) but pinned the wrong one of
    # the two remaining codes.
    rc = chk.main([])
    assert rc == 3, (
        f"a bad invocation must be rc=3, got {rc}. 2 there is UNDETERMINED "
        f"and a caller cannot tell it from an artefact that was not present.")


def test_cli_returns_the_contract_codes(tmp_path):
    page = _write(tmp_path, "page.md", "This axis genuinely converges.")
    claims = _write(tmp_path, "claims.json", _claims())
    assert chk.main([str(page), "--claims", str(claims)]) == chk.RC_REFUSED
    clean = _write(tmp_path, "clean.md", "Ordinary prose about the flow.")
    assert chk.main([str(clean), "--claims", str(claims)]) == chk.RC_OK
    assert chk.main([str(tmp_path / "gone.md"), "--claims",
                     str(claims)]) == chk.RC_UNDETERMINED


def test_list_banned_forms_is_a_read_only_query(capsys):
    assert chk.main(["--list-banned-forms"]) == chk.RC_OK
    out = capsys.readouterr().out
    for form in chk.BANNED_FORMS:
        assert form["code"] in out


# ---------------------------------------------------------------- mutation

def test_mutation_deleting_a_form_makes_its_own_fixture_pass(tmp_path):
    """Run BOTH ways. The point is not "the fixture is red" but "the fixture is
    red BECAUSE of this rule" — a red that survives the rule's removal was
    produced by something else and the rule is credited with nothing."""
    page = "This axis genuinely converges."
    rc_with, _ = _run(tmp_path, page, _claims())
    assert rc_with == chk.RC_REFUSED

    kept = tuple(f for f in chk.BANNED_FORMS
                 if f["code"] != "GENUINELY_CONVERGES")
    original = chk.BANNED_FORMS
    try:
        chk.BANNED_FORMS = kept
        rc_without, report = _run(tmp_path, page, _claims())
    finally:
        chk.BANNED_FORMS = original
    assert rc_without == chk.RC_OK, report.get("findings")


def test_mutation_without_the_strength_ordering_an_overreach_ships(
        tmp_path, monkeypatch):
    doc = _claims({"id": "over", "text": "x", "status": "MEASURED",
                   "evidence": [{"path": "a", "status": "NOT_MEASURED"}]})
    assert _run(tmp_path, "Text `[claim:over]`.", doc)[0] == chk.RC_REFUSED

    flat = {k: 1 for k in chk.STATUS_STRENGTH}
    monkeypatch.setattr(chk, "STATUS_STRENGTH", flat)
    rc, report = _run(tmp_path, "Text `[claim:over]`.", doc)
    assert rc == chk.RC_OK, report.get("findings")


def test_mutation_an_unknown_requirement_must_not_read_as_qualified():
    """A typo in a new form's `requires` must make the form unliftable, not
    unenforceable. The failure direction is chosen deliberately."""
    claim = {"id": "x", "status": "MEASURED", "text": "t",
             "scope": {"base": "v1", "reviewed": "everything"},
             "criterion": "c", "definitions": {"executable": "d"}}
    assert chk._qualification_present(claim, "base_pin") is True
    assert chk._qualification_present(claim, "bas_pin") is False
    assert chk._qualification_present(claim, "") is False


def test_an_empty_qualification_field_does_not_lift_a_form(tmp_path):
    """A field added to satisfy the gate rather than to inform a reader is a
    field the gate must not accept."""
    doc = _claims({"id": "empty", "text": "x", "status": "NOT_MEASURED",
                   "reason": "none", "scope": {"base": "   "}})
    rc, report = _run(tmp_path, "It does not measure area at all "
                                "`[claim:empty]`.", doc)
    assert rc == chk.RC_REFUSED
    assert "DOES_NOT_MEASURE_AREA" in {f["code"] for f in report["findings"]}


# --------------------------------------------------- the two programs meet

def test_the_generator_output_survives_the_checkers_strictest_mode(tmp_path):
    """End to end. A gate whose strictest mode nothing can pass is a mode
    nobody turns on."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    import ppa_report_gen as gen

    root = tmp_path / "metrics"
    root.mkdir()
    (root / "a.json").write_text(json.dumps({
        "schema": gen.METRIC_SCHEMA, "metric": "timing.setup.wns_ns",
        "status": "MEASURED", "value": -0.124, "unit": "ns",
        "scope": {"stage": "post_route_extracted"},
        "source": {"path": "sta.rpt", "sha256": "sha256:" + "b" * 64},
    }), encoding="utf-8")
    (root / "b.json").write_text(json.dumps({
        "schema": gen.METRIC_SCHEMA, "metric": "power.total_mw",
        "status": "NOT_MEASURED", "reason": "no activity basis recorded",
    }), encoding="utf-8")

    report_md = tmp_path / "report.md"
    claims_json = tmp_path / "claims.json"
    assert gen.main([str(root), "--out", str(report_md),
                     "--claims", str(claims_json)]) == gen.RC_OK

    rc, report = chk.evaluate(report_md, claims_json, cite_numbers=True)
    assert rc == chk.RC_OK, report.get("findings")
    assert report["sentences_read"] > 0
    assert report["claims_read"] > 0


# ------------------------------------------- soft line breaks (measured bug)

def test_a_hard_wrapped_sentence_keeps_its_citation(tmp_path):
    """MEASURED while writing the corrected page for the live site.

    Splitting on every newline put the number on one line and its
    `[claim:<id>]` on the next, and `--cite-numbers` reported seven findings
    against a page whose every number WAS cited. A gate that punishes the wrap
    width is a gate nobody can satisfy — and one nobody can satisfy is one that
    gets turned off, which is a worse outcome than the misses it was preventing.
    """
    doc = _claims({"id": "n", "text": "22 steps", "status": "MEASURED",
                   "evidence": [{"path": "flow.yaml", "status": "MEASURED"}]})
    wrapped = ("At the pinned base, 22 steps carried a closed_loop block\n"
               "with both a fallback_to and a trigger `[claim:n]`.\n")
    rc, report = _run(tmp_path, wrapped, doc, cite_numbers=True)
    assert rc == chk.RC_OK, report.get("findings")


def test_a_blank_line_still_ends_a_unit(tmp_path):
    """The bound on how far a citation can reach. A citation in the NEXT
    paragraph must not qualify a banned form in this one."""
    doc = _claims({"id": "q", "text": "t", "status": "MEASURED",
                   "scope": {"base": "v1.11.18"},
                   "evidence": [{"path": "flow.yaml", "status": "MEASURED"}]})
    page = ("It does not measure area at all.\n"
            "\n"
            "A separate paragraph `[claim:q]`.\n")
    rc, report = _run(tmp_path, page, doc)
    assert rc == chk.RC_REFUSED
    assert "DOES_NOT_MEASURE_AREA" in {f["code"] for f in report["findings"]}


def test_fenced_lines_are_not_joined_into_the_prose(tmp_path):
    page = ("Prose before.\n"
            "```\n"
            "run --top 12\n"
            "more 34\n"
            "```\n"
            "Prose after.\n")
    rc, report = _run(tmp_path, page, _claims(), cite_numbers=True)
    assert rc == chk.RC_OK, report.get("findings")
