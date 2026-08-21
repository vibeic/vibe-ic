"""A canned `notes` string must not outlive the canned fact it explains.

`spi_protocol_synth._apply_universal` installs, for L19/L20/L22/L23, a
presence fact ("constraints_present: False") together with a prose `notes`
string that EXPLAINS that fact ("... does not include PDK / timing
constraints"). Both were installed with the same unconditional
`setdefault`, so a real extraction could take the FACT while the PROSE
still landed. The result was a document whose notes asserted the opposite
of its own fields.

Measured on a real design: an L19 carrying an extracted `pdk_target` and an
`sdc_constraints_path`, with `constraints_present: true`, was still emitted
with notes reading "Block-level peripheral spec does not include PDK /
timing constraints".

Second clause: `_apply_universal` runs for EVERY IC, not only genuine SPI
(see the H4 note in the module). Its canned prose was peripheral-flavored
regardless -- "Block-level peripheral spec", "The peripheral register
file", "for the serial peripheral" -- so an IC that is not a peripheral at
all was described as one. The SPI wording must stay behind `is_spi`, the
same way the verification-category lists already are.
"""
from __future__ import annotations

import json

import pytest

import spi_protocol_synth as sps


_L19 = "L19_CONSTRAINTS_PDK"
_L20 = "L20_DFT_SCAN_TOPOLOGY"
_L23 = "L23_SECURITY_REQUIREMENTS"
_L11 = "L11_OTP_CONTENT"


def _seed(gd, l19_fields=None):
    gd.mkdir(parents=True, exist_ok=True)
    (gd / f"{_L19}.json").write_text(json.dumps(
        {"doc_id": "L19", "doc_name": _L19, "fields": dict(l19_fields or {})}))
    for stem, did in ((_L20, "L20"), (_L23, "L23")):
        (gd / f"{stem}.json").write_text(json.dumps(
            {"doc_id": did, "doc_name": stem, "fields": {}}))
    (gd / f"{_L11}.json").write_text(json.dumps(
        {"doc_id": "L11", "doc_name": _L11}))
    return gd


def _fields(gd, stem):
    d = json.loads((gd / f"{stem}.json").read_text())
    return d.get("fields") or d


# The extraction a real design leaves behind: the spec DOES state a PDK
# target and an SDC path, so the presence fact is already True.
_EXTRACTED = {
    "pdk_target": "someproc-xx 180nm",
    "sdc_constraints_path": "input/constraints/clock.sdc",
    "constraints_present": True,
}


def test_l19_notes_must_not_deny_constraints_the_same_document_carries(tmp_path):
    gd = _seed(tmp_path / "generated_docs", _EXTRACTED)
    sps.apply_spi_synth(gd, False, None)
    f = _fields(gd, _L19)

    # The extracted facts must survive untouched.
    assert f["constraints_present"] is True
    assert f["pdk_target"] == "someproc-xx 180nm"
    assert f["sdc_constraints_path"] == "input/constraints/clock.sdc"

    # And the document must not simultaneously deny them.
    notes = f.get("notes") or ""
    assert "does not include PDK" not in notes, (
        "L19 notes deny the PDK/timing constraints this very document carries: "
        f"{notes!r}")
    assert "does not state PDK" not in notes, (
        f"L19 notes deny constraints the document carries: {notes!r}")


def test_the_same_holds_for_a_genuine_spi(tmp_path):
    """The contradiction is not a non-SPI artefact -- it must not appear on
    the SPI path either."""
    gd = _seed(tmp_path / "generated_docs", _EXTRACTED)
    sps.apply_spi_synth(gd, True, "spi_block")
    f = _fields(gd, _L19)
    assert f["constraints_present"] is True
    notes = f.get("notes") or ""
    assert "does not include PDK" not in notes, notes


def test_canned_notes_still_emitted_when_nothing_contradicts_them(tmp_path):
    """The fix must not silence the prose in the case it is true of --
    a spec that genuinely states no PDK/timing constraints."""
    gd = _seed(tmp_path / "generated_docs", None)
    sps.apply_spi_synth(gd, False, None)
    f = _fields(gd, _L19)
    assert f["constraints_present"] is False
    assert (f.get("notes") or "").strip(), "the explanatory note was lost"


@pytest.mark.parametrize("stem", [_L19, _L20, _L23, _L11])
def test_a_non_spi_ic_is_not_described_as_a_peripheral(tmp_path, stem):
    gd = _seed(tmp_path / "generated_docs", None)
    sps.apply_spi_synth(gd, False, None)
    notes = (_fields(gd, stem).get("notes") or "").lower()
    for token in ("peripheral", "block guide", "serial"):
        assert token not in notes, (
            f"{stem} notes describe a non-SPI IC as a peripheral: {notes!r}")


@pytest.mark.parametrize(
    "stem,fragment",
    [(_L19, "Block-level peripheral spec does not include PDK / timing "
            "constraints; these are deferred to the SoC integration spec."),
     (_L20, "The peripheral register file is amenable to standard scan "
            "insertion at the SoC level."),
     (_L23, "authentication requirements for the serial peripheral."),
     (_L11, "in the serial-peripheral protocol block guide.")])
def test_spi_wording_is_preserved_verbatim_for_a_genuine_spi(tmp_path, stem, fragment):
    """Narrowing the prose must not change what a real SPI block gets."""
    gd = _seed(tmp_path / "generated_docs", None)
    sps.apply_spi_synth(gd, True, "spi_block")
    assert fragment in (_fields(gd, stem).get("notes") or "")
