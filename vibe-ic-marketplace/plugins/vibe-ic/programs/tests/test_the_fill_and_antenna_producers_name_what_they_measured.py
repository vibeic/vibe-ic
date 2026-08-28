#!/usr/bin/env python3
"""antenna.rpt and density.rpt must say WHOSE design they are about.

THE FINDING, MEASURED (vibe-ic#1119, attack A3_CROSS_DESIGN)
============================================================
Copying `sha256/clean_run_v1427_20260715`'s same-named artefacts over
`spm/v1.9.96_gf180mcuD` — a different design on a different PDK — and re-running
that cell's own sign-off gates left two of them green:

    antenna_report_check    rc 0 -> 0    SUCCEEDED
    erc_density_check       rc 0 -> 0    SUCCEEDED

Eleven sibling findings closed by teaching the GATE to read the design its
evidence declares. These two could not: their evidence declares nothing.

    reports/phase3/antenna.rpt   sha256 7c614562baacec12...  <- the cell
    reports/phase3/antenna.rpt   sha256 7c614562baacec12...  <- the donor

BYTE-IDENTICAL between two designs. 487 bytes of "0 net violations, 0 pin
violations", no name in it anywhere, citing `phase3/stage3/pnr/openroad.log` as
its source — a path typed as a constant, and a file the published cell does not
contain. `reports/density.{rpt,json}` were the same shape: real numbers, no
identifier. No gate-side rule can bind evidence that carries no distinguishing
byte, so the fix is at the PRODUCER, and this file guards the producer end.

WHAT A STAMP IS NOT
===================
It makes a report ATTRIBUTABLE. It does not make it a MEASUREMENT, and the two
must not merge — a stamped empty report is still an empty report.
`test_a_stamp_does_not_make_an_absent_or_empty_report_a_pass` holds that line
for both gates, including the case that matters most: a report carrying a
CORRECT stamp and no result at all.

WHY FIXTURES AND NOT THE PUBLISHED CELL
=======================================
The cells that produced the measurement above are not in this repository — they
moved to vibeic/benchmark-data — so a test over them runs on one host and skips
everywhere else. The property is not corpus-shaped: "two designs must not
produce the same report bytes" is expressible in two tmp directories, and it
fails on every host.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

#: The PnR log shape the in-session antenna path keys on. `ANTENNA_POSTROUTE_DONE`
#: selects the authoritative post-repair branch, which needs no container.
_PNR_LOG = ("[INFO ODB-0128] Design: {top}\n"
            "ANTENNA_POSTROUTE_DONE\n"
            "Found 0 net violations\n"
            "Found 0 pin violations\n")

_FILL_LOG = ("Placed 1234 filler instances\n"
             "Design area 1000 um^2 27% utilization\n"
             "ROW_UTILIZATION_PCT 99.5\n")


class _Pdk:
    """Only the attributes the fill emitter reads before its tool call.

    Deliberately carries no PDK identity: `_filler_masters_for_pdk` is stubbed,
    so nothing here depends on which library is installed.
    """
    name = "testpdk"
    tapcell_master = None
    tech_lef = Path("/nonexistent/tech.lef")
    cell_lef = Path("/nonexistent/cell.lef")
    liberty = Path("/nonexistent/lib.lib")
    macro_lefs: list = []


def _rtl(root: Path, top: str) -> None:
    (root / "rtl").mkdir(parents=True, exist_ok=True)
    (root / "rtl" / f"{top}.v").write_text(
        f"module {top} (input wire clk, output wire q);\n"
        f"  assign q = clk;\nendmodule\n", encoding="utf-8")


def _antenna_project(root: Path, top: str) -> Path:
    pnr = root / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / f"{top}.def").write_text(f"DESIGN {top} ;\nEND DESIGN\n",
                                    encoding="utf-8")
    (pnr / "openroad.log").write_text(_PNR_LOG.format(top=top),
                                      encoding="utf-8")
    _rtl(root, top)
    (root / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    ok = R._emit_antenna_report(root, top, None, "nocontainer",
                                root / "reports/phase3/antenna.rpt", [])
    assert ok, "the antenna emitter did not run on this fixture"
    return root


@pytest.fixture
def stub_fill_tool(monkeypatch):
    """The fill emitter shells out; the stamp does not. Stub the shell."""
    def _fake_docker(container, cmd, marker=None, outputs=None, **kw):
        for o in (outputs or []):
            Path(o).parent.mkdir(parents=True, exist_ok=True)
            Path(o).write_text("DESIGN filled ;\nEND DESIGN\n", encoding="utf-8")
        return 0, _FILL_LOG, ""
    monkeypatch.setattr(R, "_docker_exec", _fake_docker)
    monkeypatch.setattr(R, "_filler_masters_for_pdk", lambda pdk: ["FILLER_X1"])
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: str(p))


def _density_project(root: Path, top: str) -> Path:
    pnr = root / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / f"{top}.def").write_text(f"DESIGN {top} ;\nEND DESIGN\n",
                                    encoding="utf-8")
    _rtl(root, top)
    ok = R._emit_metal_fill(root, top, _Pdk(), "nocontainer",
                            pnr / "filled.def", [])
    assert ok, "the fill emitter did not run on this fixture"
    return root


def _sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def _gate(prog: str, root: Path, extra=()) -> dict:
    """The gate's own CLI and exit code — the flow reads exit codes."""
    r = _pr.run([sys.executable, str(_PROGRAMS / prog), ".", *extra],
                       cwd=str(root), capture_output=True, text=True)
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        doc = {"program": "unparseable", "stdout": r.stdout[:2000]}
    doc["rc"] = r.returncode
    return doc


