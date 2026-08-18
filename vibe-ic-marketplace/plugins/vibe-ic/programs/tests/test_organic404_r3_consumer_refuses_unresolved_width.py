#!/usr/bin/env python3
"""ORGANIC #404 round 3 — the consumer must REFUSE, not fabricate a 1.

WHAT THE FIRST TWO ROUNDS SETTLED, so this file does not re-tread it
--------------------------------------------------------------------
Round 1 added the l17 rail that REPORTS the collapse. Round 2 restructured
that rail so `width == 1` is a BRANCH inside the layer condition rather than
a GUARD in front of it, after measuring that an Increment-2 resolver in the
consumer silenced it — and silenced it EQUALLY when the parameter it joined
against contradicted the port's own stated width. Both are pinned in
`test_organic404_symbolic_width_collapse_is_reported.py` and neither is
re-argued here.

WHAT WAS STILL OPEN, and what this file closes
-----------------------------------------------
Everything landed so far REPORTS. What the flow EMITTED never changed: a
port the layers declare as `[size-1:0]` still came out of
`phase2_scaffold_gen.derive_signals` as ``width: 1`` — byte-identical to a
port that really is one bit wide. `l1_pin_bus_width_actionable_check`
returns PASS rc 0 on the published cell where that happens (it resolves the
symbol from the design's own INPUT files, finds it, and is RIGHT to pass:
the value IS resolvable), and the only rail that still saw it was wired
ADVISORY. So on `main` the emitted answer was wrong, confident, and green.

An absent answer indistinguishable from a real one is the false-certificate
shape this repo has spent a campaign removing. The repair is on the
ENFORCEMENT axis, not the resolution axis:

  * `derive_signals` gains a THIRD width state — ``width: None`` plus
    ``width_declared`` — for a width the layer STATES and the consumer
    cannot use. It still resolves nothing.
  * every scaffold emitter raises `UnresolvedPortWidth` rather than
    rendering it, and `emit_scaffold` raises BEFORE the first write, so the
    generator emits nothing and exits 1 instead of a wrong interface.
  * the l17 rail gains a third arm for the new state. All three arms are
    ERROR, so no consumer-side change can make the gate green — it can only
    change WHICH finding is reported.

WHY A WRONG WIDTH CANNOT SATISFY THIS
--------------------------------------
`test_a_resolver_writing_a_wrong_width_cannot_silence_the_gate` drives the
exact §7 hazard: a resolver that turns the symbol into a number the
document contradicts. It changes the arm and never the verdict. And
`test_the_refusal_is_keyed_on_the_declaration_not_on_the_number` pins that
the refusal is decided by what the LAYER states, which no width written by
any consumer-side repair can alter.

MEASURED BLAST RADIUS (why this can BLOCK without being turned off)
--------------------------------------------------------------------
Over the 106 published cells carrying `phase1/generated_docs` — the 15
under `benchmark-data/ic` plus the 81-IC phase-1 parity corpus, which is
where the published scaffold artefacts actually live — the stock and the
changed generator emit BYTE-IDENTICAL `_top.v` for 103, and the changed one
refuses on 3. All 3 are the same port of the same design, and none of the 3
has a published scaffold: their RTL was authored and declares the parameter
and the symbolic range correctly. Zero published artefacts change.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import phase2_scaffold_gen as scaf  # noqa: E402

_GATE = _PROGRAMS / "l17_channel_catalog_consumer_contract_check.py"
_GATE_MOD = importlib.import_module(
    "l17_channel_catalog_consumer_contract_check")
_SCAF_SRC = _PROGRAMS / "phase2_scaffold_gen.py"


# ---------------------------------------------------------------------------
# 1. derive_signals — the three states
# ---------------------------------------------------------------------------

def _sig(signals, name):
    return next(s for s in signals if s["name"] == name)


def test_a_symbolic_width_is_refused_not_coerced_to_one():
    """The issue's own reproduction, re-run. It used to print width 1."""
    out = scaf.derive_signals({}, {"top_ports": [
        {"name": "acc_o", "direction": "output",
         "width": "ACC_W-1:0", "width_symbolic": "ACC_W-1:0"}]})
    row = _sig(out, "acc_o")
    assert row["width"] is None
    assert row["width_declared"] == "ACC_W-1:0"


def test_a_prose_width_is_refused_not_coerced_to_one():
    out = scaf.derive_signals({}, {"top_ports": [
        {"name": "d_o", "direction": "output",
         "width": "the accumulator is 48 bits in this configuration"}]})
    assert _sig(out, "d_o")["width"] is None


def test_a_declared_integer_width_is_untouched():
    """Paired half one: nothing that already worked may change."""
    out = scaf.derive_signals({}, {"top_ports": [
        {"name": "bus_o", "direction": "output", "width": 32},
        {"name": "str_o", "direction": "output", "width": "16"}]})
    assert _sig(out, "bus_o")["width"] == 32
    assert _sig(out, "str_o")["width"] == 16
    assert "width_declared" not in _sig(out, "bus_o")


