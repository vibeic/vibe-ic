"""llv1 W6: a LibreLane run is imported into the canonical tree, bound by sha.

The fixtures are the two CMP3 LibreLane arms (8HD-4 and 8HD-9), trimmed; see
`fixtures/librelane_import/PROVENANCE.md`. Each test copies one into a fresh
project the way the two-segment driver will leave it (the run INSIDE the
project) and imports it.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN = PROGRAMS.parent
for _p in (str(PROGRAMS), str(_PLUGIN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "librelane_import"
RUN_REL = "phase3/librelane/runs/cmp3"
CHECK = PROGRAMS / "provenance_check.py"
MANIFEST = "reports/phase3/impl/import_manifest.json"      # W0's path


def _rows_of(doc):
    """Every row, with the run_dir of its segment, read the way W0's readers
    read a manifest (`segments_of`: a flat one-run manifest is one segment)."""
    import _external_flow_manifest as M
    return [dict(r, run_dir=seg["run_dir"]) for seg in M.segments_of(doc)
            for r in seg["rows"]]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _project(tmp_path: Path, host: str = "8HD-4", *, run_rel=RUN_REL,
             finish_fixture=False) -> Path:
    """Copy historical headers, then construct a SOURCE_FIXTURE copy witness.

    This producer copies opaque trimmed SPEF bytes; it does not extract a
    route, run EDA, or attest historical native execution/accuracy. Finalize
    once after the caller has supplied its positive fixture variations.
    Existing receipts are never refreshed, so later tampering stays unbound.
    """
    import librelane_contract as C
    proj = tmp_path / "proj"
    run = proj / run_rel
    rcx = run / "54-openroad-rcx"
    inputs = rcx / "source_fixture_inputs"
    marker = rcx / "source_fixture.json"
    if finish_fixture:
        if (rcx / "vibeic_receipt.json").exists():
            return proj
        prepared = json.loads(marker.read_text())
        state = json.loads((rcx / "state_out.json").read_text())
        before = json.loads((rcx / "state_in.json").read_text())
        cfg = json.loads((rcx / "config.json").read_text())
        if (state["spef"] != prepared["spef_population"] or
                cfg["RCX_RULESETS"] != prepared["rules_population"] or
                cfg["meta"]["step"] != "OpenROAD.RCX"):
            raise C.Refusal("LL_RCX_OUTPUT_UNBOUND", "fixture population changed")
        for path, recorded in prepared["input_files"].items():
            if C.digest(Path(path)) != recorded:
                raise C.Refusal("LL_RCX_OUTPUT_UNBOUND", "fixture input changed")
        for view in ("def", "odb", "nl", "sdc"):
            if state[view] != before[view] or before[view] not in prepared["input_files"]:
                raise C.Refusal("LL_RCX_OUTPUT_UNBOUND", "fixture route basis changed")
        payload_inputs = {}
        for pattern, value in state["spef"].items():
            output = Path(value)
            if output.is_symlink() or not output.resolve().is_relative_to(rcx.resolve()):
                raise C.Refusal("LL_RCX_OUTPUT_UNBOUND", "fixture SPEF outside producer")
            payload = inputs / (pattern.strip("*_") + ".spef.input")
            payload.write_bytes(output.read_bytes())
            payload_inputs[str(payload)] = C.digest(payload)
            shutil.copyfile(payload, output)
        fingerprint = {
            "scope": "SOURCE_FIXTURE", "producer": "_project:software_copy",
            "native_execution": "NOT_RUN", "native_accuracy": "NOT_MEASURED",
            "image": None, "step": "OpenROAD.RCX",
            "state": C.digest(rcx / "state_in.json"),
            "config": C.digest(rcx / "config.json"),
            "state_files": {str(p): C.digest(p) for p in C._walk_paths(before)},
            "config_files": {str(p): C.digest(p) for p in C._walk_paths(cfg) if p.is_file()},
            "rcx_pdk_files": C._rcx_pdk_input_hashes(cfg, proj, []),
            "copy_input_files": payload_inputs,
        }
        C.write_json(rcx / "input_fingerprint.json", fingerprint)
        hashes = {str(p.relative_to(rcx)): C.digest(p) for p in rcx.rglob("*")
                  if p.is_file() and p.name.endswith(".json")
                  and p.name != "vibeic_receipt.json"}
        hashes.update({str(Path(p).relative_to(rcx)): C.digest(Path(p))
                       for p in state["spef"].values()})
        C.write_json(rcx / "vibeic_receipt.json", {"scope": "SOURCE_FIXTURE",
                     "input": fingerprint, "sha256": hashes})
        C.validate_rcx_receipt(rcx)
        return proj
    run.parent.mkdir(parents=True)
    shutil.copytree(FIXTURES / host / "runs" / "cmp3", run)
    inputs.mkdir()
    historical = json.loads((rcx / "state_out.json").read_text())
    cfg = json.loads((rcx / "config.json").read_text())
    historical_config = dict(cfg)
    top = json.loads((run / "resolved.json").read_text())["DESIGN_NAME"]
    # These are byte-copy fixture inputs, explicitly still trimmed headers.
    # Do not invent the missing historical step-53 route or native SDC.
    views = {}
    for view, source, suffix in (
            ("def", "52-openroad-fillinsertion", "def"),
            ("odb", "44-openroad-detailedrouting", "odb"),
            ("nl", "06-yosys-synthesis", "nl.v")):
        dest = inputs / ("route." + suffix)
        shutil.copyfile(run / source / (top + "." + suffix), dest)
        views[view] = str(dest.resolve())
    sdc = inputs / "source_fixture.sdc"
    sdc.write_text("# SOURCE_FIXTURE copy inputs; no native clocks/timing asserted\n")
    views["sdc"] = str(sdc.resolve())
    tech = inputs / "source_fixture.lef"
    tech.write_text("VERSION 5.8 ;\nUNITS\n DATABASE MICRONS 1000 ;\nEND UNITS\nEND LIBRARY\n")
    spefs, rules = {}, {}
    for pattern, historical_path in historical["spef"].items():
        spefs[pattern] = str((run / historical_path.split("/runs/cmp3/", 1)[1]).resolve())
        rule = inputs / ("rules." + pattern.strip("*_") + ".json")
        C.write_json(rule, {"scope": "SOURCE_FIXTURE", "operation": "byte_copy",
                           "corner_pattern": pattern, "native_accuracy": "NOT_MEASURED"})
        rules[pattern] = str(rule.resolve())
    cfg.update({"DESIGN_NAME": top, "TECH_LEFS": {"nom_*": str(tech.resolve())},
                "RCX_RULESETS": rules})
    C.write_json(rcx / "config.json", cfg)
    C.write_json(rcx / "state_in.json", {**views, "metrics": {}})
    C.write_json(rcx / "state_out.json", {**views, "spef": spefs, "metrics": {}})
    C.write_json(marker, {"scope": "SOURCE_FIXTURE", "producer": "software_copy",
                         "native_execution": "NOT_RUN", "native_accuracy": "NOT_MEASURED",
                         "route_inputs": "opaque historical 4096-byte headers; not native route proof",
                         "historical_state": historical, "historical_config": historical_config,
                         "spef_population": spefs, "rules_population": rules,
                         "input_files": {str(p.resolve()): C.digest(p) for p in inputs.iterdir()}})
    return proj


def _import(proj: Path):
    import librelane_import as LI
    _project(proj.parent, finish_fixture=True)
    return LI.import_run(proj, proj / RUN_REL)


def _rows(proj: Path):
    return [json.loads(l) for l in
            (proj / "provenance.jsonl").read_text().splitlines() if l.strip()]


def _canonical(proj: Path):
    """Every file the import could have written, outside the run itself."""
    return sorted(p.relative_to(proj).as_posix() for p in proj.rglob("*")
                  if (p.is_file() or p.is_symlink())
                  and "phase3/librelane/runs" not in p.relative_to(proj).as_posix()
                  and "phase3/librelane/seg" not in p.relative_to(proj).as_posix())


def _nothing_written(proj: Path, before=()):
    assert _canonical(proj) == sorted(before), _canonical(proj)
    assert not list(proj.glob(".librelane_import.*"))


def _flow_lines(proj: Path, run_rel: str = RUN_REL):
    return (proj / run_rel / "flow.log").read_text().splitlines(keepends=True)


def _at(lines, needle: str) -> int:
    return next(i for i, l in enumerate(lines)
                if l.startswith("Running") and needle in l)


# ── the import itself ─────────────────────────────────────────────────────

@pytest.mark.parametrize("host", ["8HD-4", "8HD-9"])
def test_every_imported_file_is_a_copy_bound_on_both_sides(tmp_path, host):
    proj = _project(tmp_path, host)
    doc = _import(proj)
    assert doc["top"] == "spm" and len(_rows_of(doc)) > 100
    witnessed = {(w["run_dir"], w["step_dir"]): {l["path"] for l in w["logs"]}
                 for w in (r.get("witness") for r in _rows(proj)) if w}
    no_log = []
    for row in _rows_of(doc):
        # W0's meaning: tool-run paths are relative to the row's run_dir
        assert row["run_dir"] == RUN_REL, row
        base = proj / row["run_dir"]
        dest = proj / row["canonical_path"]
        src = base / row["tool_run_path"]
        assert dest.is_file() and not dest.is_symlink(), row
        assert src.is_file() and not src.is_symlink(), row
        assert row["tool_run_sha256"] == row["canonical_sha256"] \
            == "sha256:" + _sha(dest) == "sha256:" + _sha(src), row
        assert row["provenance"] == "witnessed", row
        assert row["flow"] == "librelane" and row["exit_code"] == 0, row
        # W0's final names: the logs that wrote it, each one the step's
        # witness cites, inside the step's own folder
        assert row["tool_run_path"].startswith(row["step_dir"] + "/"), row
        cited = witnessed[(row["run_dir"], row["step_dir"])]
        if not row["source_logs"]:
            no_log.append(row["tool_run_path"])
        for log in row["source_logs"]:
            assert log["sha256"] == "sha256:" + _sha(base / log["path"]), row
            assert log["path"] in cited, row
            assert Path(log["path"]).parent in Path(
                row["tool_run_path"]).parents, row
    # only the STA summaries, which LibreLane's Python assembles from the
    # corners, have no transcript of their own; and the imported StreamOut
    # transcript, which cannot witness its own run (W0's validate_row)
    assert sorted(no_log) == ["12-openroad-staprepnr/summary.rpt",
                              "55-openroad-stapostpnr/summary.rpt",
                              "57-magic-streamout/magic-streamout.log"]
    manifest = json.loads((proj / MANIFEST)
                          .read_text())
    assert manifest == doc


def test_the_canonical_views_land_where_the_gates_read_them(tmp_path):
    proj = _project(tmp_path)
    doc = _import(proj)
    by = {r["canonical_path"]: r for r in _rows_of(doc)}
    want = {
        "phase2/stage2/synth/netlist.v": ("9", "Yosys.Synthesis"),
        "phase3/stage3/pnr/floorplan.def": ("15", "OpenROAD.GeneratePDN"),
        "phase3/stage3/pnr/placed.def": ("17", "OpenROAD.DetailedPlacement"),
        "phase3/stage3/pnr/post_cts.def": ("19", "OpenROAD.CTS"),
        "phase3/stage3/cts/clock_tree.rpt": ("19", "OpenROAD.CTS"),
        "phase3/stage3/pnr/post_hold.def": ("20", "OpenROAD.ResizerTimingPostCTS"),
        "phase3/stage3/pnr/routed.def": ("21", "OpenROAD.DetailedRouting"),
        "phase3/stage3/pnr/routed_router.drc.rpt": ("21", "OpenROAD.DetailedRouting"),
        "phase3/stage3/extracted/spm.spef": ("22", "OpenROAD.RCX"),
        "phase3/stage3/extracted/spef_corners/spm.max.spef": ("22", "OpenROAD.RCX"),
        "phase3/stage3/pnr/filled.def": ("34", "OpenROAD.FillInsertion"),
        "phase3/stage4/gds/spm.gds": ("37", "Magic.StreamOut"),
        "phase3/stage4/hardmacro/spm.lef": ("37.5ip", "Magic.WriteLEF"),
    }
    for rel, (step, tool_step) in want.items():
        assert rel in by, rel
        assert (by[rel]["step_id"], by[rel]["tool_step_id"]) == (step, tool_step)
    # A corner folder holds two transcripts the flow names (sta.log and
    # filter_unannotated.log): both are listed, rather than one guessed.
    corner = next(r for r in _rows_of(doc) if r["step_id"] == "23"
                  and r["tool_run_path"].endswith("/nom_tt_025C_5v00/max.rpt"))
    assert [l["path"] for l in corner["source_logs"]] == [
        "55-openroad-stapostpnr/nom_tt_025C_5v00/filter_unannotated.log",
        "55-openroad-stapostpnr/nom_tt_025C_5v00/sta.log"]
    rcx = by["phase3/stage3/extracted/spef_corners/spm.nom.spef"]
    assert [l["path"] for l in rcx["source_logs"]] == ["54-openroad-rcx/nom/rcx.log"]
    assert [l["path"] for l in by["phase3/stage3/pnr/routed.def"]["source_logs"]] \
        == ["44-openroad-detailedrouting/openroad-detailedrouting.log"]
    # the nominal SPEF is the same tool file as the nom corner
    assert by["phase3/stage3/extracted/spm.spef"]["tool_run_sha256"] == \
        by["phase3/stage3/extracted/spef_corners/spm.nom.spef"]["tool_run_sha256"]
    # LibreLane's own sign-off reports never take a vibe-ic sign-off name
    for rel, row in by.items():
        if row["step_id"] in ("10", "23", "26", "31"):
            assert rel.startswith(f"reports/phase3/librelane/{row['step_id']}/"), rel
    assert not (proj / "reports/phase3/drc_signoff.rpt").exists()
    assert not (proj / "reports/phase3/lvs.rpt").exists()


def test_a_step_this_flow_did_not_run_is_listed_not_invented(tmp_path):
    proj = _project(tmp_path)
    doc = _import(proj)
    assert doc["not_performed"] == [{
        "flow_step": "15.5ic", "tool_step": "OpenROAD.PadRing",
        "reason": "the run's own flow.log never started OpenROAD.PadRing",
        "flow_complete": True}]
    assert doc["flow_status"]["complete"] is True        # one run: flat
    assert not (proj / "phase3/stage3/pnr/padring.def").exists()


def test_the_post_route_antenna_check_is_imported(tmp_path):
    """CheckAntennas runs top-level after global routing, nested inside
    RepairAntennas, and top-level again after the detailed route; rule 26
    takes the top-level run after DetailedRouting."""
    proj = _project(tmp_path)
    doc = _import(proj)
    ant = [r for r in _rows_of(doc) if r["step_id"] == "26"]
    assert ant and {r["tool_step_id"] for r in ant} == {"OpenROAD.CheckAntennas-1"}
    assert all(r["tool_run_path"].startswith("46-openroad-checkantennas-1/")
               for r in ant)


# ── provenance ────────────────────────────────────────────────────────────

def test_each_step_is_one_witnessed_row_the_flow_allow_lists_accept(tmp_path):
    import _tool_log_provenance as T
    proj = _project(tmp_path)
    _import(proj)
    rows = _rows(proj)
    steps = [r for r in rows if r.get("reconstructed") is False]
    _assert_witnessed_population(rows)
    assert all(T.is_witnessed(r, proj) for r in steps)
    assert all(r["attributed_to"] == "librelane" for r in steps)
    for out, tools in (("phase3/stage3/pnr/routed.def", "openroad"),
                       ("phase3/stage4/gds/spm.gds", "klayout,magic,openroad"),
                       ("phase3/stage3/extracted/spm.spef", "magic,openroad"),
                       ("phase2/stage2/synth/netlist.v", "yosys,yosys-abc")):
        r = subprocess.run([sys.executable, str(CHECK), str(proj), "--output",
                            out, "--tool", tools], capture_output=True,
                           text=True, timeout=120)
        assert r.returncode == 0, (out, r.stdout, r.stderr)


def _assert_witnessed_population(rows):
    steps = [r for r in rows if r.get("reconstructed") is False]
    assert sorted(r["step"] for r in steps) == sorted([
        "Yosys.Synthesis", "OpenROAD.STAPrePNR", "OpenROAD.GeneratePDN",
        "OpenROAD.DetailedPlacement", "OpenROAD.CTS",
        "OpenROAD.ResizerTimingPostCTS", "OpenROAD.DetailedRouting",
        "OpenROAD.RCX", "OpenROAD.STAPostPNR",
        "OpenROAD.CheckAntennas-1", "Magic.DRC", "KLayout.DRC",
        "Netgen.LVS", "OpenROAD.FillInsertion", "Magic.StreamOut",
        "KLayout.StreamOut", "Magic.WriteLEF",
    ])
    assert [sorted(r["outputs"]) for r in rows
            if r.get("reconstructed") is True] == [
                ["phase3/stage3/pnr/openroad.log"]]


def test_witnessed_population_pin_rejects_a_same_count_member_swap(tmp_path):
    proj = _project(tmp_path)
    _import(proj)
    rows = _rows(proj)
    _assert_witnessed_population(rows)
    swapped = [dict(r) for r in rows if r.get("step") != "Magic.DRC"]
    replacement = dict(next(r for r in rows if r.get("step") == "Magic.DRC"),
                       step="OpenROAD.UnrelatedReport")
    swapped.append(replacement)
    assert sum(r.get("reconstructed") is False for r in swapped) == 17
    with pytest.raises(AssertionError):
        _assert_witnessed_population(swapped)


def test_a_log_edited_after_the_import_unbinds_its_outputs(tmp_path):
    """The CTS report: only step 19 wrote those bytes. (`provenance_check`
    also binds by digest, and in this fixture two DEF heads are identical and
    several reports are empty, so those would still bind to another row.)"""
    proj = _project(tmp_path)
    _import(proj)

    def check():
        return subprocess.run(
            [sys.executable, str(CHECK), str(proj), "--output",
             "phase3/stage3/cts/clock_tree.rpt", "--tool", "openroad"],
            capture_output=True, text=True, timeout=120)
    assert check().returncode == 0
    log = proj / RUN_REL / "35-openroad-cts/openroad-cts.log"
    log.write_text(log.read_text() + "edited\n")
    r = check()
    assert r.returncode == 1 and "does not hold" in r.stdout, r.stdout


def test_the_assembled_openroad_log_cites_every_section(tmp_path):
    proj = _project(tmp_path)
    doc = _import(proj)
    text = (proj / "phase3/stage3/pnr/openroad.log").read_text()
    stages = re.findall(r"^PNR_STAGE: (\S+)$", text, re.M)
    assert stages == ["floorplan", "placement", "cts", "hold_repair",
                      "global_route", "detailed_route"]
    sections = re.findall(
        r"^# >>> LIBRELANE (\S+) (\S+) sha256:([0-9a-f]{64})\n(.*?)"
        r"^# <<< LIBRELANE \1\n", text, re.M | re.S)
    assert len(sections) == len(doc["openroad_log"]["sources"]) > 10
    for step, rel, sha, body in sections:
        src = proj / rel
        assert _sha(src) == sha, rel
        assert body.rstrip("\n") == src.read_text(errors="replace").rstrip("\n")
        assert not step.split(".", 1)[1].startswith("STA"), step
    # the STA sessions inside the span did run, and wrote logs
    assert list((proj / RUN_REL / "43-openroad-stamidpnr-3").rglob("*.log"))
    backfill = [r for r in _rows(proj)
                if "phase3/stage3/pnr/openroad.log" in r["outputs"]]
    assert len(backfill) == 1 and backfill[0]["reconstructed"] is True


# ── keyed on the run's own records ────────────────────────────────────────

def test_the_import_keys_on_the_flow_log_not_the_folder_ordinal(tmp_path):
    proj = _project(tmp_path)
    run = proj / RUN_REL
    (run / "44-openroad-detailedrouting").rename(run / "99-renamed")
    flow = run / "flow.log"
    flow.write_text(flow.read_text().replace("44-openroad-detailedrouting",
                                             "99-renamed"))
    for st in run.rglob("state_out.json"):
        st.write_text(st.read_text().replace("44-openroad-detailedrouting",
                                             "99-renamed"))
    doc = _import(proj)
    routed = [r for r in _rows_of(doc)
              if r["canonical_path"] == "phase3/stage3/pnr/routed.def"]
    assert routed and routed[0]["tool_run_path"].startswith("99-renamed/")


def test_a_folder_whose_config_names_another_step_is_refused(tmp_path):
    import librelane_contract as C
    proj = _project(tmp_path)
    cfg = proj / RUN_REL / "44-openroad-detailedrouting/config.json"
    doc = json.loads(cfg.read_text())
    doc["meta"]["step"] = "OpenROAD.GlobalRouting"
    cfg.write_text(json.dumps(doc))
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_STEP_MISMATCH"


def test_a_view_another_step_wrote_is_not_attributed_to_this_one(tmp_path):
    import librelane_contract as C
    proj = _project(tmp_path)
    st = proj / RUN_REL / "44-openroad-detailedrouting/state_out.json"
    doc = json.loads(st.read_text())
    doc["def"] = doc["def"].replace("44-openroad-detailedrouting",
                                    "34-openroad-detailedplacement")
    st.write_text(json.dumps(doc))
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_VIEW_NOT_OWN"


def test_a_run_that_stopped_in_a_step_is_refused(tmp_path):
    """flow.log ends in DetailedRouting: LibreLane never finished the run."""
    import librelane_contract as C
    proj = _project(tmp_path)
    flow = proj / RUN_REL / "flow.log"
    lines = flow.read_text().splitlines(keepends=True)
    cut = next(i for i, l in enumerate(lines)
               if "'OpenROAD.DetailedRouting'" in l and l.startswith("Running"))
    flow.write_text("".join(lines[:cut + 1]))
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_FLOW_INCOMPLETE"
    assert "OpenROAD.DetailedRouting at 44-openroad-detailedrouting" in str(exc.value)
    _nothing_written(proj)


def test_a_chosen_step_without_its_state_out_is_refused(tmp_path):
    """The flow finished, yet the step folder the rule takes has no
    state_out.json: LibreLane writes it only after run() returns."""
    import librelane_contract as C
    proj = _project(tmp_path)
    (proj / RUN_REL / "35-openroad-cts/state_out.json").unlink()
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_STEP_NOT_COMPLETED"
    _nothing_written(proj)


def test_a_symlink_at_a_destination_is_replaced_not_written_through(tmp_path):
    proj = _project(tmp_path)
    elsewhere = tmp_path / "elsewhere.def"
    elsewhere.write_text("not the routed design\n")
    dest = proj / "phase3/stage3/pnr/routed.def"
    dest.parent.mkdir(parents=True)
    dest.symlink_to(elsewhere)
    rpt = proj / "phase3/stage3/cts/clock_tree.rpt"      # a copied file
    rpt.parent.mkdir(parents=True)
    rpt.symlink_to(elsewhere)
    _import(proj)
    for p in (dest, rpt):
        assert p.is_file() and not p.is_symlink(), p
    assert elsewhere.read_text() == "not the routed design\n"


def test_a_run_outside_the_project_is_refused(tmp_path):
    import librelane_contract as C
    import librelane_import as LI
    proj = _project(tmp_path)
    outside = tmp_path / "outside"
    shutil.copytree(proj / RUN_REL, outside / "cmp3")
    with pytest.raises(C.Refusal) as exc:
        LI.import_run(proj, outside / "cmp3")
    assert exc.value.code == "LL_IMPORT_RUN_OUTSIDE_PROJECT"


# ── a run LibreLane did not finish is never imported (review W6 MAJOR) ─────

@pytest.mark.parametrize("next_step,last", [
    # W19's aborted calibration shape: the flow stops in STAMidPNR-3
    ("'OpenROAD.DetailedRouting'",
     "OpenROAD.STAMidPNR-3 at 43-openroad-stamidpnr-3"),
    # the IR-drop report dies: before, the import returned normally with
    # 31, 37 and 37.5ip listed as steps the flow 'never started'
    ("'Magic.StreamOut'", "OpenROAD.IRDropReport at 56-openroad-irdropreport"),
])
def test_a_run_that_died_outside_every_rule_is_refused_not_partially_imported(
        tmp_path, next_step, last):
    """The review's scenario: the flow dies in a step no rule names."""
    import librelane_contract as C
    proj = _project(tmp_path)
    lines = _flow_lines(proj)
    cut = _at(lines, next_step)
    (proj / RUN_REL / "flow.log").write_text("".join(lines[:cut]))
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_FLOW_INCOMPLETE"
    msg = str(exc.value)
    assert last in msg, msg
    folder = last.split(" at ")[1]
    assert f"{folder}/" in msg.split("tool's own log:")[1], msg
    _nothing_written(proj)


