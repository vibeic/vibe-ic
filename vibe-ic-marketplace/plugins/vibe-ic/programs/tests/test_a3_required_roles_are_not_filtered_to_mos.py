"""A3 must ask the deck resolver for EVERY device role the topology IR uses.

`resolve_pdk_context` filtered the IR's roles down to the MOS pair before
calling `resolve_deck_context`:

    required=tuple(r for r in roles if r in ("nmos", "pmos"))

`required` is not cosmetic. The deck resolver re-derives `device_map` from the
ELECTED PRIMARY lib and keeps the cross-lib UNION map only when the primary
cannot cover a REQUIRED role. So a role missing from `required` is dropped from
`device_map` whenever the primary satisfies the MOS pair, and A3 then refuses
with IR_NOT_RENDERABLE ("device role(s) ... do not resolve") — a statement about
our own request, not about the PDK.

WHY IT HID: `resolve_role_models` falls back to the REGISTRY device list after
the context map. The two open PDKs everything is tested against have a registry
entry that lists passives, so the dropped roles are silently rescued there. An
unknown / container-installed family resolves to `(None, {})`, leaving the
context map as the only source — so only a family that is NOT one of the two
tested open PDKs can reach the defect.

chip-AGNOSTIC: synthetic family + synthetic device names only.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_a3_netlist_emit as A3            # noqa: E402
import analog_pdk_deck_context as APDC         # noqa: E402


IR_ROLES = ["nmos", "pmos", "cap", "res"]


def _capture_required(monkeypatch) -> dict:
    """Record the `required` tuple A3 hands the deck resolver."""
    seen: dict = {}
    real = APDC.resolve_deck_context

    # **kw, not a copy of the signature: the resolver grew a `domain` keyword
    # (vibe-ic#903's per-block half) and a spy that mirrored the old parameter
    # list swallowed the TypeError inside A3's try/except, so this test went
    # red for a reason that had nothing to do with role filtering.
    def _spy(pdk_selector, res=None, required=(), reader=None, container="",
             **kw):
        seen["required"] = tuple(required)
        return real(pdk_selector, res=res, required=required,
                    reader=reader, container=container, **kw)

    monkeypatch.setattr(APDC, "resolve_deck_context", _spy)
    return seen


def test_every_ir_role_is_requested_from_the_deck_resolver(tmp_path,
                                                           monkeypatch):
    """The mechanism: no role the IR declares may be filtered out en route.

    FAILS on the unfixed program, which requests only ('nmos', 'pmos').
    """
    seen = _capture_required(monkeypatch)

    A3.resolve_pdk_context(tmp_path, "synthfoundry180", "", list(IR_ROLES))

    assert "required" in seen, "the deck resolver was never called"
    missing = [r for r in IR_ROLES if r not in seen["required"]]
    assert not missing, (
        f"A3 dropped role(s) {missing} on the way to the deck resolver; "
        f"it asked for {seen['required']}. A role the IR instantiates must be "
        f"requested, or the resolver's primary-vs-union election discards it "
        f"and the block is refused as IR_NOT_RENDERABLE.")


def test_non_mos_roles_survive_a_multi_lib_family(tmp_path, monkeypatch):
    """The user-visible effect, on a family whose devices span several libs.

    The elected primary defines only the MOS pair; the passives live in a
    second lib. With the MOS-only filter the primary covers everything that
    was REQUIRED, so the union map (the only map carrying the passives) is
    discarded and the passive roles resolve to nothing.
    """
    mos = tmp_path / "corner_mos.lib"
    passives = tmp_path / "corner_pas.lib"
    mos.write_text(
        ".LIB dev_tt\n"
        ".subckt synth_nch d g s b w=1 l=1\n.ends\n"
        ".subckt synth_pch d g s b w=1 l=1\n.ends\n"
        ".ENDL\n", encoding="utf-8")
    passives.write_text(
        ".LIB pas_typ\n"
        ".subckt synth_cap p n c=1\n.ends\n"
        ".subckt synth_res p n r=1\n.ends\n"
        ".ENDL\n", encoding="utf-8")

    res = {"available": True, "source": "container_installed",
           "family": "synthfoundry180", "target": "synthfoundry180",
           "spice_libs": [str(mos), str(passives)]}

    monkeypatch.setattr(A3, "_declared_pdk_target", lambda _p: "synthfoundry180")
    import analog_pdk_availability as APA
    monkeypatch.setattr(APA, "resolve_pdk",
                        lambda *a, **k: res)

    ctx = A3.resolve_pdk_context(tmp_path, "synthfoundry180", "",
                                 list(IR_ROLES))

    unresolved = list(ctx.get("unresolved_roles") or [])
    assert not [r for r in ("cap", "res") if r in unresolved], (
        f"passive role(s) left unresolved {unresolved} although the resolved "
        f"libs define them; role_models={ctx.get('role_models')}")
