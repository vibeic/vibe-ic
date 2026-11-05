"""The pin: the seal-ring generator contract, read from upstream.

`die_finishing_gen` drives the PDK's own seal-ring generator through what its
header calls upstream's interface "unchanged": four flags, and a named skip on
the same unset PDK-scoped variable. That is a contract with code this module
does not own, and it was written down once.

SKIPS BY NAME where upstream is not installed.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
from _tool_probes import skip_not_verified  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "_die_fin_pin", PROGRAMS / "die_finishing_gen.py")
DF = importlib.util.module_from_spec(_spec)
sys.modules["_die_fin_pin"] = DF
_spec.loader.exec_module(DF)


def _upstream(rel: str):
    project, tail = rel.split("/", 1)
    env = os.environ.get("VIBEIC_LIBRELANE_ROOT")
    if env:
        cand = Path(env) / tail
        if cand.is_file():
            return cand
    try:
        import librelane  # type: ignore
    except Exception:
        return None
    cand = Path(librelane.__file__).parent / tail
    return cand if cand.is_file() else None


def _skip(rel: str):
    skip_not_verified(
        f"upstream {rel} is not on this host: VIBEIC_LIBRELANE_ROOT does not "
        "carry it and librelane is not importable; the upstream contract was "
        "not checked",
        "set VIBEIC_LIBRELANE_ROOT to a complete librelane source tree or "
        "run this test in the shipped flow image")


def _sealring_body(text: str) -> str:
    i = text.find("class SealRing")
    assert i != -1, ("upstream no longer defines a SealRing step — the mirror "
                     "describes a shape that has moved.")
    j = text.find("\nclass ", i + 1)
    return text[i: j if j != -1 else len(text)]


def test_the_declaration_is_well_formed():
    m = DF.UPSTREAM_MIRROR
    assert m["upstream"].endswith("klayout.py")
    assert m["pinned_by"].split("::", 1)[0].rsplit("/", 1)[-1] == \
        Path(__file__).name


def test_upstream_sealring_contract_is_the_one_this_module_drives():
    """Four flags, and the variable whose absence is a named skip."""
    rel = DF.UPSTREAM_MIRROR["upstream"]
    src = _upstream(rel)
    if src is None:
        _skip(rel)
    body = _sealring_body(src.read_text(errors="replace"))

    for flag in ("--input", "--output", "--die-width", "--die-height"):
        assert f'"{flag}"' in body, (
            f"{src}: upstream's seal-ring command no longer passes {flag}. "
            f"This module drives the generator with exactly these four flags; "
            f"a contract that changed is a divergence, not a detail.")

    assert DF._ENV_SCRIPT in body, (
        f"{src}: upstream no longer gates the step on {DF._ENV_SCRIPT}. This "
        f"module reports a NAMED skip on that same variable, which is only "
        f"the same skip while upstream keys on it too.")
    assert re.search(r"This step will be skipped", body), (
        f"{src}: upstream no longer SKIPS on the unset script variable. If it "
        f"now fails instead, a disclosed skip here is the wrong verdict.")


def test_upstream_second_path_still_exports_the_tool_search_path():
    """The header says both code paths are reproduced, "KLAYOUT_PATH
    included" — that export is what makes the technology definition load."""
    rel = DF.UPSTREAM_MIRROR["upstream"]
    src = _upstream(rel)
    if src is None:
        _skip(rel)
    body = _sealring_body(src.read_text(errors="replace"))
    assert "KLAYOUT_PATH" in body, (
        f"{src}: upstream's second seal-ring path no longer exports "
        f"KLAYOUT_PATH. This module reproduces that export; if upstream "
        f"dropped it, one of the two is now wrong.")


