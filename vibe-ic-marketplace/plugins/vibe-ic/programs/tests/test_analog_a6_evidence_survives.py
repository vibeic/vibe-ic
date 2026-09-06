"""A6 must not destroy the evidence under its own number.

MEASURED on this campaign's two analog blocks (image 0.3.46, ihp-sg13g2's own
KLayout decks, 2026-09-06): A6 reported `violations: 2780` and `mismatch`, and
NOTHING on disk said which rules or which nets. Three separate reasons, three
arms:

  A  the KLayout DRC branch was handed `drc.report` as its report path, wrote
     its per-rule database there, and `_write_drc_report` then overwrote that
     file with the six-line tally. The rule names had to be recovered by
     re-running the deck by hand.
  B  the report's first line said "native svrfdrc (staged foundry .rule
     deck)" whatever engine ran — two lines above its own `method:
     klayout_runset`.
  C  the LVS runset was not told where to put its extracted netlist, so it
     derived the path from an empty cellview filename, could not write it,
     and died in CLEANUP — after printing the verdict and BEFORE writing the
     LVS database the arm went on to name in `comp.json`.
"""
from __future__ import annotations

import inspect as _inspect
import json
import re
from pathlib import Path

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path

import analog_a6_native_pv as PV


def _block(tmp_path: Path, block: str = "b") -> Path:
    bdir = tmp_path / "phase3" / "analog" / block
    bdir.mkdir(parents=True)
    (bdir / f"{block}.gds").write_text("gds")
    (bdir / f"{block}.sp").write_text(f".subckt {block} a b\nM1 a b a a m\n.ends\n")
    return bdir


def test_a_the_engines_own_report_is_not_the_file_the_summary_overwrites(
        tmp_path):
    bdir = _block(tmp_path)
    seen = {}

    def drc(deck, gds, block, container):
        # the real runner writes its database to the path it is handed
        seen["path"] = Path(_HANDED[0])
        seen["path"].write_text("<report-database><item/></report-database>")
        return 3, {"method": "klayout_runset", "rules_pass": 560}

    _HANDED = []
    real = PV._default_drc_runner

    # the path the producer hands its engine is the thing under test, so it is
    # captured through the same seam the real runner uses
    def capture(deck, gds, block, container, report_host):
        _HANDED.append(str(report_host))
        return drc(deck, gds, block, container)

    PV._default_drc_runner = capture
    try:
        out = PV.run_block_pv(tmp_path, "b",
                              {"drc_deck": "/x/deck.drc"}, container="c")
    finally:
        PV._default_drc_runner = real

    assert _HANDED and not _HANDED[0].endswith("drc.report"), (
        "the engine must not be pointed at the file the summary overwrites")
    assert (bdir / "drc.report").is_file()
    assert seen["path"].is_file(), "the per-rule database survived the summary"
    assert seen["path"].read_text().startswith("<report-database>")
    assert out["drc"]["raw_report"], "and the summary says where it is"


def test_b_the_report_header_names_the_engine_that_ran(tmp_path):
    bdir = _block(tmp_path)
    rpt = PV._write_drc_report(bdir, "b", 4,
                               {"method": "klayout_runset", "rules_pass": 560})
    head = rpt.read_text().splitlines()[0]
    assert "klayout_runset" in head
    assert "svrfdrc" not in head, (
        "a reader who takes the first line at face value must not be told an "
        "engine that did not run")
    rpt2 = PV._write_drc_report(bdir, "b", 0,
                                {"method": "svrf_native", "rules_pass": 12})
    assert "svrf_native" in rpt2.read_text().splitlines()[0]


def test_c_the_lvs_runset_is_told_where_to_put_its_extracted_netlist(tmp_path):
    """Unset, the deck derives it from an empty cellview filename, cannot
    write it, and dies in cleanup before the LVS database is written."""
    cmds = []

    # BIND THE REAL SIGNATURE rather than a remembered one. `_docker_exec`
    # grew keyword-only `marker` / `log_path` under this test while it was
    # being written, and a fake with the old positional shape reports a
    # TypeError from inside the code under test — which is a stale fake, not
    # a defect. Binding here means the NEXT drift is caught the same way.
    _REAL_SIG = _inspect.signature(PV._docker_exec)

    def fake_exec(*args, **kw):
        _REAL_SIG.bind(*args, **kw)
        cmd = kw.get("cmd", args[1] if len(args) > 1 else "")
        cmds.append(cmd)
        if "port_only" in cmd:
            # the comparison-side layout the prep script writes
            m = re.search(r"-rd out=(\S+)", cmd)
            if m:
                Path(m.group(1).strip("'\"")).write_text("gds")
            return 0, "", ""
        return 0, "Congratulations! Netlists match", ""

    real = PV._docker_exec
    PV._docker_exec = fake_exec
    PV._tool_on_path = lambda c, t: "/usr/bin/klayout"
    try:
        bdir = _block(tmp_path)
        work = tmp_path / "w"
        v, meta = PV._klayout_lvs_runset_runner(
            "/x/deck.lvs", str(bdir / "b.gds"), str(bdir / "b.sp"), "b",
            "c", work)
    finally:
        PV._docker_exec = real
    lvs_cmd = [c for c in cmds if "deck.lvs" in c and "-rd input=" in c]
    assert lvs_cmd, "the runset was invoked"
    assert "-rd target_netlist=" in lvs_cmd[0], (
        "without it the deck writes beside an empty filename, the write is "
        "refused, and the LVS database `comp.json` names is never created")