def test_an_absent_width_still_defaults_to_one_bit():
    """Paired half two, and the reason this change is landable at all.

    A layer that states NO width is a different state from one that states
    a width the consumer cannot use. Measured over the published corpus, 80
    derived ports come from an entry with no width, and the design's own
    input files (read by `l1_pin_bus_width_actionable_check`, not by any
    L-doc) prove a bit range for ZERO of them. Refusing here would block 6
    of 15 IC cells for a defect no evidence supports.
    """
    out = scaf.derive_signals({}, {"top_ports": [
        {"name": "en", "direction": "input"},
        {"name": "vld", "direction": "input", "width": None}]})
    assert _sig(out, "en")["width"] == 1
    assert _sig(out, "vld")["width"] == 1
    assert scaf.unresolved_width_ports(out) == []


def test_the_auto_added_clock_and_reset_are_never_refused():
    """They are the consumer's own stubs, not a layer declaration."""
    out = scaf.derive_signals({}, {})
    assert {s["name"] for s in out} >= {"clk", "rst_n"}
    assert scaf.unresolved_width_ports(out) == []


def test_a_numeric_l17_channel_hint_wins_over_an_unusable_l9_twin():
    """The dedup case, which is why the mark is applied in a post-pass.

    `_add` returns early for a name it has already seen, so the L17 entry
    wins. If L17 gave a real number the consumer DID resolve the width and
    must not refuse; only a port that never got one is unresolved.
    """
    l17 = {"channels": [{"name": "dq[7:0]", "direction_master": "input"}]}
    l9 = {"top_ports": [{"name": "dq", "direction": "input",
                         "width": "DW-1:0", "width_symbolic": "DW-1:0"}]}
    out = scaf.derive_signals(l17, l9)
    assert _sig(out, "dq")["width"] == 8


def test_an_l17_channel_without_a_hint_inherits_the_l9_refusal():
    """The other half of the dedup case. The consumer used its 1-bit default
    while a layer it reads declared a width it never managed to use — that is
    the collapse, arriving by the other door."""
    l17 = {"channels": [{"name": "dq", "direction_master": "input"}]}
    l9 = {"top_ports": [{"name": "dq", "direction": "input",
                         "width": "DW-1:0", "width_symbolic": "DW-1:0"}]}
    out = scaf.derive_signals(l17, l9)
    assert _sig(out, "dq")["width"] is None


# ---------------------------------------------------------------------------
# 2. The emitters refuse
# ---------------------------------------------------------------------------

_UNRESOLVED = [{"name": "acc_o", "direction": "output", "width": None,
                "comment": "", "width_declared": "ACC_W-1:0"},
               {"name": "clk", "direction": "input", "width": 1,
                "comment": ""}]
_OK = [{"name": "acc_o", "direction": "output", "width": 16, "comment": ""},
       {"name": "clk", "direction": "input", "width": 1, "comment": ""}]


@pytest.mark.parametrize("call", [
    lambda s: scaf.emit_top_v("dut", s, "ic"),
    lambda s: scaf.emit_tb_v("dut", s),
    lambda s: scaf.emit_cocotb_test("dut", s, {}, []),
    lambda s: scaf.emit_soc_wrap_v("dut", s, []),
])
def test_every_emitter_refuses_an_unresolved_width(call):
    """Not only `emit_scaffold`. Importing one emitter directly is a real
    call shape — `l4_regmap_phase2_emitter_contract_check` does exactly that
    — and a refusal only the orchestrator performs is one an importer walks
    straight past."""
    with pytest.raises(scaf.UnresolvedPortWidth) as exc:
        call(_UNRESOLVED)
    assert "acc_o" in str(exc.value)
    assert "ACC_W-1:0" in str(exc.value)


@pytest.mark.parametrize("call,marker", [
    (lambda s: scaf.emit_top_v("dut", s, "ic"), "acc_o"),
    (lambda s: scaf.emit_tb_v("dut", s), "acc_o"),
    # The cocotb emitter writes a driver SKELETON — a Timer and a log line —
    # and never names a port even for a fully resolved width. Asserting
    # "acc_o" here would be asserting something this emitter has never done,
    # so the paired half checks what it DOES render. It still refuses on an
    # unresolved width (see the test above): a test skeleton generated against
    # a port list the generator could not read is a test for an interface
    # nobody verified.
    (lambda s: scaf.emit_cocotb_test("dut", s, {}, []), "cocotb"),
    (lambda s: scaf.emit_soc_wrap_v("dut", s, []), "acc_o"),
])
def test_every_emitter_still_renders_resolved_widths(call, marker):
    """Paired half: the refusal must fire on the defect and on nothing else."""
    out = call(_OK)
    assert marker in out
    assert out.strip(), "emitter produced nothing for a fully resolved port set"


