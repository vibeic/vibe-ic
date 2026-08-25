"""Unit tests for waivers_schema_check.py.

Covers: missing file (OK), rubber-stamp (FAIL), valid waiver (OK),
duplicate ids, invalid types, self-approver rejection.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "waivers_schema_check.py"
assert SCRIPT.exists()


def _run(project_dir: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(project_dir)],
        capture_output=True,
        text=True,
    )


def _write(path: Path, data: dict):
    path.write_text(json.dumps(data))


def test_missing_file_is_ok(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0


def test_valid_waiver(tmp_path):
    _write(tmp_path / "waivers.json", {
        "waived_steps": [
            {
                "id": 11,
                "reason": "Commercial ATPG tool not available in this environment; manual scan insertion will be run at sign-off",
                "approver": "reyerchu",
                "ticket": "OPS-100",
            }
        ]
    })
    r = _run(tmp_path)
    assert r.returncode == 0, f"stderr: {r.stderr}"


def test_reject_todo_placeholder(tmp_path):
    _write(tmp_path / "waivers.json", {
        "waived_steps": [{"id": 11, "reason": "TODO", "approver": "user"}]
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "placeholder" in (r.stdout + r.stderr).lower() or "short" in (r.stdout + r.stderr).lower()


def test_reject_self_approval(tmp_path):
    _write(tmp_path / "waivers.json", {
        "waived_steps": [
            {
                "id": 11,
                "reason": "No FPGA board available and board required for on-board test",
                "approver": "agent",
            }
        ]
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "self" in (r.stdout + r.stderr).lower() or "approver" in (r.stdout + r.stderr).lower()


def test_reject_short_reason(tmp_path):
    _write(tmp_path / "waivers.json", {
        "waived_steps": [
            {"id": 11, "reason": "no tool", "approver": "reyerchu"}
        ]
    })
    r = _run(tmp_path)
    assert r.returncode == 1


def test_reject_duplicate_id(tmp_path):
    _write(tmp_path / "waivers.json", {
        "waived_steps": [
            {"id": 11, "reason": "reason one long enough to pass validation check", "approver": "reyerchu"},
            {"id": 11, "reason": "reason two long enough to pass validation check", "approver": "reyerchu"},
        ]
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "duplicate" in (r.stdout + r.stderr).lower() or "more than once" in (r.stdout + r.stderr).lower()


def test_reject_id_out_of_range(tmp_path):
    """#526 relocated the FATALITY of this finding without weakening it.

    An id naming no flow step is still REPORTED, and `--strict-ids` still
    exits 1 on it — that half is asserted below and is what a standalone gate
    invocation asks for. What changed is the DEFAULT, because these findings
    are also consumed by `flow_compliance_check`, which turns any error into
    `SystemExit(1)`: an `id: 99` waiver is inert there (it is filed under a
    key no flow step has and exempts nothing), so making it fatal withheld
    nothing and instead deleted the entire compliance report — 63 step
    verdicts and every advisory — to complain about a waiver that did
    nothing. The complaint survives; the report does too.
    """
    _write(tmp_path / "waivers.json", {
        "waived_steps": [
            {"id": 99, "reason": "this is a sufficiently long reason string to pass", "approver": "reyerchu"}
        ]
    })
    strict = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path), "--strict-ids"],
        capture_output=True, text=True)
    assert strict.returncode == 1

    r = _run(tmp_path)
    assert r.returncode == 0
    assert "id-range" in r.stdout, (
        "the finding must still be reported when it is not fatal — a "
        "downgrade that also silenced it would be a real weakening")


def test_malformed_json(tmp_path):
    (tmp_path / "waivers.json").write_text("{not json")
    r = _run(tmp_path)
    assert r.returncode == 1


def test_reject_unfilled_template_approver(tmp_path):
    """An UNFILLED waivers.json.template must not ship as waivers.json.

    waiver_template_gen.py documents that its placeholders are "GUARANTEED to
    reject", but the only approver rule was SELF_APPROVERS, which the sentinel
    __TODO_HUMAN_NAME__ does not match. With a real (>= MIN_REASON_LEN) reason
    filled in, an unapproved template therefore validated clean.
    """
    _write(tmp_path / "waivers.json", {
        "waived_steps": [
            {"id": 1,
             "reason": "IC class registers rtl_gen=null; RTL authored via the spec-to-rtl skill",
             "approver": "__TODO_HUMAN_NAME__",
             "ticket": "OPS-101"}
        ]
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "placeholder" in (r.stdout + r.stderr).lower()


def test_reject_placeholder_approver_variants(tmp_path):
    """Generalises by SHAPE (dunder sentinel / bracketed / bare filler word),
    not by our own template's literal string."""
    for filler in ("__APPROVER__", "<TODO>", "[name]", "your name", "TBD", "xxx"):
        _write(tmp_path / "waivers.json", {
            "waived_steps": [
                {"id": 11,
                 "reason": "ATPG deferred to sign-off; scan insertion runs on the final netlist",
                 "approver": filler}
            ]
        })
        r = _run(tmp_path)
        assert r.returncode == 1, f"{filler!r} was accepted as an approver"


