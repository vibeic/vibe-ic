#!/usr/bin/env python3
"""D9: the reused-IP manifest emits the side-granular pad pairs the design's
own records decide, and verifies every pair the pad side reads.

MEASURED on subservient x gf180mcuD (v1.25.64): both manifest emitters wrote
`renamed_interfaces: []`, so after D2 step 15.5ic refused PAD_GROUP_UNRESOLVED
and four pairs had to be authored by hand. Here, program first:
  R1 read/write split: `o_memory_waddr` = {memory, w+addr} against the
     document's `o_memory_addr` = {memory, addr}; same-direction tie-break;
  R2 sole remaining side: `o_memory_wen` shares only {memory}, and after R1
     the only unexplained document members of that family are on S.
A port no rule decides is listed UNRESOLVED for catalog-glue-author, whose
pairs `--check` verifies (exact-atom rule, implemented ports) and refuses with
a reason. An authored list is never rewritten (the landed merge contract).

REVIEW WAVE 2 (BLOCKER, both lenses): the derived pairs used to go into
`renamed_interfaces`, which `spec_conformance_check` and
`l9_rtl_pin_consistency_check` read as DECLARED RENAMES, so the emitter relaxed
both gates by itself on every reused IP with a pad placement. An R2 pair is a
side, not a rename. The pairs now go to `derived_pad_pairs`, read only by
`_l_doc_pad_placement.declared_renames`; `renamed_interfaces` stays authored.

Also here: step 2's `aw = $clog2(memsize)` width, which masked the pad budget
as UNDECIDED (ZERO_DENOMINATOR) on the same run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
PROGRAMS = TESTS.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(TESTS))

from _staged_top_module import EXTRACTION_STRATEGY as STAGED  # noqa: E402

DOC = """# L3 — External Interface

The I/O cell library is delegated to the PDK i/o pad defaults.

## Physical Pad Placement