# ---------------------------------------------------------------------------
# 3. emit_scaffold — BLOCKING, and before the first write
# ---------------------------------------------------------------------------

def _project(tmp_path: Path, ports, parameters=None) -> Path:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": "dut"}))
    body = {"top_ports": ports}
    if parameters is not None:
        body["parameters"] = parameters
    (gd / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"fields": body}))
    (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(
        json.dumps({"fields": {"channels": []}}))
    return tmp_path


_SYMBOLIC_PORT = [{"name": "acc_o", "direction": "output",
                   "width": "ACC_W-1:0", "width_symbolic": "ACC_W-1:0"}]


def test_emit_scaffold_raises_and_writes_no_file(tmp_path):
    """A PARTIAL scaffold is worse than none: three files built around an
    interface the fourth just declared unemittable, with nothing on disk
    saying so. The check has to be ahead of the first `_write`."""
    project = _project(tmp_path, _SYMBOLIC_PORT)
    with pytest.raises(scaf.UnresolvedPortWidth):
        scaf.emit_scaffold(project)
    out_dir = project / "phase2" / "stage1" / "scaffold"
    assert sorted(p.name for p in out_dir.iterdir()) == [], \
        "a partial scaffold was left on disk"


def test_the_cli_exits_1_and_names_the_port(tmp_path):
    project = _project(tmp_path, _SYMBOLIC_PORT)
    r = subprocess.run([sys.executable, str(_SCAF_SRC), str(project)],
                       capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    report = json.loads(r.stdout)
    assert report["status"] == "blocked"
    assert report["reason"] == "UNRESOLVED_PORT_WIDTH"
    assert report["ports"] == [{"name": "acc_o",
                                "width_declared": "ACC_W-1:0"}]


def test_the_cli_still_emits_a_scaffold_it_can_resolve(tmp_path):
    """Paired half. Without this, deleting the emitter would pass the test
    above."""
    project = _project(tmp_path, [
        {"name": "acc_o", "direction": "output", "width": 16}])
    r = subprocess.run([sys.executable, str(_SCAF_SRC), str(project)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["status"] == "ok"
    top = project / "phase2" / "stage1" / "scaffold" / "dut_top.v"
    assert "[15:0] acc_o" in top.read_text()


# ---------------------------------------------------------------------------
# 4. The gate cannot be satisfied by writing a wrong width
# ---------------------------------------------------------------------------

def _categories(project):
    findings, _info = _GATE_MOD.audit(project)
    return [f.category for f in findings]


def _resolver_writing(value):
    """A consumer-side resolver that writes `value` for every width the real
    consumer refused. It stands in for ANY repair that turns the symbol into
    a number, right or wrong."""
    original = _GATE_MOD._consumer.derive_signals

    def resolving(l17, l9):
        signals = original(l17, l9)
        for sig in signals:
            if sig.get("width") is None:
                sig["width"] = value
                sig.pop("width_declared", None)
        return signals
    return resolving


def test_a_resolver_writing_a_wrong_width_cannot_silence_the_gate(
        tmp_path, monkeypatch):
    """THE discriminator for this round, and the reason this repair is not
    the withdrawn one. The fixture states 48 in the port's own prose and
    declares the parameter as 4 in the same document — the §7 hazard,
    verbatim. A resolver writes 4. The gate must still FAIL."""
    project = _project(
        tmp_path,
        [{"name": "acc_o", "direction": "output",
          "width": "the accumulator is 48 bits in this configuration",
          "width_symbolic": "ACC_W-1:0"}],
        parameters=[{"name": "ACC_W", "default": "4"}])
    monkeypatch.setattr(_GATE_MOD._consumer, "derive_signals",
                        _resolver_writing(4))
    cats = _categories(project)
    assert "PORT_WIDTH_SYMBOL_UNCORROBORATED" in cats, cats
    assert "PORT_WIDTH_UNRESOLVED_BY_CONSUMER" not in cats, cats


def test_a_resolver_writing_the_right_width_also_cannot_silence_it(
        tmp_path, monkeypatch):
    """The half that proves the gate is not merely a wrong-value detector.
    A right value and a wrong value are indistinguishable FROM HERE — which
    is exactly why neither is trusted. If this test ever goes green by the
    finding disappearing, a resolver has bought a green light instead of an
    answer."""
    project = _project(
        tmp_path,
        [{"name": "acc_o", "direction": "output",
          "width": "the accumulator is 48 bits in this configuration",
          "width_symbolic": "ACC_W-1:0"}],
        parameters=[{"name": "ACC_W", "default": "48"}])
    monkeypatch.setattr(_GATE_MOD._consumer, "derive_signals",
                        _resolver_writing(48))
    assert "PORT_WIDTH_SYMBOL_UNCORROBORATED" in _categories(project)


def test_a_reverted_consumer_falls_back_into_the_collapse_rail(
        tmp_path, monkeypatch):
    """The revert detector. `PORT_WIDTH_COLLAPSED_TO_ONE_BIT` is kept alive
    for exactly one purpose: a tree where the silent coercion is back must
    still be reported, and reported as the DIFFERENT thing it is."""
    project = _project(tmp_path, _SYMBOLIC_PORT)
    monkeypatch.setattr(_GATE_MOD._consumer, "derive_signals",
                        _resolver_writing(1))
    cats = _categories(project)
    assert "PORT_WIDTH_COLLAPSED_TO_ONE_BIT" in cats, cats


def test_no_arm_of_the_rail_returns_clean(tmp_path, monkeypatch):
    """Stated as one assertion so it cannot rot into three that each pass
    while a fourth arm gets added with no finding."""
    project = _project(tmp_path, _SYMBOLIC_PORT)
    for width in (None, 1, 8, 4096):
        if width is None:
            monkeypatch.setattr(_GATE_MOD._consumer, "derive_signals",
                                _GATE_MOD._consumer.derive_signals)
        else:
            monkeypatch.setattr(_GATE_MOD._consumer, "derive_signals",
                                _resolver_writing(width))
        findings, _ = _GATE_MOD.audit(project)
        width_rows = [f for f in findings
                      if f.category.startswith("PORT_WIDTH_")]
        assert width_rows, f"no finding for consumer width {width!r}"
        assert all(f.severity == "ERROR" for f in width_rows)


def test_the_refusal_is_keyed_on_the_declaration_not_on_the_number():
    """Source-level pin, in the spirit of round 2's. The refusal must be
    decided by what the LAYER states — a field no consumer-side width repair
    writes — never by the number the consumer produced."""
    src = _SCAF_SRC.read_text()
    body = src.split("def _record_declared_width(")[1].split("\ndef ")[0]
    assert "width_symbolic" in body
    assert 'entry.get("width")' in body
    assert "== 1" not in body, (
        "the refusal is keyed on the consumer's own number again")


def test_a_genuine_one_bit_port_is_still_not_reported(tmp_path):
    """Carried forward from round 1 and re-asserted against the new arm:
    firing on every width==1 port would hit every clock, reset and enable in
    every design."""
    project = _project(tmp_path, [
        {"name": "en", "direction": "input", "width": 1},
        {"name": "ok", "direction": "output", "width": "8"}])
    cats = _categories(project)
    assert not [c for c in cats if c.startswith("PORT_WIDTH_")], cats


# ---------------------------------------------------------------------------
# 5. The published corpus does not regress
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    p = _PROGRAMS
    while p != p.parent and not (p / "benchmark-data").is_dir():
        p = p.parent
    return p


def test_the_published_corpus_refuses_only_where_a_layer_declares_a_symbol():
    """The blast-radius measurement, executable.

    Not "3", which would rot the moment a cell is added or removed: the
    invariant is that a cell is refused IF AND ONLY IF one of the two keys
    `derive_signals` reads carries a width it cannot use. A refusal that
    cannot be traced to a declaration in that cell's own L-docs is a false
    positive, and a declaration with no refusal is a hole.
    """
    root = _repo_root()
    corpus = root / "benchmark-data"
    if not corpus.is_dir():
        pytest.skip("no published corpus in this tree")
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "benchmark-data"],
        capture_output=True, text=True)
    cells = [root / r for r in tracked.stdout.split("\0")
             if r.endswith("phase1/generated_docs/L1_DATASHEET.json")]
    if not cells:
        pytest.skip("corpus not tracked in this tree")

    def _load(p):
        try:
            return scaf._unwrap_fields(json.loads(p.read_text()))
        except Exception:  # noqa: BLE001
            return {}

    examined = refused = declared = 0
    for l1_path in cells:
        gd = l1_path.parent
        l9 = _load(gd / "L9_INTEGRATION_SPEC.json")
        l17 = _load(gd / "L17_CHANNEL_SIGNAL_CATALOG.json")
        examined += 1
        has_decl = any(
            (isinstance(p.get("width_symbolic"), str)
             and p["width_symbolic"].strip())
            or (isinstance(p.get("width"), str) and p["width"].strip()
                and not p["width"].strip().isdigit())
            for key in ("top_ports", "ports")
            for p in (l9.get(key) or []) if isinstance(p, dict))
        declared += int(has_decl)
        got = bool(scaf.unresolved_width_ports(scaf.derive_signals(l17, l9)))
        refused += int(got)
        assert got == has_decl, (
            f"{l1_path}: refused={got} but declaration present={has_decl}")
    assert examined > 10, examined
    assert refused == declared