@pytest.mark.parametrize("appended", ["a step", "nothing"])
def test_an_aborted_rerun_appended_to_a_finished_log_is_refused(tmp_path,
                                                                appended):
    """flow.log is appended per invocation: the LAST one decides, even when
    it died before starting any step."""
    import librelane_contract as C
    proj = _project(tmp_path)
    lines = _flow_lines(proj)
    i = _at(lines, "'OpenROAD.DetailedRouting'")
    (proj / RUN_REL / "flow.log").write_text(
        "".join(lines) + "Starting…\n" + (lines[i] if appended == "a step" else ""))
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_FLOW_INCOMPLETE"
    _nothing_written(proj)


def test_the_flow_status_reader_is_calibrated():
    import librelane_import as LI
    cal = PROGRAMS / "calibration"
    failed = LI.flow_status((cal / "librelane_flow_log_failed_positive.log")
                            .read_text())
    assert failed["complete"] is False
    assert failed["last_started"][0] == "OpenROAD.STAMidPNR"
    assert LI.flow_status((cal / "librelane_flow_log_finished_negative.log")
                          .read_text())["complete"] is True


def test_segment_loop_slots_match_the_real_cut_and_full_flow_logs():
    """Both tool logs have 83 top-level loop iterations; nested runs and
    gating notices are not extra slots, while gated skips still are slots."""
    import librelane_import as LI
    cal = PROGRAMS / "calibration"
    cut = LI.run_cuts((cal / "librelane_flow_log_cut_to_positive.log").read_text())
    full = LI.run_cuts((cal / "librelane_flow_log_gated_negative.log").read_text())
    assert len(cut["slots"]) == len(full["slots"]) == 83
    assert cut["slots"][:4] == full["slots"][:4]
    assert all(kind == "skipped" for kind, _ in cut["slots"][-73:])
    assert all(kind == "running" for kind, _ in full["slots"][-5:])
    assert len(cut["gated"]) == len(full["gated"]) == 4


