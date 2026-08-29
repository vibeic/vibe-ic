#!/usr/bin/env python3
"""An empty NDA token store must not make a gate blame the design under test.

`_commercial_pdk` RAISES `NoNdaLiterals` rather than hand back an alternation of
nothing, and says in its own docstring what that obliges of every caller:

    "the empty set is the ORDINARY state of every public checkout and of every
     CI job that has not been given the tokens. Every caller must handle this
     raise, and `nda_literals_available()` is the cheap way to ask first."

Two gates did not handle it, and the unhandled call sat inside a MODULE-LEVEL
rule table — so the raise escaped at import, before argparse and before any
subject was opened. `flow_compliance_check` records an rc-1 gate by its FIRST
OUTPUT LINE, so a gf180mcuD benchmark run's completion audit carried

    {"name": "backlog_sanitize_check", "verdict": "FAIL",
     "message": "Traceback (most recent call last):"}

and Phase 2 failed on it. A crash in the gate was rendered as a defect in the
design, which is the one thing a gate must never do.

WHY THE SHIPPED SUITE NEVER CAUGHT IT, and why this file sets the environment
by hand. `programs/tests/conftest.py` does

    os.environ.setdefault("VIBEIC_NDA_TOKENS", json.dumps(FICTIONAL_NDA_TOKENS))

before any test module imports `_commercial_pdk`, and every gate subprocess the
suite spawns inherits it. That is right for the suite's other purposes and it
makes the empty store UNREACHABLE from a test — the whole suite runs in the one
state where these gates cannot crash. Measured on this host with the store
emptied, `backlog_sanitize_check --help` — which `test_help` asserts exits 0 —
exits 1 with a traceback. So the tests below scrub the environment explicitly;
inheriting it would re-hide exactly what they exist to measure.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
BACKLOG = PROGRAMS / "backlog_sanitize_check.py"
PRACTICAL = PROGRAMS / "practical_notes_specificity_check.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _nda_fixture_tokens import FICTIONAL_NDA_TOKENS  # noqa: E402


def _shipped_version() -> str:
    root = PROGRAMS.parent
    return str(json.loads(
        (root / ".claude-plugin" / "plugin.json").read_text())["version"])


def _env(tokens: dict | None, tmp_path: Path) -> dict:
    """A child environment whose token store is exactly `tokens`.

    An EMPTY store needs both halves silenced: the env var AND the private
    config, which on a configured host would otherwise supply the literals and
    quietly turn the no-token case back into the has-token case."""
    env = dict(os.environ)
    env.pop("VIBEIC_NDA_TOKENS", None)
    empty_cfg = tmp_path / "empty_private_config.json"
    empty_cfg.write_text("{}", encoding="utf-8")
    env["VIBEIC_PRIVATE_CONFIG"] = str(empty_cfg)
    if tokens:
        env["VIBEIC_NDA_TOKENS"] = json.dumps(tokens)
    return env


def _run(prog: Path, args: list[str], tokens, tmp_path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(prog), *args],
                          capture_output=True, text=True,
                          env=_env(tokens, tmp_path))


def _clean_backlog(tmp_path: Path, body: str) -> Path:
    d = tmp_path / "backlog"
    d.mkdir()
    (d / "item.yaml").write_text(
        "id: BL-0001\n"
        "type: enhancement\n"
        'component: "flow:step_rtl_gen"\n'
        f"pattern: {body}\n"
        f"plugin_version: {_shipped_version()}\n"
        "title: generalise the bus description\n"
        f"body: {body}\n", encoding="utf-8")
    return d


def _notes(tmp_path: Path, line: str) -> Path:
    d = tmp_path / "notes"
    d.mkdir()
    (d / "PRACTICAL_NOTES.md").write_text(f"# Notes\n{line}\n", encoding="utf-8")
    return d


# ── the crash itself ───────────────────────────────────────────────────────

@pytest.mark.parametrize("prog", [BACKLOG, PRACTICAL], ids=["backlog", "practical"])
def test_an_empty_token_store_does_not_crash_the_gate_at_import(prog, tmp_path):
    """THE CASE THIS FILE EXISTS FOR. Before the fix both exited 1 with
    `Traceback (most recent call last):` as the first line — the exact string
    the flow then recorded as the design's verdict."""
    r = _run(prog, ["--help"], None, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Traceback" not in r.stderr, (
        "the raise escaped at import again: --help cannot even be reached")


@pytest.mark.parametrize("prog", [BACKLOG, PRACTICAL], ids=["backlog", "practical"])
def test_no_traceback_reaches_stdout_where_the_flow_reads_the_verdict(prog, tmp_path):
    """`flow_compliance_check` takes an rc-1 gate's FIRST OUTPUT LINE as the
    finding. A traceback there becomes a sentence about the design."""
    r = _run(prog, ["--help"], None, tmp_path)
    first = (r.stdout.strip() or r.stderr.strip()).split("\n")[0]
    assert not first.startswith("Traceback"), first


# ── the honest answer that replaces it ─────────────────────────────────────

