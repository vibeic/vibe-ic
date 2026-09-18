"""A resumed Phase 3 must not revive a rejected delivery via stale routers.

Tiny neutral inputs exercise the real CLI admission and the real flow's route
conditions. PDK discovery is a recording stop: no EDA or netlists are used.
"""
import json
from types import SimpleNamespace

import pytest

import _owner_declared as OD
import _submission_template as ST
import _tapeout_declaration as TD
import phase3_one_shot_runner as R


def _write(project, rel, doc):
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


def _project(project, delivery="DIE"):
    doc = OD.attest({"answers": {"deliverable": delivery}})
    _write(project, ST.DESIGN_ANSWERS_REL, doc)
    _write(project, TD.DECLARATION_REL, doc)
    router = (TD.SELF_TAPEOUT_REL if delivery == "DIE"
              else ST.NO_TEMPLATE_REL)
    (project / router).write_text("fixture router\n")


def _main(project, monkeypatch):
    reached = []
    monkeypatch.setattr(R._runner_lock, "acquire_or_reenter", lambda *a: object())
    monkeypatch.setattr(R._canonical_admission, "admit_span",
                        lambda *a: SimpleNamespace(admitted=True))
    monkeypatch.setattr(R, "_detect_pdk", lambda *a: reached.append("PDK"))
    monkeypatch.setattr(R.sys, "argv", ["phase3_one_shot_runner.py", str(project)])
    return R.main(), reached


@pytest.mark.parametrize("fault", [
    "unattested_copy", "attested_old_answer", "changed_citation",
    "unattested_input", "unreadable_input", "missing_declaration",
    "unreadable_declaration", "no_router", "opposite_router", "both_routers",
])
def test_stale_delivery_stops_before_pdk(tmp_path, monkeypatch, capsys, fault):
    _project(tmp_path)
    if fault in {"unattested_copy", "attested_old_answer"}:
        old = {"answers": {"deliverable": "HARDMACRO"}}
        if fault == "attested_old_answer":
            OD.attest(old)
        _write(tmp_path, TD.DECLARATION_REL, old)
        (tmp_path / TD.SELF_TAPEOUT_REL).unlink()
        (tmp_path / ST.NO_TEMPLATE_REL).write_text("old router\n")
    elif fault == "changed_citation":
        doc = OD.attest({"answers": {"deliverable": "DIE"}})
        doc["answer_provenance"]["deliverable"]["citation"] = "new owner ruling"
        _write(tmp_path, ST.DESIGN_ANSWERS_REL, doc)
    elif fault == "unattested_input":
        _write(tmp_path, ST.DESIGN_ANSWERS_REL, {"answers": {"deliverable": "DIE"}})
    elif fault == "unreadable_input":
        (tmp_path / ST.DESIGN_ANSWERS_REL).write_text("{")
    elif fault == "missing_declaration":
        (tmp_path / TD.DECLARATION_REL).unlink()
    elif fault == "unreadable_declaration":
        (tmp_path / TD.DECLARATION_REL).write_text("{")
    elif fault == "no_router":
        (tmp_path / TD.SELF_TAPEOUT_REL).unlink()
    elif fault == "opposite_router":
        (tmp_path / TD.SELF_TAPEOUT_REL).unlink()
        (tmp_path / ST.NO_TEMPLATE_REL).write_text("old router\n")
    elif fault == "both_routers":
        (tmp_path / ST.NO_TEMPLATE_REL).write_text("old router\n")
    rc, reached = _main(tmp_path, monkeypatch)
    assert (rc, reached) == (2, []), "stale delivery must stop before PDK/EDA"
    report = json.loads((tmp_path / "reports/phase3/delivery_admission.json").read_text())
    assert report["verdict"] == "REFUSED"
    assert report["reason"] == "DELIVERY_AUTHORITY_STALE_OR_UNDECLARED"
    assert "step 0.5ic" in report["detail"]
    assert "DELIVERY_AUTHORITY_STALE_OR_UNDECLARED" in capsys.readouterr().err


def test_refused_declaration_cannot_fall_back_to_ip_marker(tmp_path):
    _project(tmp_path, "HARDMACRO")
    _write(tmp_path, ST.DESIGN_ANSWERS_REL,
           OD.attest({"answers": {"deliverable": "DIE"}}))
    _write(tmp_path, TD.DECLARATION_REL, {"answers": {"deliverable": "HARDMACRO"}})
    derived, _ = R._declared_deliverable(tmp_path)
    assert derived == "HARDMACRO", "exercise the actual stale router fallback"
    assert R._effective_deliverable(tmp_path, derived) is None


@pytest.mark.parametrize("delivery", ["DIE", "HARDMACRO"])
def test_current_owner_delivery_reaches_pdk(tmp_path, monkeypatch, delivery):
    _project(tmp_path, delivery)
    derived, _ = R._declared_deliverable(tmp_path)
    assert derived == delivery
    assert R._effective_deliverable(tmp_path, derived) == delivery
    assert _main(tmp_path, monkeypatch) == (0, ["PDK"])


def test_owner_declaration_without_raw_answer_remains_usable(tmp_path, monkeypatch):
    _project(tmp_path)
    (tmp_path / ST.DESIGN_ANSWERS_REL).unlink()
    assert _main(tmp_path, monkeypatch) == (0, ["PDK"])