# ── segments (review W6: the two-segment plan is one call) ────────────────

SEG1, SEG2 = "phase3/librelane/seg1/runs/cmp3", "phase3/librelane/seg2/runs/cmp3"
SEG1_END = "Checker.NetlistAssignStatements"


def _segment_project(tmp_path: Path) -> Path:
    """Segment 1 stops --to NetlistAssignStatements; segment 2 runs from
    CheckSDCFiles. Each flow.log is the real one cut the way LibreLane
    (flows/sequential.py) writes a --to / --from run: `Skipping step` for
    every step outside the range, the steps it ran, then its closing lines."""
    proj = tmp_path / "proj"
    for rel in (SEG1, SEG2):
        _project(tmp_path, run_rel=rel)
        _project(tmp_path, run_rel=rel, finish_fixture=True)
    lines = _flow_lines(proj, SEG1)
    cut = _at(lines, "'OpenROAD.CheckSDCFiles'")
    head, rest = lines[:cut], lines[cut:]
    end = [l for l in lines if l.startswith("Saving views") or
           l.startswith("Flow complete.")]
    assert len(end) == 2

    def skips(part):
        return [f"Skipping step '{l.split(chr(39))[1]}'…\n" for l in part
                if l.startswith("Running '") and "/" not in
                l.split(" at ")[1].strip("'…\n").split("runs/cmp3/", 1)[1]]
    (proj / SEG1 / "flow.log").write_text("".join(head + skips(rest) + end))
    # The trim kept state_out.json only for steps a rule imports; LibreLane
    # writes one for every step that returns, the declared end included.
    (proj / SEG1 / "09-checker-netlistassignstatements/state_out.json") \
        .write_text("{}\n")
    (proj / SEG2 / "flow.log").write_text(
        "Starting…\n" + "".join(skips(head[1:]) + rest))
    return proj


