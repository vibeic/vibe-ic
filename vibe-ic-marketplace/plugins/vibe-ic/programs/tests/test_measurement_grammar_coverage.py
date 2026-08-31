"""Steps 9 / 31 / 37 were INCOMPLETE for one reason: three artefact grammars.

`provenance_check --require-measured` asks `_mcp_measurement` for the tool's
third value; an absent record is UNMEASURED, which `flow_compliance_check`
disposes into the INCOMPLETE tier. The record is written by
`_runner_measurement`, whose dispatch table covered `.spef`, `.def` and the
KLayout report database and nothing else. The flow declares SIX
`--require-measured` clauses.

MEASURED at plugin v1.14.30 on the artefacts of run `spm_firstpass_f63410d`
(spm x gf180mcuD), one clause at a time, over its own 65-entry
provenance.jsonl::

    phase2/stage2/synth/netlist.v   [yosys,yosys-abc]        UNMEASURED   step 9
    phase3/stage3/pnr/routed.def    [openroad]               PASS         step 21
    reports/phase3/drc_signoff.rpt  [klayout,magic,svrfdrc]  PASS         step 31
    reports/phase3/lvs.rpt          [netgen,magic,klayout]   UNMEASURED   step 31
    phase3/stage4/gds/*.gds         [klayout,magic,openroad] UNMEASURED   step 37

`drc_signoff.rpt` and `lvs.rpt` share an extension and share the reader; the
KLayout database is read and the netgen text is not. The extension was never
the grammar, which is why `.rpt` is now a CHAIN.

THE SECOND GAP, and either one alone keeps the step INCOMPLETE. Only
`_log_invocation` ever attached the record; the runner's back-fill writers did
not, and `provenance_check._find_entry` binds an artefact to its MOST RECENT
declaring entry. On that run `reports/phase3/lvs.rpt` had four declaring
entries: the invocation at 08:07:43 and the one the check actually bound to, a
back-fill at 08:07:58. On `spm_manual_1.14.30` the same gap took step 21 and
step 31's DRC clause INCOMPLETE too, with the reader table unchanged.

THE LOAD-BEARING NEGATIVE CONTROLS in this file are the ones that must NOT
pass: an empty GDS library, a netlist with a module and no cell, and an LVS
report that enumerates circuits and never concludes are `measured: false` with
a hard class. Every reader here reads the ARTEFACT, never the fact that a
subprocess ran; a fix that asserted work happened because a writer fired would
satisfy the positive tests and fail all three of these.
"""
import json
import struct
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

# Imported defensively so the PRE-FIX tree still RUNS this file. A bare import
# would error at collection, and "1 error" grades nothing: a bidirectional
# control has to produce a countable FAIL on the old tree and a countable PASS
# on the new one.
try:
    import _runner_measurement as rm     # noqa: E402
except ImportError:                      # pragma: no cover - pre-fix tree
    rm = None


def _rm():
    assert rm is not None, "_runner_measurement is absent"
    return rm


def _w(d: Path, rel: str, text: str) -> Path:
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ── GDSII fixtures, built from the record grammar itself ──────────────────
def _rec(rtype: int, payload: bytes = b"") -> bytes:
    return struct.pack(">HH", 4 + len(payload), rtype) + payload


def _gds(elements: int = 1, structures: int = 1, endlib: bool = True) -> bytes:
    out = [_rec(0x0002, struct.pack(">h", 600)),          # HEADER
           _rec(0x0102, b"\x00" * 24),                    # BGNLIB
           _rec(0x0206, b"TOP\x00"),                      # LIBNAME
           _rec(0x0305, b"\x00" * 16)]                    # UNITS
    for s in range(structures):
        out.append(_rec(0x0502, b"\x00" * 24))            # BGNSTR
        # STRNAME padded to an EVEN length: GDSII record lengths always are,
        # and `gds_substance_check.parse_gds` rejects an odd one outright.
        _nm = f"C{s}".encode()
        out.append(_rec(0x0606, _nm + b"\x00" * (len(_nm) % 2)))   # STRNAME
        for _ in range(elements):
            out.append(_rec(0x0800))                      # BOUNDARY
            out.append(_rec(0x0D02, struct.pack(">h", 1)))  # LAYER
            out.append(_rec(0x1003, b"\x00" * 16))        # XY
            out.append(_rec(0x1100))                      # ENDEL
        out.append(_rec(0x0700))                          # ENDSTR
    if endlib:
        out.append(_rec(0x0400))                          # ENDLIB
    return b"".join(out)