def _generic_die_args(body: str, rect) -> tuple:
    """(width, height) upstream's generic path passes for DIE_AREA = rect.

    EVALUATED, not pattern-matched: the path has been written two ways --
    `f"{self.config['DIE_AREA'][2]:f}"` inline (to vibeic-eda 0.3.79), and
    `die_width, die_height = self.die_dimensions(self.config["DIE_AREA"])`
    (0.3.83 on) -- and a regex for one shape reads the other as unreadable.
    The statements of `run_generic` that can be evaluated against a stub
    `self` (config = {DIE_AREA: rect} plus the class's own staticmethods) are,
    and the two values after `--die-width`/`--die-height` are read back."""
    import ast
    import types

    body = body.split("\n@", 1)[0]    # the NEXT class's decorator
    cls = next(n for n in ast.parse(body).body
               if isinstance(n, ast.ClassDef) and n.name == "SealRing")
    fns = {f.name: f for f in cls.body if isinstance(f, ast.FunctionDef)}
    gen = fns.get("run_generic")
    assert gen is not None, "upstream no longer has a generic seal-ring path."

    class StepError(Exception):
        pass

    g = {"StepError": StepError, "os": os}
    stub = types.SimpleNamespace(config={"DIE_AREA": rect})
    for name, f in fns.items():
        if any(isinstance(d, ast.Name) and d.id == "staticmethod"
               for d in f.decorator_list):
            plain = ast.FunctionDef(name=f.name, args=f.args, body=f.body,
                                    decorator_list=[], returns=None,
                                    type_comment=None, type_params=[])
            mod = ast.fix_missing_locations(ast.Module([plain], []))
            exec(compile(mod, "<upstream>", "exec"), g)
            setattr(stub, name, g[name])
    local = {"self": stub}
    for st in gen.body:
        if isinstance(st, ast.Assign):
            try:
                exec(compile(ast.fix_missing_locations(ast.Module([st], [])),
                             "<upstream>", "exec"), g, local)
            except Exception:  # noqa: BLE001 -- a statement about the run
                pass           # environment, not about the die
    found = {}
    for node in ast.walk(gen):
        if isinstance(node, ast.List):
            for i, e in enumerate(node.elts[:-1]):
                if (isinstance(e, ast.Constant)
                        and e.value in ("--die-width", "--die-height")):
                    found[e.value] = node.elts[i + 1]
    out = []
    for flag in ("--die-width", "--die-height"):
        if flag not in found:
            return None
        try:
            out.append(float(eval(compile(ast.Expression(found[flag]),
                                          "<upstream>", "eval"), g, local)))
        except Exception:  # noqa: BLE001
            return None
    return tuple(out)


def test_upstream_generic_path_maps_die_area_indices_to_the_right_dimension():
    """Upstream's width is the die's X SPAN and its height the Y SPAN -- the
    numbers this module passes (`die_size`: x1-x0, y1-y0 of the DIEAREA).

    Upstream declares DIE_AREA as the four-corner rectangle "x0 y0 x1 y1".
    To vibeic-eda 0.3.79 its generic path passed DIE_AREA[2] and DIE_AREA[3]
    -- the far CORNER, equal to the spans only for a die at the origin. From
    0.3.83 it passes `die_dimensions` = (x1-x0, y1-y0), which is what this
    module always computed. So the pin is measured on a die NOT at the origin,
    the one case where "which index" and "which span" differ, and compared
    against this module's own computation -- not against a remembered index.

    THIS PIN IS SCOPED TO THE GENERIC PATH ON PURPOSE. Upstream's OTHER
    seal-ring path passes the Y span as `width` and the X span as `height`
    (upstream now says why: that PDK's own naming). Pinning it either way
    would bless or redden a path this module does not drive.
    """
    rel = DF.UPSTREAM_MIRROR["upstream"]
    src = _upstream(rel)
    if src is None:
        _skip(rel)
    body = _sealring_body(src.read_text(errors="replace"))
    rect_um = (10.0, 20.0, 110.0, 70.0)          # a die NOT at the origin
    up = _generic_die_args(body, rect_um)
    assert up is not None, (
        f"{src}: could not evaluate what the generic path passes as "
        f"--die-width and --die-height for DIE_AREA={list(rect_um)}. The "
        f"mapping is what this module mirrors, so an unreadable one is a "
        f"finding, not a pass.")

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td)
        d = proj / "phase3" / "stage3" / "pnr"
        d.mkdir(parents=True)
        (d / "routed.def").write_text(
            "UNITS DISTANCE MICRONS 1000 ;\n"
            "DIEAREA ( 10000 20000 ) ( 110000 70000 ) ;\n")
        w, h, _src = DF.die_size(proj, proj / "x.gds", None, None)
    assert (w, h) == (100.0, 50.0), (w, h, _src)
    assert up == (w, h), (
        f"{src}: for DIE_AREA={list(rect_um)} upstream's generic path passes "
        f"--die-width {up[0]} --die-height {up[1]}; this module passes "
        f"{w} x {h} (the X and Y spans). One of upstream and this module has "
        f"moved.")