def test_an_import_that_ends_at_a_declared_to_is_refused(tmp_path):
    """Review W6 wave 6: the steps after --to X are steps this import never
    reached, not steps the flow does not perform. An import whose last
    segment stops at --to is refused; the segment imports with the one that
    continues it (test_two_segments_import_as_one_tree)."""
    import librelane_contract as C
    import librelane_import as LI
    proj = _segment_project(tmp_path)
    with pytest.raises(C.Refusal) as exc:
        LI.import_run(proj, proj / SEG1, SEG1_END)
    assert exc.value.code == "LL_IMPORT_ENDS_AT_TO"
    assert SEG1_END in str(exc.value)
    _nothing_written(proj)
    proj2 = _segment_project(tmp_path / "b")
    with pytest.raises(C.Refusal) as exc:
        LI.import_run(proj2, proj2 / SEG1, "OpenROAD.DetailedRouting")
    assert exc.value.code == "LL_IMPORT_SEGMENT_END_MISMATCH"
    _nothing_written(proj2)


def test_two_segments_import_as_one_tree(tmp_path):
    import librelane_import as LI
    proj = _segment_project(tmp_path)
    rc = LI.main([str(proj), f"{proj / SEG1}={SEG1_END}", str(proj / SEG2)])
    assert rc == 0
    doc = json.loads((proj / MANIFEST).read_text())
    assert [(s["name"], s["run_dir"]) for s in doc["segments"]] == \
        [("segment-1", SEG1), ("segment-2", SEG2)]
    assert "run_dir" not in doc and "rows" not in doc
    assert [s["flow_status"]["to"] for s in doc["segments"]] == [SEG1_END, None]
    by = {r["canonical_path"]: r for r in _rows_of(doc)}
    assert by["phase2/stage2/synth/netlist.v"]["run_dir"] == SEG1
    assert by["phase3/stage3/pnr/routed.def"]["run_dir"] == SEG2
    for r in _rows_of(doc):
        assert (proj / r["run_dir"] / r["tool_run_path"]).is_file(), r
    # not_performed over the union: only the step neither segment ran
    assert [n["tool_step"] for n in doc["not_performed"]] == ["OpenROAD.PadRing"]


