#!/usr/bin/env python3
"""ORGANIC #404 increment 1 — the 1-bit coercion must be VISIBLE.

`phase2_scaffold_gen.derive_signals` coerces any width that is neither an int
nor a digit-string to 1, with no diagnostic, so a port the design declares as
`[ACC_W-1:0]` is emitted as a 1-bit scalar and the RTL is wrong at its
interface. The value is not missing — L1 keeps the textual form in
`width_symbolic` on purpose and phase1 forwards it into L9; the consumer
discards it.

WHAT THIS DELIBERATELY DOES NOT DO, and why the negative case is a test:
#404 measured that resolving the symbol against the corpus' `parameters[]`
and writing it back into L1 is WORSE than the defect — `parameters[]` carries
no module or layer qualifier, so a bare-name join let an L12 scan-chain count
`N=4` size a data bus the datasheet stated as 48, and flipped
`l1_pin_bus_width_actionable_check` from a correct FAIL to a PASS. A finding
cannot do that. `test_the_gate_writes_nothing` pins it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
GATE = _PROGRAMS / "l17_channel_catalog_consumer_contract_check.py"


def _project(tmp_path: Path, ports, channels=None) -> Path:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(json.dumps(
        {"fields": {"channels": channels
                    if channels is not None
                    else [{"name": p["name"],
                           "direction_master": p.get("direction", "input")}
                          for p in ports]}}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
        {"fields": {"top_ports": ports}}))
    return tmp_path


def _run(project: Path):
    r = subprocess.run([sys.executable, str(GATE), str(project)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_a_symbolic_width_port_is_reported(tmp_path):
    """Round 3 changed the ARM, never the verdict. The consumer no longer
    coerces to 1, so the outcome branch is the refusal one — still ERROR,
    still rc 1, still naming the port."""
    rc, out = _run(_project(tmp_path, [
        {"name": "acc_o", "direction": "output",
         "width": "ACC_W-1:0", "width_symbolic": "ACC_W-1:0"}]))
    assert rc == 1
    assert "PORT_WIDTH_UNRESOLVED_BY_CONSUMER" in out
    assert "acc_o" in out


def test_a_non_numeric_width_string_is_reported(tmp_path):
    """The other carrier: L1 sometimes lands a whole prose sentence in
    `width`. It reaches the same rail."""
    rc, out = _run(_project(tmp_path, [
        {"name": "d_o", "direction": "output",
         "width": "the accumulator is 48 bits in this configuration"}]))
    assert rc == 1 and "PORT_WIDTH_UNRESOLVED_BY_CONSUMER" in out


def test_a_genuine_one_bit_port_is_not_reported(tmp_path):
    """The paired half. Reporting every width==1 port would fire on every
    clock, reset and enable in every design — a gate nobody can act on."""
    rc, out = _run(_project(tmp_path, [
        {"name": "en", "direction": "input", "width": 1},
        {"name": "ok", "direction": "output", "width": "8"}]))
    assert "PORT_WIDTH_COLLAPSED_TO_ONE_BIT" not in out
    assert rc == 0


def test_a_digit_string_width_is_not_a_collapse(tmp_path):
    """`"8"` is a digit-string: derive_signals keeps it, so there is nothing
    to report. Only widths the consumer actually threw away count."""
    rc, out = _run(_project(tmp_path, [
        {"name": "bus_o", "direction": "output", "width": "16"}]))
    assert "PORT_WIDTH_COLLAPSED_TO_ONE_BIT" not in out


def test_the_gate_writes_nothing(tmp_path):
    """#404's core finding: the obvious repair is worse than the defect. This
    gate must not be able to turn any other gate green, so it must not modify
    a single L-doc byte."""
    p = _project(tmp_path, [
        {"name": "acc_o", "direction": "output",
         "width": "ACC_W-1:0", "width_symbolic": "ACC_W-1:0"}])
    gd = p / "phase1" / "generated_docs"
    before = {f.name: f.read_bytes() for f in sorted(gd.glob("*.json"))}
    _run(p)
    after = {f.name: f.read_bytes() for f in sorted(gd.glob("*.json"))}
    assert before == after


def test_the_finding_comes_from_the_consumers_own_derivation():
    """Not a re-implementation: the gate must read the same two L9 keys, in
    the same order, that `derive_signals` reads (phase2_scaffold_gen:238)."""
    # Searched over the WHOLE file, not a window before the first mention of
    # the finding id: that first mention is in the module docstring, and an
    # earlier version of this test looked backwards from it and failed
    # against correct code. Anchoring a source assertion to a position is
    # how you end up asserting about the wrong occurrence.
    src = GATE.read_text()
    assert 'for _key in ("top_ports", "ports")' in src
    consumer = (_PROGRAMS / "phase2_scaffold_gen.py").read_text()
    assert 'for src_key in ("top_ports", "ports")' in consumer


# ---------------------------------------------------------------------------
# ROUND 2 — the rail must survive the repair #404 itself proposed next.
#
# #404's Increment 2 was "resolve the width in the CONSUMER, scoped to the
# SAME L9 document", justified on the ground that then "no gate's input is
# rewritten by its own repair". MEASURED on the real published cell that fires
# this rail, that ground is false — this gate's input IS the consumer's
# output:
#     stock derive_signals        -> PORT_WIDTH_COLLAPSED_TO_ONE_BIT, rc 1
#     increment-2 derive_signals  -> finding absent, rail silent
# and it was equally silent when the same-document parameter default was
# mutated to contradict the port's own stated width (resolved 4 on a port
# documented and shipped as 32). These tests pin the rail against that.
# ---------------------------------------------------------------------------
import importlib  # noqa: E402

_GATE_MOD = importlib.import_module(
    "l17_channel_catalog_consumer_contract_check")


def _increment2(l9_unused=None):
    """The exact shape #404 §Increment-2 specifies: resolve `width_symbolic`
    against a `parameters[]` entry declared in the SAME L9 document, nowhere
    else. Wrapped around the REAL consumer so only the resolution is new."""
    import re as _re
    consumer = _GATE_MOD._consumer
    original = consumer.derive_signals
    sym_re = _re.compile(r"^\s*([A-Za-z_]\w*)\s*-\s*1\s*:\s*0\s*$")

    def resolving(l17, l9):
        signals = original(l17, l9)
        params = {}
        for entry in (l9.get("parameters") or []):
            if isinstance(entry, dict) and entry.get("name") is not None:
                try:
                    params[str(entry["name"])] = int(
                        str(entry.get("default")).strip())
                except (TypeError, ValueError):
                    pass
        by_name = {}
        for key in ("top_ports", "ports"):
            for entry in (l9.get(key) or []):
                if isinstance(entry, dict) and entry.get("name"):
                    by_name.setdefault(
                        consumer._sanitize_id(str(entry["name"])), entry)
        for sig in signals:
            # A resolver acts wherever the consumer has NO resolved width.
            # Round 3 gave that state a second spelling: `width is None`, the
            # honest refusal, alongside the 1-bit coercion it replaced. If
            # this guard still read `!= 1` the simulated resolver would
            # quietly stop resolving anything and the discriminator below
            # would pass for the wrong reason.
            if sig.get("width") not in (None, 1):
                continue
            src = by_name.get(sig.get("name"))
            if not isinstance(src, dict):
                continue
            hit = sym_re.match(str(src.get("width_symbolic") or ""))
            if hit and hit.group(1) in params:
                sig["width"] = params[hit.group(1)]
        return signals

    return resolving


def _symbolic_project(tmp_path, default, prose):
    """One port whose width is symbolic, plus the same-document parameter an
    Increment-2 resolver would join against."""
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(
        json.dumps({"fields": {"channels": []}}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"fields": {
        "top_ports": [{"name": "acc_o", "direction": "output",
                       "width": prose, "width_symbolic": "ACC_W-1:0"}],
        "parameters": [{"name": "ACC_W", "default": default}],
    }}))
    return tmp_path


def _categories(project):
    findings, _info = _GATE_MOD.audit(project)
    return [f.category for f in findings]


def test_a_consumer_that_resolves_the_symbol_cannot_turn_this_gate_green(
        tmp_path, monkeypatch):
    """THE discriminator. With #404's own proposed Increment 2 live in the
    consumer, the rail must still report. Before this change the rail was
    guarded by `width == 1`, so a resolver removed the finding entirely and
    the gate went green — the failure mode the issue was filed about, one
    layer down from where it was first found."""
    project = _symbolic_project(tmp_path, default="16",
                                prose="the accumulator is 16 bits")
    monkeypatch.setattr(_GATE_MOD._consumer, "derive_signals", _increment2())
    cats = _categories(project)
    assert "PORT_WIDTH_SYMBOL_UNCORROBORATED" in cats, cats
    # and it is still a BLOCKING finding, not a downgrade to advisory
    findings, _ = _GATE_MOD.audit(project)
    row = [f for f in findings
           if f.category == "PORT_WIDTH_SYMBOL_UNCORROBORATED"][0]
    assert row.severity == "ERROR"
    assert row.evidence["ports"][0]["consumer_width"] == 16


def test_a_contradicted_resolution_is_reported_not_trusted(
        tmp_path, monkeypatch):
    """§2a of #404, reproduced at the CONSUMER layer: the same-document
    parameter default disagrees with the number the port's own width prose
    states. The resolver cannot see the disagreement — nothing declares 48
    twice — so it writes 4. The rail must not accept that silently just
    because a number came out."""
    project = _symbolic_project(
        tmp_path, default="4",
        prose="the accumulator is 48 bits in this configuration")
    monkeypatch.setattr(_GATE_MOD._consumer, "derive_signals", _increment2())
    findings, _ = _GATE_MOD.audit(project)
    rows = [f for f in findings
            if f.category == "PORT_WIDTH_SYMBOL_UNCORROBORATED"]
    assert rows, [f.category for f in findings]
    assert rows[0].evidence["ports"][0]["consumer_width"] == 4


def test_the_unresolved_rail_is_the_one_that_fires_when_nothing_resolves(
        tmp_path):
    """No weakening. With the real (unpatched) consumer the same fixture must
    report EXACTLY ONE of the three arms — they are branches of one condition,
    never two at once."""
    project = _symbolic_project(tmp_path, default="16",
                                prose="the accumulator is 16 bits")
    cats = _categories(project)
    assert "PORT_WIDTH_UNRESOLVED_BY_CONSUMER" in cats, cats
    assert "PORT_WIDTH_SYMBOL_UNCORROBORATED" not in cats, cats
    assert "PORT_WIDTH_COLLAPSED_TO_ONE_BIT" not in cats, cats


def test_a_declared_integer_width_never_reaches_the_new_rail(
        tmp_path, monkeypatch):
    """The paired negative half. A port the layer declares as a plain integer
    is not symbolic, so neither rail may fire — even with the resolver live.
    Without this, "the consumer emitted a number" would report every wide
    port in every design."""
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(
        json.dumps({"fields": {"channels": []}}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"fields": {
        "top_ports": [{"name": "bus_o", "direction": "output", "width": 32},
                      {"name": "en", "direction": "input", "width": 1}],
        "parameters": [{"name": "ACC_W", "default": "16"}],
    }}))
    monkeypatch.setattr(_GATE_MOD._consumer, "derive_signals", _increment2())
    cats = _categories(tmp_path)
    assert "PORT_WIDTH_SYMBOL_UNCORROBORATED" not in cats, cats
    assert "PORT_WIDTH_COLLAPSED_TO_ONE_BIT" not in cats, cats


def test_the_rail_is_keyed_on_the_layer_not_on_the_number():
    """Source-level pin on the shape, because the shape is the whole point.
    `width == 1` must be a BRANCH inside the symbolic condition, never the
    guard in front of it — a guard is what a repair walks through."""
    src = GATE.read_text()
    block = src.split("collapsed_widths = []")[1].split(
        "if collapsed_widths:")[0]
    assert "_s.get(\"width\") != 1" not in block, (
        "the numeric outcome is back in front of the layer condition")
    assert "uncorroborated_widths.append" in block


def test_the_l1_gate_no_longer_misdirects_the_next_author():
    """Increment 3. The L1 gate said phase2 derives every port declaration
    from `L1.pin_table[]`; it goes via the L9 promotion, and `pin_table`
    appears ZERO times in either phase2 file."""
    for f in ("phase2_scaffold_gen.py", "_specrtl_common.py"):
        assert "pin_table" not in (_PROGRAMS / f).read_text(), f
    doc = (_PROGRAMS / "l1_pin_bus_width_actionable_check.py").read_text()[:4000]
    assert "derives every port DECLARATION from" not in doc
    assert "THROUGH L9" in doc
