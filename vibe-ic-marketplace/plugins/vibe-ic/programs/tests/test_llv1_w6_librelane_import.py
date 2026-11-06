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
MANIFEST = "reports/phase3/impl/import_manifest.json"      # W0's path




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
    witnessed = {(w["run_dir"], w["step_dir"]): {l["path"] for l in w["logs"]}
                 for w in (r.get("witness") for r in _rows(proj)) if w}
    no_log = []
    # only the STA summaries, which LibreLane's Python assembles from the
    # corners, have no transcript of their own; and the imported StreamOut
    # transcript, which cannot witness its own run (W0's validate_row)
    assert sorted(no_log) == ["12-openroad-staprepnr/summary.rpt",
                              "55-openroad-stapostpnr/summary.rpt",
                              "57-magic-streamout/magic-streamout.log"]
    manifest = json.loads((proj / MANIFEST)
                          .read_text())


def test_the_canonical_views_land_where_the_gates_read_them(tmp_path):
    proj = _project(tmp_path)
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
    # A corner folder holds two transcripts the flow names (sta.log and
    # filter_unannotated.log): both are listed, rather than one guessed.
    # the nominal SPEF is the same tool file as the nom corner
    # LibreLane's own sign-off reports never take a vibe-ic sign-off name
    assert not (proj / "reports/phase3/drc_signoff.rpt").exists()
    assert not (proj / "reports/phase3/lvs.rpt").exists()


def test_a_step_this_flow_did_not_run_is_listed_not_invented(tmp_path):
    proj = _project(tmp_path)
    assert not (proj / "phase3/stage3/pnr/padring.def").exists()




# ── provenance ────────────────────────────────────────────────────────────



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
    rows = _rows(proj)
    _assert_witnessed_population(rows)
    swapped = [dict(r) for r in rows if r.get("step") != "Magic.DRC"]
    replacement = dict(next(r for r in rows if r.get("step") == "Magic.DRC"),
                       step="OpenROAD.UnrelatedReport")
    swapped.append(replacement)
    assert sum(r.get("reconstructed") is False for r in swapped) == 17
    with pytest.raises(AssertionError):
        _assert_witnessed_population(swapped)




def test_the_assembled_openroad_log_cites_every_section(tmp_path):
    proj = _project(tmp_path)
    text = (proj / "phase3/stage3/pnr/openroad.log").read_text()
    stages = re.findall(r"^PNR_STAGE: (\S+)$", text, re.M)
    assert stages == ["floorplan", "placement", "cts", "hold_repair",
                      "global_route", "detailed_route"]
    sections = re.findall(
        r"^# >>> LIBRELANE (\S+) (\S+) sha256:([0-9a-f]{64})\n(.*?)"
        r"^# <<< LIBRELANE \1\n", text, re.M | re.S)
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
    for p in (dest, rpt):
        assert p.is_file() and not p.is_symlink(), p
    assert elsewhere.read_text() == "not the routed design\n"




# ── a run LibreLane did not finish is never imported (review W6 MAJOR) ─────









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




def test_two_segments_import_as_one_tree(tmp_path):
    proj = _segment_project(tmp_path)
    doc = json.loads((proj / MANIFEST).read_text())
    assert [(s["name"], s["run_dir"]) for s in doc["segments"]] == \
        [("segment-1", SEG1), ("segment-2", SEG2)]
    assert "run_dir" not in doc and "rows" not in doc
    assert [s["flow_status"]["to"] for s in doc["segments"]] == [SEG1_END, None]
    # not_performed over the union: only the step neither segment ran
    assert [n["tool_step"] for n in doc["not_performed"]] == ["OpenROAD.PadRing"]






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
    top = proj / RUN_REL / "34-openroad-detailedplacement/spm.def"
    assert _sha(proj / "phase3/stage3/pnr/placed.def") == _sha(top)




# ── all or nothing, and no stale file (review W6 MINORs) ──────────────────



def test_a_failure_while_writing_restores_every_path(tmp_path, monkeypatch):
    import librelane_contract as C
    proj = _project(tmp_path)
    placed = proj / "phase3/stage3/pnr/placed.def"
    placed.parent.mkdir(parents=True)
    placed.write_text("the previous placement\n")
    (proj / "provenance.jsonl").write_text('{"earlier": 1}\n')

    assert placed.read_text() == "the previous placement\n"
    assert (proj / "provenance.jsonl").read_text() == '{"earlier": 1}\n'
    _nothing_written(proj, ["phase3/stage3/pnr/placed.def", "provenance.jsonl"])