def test_a_step_two_segments_both_ran_is_refused(tmp_path):
    import librelane_contract as C
    import librelane_import as LI
    proj = _segment_project(tmp_path)
    shutil.copyfile(FIXTURES / "8HD-4/runs/cmp3/flow.log", proj / SEG2 / "flow.log")
    with pytest.raises(C.Refusal) as exc:
        LI.import_segments(proj, [(proj / SEG1, SEG1_END), (proj / SEG2, None)])
    assert exc.value.code == "LL_IMPORT_SEGMENT_OVERLAP"
    _nothing_written(proj)


def test_a_gap_between_segments_is_refused_before_import(tmp_path):
    """The second segment starts at Floorplan, skipping pre-PnR STA."""
    import librelane_contract as C
    import librelane_import as LI
    proj = _segment_project(tmp_path)
    lines = _flow_lines(proj, SEG2)
    first = _at(lines, "'OpenROAD.Floorplan'")
    before = []
    for line in lines[1:first]:
        if line.startswith("Skipping step '"):
            before.append(line)
        elif line.startswith("Running '") and "/" not in \
                line.split(" at ")[1].strip("'…\n").split("runs/cmp3/", 1)[1]:
            before.append(f"Skipping step '{line.split(chr(39))[1]}'…\n")
    (proj / SEG2 / "flow.log").write_text(
        "Starting…\n" + "".join(before + lines[first:]))
    with pytest.raises(C.Refusal) as exc:
        LI.import_segments(proj, [(proj / SEG1, SEG1_END), (proj / SEG2, None)])
    assert exc.value.code == "LL_IMPORT_SEGMENT_GAP"
    assert "OpenROAD.STAPrePNR" in str(exc.value)
    _nothing_written(proj)


# ── which run of a class (review W6: nested runs, top-level reruns) ───────

def _add_steps(proj: Path, before: str, steps):
    """Insert started steps into flow.log before the step ``before``; each is
    (instance, folder, class, files) with its own config and state."""
    run = proj / RUN_REL
    lines = _flow_lines(proj)
    i = _at(lines, before)
    new = []
    for instance, folder, cls, state in steps:
        d = run / folder
        d.mkdir(parents=True)
        (d / "config.json").write_text(json.dumps({"meta": {"step": cls}}))
        new.append(f"Running '{instance}' at 'runs/cmp3/{folder}'…\n")
        if state is not None:
            for name, text in state.items():
                (d / name).write_text(text)
            rec = "/host/cmp3/librelane_8HD-4/design/runs/cmp3/" + folder
            (d / "state_out.json").write_text(json.dumps(
                {"def": f"{rec}/spm.def", "odb": f"{rec}/spm.odb"}))
    (run / "flow.log").write_text("".join(lines[:i] + new + lines[i:]))