def test_backlog_answers_rc2_not_measured_on_a_clean_subject(tmp_path):
    """rc 2 is this program's existing 'cannot answer' channel, and
    `flow_compliance_check` routes rc 2 to NOT_INVOCABLE / SKIP rather than to
    a verdict. Exact code asserted: a check demoted from 1 to 2 once passed 362
    tests that only asserted `!= 0`."""
    d = _clean_backlog(tmp_path, "describe the IC class, not a part number")
    r = _run(BACKLOG, ["--dir", str(d), "--audit", "content"], None, tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT_MEASURED" in r.stderr
    assert "pdk_codename" in r.stderr, "the message must name the rule that was absent"


def test_practical_answers_rc2_not_measured_on_a_clean_subject(tmp_path):
    d = _notes(tmp_path, "Describe the protocol class, not a part number.")
    r = _run(PRACTICAL, ["--paths", str(d)], None, tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT_MEASURED" in r.stderr
    assert "specific_pdk_codename" in r.stderr


def test_the_word_printed_matches_the_exit_code(tmp_path):
    """A console line reading PASS over a catalogue that was missing a detector
    is the false clean bill this fix exists to stop."""
    d = _notes(tmp_path, "Describe the protocol class, not a part number.")
    r = _run(PRACTICAL, ["--paths", str(d)], None, tmp_path)
    assert r.stdout.strip().splitlines()[-1] == "NOT_MEASURED"
    assert "\nPASS" not in r.stdout


@pytest.mark.parametrize("prog,args_fn,key", [
    (PRACTICAL, lambda d: ["--paths", str(d), "--json"], "nda_codename_rule"),
])
def test_the_json_says_so_too(prog, args_fn, key, tmp_path):
    """A consumer of the JSON must not have to infer 'the whole catalogue ran'
    from the absence of a field."""
    d = _notes(tmp_path, "Describe the protocol class, not a part number.")
    r = _run(prog, args_fn(d), None, tmp_path)
    doc = json.loads(r.stdout)
    assert doc[key] == "NOT_MEASURED"
    assert doc["verdict"] == "NOT_MEASURED"


# ── the controls: what the fix must NOT change ─────────────────────────────

def test_control_a_real_violation_is_still_measured_without_tokens(tmp_path):
    """A rule that never ran cannot weaken a POSITIVE finding. Only the CLEAN
    claim is incomplete — so a violation the other rules caught keeps rc 1 and
    must never be masked as NOT_MEASURED."""
    d = _notes(tmp_path, "Validated against an Apple accessory over Lightning.")
    r = _run(PRACTICAL, ["--paths", str(d)], None, tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stdout.strip().splitlines()[-1] == "FAIL"

    b = _clean_backlog(tmp_path, "reproduced under /home/someuser/proj")
    r = _run(BACKLOG, ["--dir", str(b), "--audit", "content"], None, tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr


@pytest.mark.parametrize("prog,args_fn,subject,rc", [
    (PRACTICAL, lambda d: ["--paths", str(d)],
     "Describe the protocol class, not a part number.", 0),
    (PRACTICAL, lambda d: ["--paths", str(d)],
     "Validated against an Apple accessory over Lightning.", 1),
], ids=["clean", "violating"])
def test_control_with_tokens_present_behaviour_is_unchanged(
        prog, args_fn, subject, rc, tmp_path):
    """THE LOAD-BEARING CONTROL. When the store HAS literals the rule is built
    exactly as before and every verdict is the pre-fix verdict. Without this, a
    'fix' that simply deleted the rule would pass every test above."""
    d = _notes(tmp_path, subject)
    r = _run(prog, args_fn(d), FICTIONAL_NDA_TOKENS, tmp_path)
    assert r.returncode == rc, r.stdout + r.stderr


def test_control_the_codename_rule_still_fires_when_it_can_be_built(tmp_path):
    """The strongest control: a subject that ONLY the NDA rule detects. It must
    FAIL with tokens (the rule is not lost) and NOT_MEASURED without them (the
    absence is disclosed, never printed as clean)."""
    # The codename family is exactly these three roles — `_commercial_pdk.
    # nda_regex_family()` joins sku_full / foundry_product / sku_prefix and no
    # others, so a token from any other role would not exercise this rule.
    token = FICTIONAL_NDA_TOKENS["sku_full"]
    d = _notes(tmp_path, f"Targets the {token} process.")

    with_tokens = _run(PRACTICAL, ["--paths", str(d)], FICTIONAL_NDA_TOKENS, tmp_path)
    assert with_tokens.returncode == 1, with_tokens.stdout + with_tokens.stderr

    without = _run(PRACTICAL, ["--paths", str(d)], None, tmp_path)
    assert without.returncode == 2, without.stdout + without.stderr
    assert "NOT_MEASURED" in without.stderr


def test_control_the_rest_of_the_catalogue_is_intact(tmp_path):
    """A fix that dropped rules to stop the crash would also pass the rc checks.
    Pin the rule SET, both with and without the token store."""
    import importlib
    sys.path.insert(0, str(PROGRAMS))
    for mod, expected_extra in (("practical_notes_specificity_check",
                                 "specific_pdk_codename"),
                                ("backlog_sanitize_check", "pdk_codename")):
        os.environ["VIBEIC_NDA_TOKENS"] = json.dumps(FICTIONAL_NDA_TOKENS)
        m = importlib.reload(importlib.import_module(mod))
        with_ids = {r[0] for r in m.HARD_RULES}
        assert expected_extra in with_ids

        os.environ.pop("VIBEIC_NDA_TOKENS", None)
        os.environ["VIBEIC_PRIVATE_CONFIG"] = str(tmp_path / "empty.json")
        (tmp_path / "empty.json").write_text("{}", encoding="utf-8")
        m = importlib.reload(importlib.import_module(mod))
        without_ids = {r[0] for r in m.HARD_RULES}

        assert without_ids == with_ids - {expected_extra}, (
            f"{mod}: removing the token store must drop EXACTLY the one rule "
            f"that needs it, not any other")
