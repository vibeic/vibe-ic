"""Actual DRC consumer: current-stream binding, not filename precedence."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import general_precheck as GP
import phase3_one_shot_runner as P3
from test_general_precheck import _die_at_origin

NATIVE = Path(__file__).parent / "fixtures/drc_native_input_binding"


def _sha(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(project, violations=0):
    gds = _die_at_origin(project / "phase3/stage3/pnr/chip_top.gds")
    rpt = project / "phase3/reports/drc.rpt"
    rpt.parent.mkdir(parents=True)
    # Full native evidence, not the deliberately undersized no-corroboration
    # fixture. No padding or bypass of the consumer's authenticity screen.
    body = (NATIVE / "zero.xml").read_text()
    if violations:
        body = body.replace("<items>", '<items><item><category>li.1</category>'
                            '<cell>chip_top</cell><values/></item>')
    rpt.write_text(body)
    log = rpt.with_suffix(".log")
    log.write_text((NATIVE / "terminal.log").read_text().replace(
        "(0 violations)", f"({violations} violations)"))
    for source, rel in ((rpt, "reports/phase3/drc_signoff.rpt"),
                        (log, "reports/phase3/drc_signoff.log")):
        dest = project / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
    # Test input record; no assertion that this synthetic fixture ran EDA.
    record = {"record": "invocation", "measured": True, "tool": "klayout",
              "exit_code": 0,
              "inputs": {gds.relative_to(project).as_posix(): _sha(gds)},
              "outputs": {p.relative_to(project).as_posix(): _sha(p)
                          for p in (rpt, log)}}
    (project / "provenance.jsonl").write_text(json.dumps(record) + "\n")
    return gds


def _actual_delegate(project, gds):
    step = next(s for s in GP.LADDER if s.step_id == "Checker.KLayoutDRC")
    ev = GP._blank(step)
    GP._step_delegate(ev, step, project, GP.default_runner, GP._HERE, 60,
                      layout=gds)
    return ev


def _details(project):
    path = project / "reports/phase3/general_precheck/precheck_klayout_drc.json"
    return path.read_text() if path.is_file() else "delegate report absent"


def test_current_zero_ignores_preserved_different_gds_diagnostic_red(tmp_path):
    gds = _fixture(tmp_path)
    historical = tmp_path / "phase3/reports/drc_restream.rpt"
    historical.write_text("KLayout DRC: 5 violations found\n")
    before = historical.read_bytes()
    ev = _actual_delegate(tmp_path, gds)
    assert ev.verdict == GP.PASS, _details(tmp_path)
    assert historical.read_bytes() == before


def test_canonical_real_violation_is_not_rescued_by_historical_zero(tmp_path):
    gds = _fixture(tmp_path, violations=1)
    (tmp_path / "phase3/reports/drc_restream.rpt").write_text(
        "KLayout DRC: 0 violations found\n")
    assert _actual_delegate(tmp_path, gds).verdict == GP.FAIL


def test_magic_rung_scopes_its_own_bound_report_not_klayout(tmp_path):
    gds = _fixture(tmp_path, violations=1)
    magic = tmp_path / "reports/phase3/drc_signoff_magic.rpt"
    magic.write_text("# Tool: magic\nmagic DRC: 0 violations\n")
    row = {"record": "invocation", "measured": True, "tool": "magic",
           "exit_code": 0,
           "inputs": {gds.relative_to(tmp_path).as_posix(): _sha(gds)},
           "outputs": {magic.relative_to(tmp_path).as_posix(): _sha(magic)}}
    with (tmp_path / "provenance.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")
    step = next(s for s in GP.LADDER if s.step_id == "Checker.MagicDRC")
    ev = GP._blank(step)
    GP._step_delegate(ev, step, tmp_path, GP.default_runner, GP._HERE, 60,
                      layout=gds)
    command = ev.measured["command"]
    assert command[command.index("--under") + 1] == \
        "reports/phase3/drc_signoff_magic.rpt"
    magic.write_text(magic.read_text() + "changed after measurement\n")
    assert GP._bound_drc_scope(tmp_path, gds, "magic")[1]


@pytest.mark.parametrize("change", ["gds", "report", "missing_report", "missing_log",
                                    "raw_log", "native_failure"])
def test_stale_or_incomplete_binding_cannot_pass(tmp_path, change):
    gds = _fixture(tmp_path)
    if change == "gds":
        _die_at_origin(gds, w=120_000)
    elif change == "report":
        (tmp_path / "reports/phase3/drc_signoff.rpt").write_text("0 violations")
    elif change.startswith("missing_"):
        suffix = ".rpt" if change == "missing_report" else ".log"
        (tmp_path / ("reports/phase3/drc_signoff" + suffix)).unlink()
    elif change == "raw_log":
        (tmp_path / "phase3/reports/drc.log").write_text("another run")
    else:
        path = tmp_path / "provenance.jsonl"
        record = json.loads(path.read_text())
        record["exit_code"] = 1
        path.write_text(json.dumps(record) + "\n")
    assert _actual_delegate(tmp_path, gds).verdict != GP.PASS


def test_legacy_without_binding_keeps_unscoped_consumer(tmp_path):
    gds = _fixture(tmp_path)
    (tmp_path / "provenance.jsonl").unlink()
    historical = tmp_path / "phase3/reports/drc_restream.rpt"
    historical.write_text("KLayout DRC: 5 violations found\n")
    assert GP._bound_drc_scope(tmp_path, gds) == ([], "")
    assert _actual_delegate(tmp_path, gds).verdict == GP.FAIL


@pytest.mark.parametrize("changed_layout", [False, True])
def test_resolved_output_binding_uses_real_hash_writer(tmp_path, changed_layout):
    gds = _fixture(tmp_path)
    report = tmp_path / "phase3/reports/drc.rpt"
    log = report.with_suffix(".log")
    for path, target_rel in ((report, "private/native/report.rdb"),
                             (log, "private/transcripts/terminal.txt")):
        target = tmp_path / target_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        path.rename(target)
        path.symlink_to(target)
    record_path = tmp_path / "provenance.jsonl"
    record = json.loads(record_path.read_text())
    record["outputs"] = P3._hash_declared_outputs(tmp_path, [report, log])
    assert set(record["outputs"]) == {
        "private/native/report.rdb", "private/transcripts/terminal.txt"}
    record_path.write_text(json.dumps(record) + "\n")
    # Establish that this exact native zero is accepted before the mutation.
    # Otherwise an unrelated refusal could masquerade as a stale-input catch.
    assert _actual_delegate(tmp_path, gds).verdict == GP.PASS, _details(tmp_path)
    if changed_layout:
        _die_at_origin(gds, w=120_000)
        # The existing zero report remains real, but it checked OLD bytes.
        assert _actual_delegate(tmp_path, gds).verdict != GP.PASS, _details(tmp_path)
    else:
        historical = tmp_path / "phase3/reports/drc_restream.rpt"
        historical.write_text("KLayout DRC: 5 violations found\n")
        before = historical.read_bytes()
        assert _actual_delegate(tmp_path, gds).verdict == GP.PASS, _details(tmp_path)
        assert historical.read_bytes() == before
