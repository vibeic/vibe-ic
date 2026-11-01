import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import eda_report_audit as audit


def _write(project, name, text):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _report(count=0, *, producer="KLayout DRC"):
    return (
        f"{producer}\n"
        "spacing and enclosure checks\n"
        f"{count} violations total\n"
        + "# synthetic report detail\n" * 100
    )


def _declare(project, report, *, log=None):
    source = _write(project, "native/" + report.name, report.read_text())
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    outputs = {str(source.relative_to(project)): digest}
    if log is not None:
        outputs[str(log.relative_to(project))] = (
            "sha256:" + hashlib.sha256(log.read_bytes()).hexdigest()
        )
    records = [
        {"record": "invocation", "tool": "klayout", "measured": True,
         "exit_code": 0, "inputs": {}, "outputs": outputs},
        {"record": "declared_transform", "tool": "phase3_one_shot_runner",
         "producing_step": "drc:signoff", "exit_code": 0,
         "inputs": {str(source.relative_to(project)): digest},
         "outputs": {str(report.relative_to(project)): digest}},
    ]
    with (project / "provenance.jsonl").open("a") as stream:
        stream.writelines(json.dumps(record) + "\n" for record in records)
    return source


def _converter(project):
    return _write(
        project, "run/52-klayout-density/xml_drc_report_to_json.log",
        "%OL_METRIC_I klayout__density_error__count 0\n",
    )


def test_clean_declared_report_ignores_density_converter_log(tmp_path):
    report = _write(tmp_path, "reports/phase3/drc_signoff.rpt", _report())
    converter = _converter(tmp_path)
    _declare(tmp_path, report, log=converter)

    result = audit._check_drc(tmp_path)

    assert result.passed is True
    assert result.summary["files_found"] == 1
    assert result.summary["real_violation_total"] == 0
    assert not any(f.severity == "ERROR" for f in result.findings)


def test_declared_real_violations_still_fail_beside_converter(tmp_path):
    report = _write(tmp_path, "reports/phase3/drc_signoff.rpt", _report(7))
    _declare(tmp_path, report, log=_converter(tmp_path))

    result = audit._check_drc(tmp_path)

    assert result.passed is False
    assert result.summary["real_violation_total"] == 7
    assert any(f.rule == "DRC_REAL_VIOLATIONS_FOUND" for f in result.findings)


@pytest.mark.parametrize("damage", ["unreadable", "truncated"])
def test_declared_damaged_report_cannot_hide_behind_clean_sibling(tmp_path, damage):
    clean = _write(tmp_path, "reports/phase3/drc_signoff.rpt", _report())
    _declare(tmp_path, clean)
    damaged = _write(tmp_path, "reports/secondary/check-result.lyrdb", _report(1))
    source = _declare(tmp_path, damaged)
    source.unlink()
    if damage == "unreadable":
        damaged.unlink()
        damaged.symlink_to(tmp_path / "missing-output")
    else:
        damaged.write_text("<report-database><items><item>")

    result = audit._check_drc(tmp_path)

    assert result.passed is False
    assert any(f.rule == "DRC_REPORT_NOT_READABLE" for f in result.findings)


def test_converter_without_declared_reports_is_no_report(tmp_path):
    _converter(tmp_path)
    _write(tmp_path, "unclaimed_drc.rpt", _report())

    result = audit._check_drc(tmp_path)

    assert result.passed is False
    assert result.summary["files_found"] == 0
    assert any(f.rule == "DRC_REPORT_EXISTS" and "No DRC report found" in f.message
               for f in result.findings)


def test_declared_lyrdb_identity_does_not_need_drc_in_its_name(tmp_path):
    report = _write(tmp_path, "reports/geometry.lyrdb", (
        '<?xml version="1.0"?>\n<report-database>\n'
        "<generator>klayout drc: script='rules.drc'</generator>\n"
        "<categories><category><name>spacing</name></category></categories>\n"
        "<items><item><category>spacing</category></item></items>\n"
        "<!-- " + "synthetic rule detail " * 100 + " -->\n"
        "</report-database>\n"
    ))
    _declare(tmp_path, report)

    result = audit._check_drc(tmp_path)

    assert result.passed is False
    assert result.summary["files_found"] == 1
    assert result.summary["real_violation_total"] == 1