# ===========================================================================
# THE PRODUCERS
# ===========================================================================
def test_two_designs_do_not_produce_identical_antenna_reports(tmp_path):
    """THE FINDING, at the producer. Two designs, two different reports."""
    a = _antenna_project(tmp_path / "a", "my_top")
    b = _antenna_project(tmp_path / "b", "other_top")
    ra, rb = a / "reports/phase3/antenna.rpt", b / "reports/phase3/antenna.rpt"
    assert _sha(ra) != _sha(rb), (
        f"two different designs produced byte-identical antenna reports "
        f"({_sha(ra)}). Nothing downstream can tell one from the other, which "
        f"is how a gate certified one design with the other's evidence.")
    assert "measured_design: my_top" in ra.read_text(encoding="utf-8")
    assert "measured_design: other_top" in rb.read_text(encoding="utf-8")


def test_two_designs_do_not_produce_identical_density_reports(
        tmp_path, stub_fill_tool):
    a = _density_project(tmp_path / "a", "my_top")
    b = _density_project(tmp_path / "b", "other_top")
    ra, rb = a / "reports/density.rpt", b / "reports/density.rpt"
    assert _sha(ra) != _sha(rb), (
        f"two different designs produced byte-identical density reports "
        f"({_sha(ra)})")
    assert "measured_design: my_top" in ra.read_text(encoding="utf-8")
    assert "measured_design: other_top" in rb.read_text(encoding="utf-8")


def test_the_stamp_carries_the_sha256_of_the_bytes_the_tool_read(tmp_path):
    """A name alone is forgeable by a rename; the digest is what pins it."""
    root = _antenna_project(tmp_path / "a", "my_top")
    doc = json.loads((root / "reports/phase3/antenna.json").read_text())
    subj = doc["measured_subject"]
    assert subj["design"] == "my_top"
    read = {i["path"]: i for i in subj["inputs"]}
    dfile = root / "phase3/stage3/pnr/my_top.def"
    assert "phase3/stage3/pnr/my_top.def" in read, read
    assert read["phase3/stage3/pnr/my_top.def"]["sha256"] == _sha(dfile), (
        "the recorded digest is not the digest of the DEF the tool read")


def test_the_tool_log_is_recorded_as_RESOLVED_and_not_as_a_template(tmp_path):
    """`"source": "phase3/stage3/pnr/openroad.log"` was a typed constant.

    The published cell does not contain that file, so the citation named a path
    rather than a thing. What is recorded now is stat-ed and hashed.
    """
    root = _antenna_project(tmp_path / "a", "my_top")
    doc = json.loads((root / "reports/phase3/antenna.json").read_text())
    log = doc["measured_subject"]["tool_log"]
    assert log is not None, "no tool log recorded at all"
    on_disk = root / log["path"]
    assert on_disk.is_file(), (
        f"the report cites {log['path']}, which is not in the tree it sits in")
    assert log["sha256"] == _sha(on_disk)
    assert doc["source"] == log["path"], (
        f"`source` disagrees with the resolved tool log: "
        f"{doc['source']!r} vs {log['path']!r}")