# A yosys `write_verilog -noexpr -nostr -noattr` netlist, in the two shapes the
# shipped counter exists to handle: the escaped identifier and the block
# comment between the instance name and the paren.
_NETLIST = """\
module spm(clk, rst, x, y, p);
  input clk;
  wire clk;
  output p;
  \\$_NOT_  _03_ /* _05_ */ (
    .A(x),
    .Y(y)
  );
  \\$_DFF_P_  pr_reg /* _1087_ */ (
    .C(clk),
    .D(y),
    .Q(p)
  );
  $_NAND_ u1 (
    .A(x),
    .B(y),
    .Y(p)
  );
endmodule
"""

_NETLIST_NO_CELLS = """\
module spm(clk, rst);
  input clk;
  input rst;
  wire clk;
  wire rst;
endmodule
"""

_LVS_OK = """\
Subcircuit summary:
Circuit 1: spm                        |Circuit 2: spm
--------------------------------------|--------------------------------------
inv_1 (36)                            |inv_1 (36)
--------------------------------------------------------------------
Cell pin lists are equivalent.
Netlists match uniquely.

Final result: Circuits match uniquely.
"""

# The SAME grammar, opposite verdict. Must measure just as fully: an LVS run
# that proved a mismatch measured its design completely, and reporting it as
# unmeasured would hide a real defect behind "nobody looked".
_LVS_MISMATCH = """\
Subcircuit summary:
Circuit 1: spm                        |Circuit 2: spm
--------------------------------------|--------------------------------------
inv_1 (36)                            |inv_1 (35)
--------------------------------------------------------------------
Netlists do not match.

Final result: Netlists do not match.
"""

_LVS_NO_RESULT = """\
Subcircuit summary:
Circuit 1: spm                        |Circuit 2: spm
--------------------------------------|--------------------------------------
inv_1 (36)                            |inv_1 (36)
"""

_RDB = """\
<?xml version="1.0" encoding="utf-8"?>
<report-database>
 <generator>drc: script='/pdk/x.drc'</generator>
 <top-cell>spm</top-cell>
 <categories><category><name>V1.1</name></category></categories>
 <items><item><category>V1.1</category></item></items>
</report-database>
"""


# ── the table covers the six clauses the flow declares ────────────────────
def test_the_reader_table_covers_every_grammar_the_flow_demands():
    """The dispatch table is the contract's coverage, not a convenience."""
    exts = {e for e, _ in _rm()._READERS}
    for want in (".spef", ".def", ".v", ".gds", ".rpt"):
        assert want in exts, (
            f"no reader for {want}: every artefact of that grammar is "
            f"UNDECLARED, and its step is INCOMPLETE forever")


def test_the_netlist_counter_is_the_shipped_one_not_a_second_copy():
    """A counter written fresh for this change read 384 cells where the
    shipped one reads 449 on the same file, missing every
    `\\$_DFF_P_ pr_reg /* _1087_ */ (` line. If this import ever falls back to
    None the netlist rule is silently vacuous, which is worse than absent."""
    assert _rm()._count_cells is not None, (
        "synth_netlist_check.count_cell_instances did not import: the netlist "
        "reader can state nothing and step 9 stays INCOMPLETE silently")


# ── step 9: the Verilog gate netlist ──────────────────────────────────────
def test_a_mapped_netlist_is_measured_by_its_cell_instances(tmp_path):
    _w(tmp_path, "netlist.v", _NETLIST)
    rec = _rm().derive(tmp_path, "netlist.v", "yosys")
    assert rec is not None and rec["measured"] is True
    assert "3 cell instance(s)" in rec["operation"], rec["operation"]
    assert rec["stated_by"] == "runner-derived"


def test_a_netlist_with_a_module_and_no_cell_is_a_HARD_MISS(tmp_path):
    """NEGATIVE CONTROL. yosys exiting 0 having mapped nothing must not pass."""
    _w(tmp_path, "netlist.v", _NETLIST_NO_CELLS)
    rec = _rm().derive(tmp_path, "netlist.v", "yosys")
    assert rec is not None and rec["measured"] is False
    assert rec["not_measured_class"] == "TOOL_DID_NOT_RUN"


def test_a_v_file_that_is_not_a_module_states_nothing(tmp_path):
    """No rule must ADD NOTHING. Guessing here would turn a file this module
    cannot read into a claim about a tool."""
    _w(tmp_path, "notes.v", "this is not verilog\njust prose\n")
    assert _rm().derive(tmp_path, "notes.v", "yosys") is None


