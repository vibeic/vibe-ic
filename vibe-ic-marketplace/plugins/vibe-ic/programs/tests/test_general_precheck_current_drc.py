"""The real precheck DRC consumer reads the retained native current subject.

Small source-control GDS and recorded native parser artifacts only: no physical
EDA measurement is claimed. The shared direct-half writer/reader, immutable
publication writer and delegated drc_report_check CLI are real and unmocked.
"""
import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _physical_current as current
import general_precheck as GP
import phase3_one_shot_runner as P3
from _hostpaths import repo_path
from test_general_precheck import _die_at_origin


def _put(project, rel, body):
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def _fixture(project, violations=0):
    gds = _die_at_origin(project / "phase3/stage3/pnr/chip_top.gds")
    _put(project, "phase3/stage3/pnr/chip_top.def",
         "VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n")
    _put(project, "phase3/stage3/pnr/chip_top_pnr.v",
         "module chip_top(); endmodule\n")
    _put(project, "state_out.json", json.dumps({
        "gds": gds.relative_to(project).as_posix(),
        "def": "phase3/stage3/pnr/chip_top.def",
        "nl": "phase3/stage3/pnr/chip_top_pnr.v"}))
    tech = _put(project, "input/pdk/tech.lef", "VERSION 5.8 ;\nEND LIBRARY\n")
    cells = _put(project, "input/pdk/cells.lef", "VERSION 5.8 ;\nEND LIBRARY\n")
    deck = _put(project, "input/pdk/deck.lydrc", "# neutral parser-control recipe\n")
    _put(project, "reports/phase3/technology_units.json", json.dumps({"pdk": "neutral"}))
    native = project / "phase3/reports/drc.rpt"
    native.parent.mkdir(parents=True, exist_ok=True)
    log = native.with_suffix(".log")
    report = project / "reports/phase3/drc_signoff.rpt"
    transcript = report.with_suffix(".log")
    artifacts = repo_path("vibe-ic-marketplace", "plugins", "vibe-ic",
                          "programs", "tests", "fixtures", "drc_native_input_binding")

    def producer():
        body = (artifacts / "zero.xml").read_text().replace(
            "<top-cell>spm</top-cell>", "<top-cell>chip_top</top-cell>")
        if violations:
            body = body.replace("<categories>", "<categories><category><name>met2.short</name></category>", 1)
            body = body.replace("<items>", "<items><item><category>met2.short</category>"
                                "<cell>chip_top</cell><values><value>box: (0,0;1,1)</value>"
                                "</values></item>", 1)
        native.write_text(body)
        log.write_text((artifacts / "terminal.log").read_text().replace(
            "(0 violations)", f"({violations} violations)"))
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_bytes(native.read_bytes())
        transcript.write_bytes(log.read_bytes())
        invocation = {"record": "invocation", "measured": True, "tool": "klayout",
                      "exit_code": 0, "command": f"klayout -b -r {deck}",
                      "scope": "SOURCE_CONTROL recorded parser artifacts, no native EDA",
                      "inputs": P3._hash_declared_outputs(project, [gds, deck]),
                      "outputs": P3._hash_declared_outputs(project, [native, log])}
        with (project / "provenance.jsonl").open("a") as stream:
            stream.write(json.dumps(invocation) + "\n")
        assert P3._declare_immutable_transform(
            project, native, report, "drc:signoff", "phase3_one_shot_runner",
            "publish the unchanged native DRC report as canonical signoff")
        return SimpleNamespace(status="PASS", detail="source-control native leaf",
                               reason_class=None, extras={})

    row = current.direct_half(project, "chip_top", SimpleNamespace(
        name="neutral", tech_lef=tech, cell_lef=cells, drc_deck=deck), "drc", producer)
    assert row.extras["current_reader"]["verdict"] == "CURRENT", row.detail
    final = project / "phase3/stage4/gds/finished.gds"
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(gds.read_bytes())
    return final


def _consume(project, gds):
    step = next(step for step in GP.LADDER if step.step_id == "Checker.KLayoutDRC")
    evidence = GP._blank(step)
    GP._step_delegate(evidence, step, project, GP.default_runner, GP._HERE, 60,
                      layout=gds)
    return {"verdict": evidence.verdict, "evidence": evidence.evidence,
            "returncode": evidence.returncode, "measured": evidence.measured}


def test_current_native_drc_publication_reaches_the_actual_precheck_consumer(tmp_path):
    project = tmp_path / "current"
    gds = _fixture(project)
    current_path = project / "reports/phase3/direct_current_drc.json"
    subject = json.loads(current_path.read_text())
    entries = [json.loads(line) for line in (project / "provenance.jsonl").read_text().splitlines()]
    assert entries[-1]["record"] == "declared_transform"
    observed = {"scope": "Real precheck consumer -> delegated drc_report_check CLI; no native EDA",
                "positive": _consume(project, gds), "refusals": {}}
    observation = tmp_path / "CURRENT_DRC_PRECHECK_OBSERVATION.json"
    observation.write_text(json.dumps(observed, indent=2) + "\n")
    assert observed["positive"]["verdict"] == GP.PASS, observed["positive"]
    assert observed["positive"]["returncode"] == 0
    for damage in ("gds", "report", "log", "recipe", "native", "source",
                   "current_record", "rc", "engine"):
        with_project = tmp_path / damage
        shutil.copytree(project, with_project)
        changed_gds = with_project / gds.relative_to(project)
        record_path = with_project / current_path.relative_to(project)
        # File roles are project-relative; the native command is retained data,
        # not executed by any of these consumers.
        if damage == "gds":
            changed_gds.write_bytes(changed_gds.read_bytes() + b"changed")
        elif damage == "report":
            (with_project / "reports/phase3/drc_signoff.rpt").write_text("changed")
        elif damage == "log":
            (with_project / "reports/phase3/drc_signoff.log").write_text("changed")
        elif damage in ("recipe", "source"):
            role = "pdk_deck" if damage == "recipe" else "pdk_cell_lef"
            (with_project / subject["inputs"][role]["path"]).write_text("changed")
        elif damage == "current_record":
            record_path.write_text("{}")
        else:
            record = json.loads(record_path.read_text())
            native = copy.deepcopy(record["execution"]["native_invocation"])
            if damage == "native":
                (with_project / "provenance.jsonl").write_text(json.dumps(entries[-1]) + "\n")
            else:
                if damage == "rc":
                    native["exit_code"] = 1
                else:
                    native["tool"] = "magic"
                    record["tool"] = "magic"
                record["execution"]["native_invocation"] = native
                record_path.write_text(json.dumps(record))
                (with_project / "provenance.jsonl").write_text(
                    json.dumps(native) + "\n" + json.dumps(entries[-1]) + "\n")
        observed["refusals"][damage] = _consume(with_project, changed_gds)
        observation.write_text(json.dumps(observed, indent=2) + "\n")
        assert observed["refusals"][damage]["verdict"] != GP.PASS, (damage, observed)
    dirty = tmp_path / "measured_violation"
    dirty_gds = _fixture(dirty, violations=1)
    observed["measured_violation"] = _consume(dirty, dirty_gds)
    observation.write_text(json.dumps(observed, indent=2) + "\n")
    assert observed["measured_violation"]["verdict"] == GP.FAIL, observed
