#!/usr/bin/env python3
"""ORGANIC #648 ROUND-2 — L9 submodule extraction must (a) NOT leak bare prose
words and (b) capture the nested 2nd-level child.

Field-agent reopen (round-3 caravel, v1.0.38): the broadened prose/heading
submodule extraction caught `user_proj_example` but ALSO leaked bare prose
words (`Clock`/`Single`/`The` — capitalised first-words of `## Clocking`
bullets / `The …` sentences) AND dropped the nested child `counter`
(`` `user_proj_example` instantiates one `counter` ``). Two defects:
  (1) §4.05 no-leak FAIL — bare prose words passed the loose bullet gate.
  (2) the nested child `counter` failed the STRICT `_is_real_submodule_name`
      RTL-shape gate (no underscore/digit/known-stem) and was dropped.

Round-2 fix (backtick code-span provenance): a prose/bullet submodule name is
accepted only when it appears INSIDE a backtick code-span (the author's
explicit identifier marker) — accepted via a RELAXED legal-id gate so short
children like `counter` survive — OR, for a bare leading bullet word, only when
it passes the STRICT RTL-shape gate. A bare prose word (`Clock`/`Single`/`The`)
is neither code-spanned nor RTL-shaped → excluded.

ACCEPTANCE: an L2 box-tree `## Hierarchy` + an L8 two-level `instantiates`
chain + a `## Clocking` prose section → L9 submodules == EXACTLY the two
backticked children, with NO prose-word leak.

chip-AGNOSTIC: backtick grammar + identifier legality; no chip/vendor literal.
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase1_doc_one_shot_runner as R  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ── helper units ─────────────────────────────────────────────────────────────
def test_codespan_idents_only_from_backticks():
    line = "- `user_proj_example #(.BITS(32))` instantiates one `counter`"
    assert R._v648r2_codespan_idents(line) == ["user_proj_example", "counter"]
    # a bare prose bullet has NO code-span → nothing
    assert R._v648r2_codespan_idents("- Clock source muxed: clk = ...") == []
    assert R._v648r2_codespan_idents("- Single clock domain, sync reset") == []


@pytest.mark.parametrize("name,ok", [
    ("counter", True), ("alu", True), ("user_proj_example", True),
    ("fifo", True), ("a", False), ("", False), ("1bad", False),
    ("a-b", False),
])
def test_is_codespan_submodule_name(name, ok):
    assert R._is_codespan_submodule_name(name) is ok


def test_prose_instantiates_requires_backtick():
    # backticked children captured (incl nested); a BARE object is rejected
    txt = ("- `user_project_wrapper` (top) instantiates exactly one "
           "`user_proj_example`,\n"
           "- `user_proj_example #(.BITS(32))` instantiates one "
           "`counter #(.BITS(32))`.\n"
           "## Instantiation tree (DTOP instantiates everything)\n")
    kids = R._v1_0_38_prose_instantiates_children(txt)
    assert "user_proj_example" in kids and "counter" in kids
    assert "everything" not in kids          # bare object → not a submodule


# ── ACCEPTANCE: full phase1 → exactly the two children, no prose leak ────────
_L2 = ("# Arch\n\n## Hierarchy\n\n```\nuser_project_wrapper\n"
       "└── user_proj_example\n    └── counter\n```\n\n"
       "## Clocking / reset\n"
       "- Clock source muxed: `clk = sel ? a : b`.\n"
       "- Single clock domain, synchronous active-high reset.\n")
_L8 = ("# Integration\n\n## Instantiation tree (no stub modules)\n"
       "- `user_project_wrapper` (top) instantiates exactly one "
       "`user_proj_example`,\n"
       "- The wrapper exposes the Caravel pads.\n"
       "- `user_proj_example #(.BITS(32))` instantiates one "
       "`counter #(.BITS(32))`.\n")


def test_end_to_end_exact_submodules_no_prose_leak(tmp_path):
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "L2_architecture.md").write_text(_L2)
    (proj / "input" / "docs" / "L8_submodule_integration.md").write_text(_L8)
    runner = _PROGRAMS / "phase1_one_shot_runner.py"
    r = _pr.run([sys.executable, str(runner), str(proj)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    l9 = list((proj / "phase1" / "generated_docs").glob("L9*.json"))[0]
    names = {s.get("name") for s in json.loads(l9.read_text()).get(
        "submodules", [])}
    # EXACTLY the two backticked children — no prose-word leak
    assert names == {"user_proj_example", "counter"}, names
    for leak in ("Clock", "Single", "The", "everything"):
        assert leak not in names


def test_real_caravel_round3_artifact_if_present():
    """The field-agent's exact artifact: L9 submodules == {user_proj_example,
    counter}; no Clock/Single/The leak. SKIPs off-monorepo."""
    base = require_corpus("_bench7_caravel_v1034_cleanroom/caravel/input/docs")
    if not base.is_dir():
        pytest.skip("real caravel docs not on disk")
    import tempfile
    import shutil
    tmp = Path(tempfile.mkdtemp()) / "caravel"
    (tmp / "input").mkdir(parents=True)
    shutil.copytree(base, tmp / "input" / "docs")
    runner = _PROGRAMS / "phase1_one_shot_runner.py"
    r = _pr.run([sys.executable, str(runner), str(tmp)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    l9 = list((tmp / "phase1" / "generated_docs").glob("L9*.json"))[0]
    names = {s.get("name") for s in json.loads(l9.read_text()).get(
        "submodules", [])}
    assert names == {"user_proj_example", "counter"}, names


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
