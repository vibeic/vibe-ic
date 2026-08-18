"""#688 — the UPF handoff fabricated every supply-net and supply-port name.

`l21_to_upf_emit` read `d.get("supply")`. Both producers of those entries —
`l21_macro_supply_rail_synth` and `l21_doc_supply_rail_synth` — declare
`_POWER_KEY = "power_net"`, and NEITHER has ever written a field called
`supply`. So the `or` branch always fired and every emitted name was built from
the DOMAIN name instead:

    domain VDD, power_net VDD   ->  create_supply_net VDD_VDD

A UPF consumer binds by net NAME. A manufactured one binds to nothing while
reading exactly like a declaration that worked.

MEASURED after the fix, on the shape the issue reports:

    domains VDD / AUX / VSS with power_net VDD / AUX_2V5 / VDD
    -> create_supply_net VDD, AUX_2V5, VDD   (no VDD_<domain> anywhere)
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "l21_to_upf_emit", _PROGRAMS / "l21_to_upf_emit.py")
U = importlib.util.module_from_spec(_spec)
sys.modules["l21_to_upf_emit"] = U
try:
    _spec.loader.exec_module(U)
except SystemExit:
    pass


def _upf(domains):
    return U.render_upf({"power_domains": domains}, "chip_top", "L21.json")


def _nets(text):
    return re.findall(r"create_supply_net (\S+)", text)


# ── it reads the key the producers write ──────────────────────────────────
def test_the_key_matches_both_producers():
    """The mismatch, asserted against the producers themselves rather than
    against a copy of the string — a second literal is a second thing to drift."""
    for mod in ("l21_macro_supply_rail_synth", "l21_doc_supply_rail_synth"):
        src = (_PROGRAMS / f"{mod}.py").read_text(encoding="utf-8")
        assert f'_POWER_KEY = "{U._POWER_KEY}"' in src, mod


def test_the_real_net_name_is_emitted():
    out = _upf([{"name": "VDD", "power_net": "VDD"},
                {"name": "AUX", "power_net": "AUX_2V5"}])
    assert "AUX_2V5" in _nets(out)
    assert not re.search(r"create_supply_net VDD_(VDD|AUX)\b", out), \
        "a fabricated VDD_<domain> is back"


def test_a_hand_written_supply_key_still_wins():
    """`supply` is kept first: it costs nothing and a hand-authored layer may
    use it. Removing it would break a shape that works today."""
    out = _upf([{"name": "D", "supply": "HAND", "power_net": "AUTO"}])
    assert "HAND" in _nets(out) and "AUTO" not in _nets(out)


def test_the_port_and_the_connection_use_the_same_name():
    """The net, its port and the connect must agree, or the UPF declares a port
    that is wired to nothing."""
    out = _upf([{"name": "AUX", "power_net": "AUX_2V5"}])
    assert "create_supply_port AUX_2V5_port" in out
    assert "connect_supply_net AUX_2V5 -ports AUX_2V5_port" in out


# ── what it must not do ───────────────────────────────────────────────────
def test_an_unresolvable_domain_is_REFUSED_not_invented():
    """LOAD-BEARING. The old behaviour manufactured a name; the tempting fix is
    to skip the domain instead, and a UPF that silently omits a power domain
    reads as a design that does not have one."""
    with pytest.raises(ValueError) as e:
        _upf([{"name": "MYSTERY"}])
    assert "MYSTERY" in str(e.value)


def test_the_refusal_names_every_unresolvable_domain():
    with pytest.raises(ValueError) as e:
        _upf([{"name": "A"}, {"name": "B", "power_net": "OK"}, {"name": "C"}])
    msg = str(e.value)
    assert "A" in msg and "C" in msg


def test_no_fabricated_fallback_remains_in_the_source():
    """The literal that caused it. A grep-level assertion because the defect was
    a one-line `or`, and a one-line `or` is what would bring it back."""
    src = (_PROGRAMS / "l21_to_upf_emit.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert 'f"VDD_{name}"' not in body
