"""tests/test_analog_a3_netlist_gen_check.py — v1.6.35"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "analog_a3_netlist_gen_check.py")


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


def _sp(project: Path, block: str, body: str,
        design_content: str = "structure_and_geometry") -> None:
    """Write the deck AND, unless `design_content=None`, the producer's record
    beside it.

    The record is written BY DEFAULT because the gate now asks a substantive
    deck what circuit is in it, and a fixture that asserted a CERTIFIED step on
    a silent deck would be a standing statement that omission is fine — the
    incentive the disclosure tier exists to remove. Every fixture below whose
    property under test is a VALUE rule keeps measuring that rule; the tier
    tests pass the token they mean."""
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{block}.sp").write_text(body)
    if design_content is not None:
        (d / "netlist_provenance.json").write_text(json.dumps({
            "block": block,
            "_provenance": {"producer": "test-fixture",
                            "design_content": design_content}}))


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True,
    )


_REAL_NETLIST = (
    "* ldo netlist\n"
    ".subckt ldo VDD VSS VOUT VREF EN\n"
    + "M1 net1 VREF VSS VSS nmos w=2u l=0.18u\n" * 6
    + ".ends ldo\n.end\n"
)


def test_happy_path(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _sp(tmp_path, "ldo", _REAL_NETLIST)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"


# ── THREE TIERS, and the ORDER they rank in ───────────────────────────────
# design-bound > structure-only (disclosed) > undisclosed. Until v1.9.41+1 this
# gate had the middle tier and NOT the last one, so a design-bound deck and a
# silent deck produced the same rc AND the same `--json` document, while the
# deck that DISCLOSED a library default was the only one marked down. Silence
# ranked above disclosure in the one gate the flow declares for this step.

def test_a_silent_netlist_does_not_certify_the_step(tmp_path: Path) -> None:
    """Same substantive deck as `test_happy_path`, with the producer's record
    removed — the shape of a stale artefact and of every artefact written
    before the field existed."""
    _block_list(tmp_path, ["ldo"])
    _sp(tmp_path, "ldo", _REAL_NETLIST, design_content=None)
    r = _run(tmp_path)
    assert r.returncode == 1, (r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "FAIL", rpt
    assert any(f["rule"] == "A3_DESIGN_CONTENT_UNDECLARED"
               for f in rpt["findings"]), rpt


def test_an_honest_statement_of_ignorance_is_not_a_statement_of_content(
        tmp_path: Path) -> None:
    """A non-empty token that names no content must not certify either. If it
    did, a producer could buy a pass by WRITING the token instead of by
    inheriting the answer, and silence would be cheap again under a new name."""
    _block_list(tmp_path, ["ldo"])
    _sp(tmp_path, "ldo", _REAL_NETLIST, design_content="undeclared")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any(f["rule"] == "A3_DESIGN_CONTENT_UNDECLARED"
               for f in rpt["findings"]), rpt


def test_a_disclosed_library_netlist_certifies_in_its_own_tier(
        tmp_path: Path) -> None:
    """The middle tier is a CERTIFICATION, not a softer failure: rc 0, the
    block counted covered, the verdict word carrying the tier, and the
    line-start sentinel the runner and the flow auditor read."""
    _block_list(tmp_path, ["ldo"])
    _sp(tmp_path, "ldo", _REAL_NETLIST, design_content="structure_only")
    r = _run(tmp_path)
    assert r.returncode == 0, (r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS_STRUCTURE_ONLY", rpt
    assert rpt["blocks_pass"] == 1, rpt
    assert rpt["structure_only_blocks"] == ["ldo"], rpt
    assert any(l.startswith("STRUCTURE_ONLY:")
               for l in (r.stdout + r.stderr).splitlines()), r.stdout


def test_the_three_tiers_write_three_different_documents(
        tmp_path: Path) -> None:
    """THE RANKING, read from the artefact a machine consumer reads rather than
    from prose. Pre-fix the design-bound and the silent document were
    BYTE-IDENTICAL."""
    import hashlib
    shas = {}
    for tag, dc in (("d", "structure_and_geometry"),
                    ("s", "structure_only"), ("n", None)):
        p = tmp_path / tag
        _block_list(p, ["ldo"])
        _sp(p, "ldo", _REAL_NETLIST, design_content=dc)
        _run(p)
        shas[tag] = hashlib.sha256(
            (p / "report.json").read_bytes()).hexdigest()[:16]
    assert len(set(shas.values())) == 3, shas


def test_missing_per_block_waived(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 2
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["suggested_skill"] == "analog-netlist-gen"


def test_tiny_stub_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _sp(tmp_path, "ldo", "* netlist stub\n.end\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A3_NETLIST_TOO_SMALL" in f["rule"]
               for f in rpt["findings"])


def test_no_subckt_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _sp(tmp_path, "ldo",
        "* simulation script (no .subckt)\n"
        + "M1 net1 VREF VSS VSS nmos w=2u l=0.18u\n" * 12
        + ".end\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A3_NETLIST_NO_SUBCKT" in f["rule"]
               for f in rpt["findings"])


def test_multiblock_one_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo", "bandgap"])
    _sp(tmp_path, "ldo", _REAL_NETLIST)
    _sp(tmp_path, "bandgap", "* stub\n.end\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any(f["block"] == "bandgap" for f in rpt["findings"])


def test_no_block_list_vacuous(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS"