| Pad side | signals |
|---|---|
| **North (N)** | memory data bus |
| **South (S)** | memory addr + control(we / cyc) |
| **East (E)** | `clk` / `rst` |
| **West (W)** | status pin(s) |
"""


def _p(name, direction, staged, width=1):
    """An L9 top_ports entry as phase 1 writes it: a staged-top port carries
    the staged-top harvest's extraction strategy (D2's `accept_renames` reads
    that as the RTL speaking, not the document)."""
    port = {"name": name, "direction": direction, "width": width,
            "declared_by_staged_top": staged}
    if staged:
        port["extraction_strategy"] = STAGED
    return port


IMPL = [_p("clk", "input", True), _p("rst", "input", True),
        _p("o_status", "output", True),
        _p("o_memory_waddr", "output", True, 3),
        _p("o_memory_wdata", "output", True, 2),
        _p("o_memory_wen", "output", True),
        _p("o_memory_raddr", "output", True, 3),
        _p("i_memory_rdata", "input", True, 2),
        _p("o_memory_ren", "output", True)]
DOC_ONLY = [_p("o_memory_data", "output", False, 2),
            _p("i_memory_data", "input", False, 2),
            _p("o_memory_addr", "output", False, 3),
            _p("o_memory_we", "output", False),
            _p("o_memory_cyc", "output", False)]

EXPECTED = [
    {"l9": ["i_memory_data"], "rtl": ["i_memory_rdata"]},
    {"l9": ["o_memory_addr"], "rtl": ["o_memory_raddr", "o_memory_waddr"]},
    {"l9": ["o_memory_cyc", "o_memory_we"],
     "rtl": ["o_memory_ren", "o_memory_wen"]},
    {"l9": ["o_memory_data"], "rtl": ["o_memory_wdata"]},
]


def _verilog(ports):
    decl = []
    for p in ports:
        rng = f"[{p['width'] - 1}:0] " if p["width"] > 1 else ""
        decl.append(f"  {p['direction']} wire {rng}{p['name']}")
    return "module core (\n" + ",\n".join(decl) + "\n);\nendmodule\n"


def _project(tmp_path, *, impl=IMPL, doc_only=DOC_ONLY, doc=DOC,
             manifest=None):
    proj = tmp_path / "proj"
    (proj / "input/docs").mkdir(parents=True)
    if doc is not None:
        (proj / "input/docs/L3_external_interface.md").write_text(doc)
    (proj / "phase1/generated_docs").mkdir(parents=True)
    (proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "core", "top_ports": impl + doc_only}))
    (proj / "input/vendor_rtl").mkdir(parents=True)
    (proj / "input/vendor_rtl/core.v").write_text(_verilog(impl))
    if manifest is not None:
        rtl = proj / "phase2/stage1/rtl"
        rtl.mkdir(parents=True)
        (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest))
    return proj




def _lr(pairs):
    return [{"l9": p["l9"], "rtl": p["rtl"]} for p in pairs]


def _check(proj, capsys):
    import renamed_interface_derive as RID
    rc = RID.main([str(proj), "--check"])
    return rc, json.loads(capsys.readouterr().out)


# --------------------------------------------------------------------------- #
# program first — RED on main (the emitter writes [])
# --------------------------------------------------------------------------- #




def test_the_consume_emitter_derives_them_too(tmp_path):
    import reused_ip_rtl_consume as C
    proj = _project(tmp_path)
    src = proj / "input/design_src/verilog/rtl"
    src.mkdir(parents=True)
    (src / "core.v").write_text((proj / "input/vendor_rtl/core.v").read_text())
    (proj / "input/vendor_rtl/core.v").unlink()
    (proj / "input/vendor_rtl").rmdir()
    C.consume_reused_ip_rtl(proj)
    mf = json.loads((proj / "phase2/stage1/rtl/SOURCE_MANIFEST.json").read_text())
    assert _lr(mf["derived_pad_pairs"]) == EXPECTED
    assert mf["renamed_interfaces"] == []






# --------------------------------------------------------------------------- #
# AI backup: an undecided port is named, and an authored pair is verified
# --------------------------------------------------------------------------- #
_NO_DATA_IMPL = [p for p in IMPL if "data" not in p["name"]] + [
    _p("o_memory_ack", "output", True)]






@pytest.mark.parametrize("pair,why", [
    ({"l9": ["o_memory_data", "o_memory_addr"],
      "rtl": ["o_memory_wen", "o_memory_ren", "o_memory_ack"]}, "2 groups"),
    ({"l9": ["o_memory_we"], "rtl": ["o_memory_ack", "o_memory_nope"]},
     "not ports of the implemented top"),
    ({"l9": ["o_memory_bogus"], "rtl": ["o_memory_ack"]},
     "are not L9 top_ports"),
    ({"l9": ["clk"], "rtl": ["o_memory_ack"]},
     "fall in no group row"),
], ids=["spans-groups", "rtl-not-implemented", "l9-unknown", "no-group"])
def test_an_unverifiable_authored_pair_is_refused_with_its_reason(
        tmp_path, capsys, pair, why):
    proj = _project(tmp_path, impl=_NO_DATA_IMPL, manifest={
        "reused_ip": True, "renamed_interfaces": [
            {"l9": ["o_memory_addr"],
             "rtl": ["o_memory_raddr", "o_memory_waddr"]},
            {"l9": ["o_memory_we", "o_memory_cyc"],
             "rtl": ["o_memory_wen", "o_memory_ren"]}, pair]})
    rc, res = _check(proj, capsys)
    assert rc == 1
    refused = [v for v in res["pairs"] if v["verdict"] == "REFUSED"]
    assert len(refused) == 1 and why in refused[0]["reason"], refused


def test_an_all_carrier_word_name_carries_no_side(tmp_path, capsys):
    """`o_bus` has no semantic atom: it is in no group, never in every one."""
    proj = _project(tmp_path, impl=_NO_DATA_IMPL,
                    doc_only=DOC_ONLY + [_p("o_bus", "output", False)],
                    manifest={"reused_ip": True, "renamed_interfaces": [
                        {"l9": ["o_bus"], "rtl": ["o_memory_ack"]}]})
    rc, res = _check(proj, capsys)
    assert rc == 1 and "fall in no group row" in res["pairs"][0]["reason"]


# --------------------------------------------------------------------------- #
# the question does not arise: the landed empty scaffold is unchanged
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# step 2: an exact expression default is a width, not ZERO_DENOMINATOR
# --------------------------------------------------------------------------- #
_CLOG2_RTL = ("module widget #(parameter memsize = 1024,\n"
              "  parameter aw = $clog2(memsize))\n"
              " (input wire i_clk, input wire i_rst,\n"
              "  output wire [aw-1:0] o_sensor_addr, output wire [7:0] o_sensor_data,\n"
              "  input wire [7:0] i_sensor_data, output wire o_sensor_we,\n"
              "  output wire o_sensor_cyc, output wire o_gpio);\n"
              "endmodule\n")


def test_step2_resolves_a_clog2_width_and_decides():
    import test_r0915101_a_die_budgets_against_its_own_pad_ring as R0915
    rc, rep = R0915._run(R0915._project(rtl=_CLOG2_RTL))
    assert (rc, rep["verdict"]) == (0, "FITS"), rep.get("reason")
    assert rep["own_ring_arithmetic"]["signal_pads_owed"] == 29
    assert rep["params_from_top_module_exact_expressions"]["aw"] == {
        "value": 10, "expression": "$clog2(memsize)",
        "operand": {"memsize": 1024}}


def test_step2_an_inexact_expression_stays_undecided():
    import test_r0915101_a_die_budgets_against_its_own_pad_ring as R0915
    rtl = _CLOG2_RTL.replace("$clog2(memsize)", "memsize / 100")
    rc, rep = R0915._run(R0915._project(rtl=rtl))
    assert (rc, rep["verdict"]) == (2, "UNDECIDED")
    assert "o_sensor_addr" in rep["unresolved_width_ports"]


@pytest.mark.parametrize("n,want", [(0, 0), (1, 0), (2, 1), (512, 9),
                                    (513, 10), (1024, 10)])
def test_clog2_is_the_ieee_definition(n, want):
    import slot_pad_budget_check as S
    assert S._clog2(n) == want


# --------------------------------------------------------------------------- #
# the runner's hand-off to catalog-glue-author names what it still owes
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("impl,owed", [(_NO_DATA_IMPL, True), (IMPL, False)],
                         ids=["unresolved", "all-derived"])
def test_the_waive_names_the_ports_the_glue_author_must_pair(
        tmp_path, impl, owed):
    import design_one_shot_runner as R
    proj = _project(tmp_path, impl=impl)
    res = R.step_rtl_gen(proj, "digital_cmd_driven")
    assert res.extras.get("fallback_skill") == "catalog-glue-author"
    said = "renamed_interfaces: 3 implemented port(s)" in res.detail
    assert said is owed, res.detail[-600:]
    if owed:
        assert "o_memory_ack" in res.detail and "--check" in res.detail



# --------------------------------------------------------------------------- #
# D2's acceptance rule: a derived pair gives a side only if phase 2 accepts it
# --------------------------------------------------------------------------- #


def test_an_authored_pair_the_acceptance_rule_rejects_is_refused(
        tmp_path, capsys):
    proj = _project(tmp_path, impl=_NO_DATA_IMPL, manifest={
        "reused_ip": True, "renamed_interfaces": [
            {"l9": ["o_memory_addr"],
             "rtl": ["o_memory_raddr", "o_memory_waddr"]},
            {"l9": ["o_memory_we", "o_memory_cyc"],
             "rtl": ["o_memory_wen", "o_memory_ren"]},
            # same group, but i_memory_data is an INPUT and o_memory_ack an output
            {"l9": ["i_memory_data"], "rtl": ["o_memory_ack"]}]})
    rc, res = _check(proj, capsys)
    assert rc == 1
    refused = [v for v in res["pairs"] if v["verdict"] == "REFUSED"]
    assert len(refused) == 1 and "is output, l9" in refused[0]["reason"]




# --------------------------------------------------------------------------- #
# REVIEW WAVE 2 BLOCKER: a derived pair is a SIDE, never a declared rename
# --------------------------------------------------------------------------- #
#: The keys this program owns. Removing them leaves exactly what the landed
#: emitter wrote before D9: the GAP-E2E-8 empty scaffold.
_PROGRAM_KEYS = ("derived_pad_pairs", "renamed_interfaces_derivation",
                 "renamed_interfaces_check")














# --------------------------------------------------------------------------- #
# --check: every implemented port ends on EXACTLY one side (review MINOR)
# --------------------------------------------------------------------------- #


def test_check_fails_a_port_two_verified_pairs_put_on_two_sides(
        tmp_path, capsys):
    """RED on 3c5697945. Each pair verifies on its own; together they put
    `o_memory_ack` on N and on S. "Covered" is not "exactly one side"."""
    doc_only = [q if q["name"] != "o_memory_data" else
                _p("o_memory_data", "output", False, 1) for q in DOC_ONLY]
    proj = _project(tmp_path, impl=_NO_DATA_IMPL, doc_only=doc_only, manifest={
        "reused_ip": True, "renamed_interfaces": [
            {"l9": ["o_memory_addr"],
             "rtl": ["o_memory_raddr", "o_memory_waddr"]},
            {"l9": ["o_memory_we", "o_memory_cyc"],
             "rtl": ["o_memory_wen", "o_memory_ren", "o_memory_ack"]},
            {"l9": ["o_memory_data"], "rtl": ["o_memory_ack"]}]})
    rc, res = _check(proj, capsys)
    assert all(v["verdict"] == "VERIFIED" for v in res["pairs"]), res["pairs"]
    assert rc == 1 and res["verdict"] == "FAIL"
    assert res["nets_on_two_sides"] == {"o_memory_ack": ["N", "S"]}


def test_a_port_an_exact_row_names_is_placed_even_if_its_range_is_open(
        tmp_path):
    """RED on 3c5697945. W names `o_memory_waddr[AW-1:0]` with AW undeclared.
    The port is still the document's W port; deriving it onto S would put it
    on two sides the moment AW is declared."""
    import renamed_interface_derive as RID
    doc = DOC.replace("| **West (W)** | status pin(s) |",
                      "| **West (W)** | `o_status` / `o_memory_waddr[AW-1:0]` |")
    assert doc != DOC
    d = RID.derive(_project(tmp_path, doc=doc))
    assert all("o_memory_waddr" not in p["rtl"] for p in d["pairs"]), d["pairs"]
    assert "o_memory_waddr" not in d["unplaced_implemented_ports"]


# --------------------------------------------------------------------------- #
# re-emit refreshes the derivation, and the runner's note reads it
# --------------------------------------------------------------------------- #


def _waive(proj):
    import design_one_shot_runner as R
    res = R.step_rtl_gen(proj, "digital_cmd_driven")
    assert res.extras.get("fallback_skill") == "catalog-glue-author"
    return res.detail


def test_the_waive_does_not_name_a_port_the_author_has_since_paired(tmp_path):
    """RED on 3c5697945: the note read the first run's derivation, so it kept
    naming o_memory_ack/ren/wen after the author paired them."""
    proj = _project(tmp_path, impl=_NO_DATA_IMPL)
    assert "renamed_interfaces: 3 implemented port(s)" in _waive(proj)
    mf_path = proj / "phase2/stage1/rtl/SOURCE_MANIFEST.json"
    mf = json.loads(mf_path.read_text())
    mf["renamed_interfaces"] = [
        {"l9": ["o_memory_we", "o_memory_cyc"],
         "rtl": ["o_memory_wen", "o_memory_ren", "o_memory_ack"]}]
    mf_path.write_text(json.dumps(mf))
    detail = _waive(proj)
    assert "implemented port(s) have" not in detail, detail[-600:]
    assert "o_memory_ack" not in detail


def test_the_waive_names_a_refused_authored_pair(tmp_path):
    """RED on 3c5697945: a REFUSED authored pair sat in the manifest and the
    hand-off said nothing until 15.5ic refused."""
    proj = _project(tmp_path, impl=_NO_DATA_IMPL)
    _waive(proj)
    mf_path = proj / "phase2/stage1/rtl/SOURCE_MANIFEST.json"
    mf = json.loads(mf_path.read_text())
    mf["renamed_interfaces"] = [{"l9": ["i_memory_data"],
                                 "rtl": ["o_memory_ack"]}]
    mf_path.write_text(json.dumps(mf))
    detail = _waive(proj)
    assert "REFUSED" in detail and "o_memory_ack" in detail, detail[-600:]


def test_the_waive_names_a_derivation_that_did_not_run(tmp_path, monkeypatch):
    """RED on 3c5697945: an emitter exception was recorded as NOT_MEASURED in
    the manifest and nowhere in the hand-off."""
    import renamed_interface_derive as RID

    def _boom(project, mf):
        raise RuntimeError("derivation unavailable")

    monkeypatch.setattr(RID, "apply_to_manifest", _boom)
    detail = _waive(_project(tmp_path))
    assert "not measured" in detail and "derivation unavailable" in detail, \
        detail[-600:]


# --------------------------------------------------------------------------- #
# REVIEW WAVE 4b: sides are per BIT NET, as 15.5ic places them
# --------------------------------------------------------------------------- #
_IMPL_STATUS4 = [q if q["name"] != "o_status" else
                 _p("o_status", "output", True, 4) for q in IMPL]










# --------------------------------------------------------------------------- #
# an author's copy stays; only what an earlier version wrote is moved
# --------------------------------------------------------------------------- #


def test_the_waive_names_the_pairs_it_moved(tmp_path):
    """RED on 6df205cdc: the move was recorded only inside the manifest."""
    proj = _project(tmp_path)
    legacy = [dict(p, derived_by="renamed_interface_derive") for p in EXPECTED]
    rtl = proj / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps(
        {"reused_ip": True, "renamed_interfaces": legacy}))
    detail = _waive(proj)
    assert "moved 4 pair(s)" in detail, detail[-900:]


# --------------------------------------------------------------------------- #
# --check reads authored pairs the way the pad side does (all rename keys)
# --------------------------------------------------------------------------- #




# --------------------------------------------------------------------------- #
# "could not read the placement" is not "the question does not arise"
# --------------------------------------------------------------------------- #


def test_the_waive_says_a_reported_gap_keeps_rc_1(tmp_path):
    """RED on 6df205cdc: the note asked for rc 0 even for a port with no
    document counterpart, where only an invented pair reaches rc 0."""
    detail = _waive(_project(tmp_path, impl=_NO_DATA_IMPL))
    assert "keeps rc 1" in detail, detail[-900:]
    assert "must exit 0" not in detail




# --------------------------------------------------------------------------- #
# REVIEW WAVE 6: an unknown bit extent is never a definite verdict
# --------------------------------------------------------------------------- #





















# Public issue3118: frozen literal inputs, real local pinned source publication,
# then the public CLI and the shared step-2/15.5ic consumer. source57 has no
# typed-interface ingestion API: the loader double below supplies ONLY the
# caller's authored declaration at that missing seam. Official source pulls,
# independent pin verification, derived publication and output hashes are real.
# This is SOURCE_CONTROL; it does not qualify the pending typed-input route.




def _public_pad_ports(project):
    import renamed_interface_derive as RID
    top, l9 = RID._l9(project)
    return RID._implemented_ports(project, top, l9)[0]


def _public_pad_cli(project):
    import subprocess
    cp = subprocess.run([sys.executable, '-B', str(PROGRAMS / 'renamed_interface_derive.py'),
                         str(project), '--check', '--json', str(project.parent / 'public-check.json')],
                        capture_output=True, text=True)
    (project.parent / 'public-check.stdout').write_text(cp.stdout)
    (project.parent / 'public-check.stderr').write_text(cp.stderr)
    return {'rc': cp.returncode, **json.loads(cp.stdout)}