def test_an_import_over_another_runs_import_is_refused(tmp_path):
    import librelane_contract as C
    proj = _project(tmp_path)
    before = {p: _sha(proj / p) for p in _canonical(proj)}
    other = proj / "phase3/librelane/runs_b/cmp3"
    shutil.copytree(FIXTURES / "8HD-9" / "runs" / "cmp3", other)
    assert {p: _sha(proj / p) for p in _canonical(proj)} == before


def test_a_reimport_removes_what_the_same_runs_no_longer_perform(tmp_path):
    """An earlier top's actual imported output is removed after a top change."""
    proj = _project(tmp_path)
    stale = proj / "phase3/stage4/gds/spm.gds"
    assert stale.is_file()
    (proj / RUN_REL / "resolved.json").write_text('{"DESIGN_NAME": "renamed"}\n')
    assert not stale.exists()
    assert (proj / "phase3/stage4/gds/renamed.gds").is_file()






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
    assert _sha(proj / "phase3/stage3/extracted/spm.spef") == corners[key]






# ── review W6 wave 6 ──────────────────────────────────────────────────────

def _block(lines, needle):
    """(start, end) of a top-level step's block in flow.log lines."""
    i = _at(lines, needle)
    j = next((k for k in range(i + 1, len(lines))
              if lines[k].startswith("Running '") and "/" not in
              lines[k].split("runs/cmp3/", 1)[1].split("'")[0]), len(lines))
    return i, j
















def test_a_previous_manifest_that_does_not_validate_deletes_nothing(tmp_path):
    """Its canonical paths decide what a re-import removes; a path W0's
    validator rejects ('..' out of the project) is never acted on."""
    import librelane_contract as C
    proj = _project(tmp_path)
    precious = tmp_path / "outside_precious.txt"
    precious.write_text("keep\n")
    man = proj / MANIFEST
    doc = json.loads(man.read_text())
    doc["rows"].append(dict(doc["rows"][0], canonical_path="../outside_precious.txt"))
    man.write_text(json.dumps(doc))
    assert precious.read_text() == "keep\n"


def test_a_previous_manifest_cannot_claim_the_importers_provenance(tmp_path):
    import librelane_contract as C
    proj = _project(tmp_path)
    provenance = proj / "provenance.jsonl"
    before = provenance.read_bytes()
    man = proj / MANIFEST
    doc = json.loads(man.read_text())
    doc["rows"].append(dict(doc["rows"][0], canonical_path="provenance.jsonl"))
    man.write_text(json.dumps(doc))
    assert provenance.read_bytes() == before


def test_a_previous_manifest_cannot_claim_another_segments_run_tree(tmp_path):
    import librelane_contract as C
    proj = _segment_project(tmp_path)
    resolved = proj / SEG2 / "resolved.json"
    before = resolved.read_bytes()
    man = proj / MANIFEST
    doc = json.loads(man.read_text())
    doc["segments"][0]["rows"].append(dict(
        doc["segments"][0]["rows"][0],
        canonical_path=resolved.relative_to(proj).as_posix()))
    man.write_text(json.dumps(doc))
    assert resolved.read_bytes() == before


def test_a_stale_canonical_changed_since_import_is_not_deleted(tmp_path):
    import librelane_contract as C
    proj = _project(tmp_path)
    stale = proj / "phase3/stage4/gds/spm.gds"
    stale.write_text("written by someone else\n")
    (proj / RUN_REL / "resolved.json").write_text('{"DESIGN_NAME": "renamed"}\n')
    assert stale.read_text() == "written by someone else\n"


def test_a_previous_manifest_cannot_claim_matching_hash_design_input(tmp_path):
    import librelane_contract as C
    proj = _project(tmp_path)
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
    assert input_file.read_bytes() == original


def test_a_previous_row_cannot_claim_another_rules_destination(tmp_path):
    import librelane_contract as C
    proj = _project(tmp_path)
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
    assert stale.read_bytes() == original


def test_a_missing_old_canonical_is_not_reported_as_removed(tmp_path):
    proj = _project(tmp_path)
    stale = proj / "phase3/stage4/gds/spm.gds"
    stale.unlink()
    (proj / RUN_REL / "resolved.json").write_text('{"DESIGN_NAME": "renamed"}\n')
    assert (proj / "phase3/stage4/gds/renamed.gds").is_file()
