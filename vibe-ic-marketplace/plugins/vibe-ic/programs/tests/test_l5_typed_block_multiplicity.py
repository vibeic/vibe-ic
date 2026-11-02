"""Block counts come from a typed answer; heading text is never widened (ruling #107)."""
import json
from pathlib import Path

import pytest

import phase1_doc_one_shot_runner as runner

# Headings that must stay low confidence without a typed answer: the
# adversarial table from the review that refused widening the regex.
ADVERSARIAL_HEADINGS = [
    ('## `pll` of bias generator (×2)', 2),
    ('## `pll` in bias generator (×2)', 2),
    ('## `pll` on bias generator (×2)', 2),
    ('## `pll` to bias generator (×2)', 2),
    ('## `pll` at bias generator (×2)', 2),
    ('## `pll` by bias generator (×2)', 2),
    ('## `pll` via bias generator (×2)', 2),
    ('## `pll` into bias generator (×2)', 2),
    ('## `pll` onto bias generator (×2)', 2),
    ('## `pll` inside bias generator (×2)', 2),
    ('## `pll` within bias generator (×2)', 2),
    ('## `pll` under bias generator (×2)', 2),
    ('## `pll` over bias generator (×2)', 2),
    ('## `pll` behind bias generator (×2)', 2),
    ('## `pll` before bias generator (×2)', 2),
    ('## `pll` after bias generator (×2)', 2),
    ('## `pll` between bias generator (×2)', 2),
    ('## `pll` among bias generator (×2)', 2),
    ('## `pll` across bias generator (×2)', 2),
    ('## `pll` near bias generator (×2)', 2),
    ('## `pll` using bias generator (×2)', 2),
    ('## `pll` beside bias generator (×2)', 2),
    ('## `pll` besides bias generator (×2)', 2),
    ('## `pll` including bias generator (×2)', 2),
    ('## `pll` except bias generator (×2)', 2),
    ('## `pll` alongside bias generator (×2)', 2),
    ('## `pll` versus bias generator (×2)', 2),
    ('## `pll` vs bias generator (×2)', 2),
    ('## `pll` than bias generator (×2)', 2),
    ('## `pll` but bias generator (×2)', 2),
    ('## `pll` nor bias generator (×2)', 2),
    ('## `pll` then bias generator (×2)', 2),
    ('## pll ldo (×2)', 2),
    ('## pll : ldo (×2)', 2),
    ('## pll comparator (×2)', 2),
    ('## pll ldo comparator (×2)', 2),
    ('## pll block ldo block (×2)', 2),
    ('## pll generator (×6?)', 6),
    ('## pll generator (×6, TBD)', 6),
    ('## pll generator (×6 TBD)', 6),
    ('## pll generator (×6-8)', 6),
    ('## pll generator (×6–8)', 6),
    ('## pll generator (×6 or more)', 6),
    ('## pll generator (×6 max)', 6),
    ('## pll generator (×6, assumed)', 6),
    ('## pll generator (×6, tentative)', 6),
    ('## pll generator (×6, nominal)', 6),
    ('## pll generator (×6, typical)', 6),
    ('## pll generator (×6, about)', 6),
    ('## pll generator (×6, roughly)', 6),
    ('## pll generator (×6 if needed)', 6),
    ('## pll generator (×6 optional)', 6),
    ('## pll generator (×6 spare)', 6),
    ('## pll possibly generator (×6)', 6),
    ('## pll maybe generator (×6)', 6),
    ('## pll tentative generator (×6)', 6),
    ('## pll TBD (×6)', 6),
    ('## pll optional generator (×6)', 6),
    ('## pll drives comparator (×6)', 6),
    ('## pll feeds comparator (×6)', 6),
    ('The pll clocks the comparators (×6)', 6),
    ('The pll is used (×6)', 6),
    ('The pll output goes (×6)', 6),
]
HEADING = ("# Analog\n\nAnalog front end.\n\n"
           "## Block A — `pll` : low-noise clock generator (×6 copies)\n\n"
           "| Parameter | Typ | Min | Max | Unit | Note |\n|---|---|---|---|---|---|\n"
           "| Fout | 100 | 90 | 110 | MHz | output |\n")


