"""A receipt that cannot name the layout it read certifies nothing.

MEASURED on the real IC (SUB2AB2, spm x gf180mcuD on 0.3.67). The magic deck
RAN and found 0 violations — and its receipt read:

    passed               : False
    DRC_SIGNOFF_NO_LAYOUT_EVIDENCE
    layout_evidence_tier : none
    layout_evidence_witness: "recorded DRC report hash differs from current report"
    design_binding       : NOT_DETERMINED
    producers[0].deck    : null
    producers[0].top_cell: null
    categories_found     : ['spacing', 'width']   (+4 DRC_CATEGORY_PRESENT warnings)

on a run whose GDS was sitting at phase3/stage3/pnr all along. Four separate
defects, all mine, all in the receipt rather than in the check:

(1) THE REPORT WAS STILL BEING EDITED AFTER ITS PROVENANCE WAS TAKEN.
    `_docker_exec` records the sha256 of every declared OUTPUT at the moment
    the tool exits; the runner then APPENDED the deck's rule list. So
    `_recorded_layout_evidence` found the invocation, matched the tool, and
    refused on the digest — and with the invocation route gone the on-disk
    fallback had nothing to match either. The rule list is now written BY THE
    DECK, before magic exits, so the bytes whose digest was recorded are the
    bytes that ship.

(2) THE TRANSCRIPT NAMED NO DESIGN in any dialect `eda_report_audit` knows, so
    `design_binding` could not be decided. It now carries the runner's own
    `measured_design:` stamp — the dialect that exists for exactly this, "the
    runner asserting what it fed the tool" — and the sha256 of the layout it
    was handed.

(3) THE PRODUCER DECLARED NEITHER DECK NOR TOP CELL. A KLayout report database
    declares `<generator>` and `<top-cell>` and the classifier reads both; a
    Magic transcript declared neither. It now states `tech file:` and
    `top cell:`, taken from the TOOL (`tech filename`, and the cell it
    loaded), and the classifier reads them.

(4) FOUR CATEGORIES WERE LEFT UNDECIDABLE. The audit could not tell whether the
    deck HAS a density / antenna / via / enclosure rule. It does not — measured
    from the technology's own rule list, which the transcript now carries: of
    155 rule descriptions, 61 name a spacing rule, 26 a width rule, and ZERO
    name any of the other four.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402
import _signoff_drc_format as SDF  # noqa: E402
import eda_report_audit as A  # noqa: E402
import l24_signoff_evidence_backed_check as L24  # noqa: E402
from _finished_gds_fixture import publish_finished_gds

#: The transcript the deck wrote on the real IC, as evidence and as a fixture.
#: Absent on a host that has not been handed it; the tests that need it skip
#: rather than assert on a file they cannot see.
_REAL = Path("/tmp/icsub2_sub2ab2_magic/drc_signoff_magic.rpt")
needs_real = pytest.mark.skipif(not _REAL.is_file(),
                                reason="the real-IC transcript is not on this host")

_STUBS = r"""
proc drc {args} {
  switch -- [lindex $args 0] {
    listall { return {{Rule A spacing} {{0 0 1 1}}} }
    list    { return 0 }
    default { return {} }
  }
}
proc gds {args} { return }
proc load {args} { return }
proc select {args} { return }
proc box {args} { return "0 0 10 10" }
proc tech {args} {
  switch -- [lindex $args 0] {
    name     { return TECHNAME }
    filename { return TECHFILE }
    version  { return 1.2.3 }
  }
  return {}
}
proc quit {args} { exit 0 }
"""

_TECH = ('tech\n format 32\nend\n\n'
         'drc\n'
         ' width  m1 23 "Metal1 width < 0.23um (M1.1)"\n'
         ' spacing m1 m1 23 touching_ok "Metal1 spacing < 0.23um (M1.2)"\n'
         ' edge4way m2 x 1 "s"\n'
         'end\n\n'
         'extract\n style "ngspice extraction style for this technology"\nend\n')


def _run_deck(tmp_path, sha="ab" * 32, top="chip_top"):
    tclsh = shutil.which("tclsh")
    if tclsh is None:                                    # pragma: no cover
        pytest.skip("tclsh not installed")
    tech = tmp_path / "t.tech"
    tech.write_text(_TECH)
    rpt = tmp_path / "out.rpt"
    script = tmp_path / "deck.tcl"
    script.write_text(_STUBS.replace("TECHFILE", str(tech))
                      + R._magic_signoff_drc_tcl("/c/design.gds", top,
                                                 str(rpt), gds_sha256=sha))
    cp = subprocess.run([tclsh, str(script)], capture_output=True, text=True,
                        cwd=str(tmp_path))
    assert cp.returncode == 0, cp.stderr
    assert "invalid command name" not in (cp.stdout + cp.stderr)
    return rpt.read_text()


# ── (1) the report is FINAL when the tool exits ───────────────────────────

def test_driven_the_deck_writes_its_own_rule_list_before_it_exits(tmp_path):
    text = _run_deck(tmp_path)
    assert "DECK_RULE: Metal1 width < 0.23um (M1.1)" in text
    assert "DECK_RULE: Metal1 spacing < 0.23um (M1.2)" in text
    assert "(drc section): 2" in text
    # nothing outside the `drc` section is taken for a rule
    assert "ngspice" not in text
    # and the COUNT trailer is still LAST, so a truncated report is still
    # detectable as truncated
    assert text.rstrip().splitlines()[-1].startswith("COUNT:")


def test_the_runner_never_writes_to_the_report_after_the_tool_exits():
    """The defect, as a property of the source: an append here makes every
    recorded output digest stale and the invocation binding unmatchable."""
    src = Path(R.__file__).read_text()
    i = src.index("def _run_magic_signoff_drc")
    body = src[i:src.index("\ndef ", i + 10)]
    assert 'out_rpt.open("a")' not in body, body[body.find('open("a"') - 200:]
    assert ".write_text(" not in body.split("out_rpt")[-1][:200]


def test_a_technology_the_deck_cannot_open_is_named_not_silent(tmp_path):
    """The other direction: no rule list, and the report SAYS it has none."""
    tclsh = shutil.which("tclsh")
    if tclsh is None:                                    # pragma: no cover
        pytest.skip("tclsh not installed")
    rpt = tmp_path / "out.rpt"
    script = tmp_path / "deck.tcl"
    script.write_text(_STUBS.replace("TECHFILE", str(tmp_path / "absent.tech"))
                      + R._magic_signoff_drc_tcl("/c/d.gds", "chip_top",
                                                 str(rpt), gds_sha256="cd" * 32))
    subprocess.run([tclsh, str(script)], capture_output=True, text=True)
    text = rpt.read_text()
    assert "DECK_RULES_UNREADABLE:" in text
    assert "DECK_RULE: " not in text
    assert text.rstrip().splitlines()[-1].startswith("COUNT:")


# ── (2) the transcript names its design and its layout ────────────────────

def test_driven_the_transcript_states_the_design_and_the_layout_digest(tmp_path):
    text = _run_deck(tmp_path, sha="ab" * 32)
    assert "measured_design: chip_top" in text
    assert f"layout sha256: {'ab' * 32}" in text
    assert A._report_declared_designs(text) == {"chip_top"}


def test_without_the_stamp_the_design_is_undecidable():
    """THE NEGATIVE CONTROL, and it is the real artefact: the transcript the
    deck wrote on the real IC states no design at all, which is why that
    receipt read design_binding NOT_DETERMINED."""
    if not _REAL.is_file():
        pytest.skip("the real-IC transcript is not on this host")
    assert A._report_declared_designs(_REAL.read_text()) == set()


def test_the_runner_hands_the_deck_the_digest_of_the_gds_it_read(tmp_path,
                                                               monkeypatch):
    """THE WIRING, not just the parameter. The digest the deck states must be
    the one the runner took of the very file it passed as the layout — a call
    site that dropped it would leave the transcript saying `(not computed)`
    while the runner had the number in hand."""
    proj = tmp_path / "p"
    (proj / "reports" / "phase3").mkdir(parents=True)
    (proj / "phase3" / "reports").mkdir(parents=True)
    gds = tmp_path / "chip_top.gds"
    gds.write_bytes(b"not a real stream, but a real digest\n")
    want = hashlib.sha256(gds.read_bytes()).hexdigest()

    seen = {}

    def fake_exec(container, cmd, **kw):
        seen["cmd"] = cmd
        return (0, "", "")

    monkeypatch.setattr(R, "_docker_exec", fake_exec)
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: True)
    monkeypatch.setattr(R, "_to_container_path", lambda s_, c: s_)
    monkeypatch.setattr(R, "_pdk_magicrc", lambda pdk: "/pdk/x.magicrc")

    row = R._run_magic_signoff_drc(proj, "chip_top", "chip_top", object(),
                                   "c", gds)
    tcl = (proj / "phase3" / "reports" / "drc_signoff_magic.tcl").read_text()
    assert f"layout sha256: {want}" in tcl
    assert row["layout_sha256"] == want, row
    # and the deck really was the thing invoked
    assert "magic -dnull -noconsole" in seen["cmd"]


def test_a_digest_that_could_not_be_taken_is_said_so_not_faked():
    t = R._magic_signoff_drc_tcl("/c/d.gds", "top", "/c/o.rpt", gds_sha256="")
    assert "layout sha256: (not computed)" in t


# ── (3) the producer declares its deck and its top cell ───────────────────

@needs_real
def test_the_real_transcript_now_classifies_with_a_deck_and_a_top_cell():
    p = SDF.classify_file(_REAL)
    assert p.kind == SDF.MAGIC
    assert p.is_signoff_deck is True
    assert p.top_cell == "chip_top", p.top_cell
    assert p.deck and p.deck.endswith(".tech"), p.deck


def test_a_magic_transcript_without_them_still_classifies_as_magic(tmp_path):
    """OVER-BREADTH CONTROL: a transcript from anywhere else is read exactly
    as it was before — the two fields are additions, not requirements."""
    q = tmp_path / "other.rpt"
    q.write_text("Magic 8.3\ndrc check\n[INFO] COUNT: 0\n")
    p = SDF.classify_file(q)
    assert p.kind == SDF.MAGIC
    assert p.is_signoff_deck is True
    assert p.deck is None and p.top_cell is None


def test_the_router_is_still_not_a_magic_producer(tmp_path):
    q = tmp_path / "r.rpt"
    q.write_text("top cell: chip_top\ntech file: /pdk/x.tech\n"
                 "[INFO DRT-0702] Post-route verification: 0 violation(s).\n")
    assert SDF.classify_file(q).kind != SDF.MAGIC


# ── (4) which classes the deck HAS, and which it genuinely has not ────────

@needs_real
def test_the_four_undecidable_categories_are_four_the_deck_has_no_rule_for():
    """THE MEASUREMENT the warnings were asking for, taken from the deck's own
    rule list as the real transcript carries it."""
    rules = [m.group(1) for m in
             re.finditer(r"^DECK_RULE:\s*(.+?)\s*$", _REAL.read_text(), re.M)]
    assert len(rules) == 155, len(rules)
    classes = R._magic_deck_rule_classes(rules)
    assert classes == {"spacing": 61, "width": 26, "density": 0,
                       "antenna": 0, "via": 0, "enclosure": 0}, classes
    absent = sorted(k for k, v in classes.items() if v == 0)
    assert absent == ["antenna", "density", "enclosure", "via"], absent


def test_every_audited_class_is_keyed_even_at_zero():
    classes = R._magic_deck_rule_classes(["Metal1 width < 0.23um (M1.1)"])
    assert set(classes) == {n for n, _rx in R._MAGIC_AUDIT_CATEGORIES}
    assert classes["width"] == 1 and classes["antenna"] == 0


def test_the_disclosed_classes_are_the_audits_own_six():
    """AGREEING WITH THE AUDIT IS THE POINT — this table answers that table's
    question — so a drift there must break here rather than go unnoticed."""
    src = (PROGRAMS / "eda_report_audit.py").read_text()
    block = src[src.index("categories_re = {"):]
    block = block[:block.index("\n    }")]
    audit = set(re.findall(r'^\s*"([a-z_]+)":\s*re\.compile', block, re.M))
    assert audit == {n for n, _rx in R._MAGIC_AUDIT_CATEGORIES}, (
        audit ^ {n for n, _rx in R._MAGIC_AUDIT_CATEGORIES})


def test_the_absence_is_disclosed_in_a_sidecar_never_in_the_transcript(tmp_path):
    """A report that SAID "this deck has no antenna rule" would put the word
    `antenna` in the text the audit scans, and the audit would then count the
    category as NAMED. The flow would have silenced a warning by stating the
    opposite of what it measured."""
    text = _run_deck(tmp_path)
    for word in ("density", "antenna", "enclosure"):
        assert word not in text.lower(), word
    src = Path(R.__file__).read_text()
    assert "_MAGIC_CATEGORY_DISCLOSURE_REL" in src
    assert "drc_signoff_magic.categories.json" in src


# ── the two paths, end to end, through the real audit ─────────────────────

def _bind_current_drc_fixture(proj):
    """SOURCE_CONTROL context through the real current publisher/reader.

    These receipt unit fixtures predate the required Step31 current record.
    Their controlled ledger is not native physical verification evidence.
    """
    from types import SimpleNamespace
    import _physical_current as current

    def put(rel, data):
        path = proj / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path
    tech = put("input/pdk/current.tech.lef", b"SOURCE_CONTROL tech LEF\n")
    cell = put("input/pdk/current.cell.lef", b"SOURCE_CONTROL cell LEF\n")
    deck = put("input/pdk/current.deck", b"SOURCE_CONTROL rule deck\n")
    put("reports/phase3/technology_units.json", b'{"pdk":"open_fixture"}\n')
    put("phase3/stage3/pnr/chip_top.def", b"DESIGN chip_top ;\nEND DESIGN\n")
    put("phase3/stage3/pnr/chip_top_pnr.v", b"module chip_top(); endmodule\n")
    put("state_out.json", json.dumps({
        "gds": str(proj / "phase3/stage3/pnr/chip_top.gds"),
        "def": str(proj / "phase3/stage3/pnr/chip_top.def")}).encode())
    publish_finished_gds(proj)
    report = proj / R._MAGIC_SIGNOFF_DRC_REL
    native = put("phase3/reports/drc.rpt", report.read_bytes())
    put("reports/phase3/drc_signoff.rpt", report.read_bytes())
    log = put("phase3/reports/drc.log", b"SOURCE_CONTROL native transport\n")
    pdk = SimpleNamespace(name="open_fixture", tech_lef=tech, cell_lef=cell, drc_deck=deck)
    def producer():
        outputs = {str(path.relative_to(proj)): "sha256:" + current.digest(path)
                   for path in (native, log)}
        gds = proj / "phase3/stage3/pnr/chip_top.gds"
        entry = {"record": "invocation", "tool": "magic", "measured": True,
                 "exit_code": 0, "command": "SOURCE_CONTROL magic transport",
                 "scope": "SOURCE_CONTROL", "outputs": outputs,
                 "inputs": {str(gds.relative_to(proj)): "sha256:" + current.digest(gds)}}
        with (proj / "provenance.jsonl").open("a") as stream:
            stream.write(json.dumps(entry) + "\n")
        return R.StepResult("drc", "PASS", 0, "SOURCE_CONTROL current context")
    row = current.direct_half(proj, "chip_top", pdk, "drc", producer)
    assert row.status == "PASS", row
    assert current.read_direct_half(proj, "drc")["verdict"] == "CURRENT"


def _project(tmp_path, report_text, mutate_after_digest=False):
    proj = tmp_path / "p"
    (proj / "reports" / "phase3").mkdir(parents=True)
    (proj / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    # a GDS whose top cell is the one the report names
    gds = proj / "phase3" / "stage3" / "pnr" / "chip_top.gds"
    gds.write_bytes(_gds_bytes("chip_top"))
    (proj / "rtl").mkdir()
    (proj / "rtl" / "chip_top.v").write_text("module chip_top(); endmodule\n")
    rpt = proj / R._MAGIC_SIGNOFF_DRC_REL
    rpt.write_text(report_text)

    def sha(path):
        h = hashlib.sha256()
        h.update(Path(path).read_bytes())
        return "sha256:" + h.hexdigest()

    entry = {
        "record": "invocation", "tool": "magic", "measured": True,
        "exit_code": 0, "command": "magic -dnull -noconsole ...",
        "inputs": {"phase3/stage3/pnr/chip_top.gds": sha(gds)},
        "outputs": {R._MAGIC_SIGNOFF_DRC_REL: sha(rpt)},
    }
    if mutate_after_digest:
        with rpt.open("a") as fh:
            fh.write("DECK_RULE: appended after the digest was taken\n")
    (proj / "provenance.jsonl").write_text(json.dumps(entry) + "\n")
    _bind_current_drc_fixture(proj)
    return proj


def _gds_bytes(top):
    """A GDS whose only structure is `top` — enough for `gds_top_cells`."""
    def rec(tag, payload=b""):
        return (len(payload) + 4).to_bytes(2, "big") + tag + payload
    name = top.encode() + (b"\0" if len(top) % 2 else b"")
    return (rec(b"\x00\x02", b"\x00\x05")            # HEADER
            + rec(b"\x01\x02", b"\0" * 24)           # BGNLIB
            + rec(b"\x02\x06", b"l\0")               # LIBNAME
            + rec(b"\x03\x05", b"\x3e\x41\x89\x37\x4b\xc6\xa7\xf0"
                               b"\x39\x44\xb8\x2f\xa0\x9b\x5a\x54")  # UNITS
            + rec(b"\x05\x02", b"\0" * 24)           # BGNSTR
            + rec(b"\x06\x06", name)                 # STRNAME
            + rec(b"\x07\x00")                       # ENDSTR
            + rec(b"\x04\x00"))                      # ENDLIB


_GOOD = """# Tool: magic
# sign-off DRC, rule deck applied to a streamed layout
magic DRC: the rule deck of the loaded technology, applied to the streamed layout
tech name: T
tech file: /pdk/t.tech
tech version: 1.2.3
layout: /c/chip_top.gds
measured_design: chip_top
top cell: chip_top
layout sha256: %s
drc style requested: drc(full)
commands: drc check ; drc catchup ; drc listall why ; drc list count total