# ── step 31: the LVS comparison report ────────────────────────────────────
def test_an_lvs_report_that_concluded_is_measured(tmp_path):
    _w(tmp_path, "lvs.rpt", _LVS_OK)
    rec = _rm().derive(tmp_path, "lvs.rpt", "netgen")
    assert rec is not None and rec["measured"] is True
    assert "circuit pair(s) compared" in rec["operation"]


def test_a_MISMATCHING_lvs_report_is_measured_just_as_fully(tmp_path):
    """LOAD-BEARING. The reader must be polarity-neutral: a reader that only
    recognised the passing spelling would report every FAILING LVS as
    unmeasured, hiding a real defect behind "nobody looked"."""
    _w(tmp_path, "lvs.rpt", _LVS_MISMATCH)
    rec = _rm().derive(tmp_path, "lvs.rpt", "netgen")
    assert rec is not None and rec["measured"] is True, (
        "a proven mismatch is a complete measurement; only lvs_report_check "
        "owns the verdict")


def test_an_lvs_report_that_never_concluded_is_a_HARD_MISS(tmp_path):
    """NEGATIVE CONTROL. Circuits enumerated, comparator died: not a pass."""
    _w(tmp_path, "lvs.rpt", _LVS_NO_RESULT)
    rec = _rm().derive(tmp_path, "lvs.rpt", "netgen")
    assert rec is not None and rec["measured"] is False
    assert rec["not_measured_class"] == "TOOL_DID_NOT_RUN"


def test_the_rpt_chain_still_reads_a_klayout_database_first(tmp_path):
    """`.rpt` carries two grammars. The DRC database must keep its own reader,
    and it must win: it is the stricter of the two."""
    _w(tmp_path, "drc_signoff.rpt", _RDB)
    rec = _rm().derive(tmp_path, "drc_signoff.rpt", "klayout")
    assert rec is not None and rec["measured"] is True
    assert "rule-deck run" in rec["operation"], rec["operation"]


# ── step 37: the GDSII stream ─────────────────────────────────────────────
def test_a_gds_carrying_layout_is_measured(tmp_path):
    (tmp_path / "spm.gds").write_bytes(_gds(elements=3, structures=2))
    rec = _rm().derive(tmp_path, "spm.gds", "klayout")
    assert rec is not None and rec["measured"] is True
    assert "2 structure(s)" in rec["operation"] and "6 layout element" in \
        rec["operation"], rec["operation"]


def test_an_empty_gds_library_is_a_HARD_MISS(tmp_path):
    """NEGATIVE CONTROL, and the sharpest one. A streamer that exited 0 having
    read nothing writes a well-formed library with no structure. It hashes, it
    is named by a tool, and it contains no chip."""
    (tmp_path / "spm.gds").write_bytes(_gds(elements=0, structures=0))
    rec = _rm().derive(tmp_path, "spm.gds", "klayout")
    assert rec is not None and rec["measured"] is False
    assert rec["not_measured_class"] == "TOOL_DID_NOT_RUN"


def test_a_gds_with_no_ENDLIB_states_nothing(tmp_path):
    """A writer that died mid-stream. This module has no standing to say what
    that run did, so it must say nothing rather than guess either way."""
    (tmp_path / "spm.gds").write_bytes(_gds(elements=1, endlib=False))
    assert _rm().derive(tmp_path, "spm.gds", "klayout") is None


def test_bytes_that_are_not_a_gds_state_nothing(tmp_path):
    (tmp_path / "spm.gds").write_bytes(b"not a gdsii stream at all, really")
    assert _rm().derive(tmp_path, "spm.gds", "klayout") is None


def test_an_odd_record_length_states_nothing(tmp_path):
    """A GDSII record length is always even. A walk that advanced past an odd
    one would publish a count over bytes it did not understand — found by the
    cross-check below, which rejected a fixture this walk had counted."""
    bad = bytearray(_gds(elements=1))
    struct.pack_into(">H", bad, 0, 5)      # HEADER length 4 -> 5
    (tmp_path / "spm.gds").write_bytes(bytes(bad))
    assert _rm().derive(tmp_path, "spm.gds", "klayout") is None


