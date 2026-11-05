"""A failed native PSM run cannot inherit an earlier segment screen."""
import json

import phase3_one_shot_runner as R


def _project(tmp_path):
    project = tmp_path / "project"
    pnr = project / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    (pnr / "subservient.def").write_text(
        "VERSION 5.8 ;\nSPECIALNETS 1 ;\n"
        "- VP + USE POWER ;\nEND SPECIALNETS\nEND DESIGN\n")
    return project


def test_postcheck_refuses_failed_native_even_with_fresh_report_and_stale_pass(tmp_path):
    project = _project(tmp_path)
    reports = project / "reports/phase3"
    reports.mkdir(parents=True)
    called = []

    def failed_native(_project, _top, _pdk, _container, _ir, em, notes):
        em.write_text("OpenROAD PSM invocation failed: rc=1\n")
        notes.append("native execution rc=1")
        return False, False

    def stale_authority(_project, _pdk, _container, _notes):
        called.append(True)
        (reports / "em_current_authority.json").write_text(
            json.dumps({"verdict": "PASS"}))
        return True

    verdict, reason = R._ppa_power._pdn_em_post_resize_check(
        project, "subservient", object(), "test", failed_native,
        stale_authority)
    assert verdict == "NOT_MEASURED"
    assert reason.startswith("PDN_EM_POSTCHECK_NATIVE_UNMEASURED")
    assert called == []
