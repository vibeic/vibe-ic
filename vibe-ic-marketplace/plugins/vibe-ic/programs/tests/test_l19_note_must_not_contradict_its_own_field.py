"""A generated L-doc note must not assert the opposite of its own sibling field.

MEASURED DEFECT
===============
`_apply_universal` back-fills a `notes` string into L19/L20/L23 with
`fields.setdefault(...)`. `setdefault` guards the KEY, not the CLAIM: when the
real extractor has already populated the record, the `*_present` flag it wrote
survives (setdefault leaves it) but `notes` is still absent, so the canned
"...does not include..." sentence is inserted right next to it.

Observed on a real run whose L19 had a PDK target extracted from the design's
own input prose:

    "pdk_target":          "<a real process>"
    "constraints_present": true
    "notes":               "Block-level peripheral spec does not include PDK /
                            timing constraints; these are deferred to the SoC
                            integration spec."

The record answers the same question twice, in opposite directions, and the
prose is the half a human reads. A declaration that denies its own populated
field is worse than a missing note.

The fix keeps the note for the case it was written for -- a genuinely empty
record -- and withholds it when the sibling `*_present` field says otherwise.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spi_protocol_synth import _apply_universal  # noqa: E402


def _mk(tmp_path: Path, name: str, fields: dict) -> Path:
    gd = tmp_path / name.split(".")[0]
    gd.mkdir(parents=True, exist_ok=True)
    (gd / name).write_text(json.dumps({"doc_id": name.split("_")[0],
                                       "fields": fields}))
    return gd


def _fields(gd: Path, name: str) -> dict:
    return json.loads((gd / name).read_text())["fields"]


def test_populated_l19_does_not_get_a_note_saying_it_is_empty(tmp_path):
    """constraints_present=True + a pdk_target must not carry a 'does not include' note."""
    gd = _mk(tmp_path, "L19_CONSTRAINTS_PDK.json",
             {"pdk_target": "some-process 180 nm", "constraints_present": True})
    _apply_universal(gd)
    f = _fields(gd, "L19_CONSTRAINTS_PDK.json")

    assert f["constraints_present"] is True, "extractor value must survive"
    assert f["pdk_target"] == "some-process 180 nm"
    note = f.get("notes") or ""
    # Matched on the DENIAL, not on one phrasing of it: #715 split the canned
    # wording into an SPI form ("does not include") and a neutral one ("does
    # not state"), so an assertion pinned to either spelling would pass on the
    # other while the note went on denying a populated field.
    assert not _denies_constraints(note), (
        "L19 declares constraints ARE present and names a PDK target, yet the "
        "emitted note denies it: %r" % note)


def _denies_constraints(note: str) -> bool:
    """Does this note claim the spec states no PDK / timing constraints?

    #715 gave the canned strings two spellings — SPI ("Block-level peripheral
    spec does not include ...") and neutral ("Spec does not state ...") — so
    the assertions here read the CLAIM rather than one of its wordings."""
    n = (note or "").lower()
    return ("pdk" in n or "timing" in n) and (
        "does not include" in n or "does not state" in n
        or "does not specify" in n)


def test_empty_l19_still_gets_its_explanatory_note(tmp_path):
    """The note is still the right thing to say when the record really is empty."""
    gd = _mk(tmp_path, "L19_CONSTRAINTS_PDK.json", {})
    _apply_universal(gd)
    f = _fields(gd, "L19_CONSTRAINTS_PDK.json")

    assert f["constraints_present"] is False
    assert _denies_constraints(f.get("notes") or ""), (
        "an empty L19 should still explain why it is empty")


def test_populated_l20_and_l23_are_covered_by_the_same_rule(tmp_path):
    """Same defect shape, same guard -- DFT and security records."""
    gd = _mk(tmp_path, "L20_DFT_SCAN_TOPOLOGY.json", {"dft_present": True})
    _apply_universal(gd)
    note20 = _fields(gd, "L20_DFT_SCAN_TOPOLOGY.json").get("notes") or ""
    assert "does not specify" not in note20, note20

    gd = _mk(tmp_path, "L23_SECURITY_REQUIREMENTS.json",
             {"security_requirements_present": True})
    _apply_universal(gd)
    note23 = _fields(gd, "L23_SECURITY_REQUIREMENTS.json").get("notes") or ""
    assert "does not specify" not in note23, note23