def test_a_run_nested_in_a_later_composite_is_not_the_stage(tmp_path):
    """Odb.DiodesOnPorts re-runs DetailedPlacement after the route. The
    placement stage stays the top-level DetailedPlacement."""
    proj = _project(tmp_path)
    _add_steps(proj, "'OpenROAD.CheckAntennas-1'", [
        ("Odb.DiodesOnPorts", "47-odb-diodesonports", "Odb.DiodesOnPorts", None),
        ("OpenROAD.DetailedPlacement-1",
         "47-odb-diodesonports/2-openroad-detailedplacement",
         "OpenROAD.DetailedPlacement",
         {"spm.def": "VERSION 5.8 ;\nDESIGN nested ;\n", "spm.odb": "nested"})])
    _import(proj)
    top = proj / RUN_REL / "34-openroad-detailedplacement/spm.def"
    assert _sha(proj / "phase3/stage3/pnr/placed.def") == _sha(top)


def test_two_top_level_runs_of_a_stage_are_refused_not_picked(tmp_path):
    import librelane_contract as C
    proj = _project(tmp_path)
    _add_steps(proj, "'OpenROAD.CheckAntennas-1'", [
        ("OpenROAD.DetailedPlacement-1", "47-openroad-detailedplacement-1",
         "OpenROAD.DetailedPlacement",
         {"spm.def": "VERSION 5.8 ;\nDESIGN again ;\n", "spm.odb": "again"})])
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_AMBIGUOUS_STEP"
    assert "34-openroad-detailedplacement" in str(exc.value)
    _nothing_written(proj)


# ── all or nothing, and no stale file (review W6 MINORs) ──────────────────

def test_a_refusal_after_earlier_rules_writes_nothing(tmp_path):
    """Rule 21 refuses (its view is another step's); rules 9-20, which come
    first, used to have overwritten netlist.v and four DEFs already."""
    import librelane_contract as C
    proj = _project(tmp_path)
    st = proj / RUN_REL / "44-openroad-detailedrouting/state_out.json"
    doc = json.loads(st.read_text())
    doc["def"] = doc["def"].replace("44-openroad-detailedrouting",
                                    "34-openroad-detailedplacement")
    st.write_text(json.dumps(doc))
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_VIEW_NOT_OWN"
    _nothing_written(proj)


def test_a_failure_while_writing_restores_every_path(tmp_path, monkeypatch):
    import librelane_contract as C
    import librelane_import as LI
    proj = _project(tmp_path)
    placed = proj / "phase3/stage3/pnr/placed.def"
    placed.parent.mkdir(parents=True)
    placed.write_text("the previous placement\n")
    (proj / "provenance.jsonl").write_text('{"earlier": 1}\n')
    real = LI._copy

    def failing(src, dst):
        if dst.name == "clock_tree.rpt":
            raise C.Refusal("LL_IMPORT_COPY_MISMATCH", "disk full")
        return real(src, dst)
    monkeypatch.setattr(LI, "_copy", failing)
    with pytest.raises(C.Refusal):
        _import(proj)
    assert placed.read_text() == "the previous placement\n"
    assert (proj / "provenance.jsonl").read_text() == '{"earlier": 1}\n'
    _nothing_written(proj, ["phase3/stage3/pnr/placed.def", "provenance.jsonl"])


def test_an_import_over_another_runs_import_is_refused(tmp_path):
    import librelane_contract as C
    import librelane_import as LI
    proj = _project(tmp_path)
    _import(proj)
    before = {p: _sha(proj / p) for p in _canonical(proj)}
    other = proj / "phase3/librelane/runs_b/cmp3"
    shutil.copytree(FIXTURES / "8HD-9" / "runs" / "cmp3", other)
    with pytest.raises(C.Refusal) as exc:
        LI.import_run(proj, other)
    assert exc.value.code == "LL_IMPORT_OTHER_RUN_PRESENT"
    assert {p: _sha(proj / p) for p in _canonical(proj)} == before


def test_a_reimport_removes_what_the_same_runs_no_longer_perform(tmp_path):
    """An earlier top's actual imported output is removed after a top change."""
    proj = _project(tmp_path)
    before = _import(proj)
    stale = proj / "phase3/stage4/gds/spm.gds"
    assert stale.is_file()
    (proj / RUN_REL / "resolved.json").write_text('{"DESIGN_NAME": "renamed"}\n')
    doc = _import(proj)
    assert not stale.exists()
    old_paths = {r["canonical_path"] for r in before["rows"]}
    new_paths = {r["canonical_path"] for r in doc["rows"]}
    assert set(doc["removed"]) == old_paths - new_paths
    assert stale.relative_to(proj).as_posix() in doc["removed"]
    assert (proj / "phase3/stage4/gds/renamed.gds").is_file()


def test_a_canonical_file_for_a_step_not_performed_is_refused(tmp_path):
    import librelane_contract as C
    proj = _project(tmp_path)
    stale = proj / "phase3/stage3/pnr/padring.def"
    stale.parent.mkdir(parents=True)
    stale.write_text("from somewhere else\n")
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_STALE_CANONICAL"
    _nothing_written(proj, ["phase3/stage3/pnr/padring.def"])


def test_two_files_for_one_destination_are_refused(tmp_path):
    """Files('*.drc') maps every match to routed_router.drc.rpt."""
    import librelane_contract as C
    proj = _project(tmp_path)
    (proj / RUN_REL / "44-openroad-detailedrouting/zz_extra.drc").write_text("x\n")
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_AMBIGUOUS_SOURCE"
    assert "routed_router.drc.rpt" in str(exc.value)
    _nothing_written(proj)


# ── the nominal corner comes from the run (review W6 MINOR) ───────────────

def _distinct_corners(proj: Path):
    """The trimmed SPEFs share their first 4096 bytes; mark each corner so a
    wrong choice shows."""
    rcx = proj / RUN_REL / "54-openroad-rcx"
    out = {}
    for key, value in json.loads((rcx / "state_out.json").read_text())["spef"].items():
        path = proj / RUN_REL / value.split("/runs/cmp3/", 1)[1]
        path.write_text(path.read_text() + f"* corner {key}\n")
        out[key] = _sha(path)
    assert len(set(out.values())) == len(out) == 3
    return out


@pytest.mark.parametrize("default,key", [("nom_tt_025C_5v00", "nom_*"),
                                         ("max_ff_n40C_5v50", "max_*"),
                                         ("min_ss_125C_4v50", "min_*")])
