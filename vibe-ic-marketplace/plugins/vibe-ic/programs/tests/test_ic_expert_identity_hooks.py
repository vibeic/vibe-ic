"""Regression tests for the ALWAYS-ON IC-Expert identity hooks.

Owner directive (2026-07-05, STRONG RULE): "everytime when AI using vibe-ic
plugin, AI IS the IC expert with expert-DB and expert-skills … and knows
when/where to trigger the plugin's programs/gates/agents/skills."

Two hooks enforce it:
  * SessionStart  — hooks/ic-expert-identity-session.sh  (unconditional banner).
  * UserPromptSubmit — hooks/ic-expert-identity-reminder.sh (re-asserts on
    vibe-ic plugin usage / an IC-design-flow term; SILENT on unrelated chit-chat).

These tests run the actual bash scripts through subprocess to lock the identity
content + the fire / no-fire boundary, and pin the wiring in hooks.json.
"""
import json
import subprocess
from pathlib import Path

_HOOKS = Path(__file__).resolve().parents[2] / "hooks"
SESSION = _HOOKS / "ic-expert-identity-session.sh"
REMINDER = _HOOKS / "ic-expert-identity-reminder.sh"


def _run(script: Path, prompt: str | None = None) -> str:
    envelope = None if prompt is None else json.dumps({"prompt": prompt}) + "\n"
    proc = subprocess.run(
        ["bash", str(script)],
        input=envelope, capture_output=True, text=True, timeout=5)
    return proc.stdout


def _fires(prompt: str) -> bool:
    # the reminder always names the IC Expert Agent identity — a stable fire signal.
    return "IC EXPERT AGENT" in _run(REMINDER, prompt)


# --------------------------------------------------------------------------- #
# SessionStart — unconditional identity banner.
# --------------------------------------------------------------------------- #
def test_session_hook_emits_binding_identity():
    out = _run(SESSION)
    assert "<system-reminder>" in out
    assert "IC EXPERT AGENT" in out
    # points the model at the source-of-truth files (no guessing the flow)
    assert "ic_expert_db" in out
    assert "flow/phase1_phase2_phase3.yaml" in out
    assert "CAPTURE_ROUTING.json" in out
    # the two expert assets + the doctrine
    assert "expert-DB" in out and "expert-skills" in out
    assert "program-first" in out and "4.05" in out


# --------------------------------------------------------------------------- #
# UserPromptSubmit — fires on plugin usage / IC-design flow terms.
# --------------------------------------------------------------------------- #
def test_reminder_fires_on_plugin_name_and_commands():
    assert _fires("run /vibe-ic-phase1 on my project")
    assert _fires("use the vibe-ic plugin")
    assert _fires("vibeic all")


def test_reminder_fires_on_ic_design_flow_terms():
    assert _fires("design an RTL module for a UART")
    assert _fires("write a Verilog counter")
    assert _fires("let's tape out this chip")
    assert _fires("run synthesis and check STA")
    assert _fires("do place and route then DRC and LVS")


def test_reminder_silent_on_unrelated_chit_chat():
    assert not _fires("what is the weather today")
    assert not _fires("summarize this news article")
    assert not _fires("help me write a python web scraper")


def test_reminder_points_to_operating_map():
    out = _run(REMINDER, "design an RTL block")
    assert "IC-EXPERT OPERATING MAP" in out
    assert "flow/phase1_phase2_phase3.yaml" in out
    assert "CAPTURE_ROUTING.json" in out


# --------------------------------------------------------------------------- #
# Wiring — both hooks registered in hooks.json under the right events.
# --------------------------------------------------------------------------- #
def test_hooks_registered_in_hooks_json():
    cfg = json.loads((_HOOKS / "hooks.json").read_text())
    ss = json.dumps(cfg["hooks"]["SessionStart"])
    up = json.dumps(cfg["hooks"]["UserPromptSubmit"])
    assert "ic-expert-identity-session.sh" in ss
    assert "ic-expert-identity-reminder.sh" in up
    # the pre-existing hooks are preserved, not replaced
    assert "post_install.sh" in ss
    assert "benchmark-keyword-skill-reminder.sh" in up


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
