#!/usr/bin/env python3
"""v0.1.62 — L5 analog keyword negation guard (spm/sha256 benchmark).

Phase1 lifted a false "dac" analog block from a NEGATED clause
("→ 不需 … analog trim DAC 等") and "esd" from "無 ESD", flipping pure-digital
ICs into mixed-signal mode. The negation guard rejects analog keywords whose
clause carries a negation marker.
"""
from __future__ import annotations
import sys
from pathlib import Path
PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import phase1_doc_one_shot_runner as P  # noqa: E402


def _negated(text, kw):
    i = text.find(kw)
    assert i >= 0
    return P._v0_1_62_analog_kw_negated(text, i, i + len(kw))


def test_zh_bu_xu_negation_rejects_dac():
    assert _negated("→ 不需 Plugin 產生 calibration controller、analog trim DAC 等。", "DAC")


def test_zh_wu_negation_rejects_esd():
    assert _negated("本設計為純數位，無 ESD 類比保護。", "ESD")


def test_en_no_analog_negation():
    assert _negated("This is a pure-digital core with no analog DAC content.", "DAC")


def test_en_without_negation():
    assert _negated("The block operates without a bandgap reference.", "bandgap")


def test_positive_dac_not_negated():
    assert not _negated("The chip integrates a 12-bit DAC for output drive.", "DAC")


def test_positive_bandgap_not_negated():
    assert not _negated("A bandgap reference provides 1.2 V to the LDO.", "bandgap")


def test_negation_scoped_to_clause():
    # negation in a PRIOR sentence must not bleed into a later positive clause
    txt = "There is no reset. The design uses a DAC for analog output."
    assert not _negated(txt, "DAC")