def test_the_nominal_spef_is_the_corner_the_rcx_step_calls_default(
        tmp_path, default, key):
    proj = _project(tmp_path)
    corners = _distinct_corners(proj)
    cfg = proj / RUN_REL / "54-openroad-rcx/config.json"
    doc = json.loads(cfg.read_text())
    doc["DEFAULT_CORNER"] = default
    cfg.write_text(json.dumps(doc))
    _import(proj)
    assert _sha(proj / "phase3/stage3/extracted/spm.spef") == corners[key]


def test_a_run_whose_rcx_names_no_default_corner_is_refused(tmp_path):
    import librelane_contract as C
    proj2 = _project(tmp_path)
    cfg = proj2 / RUN_REL / "54-openroad-rcx/config.json"
    doc = json.loads(cfg.read_text())
    del doc["DEFAULT_CORNER"]
    cfg.write_text(json.dumps(doc))
    with pytest.raises(C.Refusal) as exc:
        _import(proj2)
    assert exc.value.code == "LL_IMPORT_NO_NOMINAL_CORNER"
    _nothing_written(proj2)


def test_a_log_the_flow_does_not_name_is_not_a_source_log(tmp_path):
    """A stray log beside the routed DEF is not a transcript the flow named,
    so the witness does not cite it and the row does not list it."""
    proj = _project(tmp_path)
    (proj / RUN_REL / "44-openroad-detailedrouting/notes.log").write_text("x\n")
    doc = _import(proj)
    routed = next(r for r in _rows_of(doc)
                  if r["canonical_path"] == "phase3/stage3/pnr/routed.def")
    assert [l["path"] for l in routed["source_logs"]] == \
        ["44-openroad-detailedrouting/openroad-detailedrouting.log"]


# ── review W6 wave 6 ──────────────────────────────────────────────────────

def _block(lines, needle):
    """(start, end) of a top-level step's block in flow.log lines."""
    i = _at(lines, needle)
    j = next((k for k in range(i + 1, len(lines))
              if lines[k].startswith("Running '") and "/" not in
              lines[k].split("runs/cmp3/", 1)[1].split("'")[0]), len(lines))
    return i, j


def test_a_to_less_run_that_was_cut_short_is_refused(tmp_path):
    """LibreLane --to X still prints `Flow complete.`; the steps after X are
    `Skipping step` lines. Without a declared `to`, such a run used to import
    as final with the rest read as steps the flow does not do."""
    import librelane_contract as C
    proj = _project(tmp_path)
    lines = _flow_lines(proj)
    _, end = _block(lines, "'OpenROAD.DetailedRouting'")
    later = [l.split("'")[1] for l in lines[end:]
             if l.startswith("Running '") and "/" not in
             l.split("runs/cmp3/", 1)[1].split("'")[0]]
    closing = [l for l in lines if l.startswith(("Saving views", "Flow complete."))]
    (proj / RUN_REL / "flow.log").write_text("".join(
        lines[:end] + [f"Skipping step '{n}'…\n" for n in later] + closing))
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_RUN_CUT_SHORT"
    assert "stopped after OpenROAD.DetailedRouting" in str(exc.value)
    _nothing_written(proj)


def test_a_run_with_a_skipped_step_is_refused(tmp_path):
    """--skip prints `Skipping step` between two started steps."""
    import librelane_contract as C
    proj = _project(tmp_path)
    lines = _flow_lines(proj)
    i, j = _block(lines, "'Netgen.LVS'")
    (proj / RUN_REL / "flow.log").write_text(
        "".join(lines[:i] + ["Skipping step 'LVS'…\n"] + lines[j:]))
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_STEPS_SKIPPED"
    assert "LVS" in str(exc.value)
    _nothing_written(proj)


def test_a_rule_step_gated_off_is_refused_not_listed_as_not_performed(tmp_path):
    """RUN_LVS=false: LibreLane prints its gating notice and skips. The flow
    performs LVS; this run's config turned it off."""
    import librelane_contract as C
    proj = _project(tmp_path)
    lines = _flow_lines(proj)
    i, j = _block(lines, "'Netgen.LVS'")
    (proj / RUN_REL / "flow.log").write_text("".join(
        lines[:i]
        + ["Gating variable for step 'Netgen.LVS' set to 'False'- the step "
           "will be skipped.\n", "Skipping step 'LVS'…\n"] + lines[j:]))
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_RULE_STEP_GATED"
    assert "Netgen.LVS" in str(exc.value)
    _nothing_written(proj)


def test_the_gated_steps_of_a_real_run_are_recorded(tmp_path):
    proj = _project(tmp_path)
    doc = _import(proj)
    assert doc["flow_status"]["gated"] == [
        "OpenROAD.RepairDesignPostGRT", "Odb.HeuristicDiodeInsertion",
        "OpenROAD.ResizerTimingPostGRT", "Yosys.EQY"]
    assert doc["flow_status"]["from_cut"] is False
    assert doc["flow_status"]["to_cut"] is False


def test_a_deferred_checker_error_is_blamed_not_the_last_step(tmp_path):
    """Every step ran and LibreLane withheld `Flow complete.` because a
    checker deferred its error: the refusal names that checker."""
    import librelane_contract as C
    proj = _project(tmp_path)
    lines = _flow_lines(proj)
    i = _at(lines, "'Checker.TrDRC'")
    lines = [l for l in lines if not l.startswith("Flow complete.")]
    lines.insert(i + 1, "2 Routing DRC errors found. - deferred\n")
    (proj / RUN_REL / "flow.log").write_text("".join(lines))
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    msg = str(exc.value)
    assert exc.value.code == "LL_IMPORT_FLOW_INCOMPLETE"
    folder = lines[i].split("runs/cmp3/", 1)[1].split("'")[0]
    assert f"Checker.TrDRC at {folder}: 2 Routing DRC errors found." in msg, msg
    assert "every step returned" in msg
    assert "Misc.ReportManufacturability" not in msg
    _nothing_written(proj)


def test_a_lone_mid_flow_segment_is_refused(tmp_path):
    """Segment 2 alone (--from): the steps before it are in no segment."""
    import librelane_contract as C
    import librelane_import as LI
    proj = _segment_project(tmp_path)
    with pytest.raises(C.Refusal) as exc:
        LI.import_run(proj, proj / SEG2)
    assert exc.value.code == "LL_IMPORT_STARTS_MID_FLOW"
    _nothing_written(proj)