@pytest.mark.parametrize("with_final", [True, False])
def test_named_router_iteration_defers_only_to_selected_final(tmp_path, with_final):
    iteration = _write(tmp_path, "routed_router.drc.iter1.rpt",
                       _report(8, producer="OpenROAD detailed_route"))
    final = _write(tmp_path, "routed_router.drc.rpt",
                   _report(producer="OpenROAD detailed_route"))
    subjects = [iteration, final] if with_final else [iteration]

    with audit.named_subjects(subjects):
        result = audit._check_drc(tmp_path)

    assert result.passed is with_final
    assert result.summary["real_violation_total"] == (0 if with_final else 8)
    assert result.summary["ignored_intermediate_reports"] == (
        [iteration.name] if with_final else []
    )


def test_current_report_roles_exclude_transcript_with_real_report_artifact(tmp_path):
    from _hostpaths import repo_path

    fixture = repo_path("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                        "tests", "fixtures", "drc_native_input_binding", "zero.xml")
    report = _write(tmp_path, "reports/geometry.lyrdb", fixture.read_text())
    native = _write(tmp_path, "native/geometry.lyrdb", fixture.read_text())
    log = _converter(tmp_path)
    _write(tmp_path, "reports/phase3/direct_current_drc.json", json.dumps({
        "outputs": {role: {"path": str(path.relative_to(tmp_path))}
                    for role, path in (("report", report), ("native_report", native),
                                       ("log", log))},
    }))

    result = audit._check_drc(tmp_path)

    assert result.summary["files_found"] == 1
    assert result.summary["unreadable_files"] == 0
    assert result.summary["real_violation_total"] == 0
    assert result.subject_files == [str(report)]


@pytest.mark.parametrize("damaged", [False, True])
def test_native_pv_uses_existing_producer_report_identity(tmp_path, damaged):
    from analog_a6_librelane_drc import ENGINES

    step, metric, basename = ENGINES[0]
    folder = Path("phase3/librelane/31-drc/01-producer")
    report = _write(tmp_path, str(folder / "reports" / basename),
                    "<report-database><items>" if damaged else _report())
    converter = _converter(tmp_path)
    _write(tmp_path, "reports/phase3/librelane_pv_drc.json", json.dumps({
        "metrics": {metric: {"step": step, "folder": str(folder)},
                    "klayout__density_error__count": {
                        "step": "KLayout.Density", "folder": str(converter.parent)}},
    }))

    result = audit._check_drc(tmp_path)

    assert result.passed is (not damaged)
    assert result.summary["files_found"] == 1
    assert result.summary["unreadable_files"] == int(damaged)
    assert result.subject_files == [str(report)]


@pytest.mark.parametrize("with_final", [True, False])
def test_recorded_router_iteration_is_a_subject_without_explicit_cli(tmp_path, with_final):
    iteration = _write(tmp_path, "phase3/stage3/pnr/routed_router.drc.iter1.rpt",
                       _report(8, producer="OpenROAD detailed_route"))
    _write(tmp_path, "reports/orchestrator/phase3_one_shot.json", json.dumps({
        "program": "phase3_one_shot_runner",
        "steps": [{"name": "pnr", "extras": {"resize_history": [{
            "router_drc_report": str(iteration), "iteration": 1,
        }]}}],
    }))
    if with_final:
        from phase3_one_shot_runner import _write_router_drc_receipt

        final = _write(tmp_path, "phase3/stage3/pnr/routed_router.drc.rpt",
                       _report(producer="OpenROAD detailed_route"))
        log = ("[INFO DRT-0195] Start detail routing.\n"
               "[INFO DRT-0199] Number of violations = 0.\n"
               "[INFO DRT-0198] Complete detail routing.\n")
        _write(tmp_path, "phase3/stage3/pnr/openroad.log", log)
        routed = _write(tmp_path, "phase3/stage3/pnr/routed.def",
                        "VERSION 5.8 ;\nDESIGN widget ;\nEND DESIGN\n")
        assert _write_router_drc_receipt(final.parent, routed, log)

    result = audit._check_drc(tmp_path)

    assert result.passed is with_final
    assert result.summary["real_violation_total"] == (0 if with_final else 8)
    assert result.summary["files_found"] == 1
    assert result.summary["ignored_intermediate_reports"] == (
        [str(iteration.relative_to(tmp_path))] if with_final else []
    )


def test_declared_identity_cannot_select_a_parent_directory_report(tmp_path):
    project = tmp_path / "subject"
    report = _write(project, "reports/phase3/drc_signoff.rpt", _report())
    _declare(project, report)
    _write(tmp_path, "foreign_drc.rpt", _report(7))
    _write(project, "reports/phase3/direct_current_drc.json", json.dumps({
        "outputs": {"native_report": {"path": "../foreign_drc.rpt"}},
    }))

    result = audit._check_drc(project)

    assert result.passed is True
    assert result.summary["files_found"] == 1
    assert result.summary["real_violation_total"] == 0