def test_an_input_that_cannot_be_read_is_named_and_marked_not_omitted(tmp_path):
    """"the input was absent" and "the input was not looked at" differ."""
    subj = R._measured_subject(tmp_path, "my_top",
                               [tmp_path / "phase3/stage3/pnr/gone.def"])
    assert len(subj["inputs"]) == 1, subj
    rec = subj["inputs"][0]
    assert rec["path"].endswith("gone.def"), rec
    assert rec["sha256"] is None and rec["bytes"] is None, (
        f"an unreadable input was given a digest: {rec}")
    assert "UNREADABLE" in R._measured_subject_lines(subj)


# ===========================================================================
# THE GATES — the finding closes here
# ===========================================================================
def test_the_antenna_gate_refuses_another_designs_report(tmp_path):
    a = _antenna_project(tmp_path / "a", "my_top")
    b = _antenna_project(tmp_path / "b", "other_top")
    for name in ("antenna.rpt", "antenna.json"):
        shutil.copy2(b / "reports/phase3" / name, a / "reports/phase3" / name)
    got = _gate("antenna_report_check.py", a, ("--mode", "antenna"))
    assert got["rc"] == 1, (
        f"antenna_report_check accepted other_top's report in a tree whose "
        f"Verilog declares only my_top:\n{json.dumps(got, indent=2)}")
    rules = [f["rule"] for f in got["findings"]]
    assert "ANTENNA_REPORT_IS_ABOUT_ANOTHER_DESIGN" in rules, rules


def test_PAIRED_the_antenna_gate_accepts_its_own_report(tmp_path):
    """The twin. A gate that refuses everything measures nothing."""
    a = _antenna_project(tmp_path / "a", "my_top")
    got = _gate("antenna_report_check.py", a, ("--mode", "antenna"))
    assert got["rc"] == 0, (
        f"a design's own antenna report was refused:"
        f"\n{json.dumps(got, indent=2)}")
    assert got["summary"]["design_binding"] is True


def test_the_density_gate_refuses_another_designs_report(
        tmp_path, stub_fill_tool):
    a = _density_project(tmp_path / "a", "my_top")
    b = _density_project(tmp_path / "b", "other_top")
    for name in ("density.rpt", "density.json"):
        shutil.copy2(b / "reports" / name, a / "reports" / name)
    got = _gate("erc_density_check.py", a)
    assert got["rc"] == 1, (
        f"erc_density_check accepted other_top's fill report in a tree whose "
        f"Verilog declares only my_top:\n{json.dumps(got, indent=2)}")
    cats = [f["category"] for f in got["findings"]]
    assert "DENSITY_IS_ABOUT_ANOTHER_DESIGN" in cats, cats


def test_PAIRED_the_density_gate_accepts_its_own_report(
        tmp_path, stub_fill_tool):
    a = _density_project(tmp_path / "a", "my_top")
    got = _gate("erc_density_check.py", a)
    assert got["summary"]["design_binding"] is True, (
        f"a design's own fill report did not bind:\n{json.dumps(got, indent=2)}")


# ===========================================================================
# ATTRIBUTABLE IS NOT MEASURED
# ===========================================================================
_STAMP_ONLY = (
    "measured_design: my_top\n"
    "measured_from: phase3/stage3/pnr/my_top.def sha256:"
    "5a60299f693ceb0e8f501d2b79093a676cba36fde5043a97fdcc68d5e818de69\n")


@pytest.mark.parametrize("body,label", [
    (None, "absent"), ("", "empty"), (_STAMP_ONLY, "stamp only, no result"),
])
def test_a_stamp_does_not_make_an_absent_or_empty_report_a_pass(
        tmp_path, body, label):
    """The failure mode this change could have introduced, held shut.

    The third case is the one that matters: a report whose stamp is present and
    CORRECT, and which measured nothing. Identity is not substance.
    """
    for prog, extra, sub, name in (
            ("antenna_report_check.py", ("--mode", "antenna"),
             "reports/phase3", "antenna.rpt"),
            ("erc_density_check.py", (), "reports", "density.rpt")):
        root = tmp_path / f"{prog}-{label}"
        (root / sub).mkdir(parents=True, exist_ok=True)
        _rtl(root, "my_top")
        if body is not None:
            (root / sub / name).write_text(body, encoding="utf-8")
        got = _gate(prog, root, extra)
        assert got["rc"] != 0, (
            f"{prog} PASSED on a {label} report. A stamp makes a report "
            f"attributable, never a measurement:\n{json.dumps(got, indent=2)}")
