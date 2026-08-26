"""The Phase-1 coverage number credits a literal that was COPIED, not read.

`extraction_patterns.json` says in its own header that it is the coverage
denominator, and a literal is credited when its verbatim string appears anywhere
in the L*.json payload. Several L fields carry the input prose unchanged, so a
literal sitting in one of those satisfies the credit test without having been
extracted into anything.

Measured on a plain-English spec for a 4-channel PWM: 35 denominator, 100.0%
reported, 8 credited only by a verbatim-prose field — and one of the eight is
`25 MHz`, the system clock, in a run whose `L8.clock_mhz` came out 10.0. The
metric certified as extracted the number the extractor got wrong.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _project(tmp_path: Path, denominator, structured: dict, prose: dict) -> Path:
    p = tmp_path / "proj"
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "phase1" / "extraction_patterns.json").write_text(json.dumps({
        "_comment": "this file is the coverage denominator",
        "design_description.txt": [{"literal": l, "label": "auto"}
                                   for l in denominator],
    }))
    (p / "phase1" / "generated_docs" / "L2_FRS.json").write_text(
        json.dumps({"frs_sections": prose.get("frs_sections", [])}))
    (p / "phase1" / "generated_docs" / "L8_RTL_CONSTANTS.json").write_text(
        json.dumps(structured))
    return p


def _audit(p: Path):
    from extraction_credited_by_prose_only_check import audit
    return audit(p)


def test_a_literal_carried_only_by_prose_is_named(tmp_path):
    """`0xDEADBEEF` sits inside a requirement SENTENCE and nowhere structured.
    The published metric credits it; this one does not."""
    p = _project(
        tmp_path,
        denominator=["0xDEADBEEF", "0x2A"],
        structured={"parameters": [{"name": "ID_VALUE", "value": "0x2A"}]},
        prose={"frs_sections": [{"text": "the trim code is 0xDEADBEEF"}]},
    )
    rep = _audit(p)
    assert rep["prose_only"] == ["0xDEADBEEF"], rep
    assert rep["structured"] == 1 and rep["denominator"] == 2
    assert rep["structured_pct"] == 50.0


def test_a_structured_literal_is_credited(tmp_path):
    """Nothing that is genuinely extracted may be penalised — otherwise the
    gate is a complaint rather than a measurement."""
    p = _project(
        tmp_path,
        denominator=["0x2A"],
        structured={"parameters": [{"name": "ID_VALUE", "value": "0x2A"}]},
        prose={"frs_sections": []},
    )
    rep = _audit(p)
    assert rep["prose_only"] == [] and rep["structured_pct"] == 100.0


def test_the_same_literal_in_both_places_counts_as_structured(tmp_path):
    """A number quoted in a sentence AND carried in a typed field was
    extracted; the prose copy beside it does not take that away."""
    p = _project(
        tmp_path,
        denominator=["0x2A"],
        structured={"parameters": [{"name": "ID_VALUE", "value": "0x2A"}]},
        prose={"frs_sections": [{"text": "the ID register reads 0x2A"}]},
    )
    assert _audit(p)["structured_pct"] == 100.0


def test_a_denominator_literal_in_no_doc_at_all_is_separated(tmp_path):
    """"copied instead of read" and "absent entirely" are different failures
    and are reported as different lists."""
    p = _project(
        tmp_path,
        denominator=["0xFEEDFACE"],
        structured={"parameters": []},
        prose={"frs_sections": []},
    )
    rep = _audit(p)
    assert rep["uncredited"] == ["0xFEEDFACE"] and rep["prose_only"] == []


def test_a_zero_denominator_refuses(tmp_path):
    """The house rule: nothing to examine is not the same as everything
    examined and clean, so it exits 2 rather than 0."""
    from extraction_credited_by_prose_only_check import main
    p = tmp_path / "empty"
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    assert main([str(p)]) == 2