def test_the_gds_walk_agrees_with_the_independent_whole_file_parser(tmp_path):
    """CROSS-CHECK against a DIFFERENT implementation. A number this fix
    produces and then grades itself on is not a measurement.
    On the real spm sign-off GDS both read 49 structures / 29748 elements."""
    gds_substance_check = pytest.importorskip("gds_substance_check")
    data = _gds(elements=4, structures=3)
    (tmp_path / "spm.gds").write_bytes(data)
    _findings, stats = gds_substance_check.parse_gds(data)
    rec = _rm().derive(tmp_path, "spm.gds", "klayout")
    assert rec is not None
    assert f"{stats.structures} structure(s)" in rec["operation"]
    assert f"{stats.elements} layout element(s)" in rec["operation"]


# ── the second gap: attach(), at every writer ─────────────────────────────
def test_attach_puts_the_record_on_an_entry_that_has_none(tmp_path):
    (tmp_path / "spm.gds").write_bytes(_gds(elements=2))
    entry = {"tool": "klayout", "exit_code": 0, "reconstructed": True,
             "outputs": {"spm.gds": "sha256:x"}}
    _rm().attach(tmp_path, entry)
    assert entry["measurement"]["measured"] is True


def test_attach_never_overwrites_a_record_that_is_already_there(tmp_path):
    (tmp_path / "spm.gds").write_bytes(_gds(elements=2))
    entry = {"tool": "klayout", "outputs": {"spm.gds": "sha256:x"},
             "measurement": {"schema": "mcp-eda/measurement/1",
                             "measured": False, "sentinel": True}}
    _rm().attach(tmp_path, entry)
    assert entry["measurement"].get("sentinel") is True, (
        "a tool's own record outranks a derived one and must survive")


def test_attach_on_an_EMPTY_gds_states_the_miss_not_a_pass(tmp_path):
    """THE ANTI-CHEAT for the writer half. A back-fill is sound only because it
    reads the ARTEFACT. Wired to the fact that a writer fired, it would assert
    a stream-out over an empty library."""
    (tmp_path / "spm.gds").write_bytes(_gds(elements=0, structures=0))
    entry = {"tool": "klayout", "outputs": {"spm.gds": "sha256:x"}}
    _rm().attach(tmp_path, entry)
    assert entry["measurement"]["measured"] is False
    assert entry["measurement"]["not_measured_class"] == "TOOL_DID_NOT_RUN"


def test_attach_adds_nothing_when_no_reader_has_a_rule(tmp_path):
    (tmp_path / "x.unknown").write_text("whatever")
    entry = {"tool": "klayout", "outputs": {"x.unknown": "sha256:x"}}
    _rm().attach(tmp_path, entry)
    assert "measurement" not in entry


def test_attach_never_raises_on_a_malformed_entry(tmp_path):
    """Provenance bookkeeping must never break a run."""
    for bad in (None, [], {"outputs": "not a dict"}, {"tool": None}):
        _rm().attach(tmp_path, bad)


# ── driven end to end through the runner's own back-fill writer ───────────
def test_the_pv_backfill_writer_attaches_the_record(tmp_path):
    """DRIVEN, not asserted. `_v1_6_620_append_pv_signoff_provenance` is the
    writer whose records superseded the invocation records that carried the
    reading — on the real run, lvs.rpt's binding entry was this one."""
    P = pytest.importorskip("phase3_one_shot_runner")
    fn = getattr(P, "_v1_6_620_append_pv_signoff_provenance", None)
    if fn is None:
        pytest.skip("writer not present in this tree")
    _w(tmp_path, "reports/phase3/lvs.rpt", _LVS_OK)
    (tmp_path / "phase3/stage4/gds").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3/stage4/gds/spm.gds").write_bytes(_gds(elements=2))
    (tmp_path / "provenance.jsonl").write_text("")

    declared = fn(tmp_path, "spm")
    assert declared, "the writer declared nothing; the fixture is wrong"
    records = [json.loads(l) for l in
               (tmp_path / "provenance.jsonl").read_text().splitlines() if l.strip()]
    by_out = {rel: r for r in records for rel in (r.get("outputs") or {})}
    for rel in ("reports/phase3/lvs.rpt", "phase3/stage4/gds/spm.gds"):
        assert rel in by_out, f"{rel} was not declared at all"
        meas = by_out[rel].get("measurement")
        assert meas is not None and meas.get("measured") is True, (
            f"the back-fill for {rel} carries no measurement, so it "
            f"supersedes any invocation record that did and the step stays "
            f"INCOMPLETE")
