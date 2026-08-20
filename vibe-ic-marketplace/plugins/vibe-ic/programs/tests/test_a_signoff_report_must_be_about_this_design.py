#!/usr/bin/env python3
"""A sign-off gate must not certify THIS design with ANOTHER design's evidence.

THE FINDING, MEASURED (vibe-ic#1119, attack A3_CROSS_DESIGN)
============================================================
`adversarial_agent.py` copies a different design's same-named reports over a
published cell and re-runs that cell's own sign-off gates. Against
`spm/v1.9.96_gf180mcuD` with 149 artefacts from `sha256/clean_run_v1427_20260715`
— a different design, a different PDK — six of seven gates stayed green::

    drc_report_check        rc 0 -> 0    SUCCEEDED
    antenna_report_check    rc 0 -> 0    SUCCEEDED
    em_report_check         rc 0 -> 0    SUCCEEDED
    erc_density_check       rc 0 -> 0    SUCCEEDED
    lvs_report_check        rc 0 -> 0    SUCCEEDED
    ir_drop_report_check    rc 0 -> 0    SUCCEEDED

They did it while reading files that state whose evidence they are::

    cell   phase3/reports/drc.rpt   <top-cell>chip_top</top-cell>
    donor  phase3/reports/drc.rpt   <top-cell>sha256</top-cell>

`sta_report_check` was the one that objected, and it is worth being exact about
why, because the campaign's own note reads as though it caught the forgery: it
did not. It tripped `STA_REAL_VIOLATION_FOUND` on a negative slack in the
donor's numbers and `STA_REPORT_TOO_SMALL` on one donor file. A clean donor
would have passed. NO gate was reading design identity.

WHY THE FIXTURES HERE AND NOT THE PUBLISHED CELL
================================================
The cells the attack used are not in this repository — they moved to
vibeic/benchmark-data — so a test written over them runs on a host with a clone
and nowhere else. The property is not corpus-shaped anyway: it is "a report that
names a design this tree does not contain must not be accepted", and two files
express that completely. The corpus-backed measurement above is what the
adversarial ratchet re-runs; this is what fails on every host.

WHAT IS DELIBERATELY NOT ASSERTED
=================================
That a report naming NO design is refused. `antenna`, `lvs`, `power` and `sta`
reports on the published cell name no design at all, and the auditor records
that as `design_binding: "NOT_DETERMINED"` rather than as either colour. Failing
them would redden honest evidence for a gap in the PRODUCERS; passing them
silently is what let the attack work. Publishing the third value is the only
honest option available to a reader, and `test_a_report_that_names_nothing_is_not
_determined` pins that it stays a third value.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import eda_report_audit as E  # noqa: E402

#: The bound on every CLI subprocess here. These fixtures are a few kB and the
#: gate is pure Python; measured at well under a second.
_CLI_BOUND_S = 60

_EM_HEAD = [
    "OpenROAD v2.0 electromigration analysis",
    "[INFO ODB-0127] Reading DEF file: pnr/{top}.def",
    "[INFO ODB-0128] Design: {top}",
    "EM lifetime screen, current density report",
    "Maximum current    : 6.85e-05 A",
    "Javg  1.2 mA   Jpeak  3.4 mA",
    "RMS current: 1.0e-05 A",
    "Peak current: 6.85e-05 A",
]


def _project(root: Path, rtl_top: str, report_top: str | None) -> Path:
    """A project whose Verilog declares `rtl_top` and whose EM report names
    `report_top` (or names no design at all when it is None).

    Everything except the design name is held identical between the two calls a
    test makes, so the only thing a verdict can be responding to is the name.
    """
    (root / "rtl").mkdir(parents=True, exist_ok=True)
    (root / "rtl" / f"{rtl_top}.v").write_text(
        f"module {rtl_top} (input wire clk, output wire q);\n"
        f"  assign q = clk;\nendmodule\n", encoding="utf-8")
    rep = root / "reports" / "phase3"
    rep.mkdir(parents=True, exist_ok=True)
    if report_top is None:
        head = [l for l in _EM_HEAD if "Design:" not in l and "DEF file" not in l]
    else:
        head = [l.format(top=report_top) for l in _EM_HEAD]
    # Padded past MIN_REPORT_BYTES["em"] (1024) with per-segment rows, so the
    # size floor is never what a verdict here is about.
    body = head + [f"  segment {i:04d}  Javg 1.0e-03 mA  Jpeak 2.0e-03 mA"
                   for i in range(40)]
    (rep / "em.rpt").write_text("\n".join(body) + "\n", encoding="utf-8")
    (rep / "em.json").write_text(json.dumps(
        {"segments_analysed": 40, "max_segment_current_A": 6.85e-05},
        indent=2), encoding="utf-8")
    return root


def _audit(project: Path) -> dict:
    """The GATE'S OWN CLI, and its exit code — not an imported function.

    The flow reads exit codes. An assertion over `_check_em()` would leave the
    verdict-to-exit-code mapping unmeasured, which is the hole
    `gate_cli_mutation_probe` exists for.
    """
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "em_report_check.py"), ".",
         "--mode", "em"],
        cwd=str(project), capture_output=True, text=True, timeout=_CLI_BOUND_S)
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        doc = {"program": "unparseable", "stdout": r.stdout, "stderr": r.stderr}
    doc["rc"] = r.returncode
    return doc


def test_a_report_naming_this_design_passes(tmp_path):
    """The discriminating twin. Without it this file could pass by refusing
    everything, and a gate that refuses everything measures nothing."""
    got = _audit(_project(tmp_path / "own", "my_top", "my_top"))
    assert got["rc"] == 0, (
        f"a report about THIS design was refused; the binding is not "
        f"discriminating, it is just failing:\n{json.dumps(got, indent=2)}")
    assert got["summary"]["design_binding"] is True


def test_a_report_about_another_design_is_refused(tmp_path):
    """THE FINDING. Identical evidence, one name changed."""
    got = _audit(_project(tmp_path / "foreign", "my_top", "someone_elses_chip"))
    assert got["rc"] == 1, (
        f"a sign-off gate accepted a report that states it is about "
        f"someone_elses_chip while this project's Verilog declares only "
        f"my_top. That is A3_CROSS_DESIGN, and it is how six gates certified "
        f"one design with another's evidence:\n{json.dumps(got, indent=2)}")
    assert got["summary"]["design_binding"] is False
    rules = [f["rule"] for f in got["findings"]]
    assert "EM_REPORT_IS_ABOUT_ANOTHER_DESIGN" in rules, (
        f"the gate failed, but not for this reason; a failure that names the "
        f"wrong cause is not this guard passing: {rules}")


def test_the_refusal_is_an_ERROR_and_not_a_note(tmp_path):
    """A finding recorded at INFO/WARNING would leave the verdict unmoved.

    That combination is not hypothetical here: `ir_drop` on the published cell
    emits `IR_DROP_REPORT_TOO_SMALL` and `IR_DROP_NO_TOOL_SIGNATURE`, both
    severity ERROR, and still exits 0.
    """
    got = _audit(_project(tmp_path / "sev", "my_top", "someone_elses_chip"))
    sev = {f["rule"]: f["severity"] for f in got["findings"]}
    assert sev.get("EM_REPORT_IS_ABOUT_ANOTHER_DESIGN") == "ERROR", sev


def test_a_report_that_names_nothing_is_not_determined(tmp_path):
    """The third value, published rather than resolved to a colour."""
    got = _audit(_project(tmp_path / "silent", "my_top", None))
    assert got["summary"]["design_binding"] == E.DESIGN_BINDING_NOT_DETERMINED, (
        f"a report naming no design was recorded as "
        f"{got['summary']['design_binding']!r}. Neither colour is true of it, "
        f"and rendering it as one is how the gap in the producers stops being "
        f"visible.")
    assert got["rc"] == 0, (
        "a report that names no design was FAILED. The gap is in the producer, "
        "not in this run's evidence, and reddening honest cells for it would "
        "get the whole binding removed.")


def test_the_project_reference_is_the_design_and_not_a_report(tmp_path):
    """What the report is compared AGAINST must survive the attack.

    The substitution attack rewrites `.rpt` / `.json` / `.log`. If the
    reference were read from one of those, the attacker would supply both sides
    of the comparison and it would agree with itself.
    """
    root = _project(tmp_path / "ref", "my_top", "my_top")
    names = E._project_design_names(root)
    assert "my_top" in names
    # Planting the foreign name in every attackable artefact must not enrol it.
    for rel in ("reports/phase3/em.json", "reports/phase3/em.rpt"):
        p = root / rel
        p.write_text(p.read_text(encoding="utf-8")
                     + "\nmodule someone_elses_chip;\nendmodule\n",
                     encoding="utf-8")
    E._design_names_cache.clear()
    assert "someone_elses_chip" not in E._project_design_names(root), (
        "a name planted in a REPORT was accepted as one of this project's own "
        "design names; the comparison would then have both sides under the "
        "attacker's control")