def _answers(project, value, citation="input/docs/spec.md:1 sha256:00"):
    path = project / "input/step_0_5ic_answers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"answers": {"analog_block_multiplicity": value}, "answer_provenance": {}}
    if citation:
        doc["answer_provenance"]["analog_block_multiplicity"] = {
            "answered_by": "agent", "citation": citation}
    path.write_text(json.dumps(doc), encoding="utf-8")


def _l5(project, text):
    emitted = runner.gen_l5_adi_spec(project, {"spec.md": text})
    return json.loads(Path(emitted.path).read_text())


def _pll(doc):
    return next(blk for blk in doc["analog_blocks"] if blk["name"] == "pll")


@pytest.mark.parametrize("heading,count", ADVERSARIAL_HEADINGS)
def test_adversarial_heading_without_typed_answer_stays_low(heading, count):
    assert runner._block_multiplicity_is_explicit(heading, r"\bpll\b", count) is False


def test_head_noun_heading_without_typed_answer_stays_low(tmp_path):
    assert _pll(_l5(tmp_path, HEADING))["multiplicity_evidence"]["low_confidence"] is True


def test_typed_answer_agreeing_with_heading_is_explicit(tmp_path):
    _answers(tmp_path, {"pll": 6})
    block = _pll(_l5(tmp_path, HEADING))
    evidence = block["multiplicity_evidence"]
    assert block["count"] == 6
    assert evidence["low_confidence"] is False
    assert evidence["typed_answer"]["answer"] == "answers.analog_block_multiplicity.pll"
    assert evidence["typed_answer"]["citation"].startswith("input/docs/spec.md:1")
    assert evidence["text"].startswith("## Block A")


def test_typed_answer_supplies_a_count_the_document_leaves_open(tmp_path):
    _answers(tmp_path, {"pll": 2})
    block = _pll(_l5(tmp_path, "The analog section contains a PLL at 1.8 V.\n"))
    assert block["count"] == 2
    assert block["multiplicity_evidence"]["low_confidence"] is False


def test_contradiction_is_refused_by_name(tmp_path):
    _answers(tmp_path, {"pll": 4})
    with pytest.raises(ValueError, match="L5_BLOCK_MULTIPLICITY_CONTRADICTION: pll"):
        _l5(tmp_path, HEADING)
    assert runner._typed_block_multiplicity_refusal(
        runner._typed_block_multiplicity(tmp_path), {"spec.md": HEADING}
    ).startswith("L5_BLOCK_MULTIPLICITY_CONTRADICTION: pll")


def test_block_the_document_does_not_emit_is_refused(tmp_path):
    _answers(tmp_path, {"ldo": 1})
    with pytest.raises(ValueError, match="L5_BLOCK_MULTIPLICITY_UNKNOWN_BLOCK: ldo"):
        _l5(tmp_path, HEADING)


def test_unregistered_block_name_is_refused(tmp_path):
    _answers(tmp_path, {"not_a_block_class": 1})
    assert runner._typed_block_multiplicity_refusal(
        runner._typed_block_multiplicity(tmp_path), {"spec.md": HEADING}
    ) == "L5_BLOCK_MULTIPLICITY_UNKNOWN_BLOCK: not_a_block_class"


@pytest.mark.parametrize("value", [
    6, [6], {"pll": True}, {"pll": 0}, {"pll": -1}, {"pll": 6.0}, {"pll": "6"}, {}])
def test_malformed_answer_is_refused(tmp_path, value):
    _answers(tmp_path, value)
    with pytest.raises(ValueError, match="L5_BLOCK_MULTIPLICITY_INVALID"):
        runner._typed_block_multiplicity(tmp_path)


def test_uncited_answer_is_refused(tmp_path):
    _answers(tmp_path, {"pll": 6}, citation=None)
    with pytest.raises(ValueError, match="L5_BLOCK_MULTIPLICITY_PROVENANCE_ABSENT"):
        runner._typed_block_multiplicity(tmp_path)


