#!/usr/bin/env python3
"""ORGANIC #781 — a testbench signature / handshake / tohost / fromhost address
is a VERIFICATION-HARNESS constant, not a chip-design fact, and must not be
counted against the 100%-capture design-token denominator of
phase1_doc_input_completeness_check.py.

Real campaign reproduction (ibex × sky130A, 1.5.51): the single missing token
of the whole run was ``0x8ffffffc`` from the verification HOWTO doc's sentence
"the signature address that this testbench uses for the handshaking is
``0x8ffffffc``." — a RISCV-DV testbench convention. The value is written by the
software test program and monitored by the EXTERNAL testbench; it is never
latched or decoded inside the DUT RTL, so it has no L1-L27 design-layer home and
can never be captured without fabricating a layer. Excluding it mirrors the
existing URL-slug / binary-garble / fabrication-vocabulary denominator filters.

NO-LEAK: the filter is restricted to hex-address-shaped tokens AND an
unambiguous verification-harness marker; a real design register address decoded
by the RTL is still a design token and still FAILs when dropped.

chip-AGNOSTIC: synthetic docs with invented signal names + generic verification
vocabulary; no chip/vendor literal.
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
    proj = tmp_path / "proj"
    (proj / "phase1" / "input_doc").mkdir(parents=True)
    (proj / "phase1" / "input_doc" / "verification.txt").write_text(doc_text)
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


# >= _MIN_TOKENS (10) design tokens so the doc is audited (not skipped),
# all captured, plus a verification-harness address that is NOT in any L doc.
_DESIGN_TERMS = [
    "AUTHCTRL", "IDBUS", "CRCPOLY", "TXFIFO", "RXFIFO", "STATUSREG",
    "CMDREG", "WAKEPIN", "SLEEPCTL", "PARITYERR", "TIMEOUTCNT",
]


def _doc(extra: str) -> str:
    body = " ".join(f"Signal {t} is defined." for t in _DESIGN_TERMS)
    return "Verification methodology.\n" + body + "\n" + extra


@pytest.mark.parametrize("sentence", [
    "As a sidenote, the signature address that this testbench uses for the "
    "handshaking is 0x8ffffffc.",
    "The test writes its result to the tohost address 0x80001000 to end sim.",
    "The testbench polls the handshake at 0x40002000 during the run.",
])
def test_verification_harness_address_not_counted_missing(tmp_path, sentence):
    """A testbench signature/handshake/tohost address (absent from every L
    doc) must NOT FAIL a fully-captured doc."""
    proj = _mk_project(tmp_path, _doc(sentence), _DESIGN_TERMS)
    r, rep = _run(proj)
    assert rep is not None
    assert rep["tokens_missing_everywhere"] == 0, \
        f"harness address counted missing: " \
        f"{rep.get('tokens_missing_everywhere_list')}"
    assert rep["verdict"] == "PASS"
    assert r.returncode == 0


def test_design_register_address_still_counts(tmp_path):
    """NO-LEAK: a real design register address (decoded by the core), genuinely
    absent from every L doc, is STILL a missing design token → FAIL. The
    filter must stay narrow to the verification-harness vocabulary."""
    proj = _mk_project(
        tmp_path,
        _doc("The control register lives at 0x40000010 and is decoded by the "
             "core to select the mode."),
        _DESIGN_TERMS)  # 0x40000010 deliberately NOT captured
    r, rep = _run(proj)
    assert rep is not None
    assert "0x40000010" in rep["tokens_missing_everywhere_list"], \
        "a real design register address was wrongly excluded"
    assert rep["verdict"] == "FAIL"
    assert r.returncode == 1


def test_isa_token_near_signature_still_captured(tmp_path):
    """NO-LEAK: an ISA / all-caps design token that happens to sit near a
    'signature address' sentence must still be a design token (only the hex
    address is filtered)."""
    proj = _mk_project(
        tmp_path,
        _doc("All RV32IMCB instructions verified; the signature address is "
             "0x8ffffffc for handshaking."),
        _DESIGN_TERMS)  # RV32IMCB deliberately NOT captured
    r, rep = _run(proj)
    assert rep is not None
    assert "RV32IMCB" in rep["tokens_missing_everywhere_list"], \
        "an ISA design token near the harness address was wrongly excluded"
    assert "0x8ffffffc" not in rep["tokens_missing_everywhere_list"]


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q",
                              str(Path(__file__))]))
