"""`tokens_missing_everywhere` must be triageable, and must not count
fabrication vocabulary as a design token.

Two findings from a real campaign run, both reproduced here.

1. FALSE POSITIVE. A run reported ``tokens_missing_everywhere: 1`` out
   of 328 and FAILed the gate. The single token was **CMOS**, harvested
   by the all-caps family out of ordinary datasheet prose ("a low-power
   CMOS process"). A process-family noun names no signal, register,
   field, opcode, command, timing parameter or interface contract, so
   there is nothing for a generated L doc to carry and its absence can
   never be a real coverage gap — only a permanent false FAIL. Process
   selection is carried by L19 from the PDK configuration, not by
   round-tripping a prose noun.

2. UNACTIONABLE REPORT. The headline metric was a bare count. Nothing
   in the report named the token, so a reader could not tell a real
   coverage gap from a tokenizer artefact without re-deriving it from
   ``per_doc[]``. A 1-in-328 signal is exactly the size where the two
   are equally likely, so the count alone cost every reader the same
   investigation.

The gate must still FAIL on a genuinely absent design token — a
completeness check that cannot report incompleteness is an alarm that
cannot ring.

chip-AGNOSTIC: fixtures are synthetic docs with invented signal names.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1] / \
    "phase1_doc_input_completeness_check.py"
REPORT = Path("reports/phase1/phase1_input_vs_generated_completeness.json")


def _mk_project(tmp_path: Path, doc_text: str, captured_terms) -> Path:
    """Minimal project: one input doc + one generated L doc.

    ``captured_terms`` is what the generated L doc carries, i.e. what
    Phase 1 successfully extracted.
    """
    proj = tmp_path / "proj"
    (proj / "phase1" / "input_doc").mkdir(parents=True)
    (proj / "phase1" / "input_doc" / "spec.txt").write_text(doc_text)
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "dut", "content": list(captured_terms)}))
    return proj


def _run(proj: Path):
    r = subprocess.run([sys.executable, str(PROG), str(proj)],
                       capture_output=True, text=True)
    rep_path = proj / REPORT
    rep = json.loads(rep_path.read_text()) if rep_path.is_file() else None
    return r, rep


# A doc whose design tokens are all captured, plus prose that mentions
# the fabrication process. >= _MIN_TOKENS (10) distinct design tokens so
# the doc is audited rather than skipped.
_DESIGN_TERMS = [
    "AUTHCTRL", "IDBUS", "CRCPOLY", "TXFIFO", "RXFIFO", "STATUSREG",
    "CMDREG", "WAKEPIN", "SLEEPCTL", "PARITYERR", "TIMEOUTCNT",
]


def _doc_with_process_prose(extra: str = "") -> str:
    body = " ".join(f"Signal {t} is defined." for t in _DESIGN_TERMS)
    return (
        "Theory of operation.\n"
        "The device is fabricated in a low-power CMOS process with "
        "NMOS pull-downs and PMOS pull-ups.\n"
        + body + "\n" + extra
    )


# ------------------------------------------------------- false positive
def test_process_vocabulary_is_not_a_missing_design_token(tmp_path):
    """The reproduction: CMOS must not FAIL a fully-captured doc."""
    proj = _mk_project(tmp_path, _doc_with_process_prose(), _DESIGN_TERMS)
    r, rep = _run(proj)

    assert rep is not None
    assert rep["tokens_missing_everywhere"] == 0, \
        f"process vocabulary counted as missing: " \
        f"{rep.get('tokens_missing_everywhere_list')}"
    assert rep["verdict"] == "PASS"
    assert r.returncode == 0


@pytest.mark.parametrize("term", ["CMOS", "NMOS", "PMOS", "BICMOS",
                                  "MOSFET", "FINFET"])
def test_no_fabrication_term_is_harvested(tmp_path, term):
    proj = _mk_project(
        tmp_path,
        _doc_with_process_prose(f"Implemented in {term} technology."),
        _DESIGN_TERMS)
    _, rep = _run(proj)
    assert term not in rep["tokens_missing_everywhere_list"]


def test_io_standards_are_still_design_content(tmp_path):
    """Interface / I-O standards are NOT fabrication vocabulary.

    LVCMOS is a real electrical contract that must round-trip; it must
    keep behaving as a design token, so the exclusion stays narrow.
    """
    proj = _mk_project(
        tmp_path,
        _doc_with_process_prose("Bank I/O standard is LVCMOS33."),
        _DESIGN_TERMS)  # LVCMOS33 deliberately NOT captured
    _, rep = _run(proj)
    assert "LVCMOS33" in rep["tokens_missing_everywhere_list"]


# --------------------------------------------------------- must still fire
def test_genuinely_missing_design_token_still_fails(tmp_path):
    """The alarm must still ring — no false-clean.

    A real signal named in the input doc but absent from every
    generated L doc is a true coverage gap.
    """
    proj = _mk_project(
        tmp_path,
        _doc_with_process_prose("Signal SECUREBOOTEN gates the core."),
        _DESIGN_TERMS)  # SECUREBOOTEN deliberately NOT captured
    r, rep = _run(proj)

    assert rep["tokens_missing_everywhere"] >= 1
    assert "SECUREBOOTEN" in rep["tokens_missing_everywhere_list"]
    assert rep["verdict"] == "FAIL"
    assert r.returncode == 1


# ------------------------------------------------------- actionability
def test_missing_tokens_are_named_in_the_report(tmp_path):
    """The headline count must be triageable without re-deriving it."""
    proj = _mk_project(
        tmp_path,
        _doc_with_process_prose("Signal SECUREBOOTEN gates the core."),
        _DESIGN_TERMS)
    _, rep = _run(proj)

    assert "tokens_missing_everywhere_list" in rep
    named = rep["tokens_missing_everywhere_list"]
    assert len(named) == rep["tokens_missing_everywhere"], \
        "named tokens must account for the whole headline count"
    assert named == sorted(named)


def test_clean_project_reports_empty_list_not_absent_key(tmp_path):
    """A clean run still carries the key, so consumers never KeyError."""
    proj = _mk_project(tmp_path, _doc_with_process_prose(), _DESIGN_TERMS)
    _, rep = _run(proj)
    assert rep["tokens_missing_everywhere_list"] == []
