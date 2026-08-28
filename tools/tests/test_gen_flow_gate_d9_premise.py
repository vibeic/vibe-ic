"""The D9 generator's subject stopped existing, and it must say so.

MEASURED 2026-08-28. `gen_flow_gate_d9_section.py` (#1009, 2026-08-11) refuses
to publish D9 as a shipped dimension because "nothing in
flow/phase1_phase2_phase3.yaml asks the ninth question". The flow it names now
carries four `# D9` labelled clauses, one of them a BLOCKING
`program_exit_zero: "step_internal_fail_bubble_up_check ."` in step 36.

The question also changed identity: #1009 measured "is the output CORRECT"; the
D9 that shipped is `verdict_consumed`, and the published page says so -- "The
ninth question is shipped -- and it is not 'is the output correct?'". So the
block is not a stale version of that section, it is a denial of it.

Its own `--check` used to say only "D9 block absent from page", which reads as
an invitation to `--install`. These tests pin the refusal instead.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

for _anc in Path(__file__).resolve().parents:
    if (_anc / "tools" / "gen_flow_gate_d9_section.py").is_file():
        _ROOT = _anc
        break
else:                                                    # pragma: no cover
    raise RuntimeError("gen_flow_gate_d9_section.py not found above this test")

_GEN = _ROOT / "tools" / "gen_flow_gate_d9_section.py"
_REALITY = _ROOT / "tools" / "d9_reality" / "d9_reality.json"
_FLOW = (_ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
         / "flow" / "phase1_phase2_phase3.yaml")


def _run(*args: str):
    return subprocess.run([sys.executable, str(_GEN), *args],
                          capture_output=True, text=True)


# ------------------------------------------------------- the premise is dead --
def test_the_flow_asks_the_ninth_question_today():
    """The sentence the generator justifies itself with, checked against its subject."""
    text = _FLOW.read_text(encoding="utf-8", errors="ignore")
    assert "# D9" in text, "the flow no longer labels D9 clauses; re-read this fix"
    assert 'program_exit_zero: "step_internal_fail_bubble_up_check' in text


def test_every_path_refuses_and_says_why(tmp_path):
    """--check, --emit, --install and --write all exit 2 with the real reason."""
    page = tmp_path / "page.html"
    page.write_text("<html><body>x</body></html>", encoding="utf-8")
    for args in (["--reality", str(_REALITY), "--page", str(page), "--check"],
                 ["--reality", str(_REALITY), "--emit", str(tmp_path / "f.html")],
                 ["--reality", str(_REALITY), "--page", str(page), "--install"],
                 ["--reality", str(_REALITY), "--page", str(page), "--write"]):
        r = _run(*args)
        assert r.returncode == 2, (args, r.stdout + r.stderr)
        assert "premise" in r.stderr, (args, r.stderr)
        assert "NOT an invitation to re-install" in r.stderr, args


def test_the_refusal_writes_nothing(tmp_path):
    """A refusal that still emitted would let the next caller install it."""
    page = tmp_path / "page.html"
    page.write_text("<html><body>x</body></html>", encoding="utf-8")
    before = page.read_bytes()
    frag = tmp_path / "fragment.html"
    _run("--reality", str(_REALITY), "--page", str(page),
         "--emit", str(frag), "--install", "--write")
    assert not frag.exists(), "a fragment was emitted despite the refusal"
    assert page.read_bytes() == before, "the page was modified despite the refusal"


def test_the_published_page_is_untouched_by_a_check():
    """The real subject: today's flow-gate.html, if it is on this host."""
    live = Path("/home/reyerchu/vibeic.ai/flow-gate.html")
    if not live.is_file():                              # pragma: no cover
        import pytest
        pytest.skip("the published page is not on this host")
    before = live.read_bytes()
    r = _run("--reality", str(_REALITY), "--page", str(live), "--check")
    assert r.returncode == 2, r.stdout + r.stderr
    assert live.read_bytes() == before


# ------------------------------------------------------ the guard can pass --
def test_a_flow_that_stops_asking_restores_the_program(tmp_path):
    """The guard reads the tree, not this file's prose.

    Built by REMOVING the D9 labels from a copy of the real flow, so the
    can-pass arm is the same subject minus exactly the thing under test -- and
    the report's own step count is set to match, since that is the second gate.
    """
    import re
    sys.path.insert(0, str(_ROOT / "tools"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("g", _GEN)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)

    root = tmp_path / "repo"
    flow = root / g._FLOW_REL
    flow.parent.mkdir(parents=True)
    stripped = re.sub(r"^\s*#\s*D9\b.*$", "        # (label removed)",
                      _FLOW.read_text(encoding="utf-8"), flags=re.M)
    flow.write_text(stripped, encoding="utf-8")

    assert g.flow_asks_the_ninth_question(root) == 0
    steps = g.flow_step_count(root)
    assert g.premise_refusal({"steps": steps}, root) is None


def test_a_report_describing_another_flow_is_refused(tmp_path):
    """Second gate: 63-step data against a 68-step flow."""
    import re, importlib.util
    spec = importlib.util.spec_from_file_location("g2", _GEN)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)

    root = tmp_path / "repo"
    flow = root / g._FLOW_REL
    flow.parent.mkdir(parents=True)
    flow.write_text(re.sub(r"^\s*#\s*D9\b.*$", "        # (label removed)",
                           _FLOW.read_text(encoding="utf-8"), flags=re.M),
                    encoding="utf-8")
    live = g.flow_step_count(root)
    why = g.premise_refusal({"steps": live - 5}, root)
    assert why and f"{live - 5}-step flow" in why and f"has {live} steps" in why


def test_the_shipped_report_is_the_one_that_cannot_be_published():
    """Not a synthetic number: the json in the tree describes a smaller flow."""
    rep = json.loads(_REALITY.read_text(encoding="utf-8"))
    assert rep["steps"] == 63, rep["steps"]
