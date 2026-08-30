"""`fires_on:` was DECORATIVE. Measured, then made load-bearing.

MEASURED ON v1.13.66, unmodified: set the shipped `stage1` block's
`fires_on: stage_pass` to `never` and `stage_on_pass_review` went on rejecting
the published known-BAD tree, byte for byte, at rc 1. Nothing read the field.

A field the engine does not read is worse than an absent one, because the flow
author believes it and writes to it. The field was NOT deleted: deleting it
would also have to delete `on_pass_review_declared_command_runs_check`'s P4, a
BLOCKING declaration-time gate that already refuses any other value in the
shipped flow. So the pair is — the declaration gate refuses a block that
declares something else, and the engine refuses to RUN one.

Every arm below has a CONTROL: the same tree, the same argv, the shipped
declaration, which must keep answering rc 1 on known-BAD and rc 0 on
known-GOOD in every arm.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))

import on_pass_review_declared_command_runs_check as K  # noqa: E402
import stage_on_pass_review as S  # noqa: E402

SUBJECT = PROGRAMS / "stage_on_pass_review.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
STAGE, BAD, GOOD = "stage1", "reject_caravel", "accept_spm"
ARGV = ["--stage", STAGE, "--json", "rec.json",
        "--compliance", "reports/flow_compliance.json"]


def _run(tmp_path: Path, tree: str, flow: Path, extra=()) -> tuple[int, str, dict | None]:
    root = tmp_path / f"run_{tree}_{abs(hash((str(flow), tuple(extra))))}"
    root.mkdir(parents=True)
    K.materialise(STAGE, tree, root)
    rep = root / "reports" / "flow_compliance.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps({"steps": [{"stage": STAGE, "status": "PASS"}]}))
    proc = subprocess.run(
        [sys.executable, str(SUBJECT), "--flow-def", str(flow), "."]
        + ARGV + list(extra),
        cwd=str(root), capture_output=True, text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    try:
        rec = json.loads((root / "rec.json").read_text())
    except (OSError, ValueError):
        rec = None
    return proc.returncode, (proc.stdout or "") + (proc.stderr or ""), rec


def _flow_with_fires_on(tmp_path: Path, value: str) -> Path:
    """The shipped flow with ONLY stage1's `fires_on:` rewritten."""
    text = FLOW.read_text(encoding="utf-8")
    i = text.index("id: stage1")
    j = text.index("fires_on: stage_pass", i)
    out = tmp_path / f"flow_{value}.yaml"
    out.write_text(text[:j] + f"fires_on: {value}"
                   + text[j + len("fires_on: stage_pass"):], encoding="utf-8")
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    got = next(st["on_pass_review"]["fires_on"] for st in doc["stages"]
               if str(st.get("id")) == STAGE)
    assert str(got) == value, f"the mutation did not land: {got!r}"
    return out


def _controls_hold(tmp_path: Path) -> None:
    """The shipped declaration still refuses BAD and accepts GOOD."""
    rc_bad, _, rec = _run(tmp_path, BAD, FLOW)
    assert rc_bad == 1, "the control stopped refusing its known-BAD tree"
    assert (rec or {}).get("rejections"), "the control produced no rejection"
    rc_good, _, _ = _run(tmp_path, GOOD, FLOW)
    assert rc_good == 0, "the control stopped accepting its known-GOOD tree"


def test_the_shipped_flow_declares_only_the_supported_value():
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    declared = {str(st["on_pass_review"].get("fires_on"))
                for st in (doc.get("stages") or [])
                if isinstance(st.get("on_pass_review"), dict)}
    assert declared == {S._SUPPORTED_FIRES_ON}, declared


def test_the_control_refuses_BAD_and_accepts_GOOD(tmp_path):
    _controls_hold(tmp_path)


@pytest.mark.parametrize("value", ["never", "stage_fail", "always", "Stage_Pass"])
def test_an_unsupported_fires_on_is_a_disclosed_skip_not_a_review(tmp_path, value):
    """rc 2, and NOT rc 0. This is the whole reason the refusal is a disclosed
    skip: through `advisory_program_exit_zero` rc 2 records as `n/a`, while rc 0
    would record as `ok` — and "the declaration asked for something I do not
    implement" is not "reviewed and clean". `Stage_Pass` is in the list because
    a case-insensitive match would be a second spelling of the field."""
    flow = _flow_with_fires_on(tmp_path, value)
    rc, out, _ = _run(tmp_path, BAD, flow)
    assert rc == 2, f"rc={rc}\n{out}"
    assert "NOT CHECKED" in out and "fires_on" in out
    assert S._SUPPORTED_FIRES_ON in out
    _controls_hold(tmp_path)


def test_the_pre_fix_behaviour_is_what_the_arm_reproduces(tmp_path):
    """THE NEGATIVE CONTROL FOR THE ARM ITSELF. `never` must reach the engine
    as `never` — if the mutation silently failed to land, the arm above would
    be asserting nothing. Proven by reading the mutated flow back."""
    flow = _flow_with_fires_on(tmp_path, "never")
    doc = yaml.safe_load(flow.read_text(encoding="utf-8"))
    blocks = {str(st.get("id")): st["on_pass_review"].get("fires_on")
              for st in doc["stages"] if isinstance(st.get("on_pass_review"), dict)}
    assert blocks[STAGE] == "never"
    # ...and every OTHER stage is untouched, so a whole-file rewrite cannot
    # masquerade as a one-field mutation.
    assert {v for k, v in blocks.items() if k != STAGE} == {S._SUPPORTED_FIRES_ON}


def test_a_stage_declaring_no_fires_on_at_all_is_also_refused(tmp_path):
    """An ABSENT field is not a supported firing condition either. It reads as
    None, which is not `stage_pass`, and the engine declines — the same answer
    the declaration gate's P4 gives, so the two cannot disagree."""
    text = FLOW.read_text(encoding="utf-8")
    i = text.index("id: stage1")
    j = text.index("      fires_on: stage_pass", i)
    out = tmp_path / "flow_absent.yaml"
    out.write_text(text[:j] + text[j + len("      fires_on: stage_pass\n"):],
                   encoding="utf-8")
    rc, msg, _ = _run(tmp_path, BAD, out)
    assert rc == 2 and "fires_on" in msg
    _controls_hold(tmp_path)