def test_segments_may_name_different_tops(tmp_path):
    """The Chip flow: segment 1 synthesizes the core, segment 2 lays out the
    chip top. Each rule names its destinations by its segment's top."""
    import librelane_import as LI
    proj = _segment_project(tmp_path)
    (proj / SEG2 / "resolved.json").write_text('{"DESIGN_NAME": "chip_x"}\n')
    doc = LI.import_segments(proj, [(proj / SEG1, SEG1_END), (proj / SEG2, None)])
    assert doc["top"] == "chip_x" and doc["tops"] == ["spm", "chip_x"]
    assert [s["flow_status"]["design_name"] for s in doc["segments"]] == \
        ["spm", "chip_x"]
    got = {r["canonical_path"] for r in _rows_of(doc)}
    for rel in ("phase3/stage4/gds/chip_x.gds", "phase3/stage3/extracted/chip_x.spef",
                "phase3/stage3/extracted/spef_corners/chip_x.nom.spef",
                "phase3/stage4/hardmacro/chip_x.lef",
                "phase2/stage2/synth/netlist.v"):
        assert rel in got, rel
    assert not any("/spm." in p for p in got), sorted(got)


def test_a_previous_manifest_that_does_not_validate_deletes_nothing(tmp_path):
    """Its canonical paths decide what a re-import removes; a path W0's
    validator rejects ('..' out of the project) is never acted on."""
    import librelane_contract as C
    proj = _project(tmp_path)
    _import(proj)
    precious = tmp_path / "outside_precious.txt"
    precious.write_text("keep\n")
    man = proj / MANIFEST
    doc = json.loads(man.read_text())
    doc["rows"].append(dict(doc["rows"][0], canonical_path="../outside_precious.txt"))
    man.write_text(json.dumps(doc))
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_MANIFEST_UNREADABLE"
    assert precious.read_text() == "keep\n"


def test_a_previous_manifest_cannot_claim_the_importers_provenance(tmp_path):
    import librelane_contract as C
    proj = _project(tmp_path)
    _import(proj)
    provenance = proj / "provenance.jsonl"
    before = provenance.read_bytes()
    man = proj / MANIFEST
    doc = json.loads(man.read_text())
    doc["rows"].append(dict(doc["rows"][0], canonical_path="provenance.jsonl"))
    man.write_text(json.dumps(doc))
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_MANIFEST_UNREADABLE"
    assert provenance.read_bytes() == before


def test_a_previous_manifest_cannot_claim_another_segments_run_tree(tmp_path):
    import librelane_contract as C
    import librelane_import as LI
    proj = _segment_project(tmp_path)
    LI.import_segments(proj, [(proj / SEG1, SEG1_END), (proj / SEG2, None)])
    resolved = proj / SEG2 / "resolved.json"
    before = resolved.read_bytes()
    man = proj / MANIFEST
    doc = json.loads(man.read_text())
    doc["segments"][0]["rows"].append(dict(
        doc["segments"][0]["rows"][0],
        canonical_path=resolved.relative_to(proj).as_posix()))
    man.write_text(json.dumps(doc))
    with pytest.raises(C.Refusal) as exc:
        LI.import_segments(proj, [(proj / SEG1, SEG1_END), (proj / SEG2, None)])
    assert exc.value.code == "LL_IMPORT_MANIFEST_UNREADABLE"
    assert resolved.read_bytes() == before


def test_a_stale_canonical_changed_since_import_is_not_deleted(tmp_path):
    import librelane_contract as C
    proj = _project(tmp_path)
    _import(proj)
    stale = proj / "phase3/stage4/gds/spm.gds"
    stale.write_text("written by someone else\n")
    (proj / RUN_REL / "resolved.json").write_text('{"DESIGN_NAME": "renamed"}\n')
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_STALE_CANONICAL"
    assert stale.read_text() == "written by someone else\n"


def test_a_previous_manifest_cannot_claim_matching_hash_design_input(tmp_path):
    import _external_flow_manifest as M
    import librelane_contract as C
    proj = _project(tmp_path)
    _import(proj)
    input_file = proj / "input/phase1_prompt.md"
    input_file.parent.mkdir(parents=True)
    input_file.write_text("owner supplied design input\n")
    original = input_file.read_bytes()
    man = proj / MANIFEST
    doc = json.loads(man.read_text())
    doc["rows"].append(dict(
        doc["rows"][0], canonical_path=input_file.relative_to(proj).as_posix(),
        canonical_sha256="sha256:" + _sha(input_file),
        tool_run_sha256="sha256:" + _sha(input_file)))
    man.write_text(json.dumps(doc))
    assert M.validate_manifest(doc, proj, verify_disk=False) == []
    try:
        _import(proj)
    except C.Refusal as exc:
        assert exc.code == "LL_IMPORT_MANIFEST_UNREADABLE"
    else:
        assert input_file.is_file(), "a design input was deleted by re-import"
    assert input_file.read_bytes() == original


def test_a_previous_row_cannot_claim_another_rules_destination(tmp_path):
    import librelane_contract as C
    proj = _project(tmp_path)
    _import(proj)
    stale = proj / "phase3/stage3/pnr/padring.def"
    stale.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(proj / "phase3/stage3/pnr/floorplan.def", stale)
    original = stale.read_bytes()
    man = proj / MANIFEST
    doc = json.loads(man.read_text())
    floorplan = next(r for r in doc["rows"]
                     if r["canonical_path"] == "phase3/stage3/pnr/floorplan.def")
    doc["rows"].append(dict(floorplan,
                            canonical_path=stale.relative_to(proj).as_posix()))
    man.write_text(json.dumps(doc))
    with pytest.raises(C.Refusal) as exc:
        _import(proj)
    assert exc.value.code == "LL_IMPORT_MANIFEST_UNREADABLE"
    assert stale.read_bytes() == original


def test_a_missing_old_canonical_is_not_reported_as_removed(tmp_path):
    proj = _project(tmp_path)
    _import(proj)
    stale = proj / "phase3/stage4/gds/spm.gds"
    stale.unlink()
    (proj / RUN_REL / "resolved.json").write_text('{"DESIGN_NAME": "renamed"}\n')
    doc = _import(proj)
    assert stale.relative_to(proj).as_posix() not in doc["removed"]
    assert (proj / "phase3/stage4/gds/renamed.gds").is_file()


def test_a_previous_manifest_must_bind_the_tool_run_source(tmp_path):
    import librelane_contract as C
    proj = _project(tmp_path)
    _import(proj)
    man = proj / MANIFEST
    doc = json.loads(man.read_text())
    row = doc["rows"][0]
    row["canonical_sha256"] = row["tool_run_sha256"] = "sha256:" + "0" * 64
    man.write_text(json.dumps(doc))
    tampered = man.read_bytes()
    try:
        _import(proj)
    except C.Refusal as exc:
        assert exc.code == "LL_IMPORT_MANIFEST_UNREADABLE"
    else:
        assert man.read_bytes() == tampered, "re-import accepted the forged hash"
