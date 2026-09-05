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


# ── LAYOUT-REALIZABILITY (A3_NETLIST_IDEAL_PRIMITIVE_IN_BLOCK) ────────────
# A6 grades DRC == 0 AND a netgen LVS match. The netgen PDK setup declares
# device classes for the PDK's own res_*/cap_* subcircuits and NOTHING that
# equates an ideal SPICE primitive to a drawn device, so a block carrying one
# cannot match — before anyone draws anything. Measured on the deck below:
# A3, A4 and A5 all certified it and the only signal was an A6 mismatch three
# steps later, which reads as a layout defect.

_MOS = ("Mn1 nd1 VINP ntail VSS nfet_01v8 W=8u L=0.5u\n"
        "Mn2 nd2 VINN ntail VSS nfet_01v8 W=8u L=0.5u\n"
        "Mp3 nd1 nd1 VDD VDD pfet_01v8 W=8u L=0.5u\n"
        "Mp4 nd2 nd1 VDD VDD pfet_01v8 W=8u L=0.5u\n"
        "Mtail ntail nbias VSS VSS nfet_01v8 W=4u L=0.5u\n")
_PORTS = ".subckt ota VDD VSS VINP VINN VOUT FB nbias nd2\n"
_HDR = "* ota — realizability fixtures\n"


def _rules(project: Path):
    rpt = json.loads((project / "report.json").read_text())
    return rpt, sorted({f["rule"] for f in rpt.get("findings", [])})


def test_ideal_primitives_inside_the_block_subckt_fail(tmp_path: Path) -> None:
    """(a) of the three-way proof — the authoring skill's own worked example."""
    _block_list(tmp_path, ["ota"])
    _sp(tmp_path, "ota",
        _HDR + _PORTS + _MOS
        + "Vbias nbias VSS 0.8\n"
          "R1 VOUT FB 100k\n"
          "Cc nd2 VOUT 3p\n"
          ".ends ota\n")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.stdout, r.stderr)
    rpt, rules = _rules(tmp_path)
    assert rules == ["A3_NETLIST_IDEAL_PRIMITIVE_IN_BLOCK"], rpt
    cards = {c["card"] for c in rpt["findings"][0]["ideal_cards"]}
    assert cards == {"Vbias", "R1", "Cc"}, rpt


def test_the_same_devices_in_the_testbench_pass(tmp_path: Path) -> None:
    """(b) — the testbench is where the remediations SEND these elements
    ("hoist the source to a port", "move the load to the TB"). A rule that
    fired on them would push the fix straight back out again."""
    _block_list(tmp_path, ["ota"])
    _sp(tmp_path, "ota",
        _HDR + _PORTS + _MOS + ".ends ota\n"
        + ".subckt ota_tb VDD VSS\n"
          "Xdut VDD VSS ninp ninn nout nfb nbias nd2 ota\n"
          "Vbias nbias VSS 0.8\n"
          "R1 nout nfb 100k\n"
          "Cload nout VSS 1p\n"
          ".ends ota_tb\n")
    r = _run(tmp_path)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _rules(tmp_path)[1] == []


def test_pdk_res_and_cap_devices_pass(tmp_path: Path) -> None:
    """(c) — both PDK forms. `X...` is the subcircuit instance every PDK
    device takes, and an R/C card NAMING A MODEL is a semiconductor device the
    PDK can declare a device class for. A SPICE identifier cannot begin with a
    digit, so value and model are separable exactly, with no model-name list."""
    _block_list(tmp_path, ["ota"])
    _sp(tmp_path, "ota",
        _HDR + _PORTS + _MOS
        + "XR1 VOUT FB VSS res_xhigh_po W=0.35u L=48u\n"
          "XCc nd2 VOUT cap_mim_m3 W=10u L=10u\n"
          "R2 VOUT FB res_generic_po W=1u L=10u\n"
          "C2 nd2 VSS cap_var_lvt W=5u L=5u\n"
          ".ends ota\n")
    r = _run(tmp_path)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _rules(tmp_path)[1] == []


def test_a_controlled_source_is_not_a_way_round_the_rule(
        tmp_path: Path) -> None:
    """A linear VCCS IS a resistor. Covering E/F/G/H/B is what stops the rule
    being evaded by writing the same ideal element with a different letter."""
    _block_list(tmp_path, ["ota"])
    _sp(tmp_path, "ota",
        _HDR + _PORTS + _MOS
        + "G1 VOUT FB VOUT FB 1e-5\n"
          "B1 nd2 VSS I=V(nd1)*1e-3\n"
          ".ends ota\n")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.stdout, r.stderr)
    rpt, rules = _rules(tmp_path)
    assert rules == ["A3_NETLIST_IDEAL_PRIMITIVE_IN_BLOCK"], rpt
    assert {c["card"] for c in rpt["findings"][0]["ideal_cards"]} == {"G1",
                                                                     "B1"}


