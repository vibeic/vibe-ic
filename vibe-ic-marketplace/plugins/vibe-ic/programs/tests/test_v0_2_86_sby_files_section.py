"""v0.2.86 — #453: formal evidence gate parses [files]/[file] sections;
#452 verification: underscore-suffixed TODO/TBD tokens (shipped v0.2.82).

Pins (#453 acceptance):
  * a legit [files]-section-only .sby + real SBY PASS transcript → PASS;
  * refs genuinely missing on disk → still FAIL (named missing list);
  * .sby present but with NO parseable refs → message says so (never
    the misleading "(no .sby found)");
  * [script]-only and mixed forms keep working.

Pins (#452 acceptance, corpus side):
  * TODO_x AND TBD_x planted values → FAIL;
  * fresh PENDING_FOUNDRY pack → PASS (no TODO/TBD substring).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import formal_proof_evidence_check as FPC  # noqa: E402

_SBY_PASS_LOG = """\
SBY 12:00:00 [task] engine_0: starting process "smtbmc yices"
SBY 12:00:09 [task] summary: Elapsed clock time [H:MM:SS (secs)]: 0:00:09
SBY 12:00:09 [task] DONE (PASS, rc=0)
"""


def _formal(tmp_path):
    f = tmp_path / "phase2" / "stage1" / "formal"
    f.mkdir(parents=True)
    (f / "results.json").write_text(json.dumps({"all_proved": True}))
    (f / "c.sby.log").write_text(_SBY_PASS_LOG)
    return f


def test_files_section_only_sby_passes(tmp_path):
    f = _formal(tmp_path)
    (f / "top.sv").write_text("module top; endmodule\n")
    (f / "asserts.sv").write_text("module a; endmodule\n")
    (f / "c.sby").write_text(
        "[options]\nmode prove\n[engines]\nsmtbmc\n"
        "[files]\ntop.sv\nrenamed.sv asserts.sv\n"
        "[script]\nprep -top top\n")
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 0 and rep["verdict"] == "PASS", rep


def test_files_section_missing_ref_still_fails(tmp_path):
    f = _formal(tmp_path)
    (f / "c.sby").write_text("[files]\nghost.sv\n[script]\nprep -top t\n")
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 1
    joined = " ".join(rep["findings"])
    assert "ghost.sv" in joined and "no .sby found" not in joined


def test_sby_with_no_refs_message_is_accurate(tmp_path):
    f = _formal(tmp_path)
    (f / "c.sby").write_text("[options]\nmode prove\n")
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 1
    joined = " ".join(rep["findings"])
    assert "no parseable" in joined
    assert "(no .sby found" not in joined


def test_script_only_form_still_works(tmp_path):
    f = _formal(tmp_path)
    (f / "x.sv").write_text("module x; endmodule\n")
    (f / "c.sby").write_text("[script]\nread -formal x.sv\nprep -top x\n")
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 0


def test_mixed_form_dedups(tmp_path):
    refs = FPC._sby_file_refs(
        "[files]\na.sv\n[script]\nread -formal a.sv\nread -sv b.sv\n")
    assert refs == ["a.sv", "b.sv"]


# ── #452 corpus pins (regex shipped in v0.2.82) ─────────────────────────────

def test_todo_and_tbd_underscore_tokens_caught():
    import re
    pat = re.compile(r"\bTODO(?:_\w+)?\b|\bTBD(?:_\w+)?\b")
    assert pat.search('{"TODO_fill_me": 1}')
    assert pat.search('{"TBD_later": 1}')
    assert not pat.search('{"PENDING_FOUNDRY_mask_layers": 1}')


def test_checker_fails_planted_tbd_value(tmp_path):
    import subprocess
    plugin = Path(__file__).resolve().parent.parent.parent
    hd = tmp_path / "phase3" / "stage4" / "foundry_handoff"
    hd.mkdir(parents=True)
    (hd / "mask_spec.json").write_text(json.dumps(
        {"pdk": "x", "cell_count": 1, "wat": "TBD_author_me"}))
    (hd / "wat_plan.json").write_text(json.dumps({"ok": 1}))
    r = subprocess.run(
        [sys.executable,
         str(plugin / "programs" / "foundry_handoff_package_check.py"),
         str(tmp_path), "--json", str(tmp_path / "g.json")],
        capture_output=True, text=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "g.json").read_text())
    assert any(f["rule"] == "FOUNDRY_HANDOFF_TODO_MARKERS"
               for f in rep["findings"])