def test_real_approver_still_accepted(tmp_path):
    """The placeholder rule must not swallow legitimate approvers — including
    the sanctioned machine tier used by waivers_materialize.py."""
    for good in ("reyerchu", "field-agent-attest (fpga-board cap-gap tier)",
                 "Ada Lovelace", "eng-owner@example.com"):
        _write(tmp_path / "waivers.json", {
            "waived_steps": [
                {"id": 11,
                 "reason": "ATPG deferred to sign-off; scan insertion runs on the final netlist",
                 "approver": good}
            ]
        })
        r = _run(tmp_path)
        assert r.returncode == 0, f"{good!r} was wrongly rejected: {r.stdout}{r.stderr}"


# ---------------------------------------------------------------------------
# THE EMITTER'S GUARANTEE IS NOW A WIRING, NOT A COINCIDENCE OF TWO LISTS.
#
# `waiver_template_gen.py` says its scaffold values are ones this schema is
# "GUARANTEED to reject". Until this edge that held only because the two files
# happened to spell the same words, nothing compared them, and the emitter was
# reachable from no runner, flow clause, gate or skill. The test below changes
# the EMITTER's value to a word this file's own sets do not carry and asserts
# the schema still rejects it — which is false unless the value is read.
# ---------------------------------------------------------------------------
import importlib


def _reload_schema():
    sys.path.insert(0, str(SCRIPT.parent))
    import waivers_schema_check as W
    return importlib.reload(W)


def test_placeholder_sets_are_read_from_the_emitter():
    W = _reload_schema()
    assert W.TEMPLATE_PLACEHOLDER_SOURCE == "waiver_template_gen"
    import waiver_template_gen as G
    assert G.PLACEHOLDER_APPROVER.strip().lower() in W.PLACEHOLDER_APPROVERS
    assert G.PLACEHOLDER_REASON.strip().lower() in W.PLACEHOLDER_REASONS


def test_a_novel_emitter_placeholder_is_still_rejected(tmp_path):
    """THE MUTATION IS IN THE EMITTER. Same waiver shape, same denominator; what
    moves is the word the scaffold leaves behind, and the schema must follow it."""
    sys.path.insert(0, str(SCRIPT.parent))
    import waiver_template_gen as G
    novel = "zzq_unfilled_slot"
    old_a, old_r = G.PLACEHOLDER_APPROVER, G.PLACEHOLDER_REASON
    # Sanity: the shipped sets do NOT carry it, so a pass here would be the
    # coincidence and not the wiring.
    W0 = _reload_schema()
    assert novel not in (W0.PLACEHOLDER_APPROVERS | W0.SELF_APPROVERS)
    try:
        G.PLACEHOLDER_APPROVER = novel
        W = _reload_schema()
        assert novel in W.PLACEHOLDER_APPROVERS
        assert W._is_placeholder_approver(novel)
    finally:
        G.PLACEHOLDER_APPROVER, G.PLACEHOLDER_REASON = old_a, old_r
        _reload_schema()
