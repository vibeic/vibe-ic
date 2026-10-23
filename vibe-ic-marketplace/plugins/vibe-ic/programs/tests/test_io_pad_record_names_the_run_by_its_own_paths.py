#!/usr/bin/env python3
"""The IO-pad chip-top record names the run's own files by their run-relative
path, never by the mount the producer happened to run under.

MEASURED (subservient x gf180mcuD, IC route, 8hd-3, 2026-09-28, run root
`subic_ic_20260928`): step 15.5ic's producer runs INSIDE the EDA container,
where the project is bind-mounted at `/foss/designs/<run>`, and it wrote

    "project": "/foss/designs/subic_ic_20260928"
    "netlist": "/foss/designs/subic_ic_20260928/phase2/stage2/synth/subservient_synth.v"

into `reports/phase3/io_pad_chip_top.json`. Read back on the host, the first
names a directory that does not exist there, and P0's
`project_outputs_in_tree_check` FAILed the run on it:

    1 blocking external-storage reference(s) (0 live, 0 dangling, 1 outside-root)
    reports/phase3/io_pad_chip_top.json -> /foss/designs/subic_ic_20260928

The gate was right about the record: a spelling that resolves only under one
mount is not a reference a reader can follow. The producer now records every
path inside the run root relative to the run root (and the run by its
directory name), so the same record reads the same under every mount. The gate
is NOT changed; the controls below prove it still blocks on both a genuinely
external reference and the exact spelling the run recorded.

HOW THE CONTAINER IS SIMULATED. Without root a test cannot bind-mount, so it
reproduces the one property a bind mount has that matters here: the tree is
spelled one way when the producer WRITES the record and another way when the
gate READS it. The producer runs on `<tmp>/ctr/foss/designs/<run>`; that same
tree is then renamed to `<tmp>/host/<run>` and the gate reads it there, where
the write-time spelling no longer exists.

WHY THE PDK ROOT IS PASSED RELATIVE. The fixture PDK lives under pytest's
tmp_path, which is `/tmp/...` on most hosts, and every `/tmp` path in a
declaration file is blocking for this gate by design. A real run's PDK is
`/foss/pdks/...`, outside that population. Passing the fixture PDK as a
relative root (from the fixture's own directory) keeps the harness's location
out of the verdict, so the gate's answer turns on the project-path spelling
alone -- the one thing under test.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterator, List, Tuple

import pytest

TESTS = Path(__file__).resolve().parent
PROGRAMS = TESTS.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(TESTS))

import _designs_root as DR                              # noqa: E402
import _l_doc_pad_placement as LPP                      # noqa: E402
import test_io_pad_chip_top_gen as IO                   # noqa: E402
import test_io_pad_power_domain_plan as PDP             # noqa: E402
import fault_scan_chain_insert as SCI                   # noqa: E402

GEN = PROGRAMS / "io_pad_chip_top_gen.py"
GATE = PROGRAMS / "project_outputs_in_tree_check.py"
RECORD = "reports/phase3/io_pad_chip_top.json"
#: A neutral run-root name. The gate derives its relocated-copy class from the
#: run root's own directory name, so the name only has to be distinctive.
RUN = "ioring_run7"


def _spellings(tmp: Path) -> Tuple[Path, Path]:
    """(container spelling, host spelling) of the same run root."""
    ctr = tmp / "ctr" / DR.DEFAULT_CONT_ROOT.strip("/") / RUN
    host = tmp / "host" / RUN
    return ctr, host


def _relocate(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return dst


def _produce(project: Path, cwd: Path, extra=()) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GEN), str(project),
         "--pdk-root", "pdk", "--pdk", "testpdk", *extra],
        capture_output=True, text=True, cwd=str(cwd))


def _gate(project: Path, tmp: Path) -> Tuple[subprocess.CompletedProcess, List[dict]]:
    report = tmp / "gate_report.json"
    res = subprocess.run(
        [sys.executable, str(GATE), str(project), "--json", str(report)],
        capture_output=True, text=True)
    flagged = (json.loads(report.read_text()).get("flagged") or []
               if report.is_file() else [])
    return res, flagged


def _strings(obj) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _container_run_with_scan_core(tmp: Path) -> Tuple[Path, Path]:
    """The producer's fullest record: a published scan core with a declared
    test-access plan (netlist, scan metadata, integration spec and plan are all
    recorded), plus one OPTIONAL L9 port the netlist lacks (the dropped-port
    record carries the netlist too). Built, relocated to the container spelling,
    produced there, then relocated to the host spelling."""
    proj, _cfg, _plan = IO._scan_project(tmp)
    # Bring the older path-relocation fixture up to the current scan-selection
    # contract.  A published bit alone is no longer enough: PnR selects the
    # post-DFT subject only when its exact L20 bytes and measured chain agree.
    net = proj / "phase2/stage2/synth/post_dft_netlist.v"
    text = net.read_text().replace("serial_in", "sin").replace(
        "serial_out", "sout").replace("scan_enable", "shift")
    net.write_text(text)
    l20 = proj / "phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json"
    l20.write_text(json.dumps({
        "doc_id": "L20", "applicability": "APPLICABLE",
        "extraction_status": "EXTRACTED", "fields": {
            "dft_present": True, "scan_chains": [{
                "name": "core_scan", "length": 1, "scan_in": "sin",
                "scan_out": "sout", "clock": "clk"}]}}))
    meta_path = proj / "reports/phase2/dft/scan_chain.json"
    meta = json.loads(meta_path.read_text())
    meta.update({
        "dft_ports": ["sin", "sout", "shift"],
        "functional_mode_tieoff": {"sin": 0, "shift": 0},
        "scan_out_port": "sout", "clock": "clk",
        "input_flop_count": 1, "internal_chain_length": 1})
    binding, problems = SCI.load_l20_scan_contract(proj, "clk", 1)
    assert binding is not None and not problems, problems
    meta["l20_contract"] = binding
    meta["l20_reconciliation"] = SCI.reconcile_l20_scan_contract(binding, meta)
    meta_path.write_text(json.dumps(meta))
    plan_path = proj / "config/dft_test_access.json"
    plan = json.loads(plan_path.read_text())
    plan.update({
        "netlist_sha256": _sha(net),
        "scan_metadata_sha256": _sha(meta_path),
        "functional_mode": {"sin": 0, "shift": 0},
        "ports": [{"name": name, "direction": direction, "side": "W"}
                  for name, direction in (("sin", "input"),
                                           ("sout", "output"),
                                           ("shift", "input"))]})
    plan_path.write_text(json.dumps(plan))
    spec_path = proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    spec = json.loads(spec_path.read_text())
    spec["top_ports"].append({"name": "i_unbuilt", "direction": "input",
                              "width": 1, "optional": True})
    spec_path.write_text(json.dumps(spec))
    IO._pdk(tmp / "pdk")
    ctr, host = _spellings(tmp)
    _relocate(proj, ctr)
    res = _produce(ctr, tmp)
    assert res.returncode == 0, res.stdout + res.stderr
    return ctr, _relocate(ctr, host)


# --------------------------------------------------------------------------- #
# (a) the measured shape: RED on main, GREEN once the producer records paths
#     relative to the run root
# --------------------------------------------------------------------------- #
def test_a_record_written_under_the_container_mount_carries_no_mount_spelling(
        tmp_path):
    ctr, host = _container_run_with_scan_core(tmp_path)
    rec = json.loads((host / RECORD).read_text())
    # precondition: every project-path-bearing section was actually written,
    # so the assertion below is not vacuous
    assert rec["verdict"] == "WROTE"
    assert rec["scan_interface"]["selected_scan_netlist"] is True
    assert rec["optional_ports_not_implemented"], rec.get(
        "optional_ports_not_implemented")
    assert rec.get("test_access"), sorted(rec)
    assert rec["project"] == RUN

    leaked = sorted({s for s in _strings(rec) if str(ctr) in s})
    assert not leaked, (
        "the record names the run by the mount it was written under, which "
        f"does not exist where it is read: {leaked[:6]}")


def test_the_recorded_run_relative_paths_name_the_files_that_were_read(tmp_path):
    """Not just absent: each recorded path resolves, in the tree as the gate
    sees it, to the very file whose digest the record carries."""
    _ctr, host = _container_run_with_scan_core(tmp_path)
    rec = json.loads((host / RECORD).read_text())
    scan = rec["scan_interface"]
    for key in ("netlist", "scan_metadata", "integration_spec"):
        rel = Path(scan[key])
        assert not rel.is_absolute(), (key, scan[key])
        assert (host / rel).is_file(), (key, scan[key])
        assert _sha(host / rel) == scan[f"{key}_sha256"], key
    decl = Path(rec["test_access"]["declaration"])
    assert not decl.is_absolute() and (host / decl).is_file(), decl
    assert _sha(host / decl) == rec["test_access"]["declaration_sha256"]
    for dropped in rec["optional_ports_not_implemented"]:
        net = Path(dropped["netlist"])
        assert not net.is_absolute() and (host / net).is_file(), dropped


def test_the_gate_passes_the_record_read_through_the_other_mount(tmp_path):
    _ctr, host = _container_run_with_scan_core(tmp_path)
    res, flagged = _gate(host, tmp_path)
    assert res.returncode == 0, (res.stdout + res.stderr, flagged)
    assert flagged == []


def test_a_refusal_written_under_the_container_mount_names_no_mount_spelling(
        tmp_path):
    """The refusal path spells the project too: a measured-current second pass
    whose floorplan DEF is missing names where it looked."""
    project, _root = PDP._tree(tmp_path)
    ctr, host = _spellings(tmp_path)
    _relocate(project, ctr)
    plan = tmp_path / "supply_plan.json"
    plan.write_text(json.dumps({"verdict": "PLANNED", "pair_count": 12,
                                "subject_def_sha256": "a" * 64,
                                "die_side_um": 500}))
    res = _produce(ctr, tmp_path, ["--power-net", "VDD", "--ground-net", "VSS",
                                   "--supply-plan", str(plan)])
    assert res.returncode == 1, res.stdout + res.stderr
    _relocate(ctr, host)
    rec = json.loads((host / RECORD).read_text())
    assert rec["rule"] == "SUPPLY_ENTRY_FLOORPLAN_MISSING", rec
    leaked = sorted({s for s in _strings(rec) if str(ctr) in s})
    assert not leaked, leaked
    assert "phase3/stage3/pnr/floorplan.def" in " ".join(rec["findings"])
    gate, flagged = _gate(host, tmp_path)
    assert gate.returncode == 0, (gate.stdout + gate.stderr, flagged)


def test_an_unreadable_test_access_plan_is_named_by_its_run_relative_path(
        tmp_path):
    proj, cfg, _plan = IO._scan_project(tmp_path)
    cfg.write_text("{ not json")
    IO._pdk(tmp_path / "pdk")
    ctr, host = _spellings(tmp_path)
    _relocate(proj, ctr)
    res = _produce(ctr, tmp_path)
    assert res.returncode == 1, res.stdout + res.stderr
    _relocate(ctr, host)
    rec = json.loads((host / RECORD).read_text())
    assert rec["rule"] == "DFT_TEST_ACCESS_INVALID", rec
    assert not sorted({s for s in _strings(rec) if str(ctr) in s})
    assert "config/dft_test_access.json" in " ".join(rec["findings"])


def test_a_permission_denied_test_access_plan_survives_relocation(tmp_path):
    proj, _cfg, _plan = IO._scan_project(tmp_path)
    IO._pdk(tmp_path / "pdk")
    ctr, host = _spellings(tmp_path)
    _relocate(proj, ctr)
    plan = ctr / "config/dft_test_access.json"
    plan.chmod(0o000)
    try:
        res = _produce(ctr, tmp_path)
    finally:
        plan.chmod(0o644)
    assert res.returncode == 1, res.stdout + res.stderr
    _relocate(ctr, host)
    rec = json.loads((host / RECORD).read_text())
    assert rec["rule"] == "DFT_TEST_ACCESS_INVALID", rec
    assert "config/dft_test_access.json" in " ".join(rec["findings"])
    assert str(ctr) not in json.dumps(rec), rec
    assert "PermissionError" in " ".join(rec["findings"])
    gate, flagged = _gate(host, tmp_path)
    assert gate.returncode == 0, (gate.stdout + gate.stderr, flagged)
    assert flagged == []


def test_a_permission_denied_design_document_survives_relocation(tmp_path):
    proj, _cfg, _plan = IO._scan_project(tmp_path)
    IO._pdk(tmp_path / "pdk")
    ctr, host = _spellings(tmp_path)
    _relocate(proj, ctr)
    doc = ctr / "input/docs/L3_external_interface.md"
    doc.chmod(0o000)
    try:
        _placement, _params, unreadable, _scanned = LPP.read_project_placement(ctr)
        res = _produce(ctr, tmp_path)
    finally:
        doc.chmod(0o644)
    assert res.returncode == 1, res.stdout + res.stderr
    _relocate(ctr, host)
    rec = json.loads((host / RECORD).read_text())
    assert rec["rule"] == "L_DOC_UNREADABLE", rec
    assert unreadable[0]["file"] == (
        "input/docs/L3_external_interface.md")
    assert str(ctr) not in unreadable[0]["reason"], unreadable
    assert "PermissionError" in unreadable[0]["reason"]
    assert "input/docs/L3_external_interface.md" in " ".join(rec["findings"])
    assert str(ctr) not in json.dumps(rec), rec
    gate, flagged = _gate(host, tmp_path)
    assert gate.returncode == 0, (gate.stdout + gate.stderr, flagged)
    assert flagged == []


# --------------------------------------------------------------------------- #
# (b) controls: the gate was not widened. GREEN on main and on the branch.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("reference", [
    # a relocated copy of this run that is gone: lost evidence
    f"/scratch_gone/{RUN}/phase3/stage3/pnr/lost_output.v",
    # the exact spelling the measured run recorded: the container mount of the
    # run root itself, read on a host where it does not exist
    f"{DR.DEFAULT_CONT_ROOT}/{RUN}",
])
def test_a_genuinely_external_reference_in_the_same_record_still_fails(
        tmp_path, reference):
    host = tmp_path / "host" / RUN
    path = host / RECORD
    path.parent.mkdir(parents=True)
    rec = {"program": "io_pad_chip_top_gen", "project": RUN,
           "control_external_reference": reference}
    path.write_text(json.dumps(rec, indent=2))
    res, flagged = _gate(host, tmp_path)
    assert res.returncode == 1, res.stdout + res.stderr
    assert [(f["file"], f["path"]) for f in flagged] == [(RECORD, reference)]
    assert flagged[0]["class"] == "outside-root"