@pytest.mark.parametrize("value,named", [
    ({"pll": 0}, "L5_BLOCK_MULTIPLICITY_INVALID"),
    ({"pll": 4}, "L5_BLOCK_MULTIPLICITY_CONTRADICTION"),
])
def test_refusal_stops_the_runner_before_any_stub(tmp_path, monkeypatch, capsys, value, named):
    (tmp_path / "input/docs").mkdir(parents=True)
    (tmp_path / "input/docs/spec.md").write_text(HEADING, encoding="utf-8")
    _answers(tmp_path, value)
    monkeypatch.setattr("sys.argv", ["phase1_doc_one_shot_runner", str(tmp_path)])
    assert runner.main() == 2
    assert named in capsys.readouterr().err
    assert not (tmp_path / "phase1/generated_docs/L5_ADI_SPEC.json").exists()


@pytest.mark.parametrize("text,value,named", [
    (HEADING, {"ldo": 1}, "L5_BLOCK_MULTIPLICITY_UNKNOWN_BLOCK: ldo"),
    ("The analog section contains 3 x PLL at 1.8 V.\n", {"pll": 2},
     "L5_BLOCK_MULTIPLICITY_CONTRADICTION: pll"),
    (HEADING + "\n## Block C — `pll` : spare clock generator (×4)\n",
     {"pll": 6}, "L5_BLOCK_MULTIPLICITY_CONTRADICTION: pll"),
])
def test_document_refusal_is_fatal_without_l5_stub(
        tmp_path, monkeypatch, capsys, text, value, named):
    (tmp_path / "input/docs").mkdir(parents=True)
    (tmp_path / "input/docs/spec.md").write_text(text, encoding="utf-8")
    _answers(tmp_path, value)
    monkeypatch.setattr("sys.argv", ["phase1_doc_one_shot_runner", str(tmp_path)])
    result = runner.main()
    assert result == 2
    assert named in capsys.readouterr().err
    assert not (tmp_path / "phase1/generated_docs/L5_ADI_SPEC.json").exists()


def test_later_document_heading_contradiction_is_refused(tmp_path):
    _answers(tmp_path, {"pll": 6})
    with pytest.raises(ValueError, match="L5_BLOCK_MULTIPLICITY_CONTRADICTION: pll"):
        runner.gen_l5_adi_spec(tmp_path, {
            "first.md": HEADING,
            "second.md": "## Block B — pll (×4)\n",
        })
    assert not (tmp_path / "phase1/generated_docs/L5_ADI_SPEC.json").exists()


def test_matching_headings_across_documents_accept_the_typed_count(tmp_path):
    _answers(tmp_path, {"pll": 6})
    emitted = runner.gen_l5_adi_spec(tmp_path, {
        "first.md": HEADING,
        "second.md": "## Block B — pll (×6)\n",
    })
    block = _pll(json.loads(Path(emitted.path).read_text()))
    assert block["count"] == 6
    assert block["multiplicity_evidence"]["low_confidence"] is False


def test_fatal_refusal_keeps_prior_l5(tmp_path, monkeypatch, capsys):
    (tmp_path / "input/docs").mkdir(parents=True)
    (tmp_path / "input/docs/spec.md").write_text(HEADING, encoding="utf-8")
    _answers(tmp_path, {"ldo": 1})
    l5 = tmp_path / "phase1/generated_docs/L5_ADI_SPEC.json"
    l5.parent.mkdir(parents=True)
    before = b'{"analog_blocks": [{"name": "pll", "count": 6}]}\n'
    l5.write_bytes(before)
    monkeypatch.setattr("sys.argv", ["phase1_doc_one_shot_runner", str(tmp_path)])
    assert runner.main() == 2
    assert "L5_BLOCK_MULTIPLICITY_UNKNOWN_BLOCK: ldo" in capsys.readouterr().err
    assert l5.read_bytes() == before


@pytest.mark.parametrize("provenance", [["x"], "invalid", 5])
def test_malformed_provenance_is_a_named_refusal(tmp_path, provenance):
    _answers(tmp_path, {"pll": 6})
    path = tmp_path / "input/step_0_5ic_answers.json"
    doc = json.loads(path.read_text())
    doc["answer_provenance"] = provenance
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="L5_BLOCK_MULTIPLICITY_PROVENANCE_ABSENT"):
        runner._typed_block_multiplicity(tmp_path)