def test_file_scope_cards_are_not_block_content(tmp_path: Path) -> None:
    """`<block>.sp` is `.include`d by its testbench; a card at file scope is
    not inside the block. Same depth discipline `_subckt_device_count` uses."""
    _block_list(tmp_path, ["ota"])
    _sp(tmp_path, "ota",
        _HDR + _PORTS + _MOS + ".ends ota\n"
        + "Vsup VDD VSS 1.8\n"
          "Rload VOUT VSS 10k\n")
    r = _run(tmp_path)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _rules(tmp_path)[1] == []


def test_a_disclosed_stub_is_not_charged_for_its_disclosure(
        tmp_path: Path) -> None:
    """The runner's own deterministic A3 stub is `r_stub vin vout 1k` inside
    the block subckt. It already SAYS it is a placeholder; failing it here
    would charge for the disclosure and replace an accurate PASS_WITH_STUB
    with a realizability complaint about a circuit nobody claims is real.
    This pins the rule's POSITION, after the stub short-circuit."""
    _block_list(tmp_path, ["ota"])
    _sp(tmp_path, "ota",
        "* deterministic_stub extraction_strategy=deterministic_stub\n"
        "* ota — SPICE netlist (stub)\n"
        ".subckt ota vdd vss vin vout\n"
        "* replace with extracted netlist when analog-netlist-gen skill runs\n"
        "r_stub vin vout 1k\n"
        ".ends ota\n"
        + "* padding to clear the 200-byte substance floor\n" * 4,
        design_content=None)
    r = _run(tmp_path)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _rules(tmp_path)[1] == []


def test_the_value_rules_still_come_first(tmp_path: Path) -> None:
    """Ordering: a `.subckt` shell with one ideal R and nothing else is
    diagnosed as the deeper defect it is, not as a realizability complaint."""
    _block_list(tmp_path, ["ota"])
    _sp(tmp_path, "ota",
        "* simulation script (no .subckt)\n"
        + "R1 a b 1k\n" * 30 + ".end\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert _rules(tmp_path)[1] == ["A3_NETLIST_NO_SUBCKT"]


# ── the deck must be CURRENT with the IR it says it rendered ──────────────
# MEASURED on a real project, and it is why this rule is a FAIL and not a
# note: the checked-in `delta_sigma.sp` carried 222 device cards while the
# `topology.json` in the SAME directory declared 238 — the deck predated an
# emitter fix and nothing had re-emitted since. Three lanes measured that
# deck. Every gate in the flow passed it, because each asks whether the deck
# is WELL FORMED and none asked whether it is CURRENT. A producer fix that a
# measurement cannot see is indistinguishable from no fix.
_IR = {"block": "ota", "block_type": "ldo", "devices": [], "ports": []}


def _with_ir(project: Path, block: str, ir: dict, stamped: str) -> None:
    """Write an IR beside the deck and stamp `stamped` into the deck header as
    the digest it was rendered from."""
    d = project / "phase3" / "analog" / block
    (d / "topology.json").write_text(json.dumps(ir))
    sp = d / f"{block}.sp"
    sp.write_text(
        f"* _provenance: topology_ir=phase3/analog/{block}/topology.json "
        f"sha256={stamped}\n" + sp.read_text())


def _good_deck(project: Path, block: str) -> None:
    _block_list(project, [block])
    _sp(project, block,
        f".subckt {block} vdd vss vin vout\n"
        + "".join(f"xm{i} a{i} b{i} vss vss nfet w=1u l=1u\n"
                  for i in range(12))
        + f".ends {block}\n"
        + "* padding to clear the substance floor\n" * 6)


def test_a_deck_rendered_from_a_superseded_topology_fails(tmp_path: Path
                                                          ) -> None:
    import hashlib
    _good_deck(tmp_path, "ota")
    # stamped with the digest of an IR that is NOT the one now on disk
    _with_ir(tmp_path, "ota", _IR, hashlib.sha256(b"an older IR").hexdigest())
    r = _run(tmp_path)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert _rules(tmp_path)[1] == ["A3_NETLIST_STALE_VS_IR"]


def test_a_deck_current_with_its_topology_passes(tmp_path: Path) -> None:
    """THE CONTROL. Same fixture, same rule, digest matching — so the rule is
    firing on staleness and not on the presence of a stamp."""
    import hashlib
    _good_deck(tmp_path, "ota")
    body = json.dumps(_IR).encode()
    _with_ir(tmp_path, "ota", _IR, hashlib.sha256(body).hexdigest())
    r = _run(tmp_path)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "A3_NETLIST_STALE_VS_IR" not in _rules(tmp_path)[1]


def test_a_deck_that_records_no_topology_digest_is_left_alone(tmp_path: Path
                                                              ) -> None:
    """The second control. This rule can fire only on a stamp that DISAGREES,
    never on one that is absent — a hand-authored deck records no IR and must
    not be failed for it."""
    _good_deck(tmp_path, "ota")
    (tmp_path / "phase3/analog/ota/topology.json").write_text(json.dumps(_IR))
    r = _run(tmp_path)
    assert "A3_NETLIST_STALE_VS_IR" not in _rules(tmp_path)[1]
