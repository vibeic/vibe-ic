"""BIDIRECTIONAL test: an UNDECLARED `--pdk <name>` must REFUSE, never silently
resolve to sky130A.

THE DEFECT
==========
#211 built the resolve-or-REFUSE contract for `--pdk` and stated it plainly:

    "the named PDK either resolves to ITS OWN assets, or — when those assets
     cannot be resolved — REFUSES (SystemExit). It must NEVER silently
     masquerade as sky130A."
     (tests/test_issue162_167_asap7_pdk_agnostic.py, module docstring)

But it wired that refusal exclusively to the DECLARED path. In
`phase3_one_shot_runner._detect_pdk` the `raise SystemExit(...)` lives INSIDE
`if _reg is not None:`, so a `--pdk` name that is simply ABSENT from
`pdk_registry.json` raises nothing, falls through the whole override block, and
lands on the function's last line:

    # fallback: sky130A in container
    return _detect_pdk(project, override="sky130A")

MEASURED (spm x ihp-sg13cmos5l, plugin 1.6.4, image vibeic-eda:0.2.30
id sha256:4182c63b10d1) — before the fix, both of these returned
`PdkConfig(name='sky130A', liberty=.../sky130_fd_sc_hd__tt_025C_1v80.lib)` with
no exception and nothing on stderr:

    --pdk ihp-sg13cmos5l            -> name='sky130A'
    --pdk totally-made-up-pdk-xyz   -> name='sky130A'

`/foss/pdks/ihp-sg13cmos5l` is a REAL, complete digital PDK inside that image —
it is merely absent from the registry. Its near-miss against the DECLARED
`ihp-sg13g2` is exactly what makes the substitution easy to ship unnoticed: the
whole Phase-3 sign-off (PnR, DRC deck, LVS deck, GDS layer map, STA liberty)
silently comes from a different foundry at a different node.

The undeclared name is STRICTLY WORSE than the declared-but-unresolvable case
#211 did cover, because nothing anywhere records what was actually asked for.

WHY NOT A BLANKET REFUSAL
=========================
`--pdk <custom>` backed by a project-local `input/pdk/` is a LEGITIMATE, still-
supported path (the branch below the override block returns `custom:<dir>`).
The refusal therefore fires ONLY when that path cannot serve the name either —
i.e. when the sole remaining outcome is the sky130A fallback. The
POSITIVE_CONTROL below pins that: with `input/pdk/{liberty,lef}/` present, the
same undeclared name must NOT raise.

Every assertion is bidirectional. A test that cannot fail proves nothing.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]


def _load_runner():
    """Import phase3_one_shot_runner under its own module name.

    (It uses @dataclass at import time, which needs the module registered in
    sys.modules before exec_module.)"""
    sys.path.insert(0, str(PROGRAMS))
    spec = importlib.util.spec_from_file_location(
        "_p3_undeclared_pdk_test", PROGRAMS / "phase3_one_shot_runner.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_p3_undeclared_pdk_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _registry_names() -> list[str]:
    return [e["name"] for e in
            (json.loads((PROGRAMS / "pdk_registry.json").read_text())
             .get("pdks") or []) if e.get("name")]


def _mk_local_pdk(project: Path) -> None:
    """A minimally-shaped project-local PDK: the resolver's own precondition is
    that BOTH input/pdk/liberty/ and input/pdk/lef/ are directories."""
    (project / "input" / "pdk" / "liberty").mkdir(parents=True)
    (project / "input" / "pdk" / "lef").mkdir(parents=True)


# --------------------------------------------------------------------------
# NEGATIVE CONTROLS — the defect present must make this FAIL (i.e. must raise)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("undeclared", [
    "ihp-sg13cmos5l",            # a REAL PDK in the image, absent from registry
    "totally-made-up-pdk-xyz",   # pure nonsense
    "ihp-sg13g2-typo",           # near-miss on a DECLARED name
    "sky130Z",                   # near-miss on the fallback itself
])
def test_NEGATIVE_CONTROL_undeclared_pdk_refuses(tmp_path, undeclared):
    """An undeclared --pdk with no project-local PDK must REFUSE, not
    substitute sky130A."""
    m = _load_runner()
    assert undeclared not in _registry_names(), (
        f"{undeclared!r} is declared in pdk_registry.json — this test's "
        f"premise (an UNDECLARED name) no longer holds; pick another name.")

    with pytest.raises(SystemExit) as exc:
        m._detect_pdk(tmp_path, override=undeclared)

    msg = str(exc.value)
    assert "NOT declared in" in msg, msg
    assert undeclared in msg, msg
    # The refusal must SAY it is refusing the substitution — a bare traceback
    # would leave an operator guessing which PDK they actually got.
    assert "REFUSING to fall back to sky130A" in msg, msg
    # ...and must be actionable: name the registry it consulted.
    assert "pdk_registry.json" in msg, msg


def test_NEGATIVE_CONTROL_near_miss_offers_the_declared_sibling(tmp_path):
    """The near-miss that motivated this fix must surface its declared sibling,
    so an operator sees ihp-sg13g2 when they typo'd toward it."""
    m = _load_runner()
    names = _registry_names()
    if "ihp-sg13g2" not in names:
        pytest.skip("registry no longer declares ihp-sg13g2")
    with pytest.raises(SystemExit) as exc:
        m._detect_pdk(tmp_path, override="ihp-sg13g22")
    assert "Did you mean" in str(exc.value), str(exc.value)
    assert "ihp-sg13g2" in str(exc.value), str(exc.value)


