"""The D9 block is pinned to a flow that no longer exists, and it must say so.

MEASURED 2026-08-28. `gen_flow_gate_d9_section.py` (#1009, 2026-08-11) renders a
D9 block whose `--check` said only "D9 block absent from page" -- which reads as
an invitation to `--install`. Two facts make installing it wrong, and neither is
repairable by refreshing its data:

  * the report describes a 63-step flow and the flow has 68; and
  * `63 步`, `上面那 504 格`, `47 / 63`, `25 / 63` are STRING LITERALS in the
    rendering, so a regenerated 68-step report would still print 63.

A GUARD THAT WAS WRONG, PINNED HERE SO IT IS NOT RE-ADDED. The first version
counted `# D9` comment lines in the flow yaml. Deleting four comments -- changing
no criterion, leaving the blocking `step_internal_fail_bubble_up_check` in place
-- flipped it back to "publish", and those comments were written by the D9
campaign itself. `test_deleting_comments_does_not_re_arm_publication` is that
refutation, kept executable.
"""
from __future__ import annotations

import importlib.util
import json
import re
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


def _module():
    spec = importlib.util.spec_from_file_location("d9gen", _GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _flow_text() -> str:
    return (_ROOT / _module()._FLOW_REL).read_text(encoding="utf-8", errors="ignore")


def _tree(tmp_path: Path, flow_text: str) -> Path:
    g = _module()
    root = tmp_path / "repo"
    flow = root / g._FLOW_REL
    flow.parent.mkdir(parents=True, exist_ok=True)
    flow.write_text(flow_text, encoding="utf-8")
    return root


def _run(*args: str):
    return subprocess.run([sys.executable, str(_GEN), *args],
                          capture_output=True, text=True)


# ---------------------------------------------------------------- can FAIL --
def test_the_shipped_report_describes_a_smaller_flow():
    """Not a synthetic number: the json in the tree, against the flow in the tree."""
    g = _module()
    rep = json.loads(_REALITY.read_text(encoding="utf-8"))
    assert rep["steps"] == 63
    assert g.flow_step_count(_ROOT) == 68


def test_every_path_refuses_and_says_why(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<html><body>x</body></html>", encoding="utf-8")
    for args in (["--reality", str(_REALITY), "--page", str(page), "--check"],
                 ["--reality", str(_REALITY), "--emit", str(tmp_path / "f.html")],
                 ["--reality", str(_REALITY), "--page", str(page), "--install"],
                 ["--reality", str(_REALITY), "--page", str(page), "--write"]):
        r = _run(*args)
        assert r.returncode == 2, (args, r.stdout + r.stderr)
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
    live = Path("/home/reyerchu/vibeic.ai/flow-gate.html")
    if not live.is_file():                              # pragma: no cover
        import pytest
        pytest.skip("the published page is not on this host")
    before = live.read_bytes()
    r = _run("--reality", str(_REALITY), "--page", str(live), "--check")
    assert r.returncode == 2, r.stdout + r.stderr
    assert live.read_bytes() == before


# ------------------------------------------- the refuted guard, kept executable --
def test_deleting_comments_does_not_re_arm_publication(tmp_path):
    """The adversarial refutation of the FIRST guard, as a standing test.

    Strip every `# D9` comment from the real flow. No criterion changes -- the
    blocking clause is still there -- so the refusal must not lift.
    """
    g = _module()
    stripped = re.sub(r"^\s*#\s*D9\b.*$", "        # (comment removed)",
                      _flow_text(), flags=re.M)
    assert 'program_exit_zero: "step_internal_fail_bubble_up_check' in stripped, \
        "the mutation removed a criterion; it must remove only comments"
    root = _tree(tmp_path, stripped)
    assert g.premise_refusal({"steps": 63}, root) is not None


def test_the_typed_figures_are_read_from_string_literals_not_comments():
    """The guard reads what the block PRINTS, never what the file discusses."""
    g = _module()
    typed = g.typed_populations()
    assert 504 in typed and 63 in typed, typed
    # the docstring above discusses 68 at length; that must not be collected
    # as something the block prints.
    assert all(isinstance(v, str) for v in typed.values())


# ---------------------------------------------------------------- can PASS --
def test_a_matching_report_on_a_derived_block_would_publish(tmp_path, monkeypatch):
    """Both gates lift together: same-size report AND no typed populations.

    Neither alone is enough, which is the point -- so the can-pass arm has to
    clear both, and it does so without editing the flow's criteria.
    """
    g = _module()
    root = _tree(tmp_path, _flow_text())
    steps = g.flow_step_count(root)
    monkeypatch.setattr(g, "typed_populations", lambda: {})
    assert g.premise_refusal({"steps": steps}, root) is None


def test_a_same_size_report_still_refuses_while_the_figures_are_typed(tmp_path):
    """Gate 2 alone holds: refreshing the report does not correct a literal."""
    g = _module()
    root = _tree(tmp_path, _flow_text())
    why = g.premise_refusal({"steps": g.flow_step_count(root)}, root)
    assert why is not None and "TYPED" in why