deck rules declared by /pdk/t.tech (drc section): 3
DECK_RULE: Metal1 spacing < 0.23um (M1.2)
DECK_RULE: Metal1 width < 0.23um (M1.1)
DECK_RULE: %s

rules with violations: 0
error tiles (drc list count total): 0
total violations: 0
COUNT: 0
""" % ("ab" * 32, "padding rule text so the report clears the stub floor " * 30)


def _audit(proj):
    prog = PROGRAMS / "drc_report_check.py"
    cp = subprocess.run(
        [sys.executable, str(prog), ".", "--mode", "drc", "--signoff",
         "--under", R._MAGIC_SIGNOFF_DRC_REL,
         "--subject", R._MAGIC_SIGNOFF_DRC_REL, "--json", R._MAGIC_SIGNOFF_DRC_JSON_REL],
        cwd=str(proj), capture_output=True, text=True)
    return cp, json.loads((proj / R._MAGIC_SIGNOFF_DRC_JSON_REL).read_text())


def test_the_receipt_binds_to_the_layout_and_the_design(tmp_path):
    """THE PASS PATH: tier `invocation`, the witness names the GDS and its
    digest, the top cell matches, the design is decided."""
    proj = _project(tmp_path, _GOOD)
    cp, doc = _audit(proj)
    s = doc["summary"]
    assert s["layout_evidence_tier"] == "invocation", s["layout_evidence_witness"]
    assert s["layout_topcell"] == "chip_top"
    assert s["layout_topcell_match"] is True
    assert "phase3/stage3/pnr/chip_top.gds" in s["layout_evidence_witness"]
    assert s["design_binding"] is True, s["design_binding"]
    assert s["producers"][0]["deck"] == "/pdk/t.tech"
    assert s["producers"][0]["top_cell"] == "chip_top"
    assert doc["passed"] is True, [f for f in doc["findings"]
                                   if f.get("severity") == "ERROR"]
    assert cp.returncode == 0, cp.stdout
    assert L24._report_engine(R._MAGIC_SIGNOFF_DRC_JSON_REL, doc, proj) == "magic"


def test_a_report_edited_after_its_digest_loses_the_binding(tmp_path):
    """THE OTHER DIRECTION, and it is the real IC's own failure reproduced:
    append one line after the provenance digest and the receipt goes back to
    `recorded DRC report hash differs from current report`, tier none,
    DRC_SIGNOFF_NO_LAYOUT_EVIDENCE."""
    proj = _project(tmp_path, _GOOD, mutate_after_digest=True)
    _cp, doc = _audit(proj)
    s = doc["summary"]
    assert s["layout_evidence_tier"] == "none", s
    assert "hash differs" in s["layout_evidence_witness"]
    assert any(f["rule"] == "DRC_SIGNOFF_NO_LAYOUT_EVIDENCE"
               for f in doc["findings"]), doc["findings"]
    assert doc["passed"] is False