def test_NEGATIVE_CONTROL_refusal_does_not_return_a_config(tmp_path):
    """The precise regression: the pre-fix code RETURNED a usable sky130A
    PdkConfig. Assert no value can escape for an undeclared name."""
    m = _load_runner()
    got = None
    try:
        got = m._detect_pdk(tmp_path, override="definitely-not-a-real-pdk")
    except SystemExit:
        pass
    assert got is None, (
        f"undeclared --pdk resolved to {getattr(got, 'name', got)!r} instead of "
        f"refusing — this is the silent-substitution regression")


# --------------------------------------------------------------------------
# POSITIVE CONTROLS — the fixed/legitimate cases must NOT be blocked
# --------------------------------------------------------------------------

def test_POSITIVE_CONTROL_undeclared_name_with_project_local_pdk_is_allowed(
        tmp_path):
    """`--pdk <custom>` served by input/pdk/ is legitimate and must still pass
    THROUGH the override block (no SystemExit from the undeclared guard).

    We assert only that the UNDECLARED guard does not fire: downstream
    resolution of a skeleton PDK dir may still legitimately fail or return
    None, which is a different code path and not what this test pins."""
    m = _load_runner()
    _mk_local_pdk(tmp_path)
    try:
        m._detect_pdk(tmp_path, override="my-custom-inhouse-pdk")
    except SystemExit as exc:
        assert "NOT declared in" not in str(exc.value), (
            "the undeclared-name guard fired even though a project-local PDK "
            f"is present — this breaks the supported `--pdk <custom>` path: {exc.value}")
    except Exception:
        pass  # any other resolution error is a different path, not this guard


@pytest.mark.parametrize("declared", ["sky130A", "nangate45", "asap7"])
def test_POSITIVE_CONTROL_builtin_branch_names_still_resolve(tmp_path, declared):
    """The three names with their own named branches must be unaffected."""
    m = _load_runner()
    cfg = m._detect_pdk(tmp_path, override=declared)
    assert cfg is not None and cfg.name == declared


def test_POSITIVE_CONTROL_registry_declared_name_still_resolves(tmp_path):
    """A registry-DECLARED name must keep resolving to its OWN assets — the
    #211 contract this fix extends, not replaces."""
    m = _load_runner()
    names = _registry_names()
    target = next((n for n in names
                   if n not in ("sky130A", "nangate45", "asap7",
                                "custom_auto_detect")), None)
    if target is None:
        pytest.skip("registry declares no generically-resolved PDK")
    try:
        cfg = m._detect_pdk(tmp_path, override=target)
    except SystemExit as exc:
        # Declared-but-unresolvable is #211's OWN refusal and is correct here
        # (it fires when the container lacks the assets). It must NOT be
        # mistaken for the undeclared guard.
        assert "declared in pdk_registry.json" in str(exc.value), str(exc.value)
        assert "NOT declared in" not in str(exc.value), str(exc.value)
        return
    assert cfg.name == target, (
        f"registry-declared {target!r} resolved to {cfg.name!r} — silent "
        f"substitution of a declared PDK")


def test_POSITIVE_CONTROL_auto_and_none_are_untouched(tmp_path):
    """`--pdk auto` (the default) and no override must keep their behaviour:
    they are not a NAMED request, so the undeclared guard must not fire."""
    m = _load_runner()
    for override in ("auto", None):
        cfg = m._detect_pdk(tmp_path, override=override)
        assert cfg is not None
        assert cfg.name == "sky130A", (
            f"--pdk {override!r} should still reach the documented sky130A "
            f"fallback, got {cfg.name!r}")
