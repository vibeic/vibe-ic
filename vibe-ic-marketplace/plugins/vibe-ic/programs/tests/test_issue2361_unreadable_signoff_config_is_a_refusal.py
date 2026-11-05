"""vibe-ic#2361 — a signoff_config.json that exists but does not parse REFUSES.

Before the fix the staged-PDK branch of `_detect_pdk` read the bridge
declaration inside `except Exception: _signoff_cfg = {}`, so one misplaced comma
was indistinguishable from an absent file: `lvs_engine` silently reverted to
"magic" (and tap_geom_layers, dummy_fill, ... to their defaults) with nothing
on stderr and nothing in any report. `_staged_pdk_tech_lef._declared_path` did
the same for the declared `tech_lef`.

Measured on main dfdb3e8d2 before the fix: a staged PDK whose
signoff_config.json is `{"lvs_engine": "klayout", "port_label_restore": true,}`
resolved to `lvs_engine='magic'`, `port_label_restore=None`, no stderr line.

After: ABSENT -> defaults (the file declared nothing); UNREADABLE ->
`SIGNOFF_CONFIG_UNREADABLE` naming the path and the parse error, and the flow
halts at PDK resolution; WELL-FORMED -> the declared values are the ones used.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import _staged_pdk_tech_lef as T  # noqa: E402

_TECH = "LAYER MET1\n  TYPE ROUTING ;\nEND MET1\nEND LIBRARY\n"
_CELLS = ("SITE core ;\nMACRO INVX1\n  CLASS CORE ;\n  SITE core ;\n"
          "END INVX1\nEND LIBRARY\n")


def _stage(root: Path, signoff_text: str | None, techs=("x_tech.tlef",)) -> Path:
    pdk = root / "input" / "pdk"
    (pdk / "liberty").mkdir(parents=True)
    (pdk / "liberty" / "x_tt.lib").write_text("library(x){}\n")
    (pdk / "lef").mkdir()
    for t in techs:
        (pdk / "lef" / t).write_text(_TECH)
    (pdk / "lef" / "x_cells.lef").write_text(_CELLS)
    if signoff_text is not None:
        (pdk / "bridge").mkdir()
        (pdk / "bridge" / "signoff_config.json").write_text(signoff_text)
    return root


@pytest.fixture(autouse=True)
def _no_container(monkeypatch):
    monkeypatch.delenv("EDA_CONTAINER", raising=False)


_MALFORMED = {
    "trailing_comma": '{"lvs_engine": "klayout", "port_label_restore": true,}',
    "truncated": '{"lvs_engine": "klayout"',
    "top_level_list": '["lvs_engine", "klayout"]',
    "top_level_null": "null",
}








def test_the_shared_loader_refuses_for_every_consumer(tmp_path):
    pdk = _stage(tmp_path, _MALFORMED["truncated"]) / "input" / "pdk"
    with pytest.raises(T.SignoffConfigUnreadable):
        T.load_signoff_config(pdk)
    # The stack resolver's existing catchers (runner, via-stack gate) catch
    # TechLefResolutionError; the refusal must reach them as one.
    with pytest.raises(T.TechLefResolutionError, match="SIGNOFF_CONFIG_UNREADABLE"):
        T.select_staged_tech_lef(pdk, (pdk / "lef" / "x_tech.tlef",))






# ── no broad except left at the site ───────────────────────────────────────
def _fn(tree: ast.AST, name: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


def _broad_handlers(fn: ast.FunctionDef):
    return [h.lineno for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)
            and (h.type is None
                 or (isinstance(h.type, ast.Name)
                     and h.type.id in ("Exception", "BaseException")))]


def test_detect_pdk_has_no_broad_except():
    tree = ast.parse((PROGRAMS / "phase3_one_shot_runner.py").read_text(
        encoding="utf-8"))
    assert _broad_handlers(_fn(tree, "_detect_pdk")) == []


def test_the_signoff_readers_have_no_broad_except():
    tree = ast.parse((PROGRAMS / "_staged_pdk_tech_lef.py").read_text(
        encoding="utf-8"))
    for name in ("load_signoff_config", "_declared_path"):
        assert _broad_handlers(_fn(tree, name)) == [], name
