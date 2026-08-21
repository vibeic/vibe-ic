"""test_a4_consumes_design_netlist.py — A4 must simulate the DESIGN, not itself.

THE OTHER HALF OF A RULE THAT WAS ONLY HALF ENFORCED
====================================================
A sibling change made the corner sweep REFUSE when the upstream netlist step
produced nothing. That closed the loud half of "a step must not substitute its
own content for an upstream step's declared output". The quiet half stayed
open: with the netlist ON DISK, the sweep still simulated its own built-in
per-block-type testbench table and stamped the artefact `builtin_template` —
an accurate label on a measurement of the wrong circuit. Nine real PVT corners,
a real simulator, a real log per corner, and a subject that was a pure function
of (block type, PDK section, sweep knob).

THE RULE UNDER TEST, stated without naming a tool or a block:

    Where a step's declared upstream artefact EXISTS, that artefact is the
    subject of measurement. Where it does not, the step measures nothing and
    records a named blocked result. A step never stands its own content in for
    the artefact — not when the artefact is missing, and not when it is there.

WHY THE TESTS LOOK LIKE THIS. Every assertion is on bytes on disk or on the
argv/rc of a shipped gate, and each one first asserts a PRECONDITION that the
producer actually ran. "No template deck was written" and "the artefact is not
design-traceable" are both true of a tree where nothing happened; a control
that cannot fail is the defect this campaign exists to remove.

Every fixture is synthetic: invented block names, an open PDK selector, and
device geometry chosen to be obviously not anyone's design.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
GATE = PROGRAMS / "analog_a4_corner_sweep_check.py"

sys.path.insert(0, str(PROGRAMS))


# ───────────────────────────── synthetic fixture ───────────────────────────
#
# A marker that appears in the delivered netlist and in NO built-in template,
# so "which circuit ran" is decidable by reading the deck.
MARKER_NET = "n_synthetic_marker"


def _netlist(block: str, *, extra_card: str = "") -> str:
    """A synthetic delivered netlist: a `.subckt` with real device cards, its
    own model-lib card, and a node name no built-in template contains."""
    return (
        f"* {block} — synthetic delivered block netlist\n"
        f"* _provenance: producer=synthetic-fixture\n"
        f".option scale=1u\n"
        f".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt\n"
        f"\n"
        f".subckt {block} vdd vss vref vout\n"
        f"xm_in {MARKER_NET} vref vss vss sky130_fd_pr__nfet_01v8 w=7 l=3\n"
        f"xm_out vout {MARKER_NET} vdd vdd sky130_fd_pr__pfet_01v8 w=11 l=3\n"
        f"{extra_card}"
        f"r_fb vout {MARKER_NET} 123k\n"
        f".ends {block}\n")


def _testbench(block: str, *, control: str | None = None) -> str:
    ctrl = control if control is not None else (
        "op\nlet vo = v(vout)\necho \"MEAS vout=\" $&vo\n")
    return (
        f"* tb_{block} — synthetic stimulus for the delivered netlist\n"
        f"* condition: supply = 3.3 V (testbench condition)\n"
        f".include {block}.sp\n"
        f"v_vdd vdd 0 3.3\n"
        f"v_vref vref 0 0.9\n"
        f"xdut vdd 0 vref vout {block}\n"
        f"r_load vout 0 1k\n"
        f".control\n{ctrl}.endc\n"
        f".end\n")


def _project(tmp_path, blocks, *, netlist=(), testbench=(), extra_card="",
             control=None) -> Path:
    """`blocks` is [(name, type)]. `netlist` / `testbench` name the blocks for
    which each half of the delivered pair exists, so the two can be varied
    independently."""
    root = tmp_path / "proj"
    adir = root / "phase3" / "analog"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": n, "type": t} for n, t in blocks]}, indent=2))
    for name, _t in blocks:
        (adir / name).mkdir(parents=True, exist_ok=True)
    for name in netlist:
        (adir / name / f"{name}.sp").write_text(
            _netlist(name, extra_card=extra_card))
    for name in testbench:
        (adir / name / f"{name}.sp").parent.mkdir(parents=True, exist_ok=True)
        (adir / name / f"tb_{name}.sp").write_text(
            _testbench(name, control=control))
    return root


#: The two answers that NAME what a netlist contains. Anything else — the
#: record absent, or present and saying it has no answer — is the upstream
#: declining to say, and a run built on it cannot be certified.
STRUCTURE_ONLY = "structure_only"
SIZED = "structure_and_geometry"


def _sidecar(project: Path, block: str, design_content: str = SIZED) -> None:
    """The upstream producer's record of WHAT its netlist contains.

    Deliberately NOT written by `_project`. Whether the chain discloses is a
    property several tests here vary on purpose, and a fixture that supplied it
    unconditionally would hide the tree in which nobody says anything — which
    is the tree the gate exists for. No consumer can look at a `.sp` and know
    whether a number in it came from a bound input or from a library default;
    only the producer that resolved it knows, and this is where it writes the
    answer down.
    """
    (project / "phase3" / "analog" / block / "netlist_provenance.json"
     ).write_text(json.dumps({
         "block": block,
         "_provenance": {
             "producer": "synthetic-fixture",
             "design_content": design_content,
             "spec_bound_params": ([] if design_content == STRUCTURE_ONLY
                                   else ["r1.l"]),
             "library_nominal_params": ["m1.w", "m1.l"],
         }}, indent=2))


def _fake_docker(meas="MEAS vout=1.800000e+00\n", decks=None, calls=None):
    """A container stand-in that answers the sweep's probes and RECORDS the
    exact deck text handed to the simulator, so the assertions are about the
    bytes ngspice would have read."""
    def fake(container, cmd, timeout=120):
        if calls is not None:
            calls.append(cmd)
        if "command -v ngspice" in cmd or "which ngspice" in cmd \
                or "ls /foss/tools" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "/usr/bin/ngspice\n", "")
        if "--json-measure" in cmd and " -v " in cmd:
            return subprocess.CompletedProcess(cmd, 0, "unrecognized option", "")
        if cmd.startswith("grep -ioE") and ".lib" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, ".lib ss\n.lib tt\n.lib ff\n", "")
        if " -b " in cmd and ".sp" in cmd:
            for tok in cmd.split():
                p = Path(tok.strip("'\""))
                if p.suffix == ".sp" and p.is_file():
                    if decks is not None:
                        decks[str(p)] = p.read_text()
            return subprocess.CompletedProcess(cmd, 0, meas, "")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return fake


def _sweep(monkeypatch, *, meas="MEAS vout=1.800000e+00\n", decks=None,
           calls=None):
    import analog_real_corner_sweep as S
    monkeypatch.setattr(S, "_docker",
                        _fake_docker(meas=meas, decks=decks, calls=calls))
    S._NGSPICE_CACHE.clear()
    S._CONTAINER_PATH_CACHE.clear()
    S._JSON_MEASURE_SUPPORT.clear()
    S._PDK_SECTION_CACHE.clear()
    return S


def _decks_on_disk(project, block):
    d = project / "phase3" / "analog" / block / "sizing_loop"
    return sorted(d.glob("*.sp")) if d.is_dir() else []


def _record(project, block):
    return json.loads((project / "phase3" / "analog" / block
                       / "corner_results.json").read_text())


# ── 1. THE CENTRAL CLAIM ────────────────────────────────────────────────────

def test_the_deck_handed_to_the_simulator_is_the_delivered_netlist(
        tmp_path: Path, monkeypatch) -> None:
    """The bytes ngspice reads must be the delivered circuit.

    Asserted from BOTH sides, because either alone is passable by accident:
    the delivered netlist's own device cards must be present, AND the built-in
    table's cards for this same block type must be absent. A producer that
    merely appended the netlist as dead text beside its own testbench would
    satisfy the first and fail the second.
    """
    decks: dict = {}
    S = _sweep(monkeypatch, decks=decks)

    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    rc = S.run_block(project, "blk_alpha", "fake", "sky130", "auto")

    # PRECONDITION — the producer ran and reached the simulator. Without this,
    # every assertion below is also true of a tree where nothing happened.
    assert rc == 0, "the sweep did not complete over the delivered netlist"
    assert decks, "the simulator was never handed a deck"

    builtin = S.T["ldo"]
    for path, text in decks.items():
        assert f".subckt blk_alpha" in text, (
            f"{Path(path).name} does not contain the delivered netlist")
        assert MARKER_NET in text, (
            f"{Path(path).name} is missing the delivered netlist's own nodes")
        assert "w=7 l=3" in text and "r_fb vout" in text, (
            f"{Path(path).name} does not carry the delivered device cards")
        # The built-in ldo deck's distinctive cards must be nowhere in it.
        for card in ("r_ibias vdd nbias 600k", ".param m_pass=",
                     "xmn_b nbias nbias 0 0"):
            assert card in builtin, "fixture drifted from the built-in table"
            assert card not in text, (
                f"{Path(path).name} carries the BUILT-IN template card "
                f"{card!r} — the sweep is still simulating its own circuit")

    rec = _record(project, "blk_alpha")
    assert rec["netlist_provenance"] == "a3_netlist"
    assert rec["design_traceable"] is True
    assert rec["deck_source"] == "a3_netlist"
    assert rec["netlist_source"].endswith("blk_alpha.sp")
    assert rec["netlist_testbench"].endswith("tb_blk_alpha.sp")
    assert rec["netlist_sha256"] and rec["netlist_testbench_sha256"]


def test_the_artefact_digests_match_the_files_that_were_simulated(
        tmp_path: Path, monkeypatch) -> None:
    """A provenance field that does not tie to bytes proves nothing."""
    import hashlib
    S = _sweep(monkeypatch)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    assert S.run_block(project, "blk_alpha", "fake", "sky130", "auto") == 0
    rec = _record(project, "blk_alpha")
    adir = project / "phase3" / "analog" / "blk_alpha"
    assert rec["netlist_sha256"] == hashlib.sha256(
        (adir / "blk_alpha.sp").read_bytes()).hexdigest()
    assert rec["netlist_testbench_sha256"] == hashlib.sha256(
        (adir / "tb_blk_alpha.sp").read_bytes()).hexdigest()


# ── 2. THE REFUSALS ─────────────────────────────────────────────────────────

def test_a_netlist_with_no_stimulus_is_refused_not_improvised(
        tmp_path: Path, monkeypatch) -> None:
    """Half a delivered pair is not a subject of measurement.

    A netlist is a `.subckt`; exciting it needs supplies, a reference and a
    load. Those are operating conditions, and inventing them here is the same
    substitution in a smaller coat — so the step refuses and names the half it
    is missing.
    """
    calls: list = []
    S = _sweep(monkeypatch, calls=calls)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",))       # no tb_blk_alpha.sp

    # PRECONDITION — the netlist really is on disk, so this is not just the
    # already-covered "nothing was produced" path.
    sp = project / "phase3" / "analog" / "blk_alpha" / "blk_alpha.sp"
    assert sp.is_file() and sp.stat().st_size > 200

    rc = S.run_block(project, "blk_alpha", "fake", "sky130", "auto")
    assert rc == 2
    assert calls == [], (
        f"the simulator was reached for an unusable delivered pair: {calls[:3]}")
    assert not _decks_on_disk(project, "blk_alpha"), (
        "a deck was written for a netlist that has no declared stimulus")

    rec = _record(project, "blk_alpha")
    assert rec["status"] == "BLOCKED"
    assert rec["design_traceable"] is False
    assert rec["simulator_run"] is False
    assert rec["corners"] == [] and rec["spec_results"] == []
    assert rec["netlist_present_but_unusable"].endswith("blk_alpha.sp"), (
        "the record must distinguish 'nothing was produced' from 'what was "
        "produced cannot be simulated' — they need different fixes")
    assert "tb_blk_alpha.sp" in rec["reason"]


def test_the_stimulus_must_name_the_netlist_exactly_once(
        tmp_path: Path, monkeypatch) -> None:
    """Two include cards, or none, means the circuit under test is ambiguous.

    Refusing beats picking one: the whole point of the artefact is that a
    reader can say which circuit produced the number.
    """
    calls: list = []
    S = _sweep(monkeypatch, calls=calls)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    tb = project / "phase3" / "analog" / "blk_alpha" / "tb_blk_alpha.sp"
    tb.write_text(tb.read_text().replace(
        ".include blk_alpha.sp",
        ".include blk_alpha.sp\n.include blk_alpha.sp"))
    assert tb.read_text().count(".include blk_alpha.sp") == 2   # precondition

    rc = S.run_block(project, "blk_alpha", "fake", "sky130", "auto")
    assert rc == 2
    assert not _decks_on_disk(project, "blk_alpha")
    rec = _record(project, "blk_alpha")
    assert rec["status"] == "BLOCKED"
    assert rec["deck_unbuildable_reason"], (
        "a refusal must say what about the delivered pair could not be used")
    assert "include" in rec["deck_unbuildable_reason"]


# ── 3. THE BUILT-IN TABLE ───────────────────────────────────────────────────

def test_the_builtin_table_is_unreachable_while_a_delivered_netlist_exists(
        tmp_path: Path, monkeypatch) -> None:
    """The opt-in is an escape hatch for ABSENCE, never an override.

    Otherwise one environment variable silently turns a design measurement back
    into a self-test, and the artefact would say so only in a field nobody
    reads.
    """
    decks: dict = {}
    S = _sweep(monkeypatch, decks=decks)
    monkeypatch.setenv("ANALOG_ALLOW_BUILTIN_NETLIST", "1")
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))

    rc = S.run_block(project, "blk_alpha", "fake", "sky130", "auto")
    assert rc == 0 and decks                      # precondition: it really ran
    rec = _record(project, "blk_alpha")
    assert rec["design_traceable"] is True
    assert rec["deck_source"] == "a3_netlist"
    for text in decks.values():
        assert MARKER_NET in text
        assert ".param m_pass=" not in text


def test_every_artefact_a_builtin_deck_touches_says_it_is_builtin(
        tmp_path: Path, monkeypatch) -> None:
    """The table survives as a labelled fallback, so the label has to be
    everywhere: a reader who opens ONE file must not have to know that another
    file exists to learn the deck carried no design content."""
    decks: dict = {}
    S = _sweep(monkeypatch, meas="MEAS vout=1.800000e+00 reff=5.0e+04\n",
               decks=decks)
    monkeypatch.setenv("ANALOG_ALLOW_BUILTIN_NETLIST", "1")
    project = _project(tmp_path, [("blk_alpha", "ldo")])   # nothing delivered

    rc = S.run_block(project, "blk_alpha", "fake", "sky130", "auto")
    # PRECONDITION — the opt-in really did produce a simulated sweep.
    assert rc == 0 and decks, "the built-in path did not run"

    rec = _record(project, "blk_alpha")
    assert rec["design_traceable"] is False
    assert rec["deck_source"] == "builtin_template"
    assert rec["netlist_provenance"] == "builtin_template"
    assert "BUILT-IN" in rec["deck_authored_by"]
    assert rec["builtin_override"] == "ANALOG_ALLOW_BUILTIN_NETLIST", (
        "the artefact must name what unlocked the fallback, or a reader "
        "cannot tell a deliberate exercise from a default")

    sl = json.loads((project / "phase3" / "analog" / "blk_alpha"
                     / "sizing_loop" / "results.json").read_text())
    assert sl["netlist_provenance"] == "builtin_template"

    on_disk = _decks_on_disk(project, "blk_alpha")
    assert on_disk
    for p in on_disk:
        head = "\n".join(p.read_text().splitlines()[:6])
        assert "netlist_provenance: builtin_template" in head
        assert "design_traceable: false" in head
        assert "BUILT-IN" in head, (
            f"{p.name} read on its own does not say its circuit is built-in")

    # And the gate of record still refuses to certify it.
    r = subprocess.run([sys.executable, str(GATE), str(project),
                        "--block", "blk_alpha"], capture_output=True, text=True)
    assert r.returncode == 1, "a built-in sweep must not be certifiable"
    assert "A4_NETLIST_NOT_FROM_A3" in (r.stdout + r.stderr)


def test_a_block_type_the_table_does_not_carry_is_still_simulated(
        tmp_path: Path, monkeypatch) -> None:
    """A delivered netlist is not gated on this program owning a template.

    Before, a type absent from the table deferred outright — so the set of
    measurable circuits was the set this file happened to have authored. The
    delivered artefact decides now.
    """
    decks: dict = {}
    S = _sweep(monkeypatch, decks=decks)
    assert "widget_q" not in S.T                          # precondition
    project = _project(tmp_path, [("blk_beta", "widget_q")],
                       netlist=("blk_beta",), testbench=("blk_beta",))

    rc = S.run_block(project, "blk_beta", "fake", "sky130", "auto")
    assert rc == 0, "a delivered netlist was refused for want of a template"
    assert decks
    rec = _record(project, "blk_beta")
    assert rec["design_traceable"] is True
    assert rec["block_type"] == "widget_q"


# ── 4. WHAT A DESIGN DECK IS *NOT* ──────────────────────────────────────────

def test_a_delivered_netlist_is_not_swept_and_the_record_says_why(
        tmp_path: Path, monkeypatch) -> None:
    """Sweeping delivered geometry means rewriting the design's devices.

    That is a different step with a different producer. The record has to say
    the sweep did not happen, or a reader assumes the reported point is a
    chosen one.
    """
    decks: dict = {}
    S = _sweep(monkeypatch, decks=decks)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    # PRECONDITION — this block type DOES have a multi-point knob sweep, so a
    # single nominal deck is a decision and not an artefact of the fixture.
    assert len(S.SWEEPS["ldo"]) > 1

    assert S.run_block(project, "blk_alpha", "fake", "sky130", "auto") == 0
    rec = _record(project, "blk_alpha")
    assert rec["sizing_knob_swept"] is None
    assert "sizing" in rec["sizing_knob_disclosure"]
    nominal = [p for p in _decks_on_disk(project, "blk_alpha")
               if p.name.startswith("run_")]
    assert len(nominal) == 1, (
        f"expected exactly one nominal deck at the delivered geometry, got "
        f"{[p.name for p in nominal]}")
    assert len(rec["all_runs"]) == 1


def test_a_corner_deck_differs_from_its_sibling_only_in_the_corner_cards(
        tmp_path: Path, monkeypatch) -> None:
    """Proof that the corner sweep does not edit the design.

    Two corners of the same block must differ in the process section and the
    temperature and in NOTHING else; any other differing line is this program
    changing the circuit between corners.
    """
    decks: dict = {}
    S = _sweep(monkeypatch, decks=decks)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    assert S.run_block(project, "blk_alpha", "fake", "sky130", "auto") == 0

    sl = project / "phase3" / "analog" / "blk_alpha" / "sizing_loop"
    a, b = (sl / "pvt_ss_m40c.sp"), (sl / "pvt_ff_125c.sp")
    assert a.is_file() and b.is_file()
    # PRECONDITION — the decks being compared are the DESIGN's. Without this
    # the assertion below is equally true of two built-in decks, which also
    # differ only in their corner cards: a control that cannot fail.
    for p in (a, b):
        t = p.read_text()
        assert ".subckt blk_alpha" in t and MARKER_NET in t, (
            f"{p.name} is not the delivered circuit — this comparison would "
            f"pass on a tree where the design was never consumed")
    la, lb = a.read_text().splitlines(), b.read_text().splitlines()
    assert len(la) == len(lb)
    diff = [(x, y) for x, y in zip(la, lb) if x != y]
    assert diff, "two different corners produced byte-identical decks"
    for x, y in diff:
        head = x.strip().split()[0] if x.strip() else ""
        assert head in (".lib", ".temp"), (
            f"the corner sweep changed a non-corner line: {x!r} -> {y!r}")


def test_the_graded_metric_comes_from_the_design_when_the_table_has_none(
        tmp_path: Path, monkeypatch) -> None:
    """A delivered deck reports what the DESIGN measures.

    When that is not the metric this file's static table grades, the honest
    move is to grade what was measured and carry NO target for it — inventing
    one would be this program deciding what the design is for. Discarding the
    measurement would be worse: a real result thrown away because a constant
    table did not anticipate it.
    """
    decks: dict = {}
    S = _sweep(monkeypatch, meas="MEAS freq=8.4e+09 period=1.19e-10\n",
               decks=decks)
    # PRECONDITION — the static table grades a DIFFERENT key for this type.
    assert S.TARGETS["oscillator"]["key"] == "vout"
    project = _project(
        tmp_path, [("tick_src", "oscillator")],
        netlist=("tick_src",), testbench=("tick_src",),
        control=("tran 1p 1n\nlet freq = 8.4e9\n"
                 "echo \"MEAS freq=\" $&freq\n"))

    rc = S.run_block(project, "tick_src", "fake", "sky130", "auto")
    assert rc == 0 and decks
    rec = _record(project, "tick_src")
    sub = rec["graded_metric_substituted"]
    assert sub, "the substitution must be recorded, not silently performed"
    assert sub["graded_key"] == "freq"
    assert sub["static_table_key"] == "vout"
    assert rec["spec_results"][0]["name"] == "freq"
    assert rec["spec_results"][0]["target"] is None, (
        "a target for a metric the static table never had would be invented")
    assert rec["spec_results"][0]["value"] == 8.4e9


def test_the_l5_deck_overrides_are_disclosed_rather_than_applied(
        tmp_path: Path, monkeypatch) -> None:
    """Two derivations of the same operating condition must not both be in the
    deck with only one of them recorded.

    The delivered stimulus already carries conditions bound upstream. This
    program's own read of the same source is kept — visibly — beside the
    record instead of being written over them.
    """
    decks: dict = {}
    S = _sweep(monkeypatch, decks=decks)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    l5 = project / "phase1" / "generated_docs"
    l5.mkdir(parents=True, exist_ok=True)
    (l5 / "L5_ADI_SPEC.json").write_text(json.dumps({"analog_blocks": [
        {"name": "blk_alpha", "type": "ldo", "spec": {"specs": [
            {"name": "vout", "target": 1.8, "unit": "V"}]}}]}, indent=2))

    assert S.run_block(project, "blk_alpha", "fake", "sky130", "auto") == 0
    rec = _record(project, "blk_alpha")
    # PRECONDITION — this program really did derive an override from L5.
    assert rec["l5_deck_overrides_not_applied"], (
        "fixture did not exercise the override path")
    assert rec["deck_overrides"] == {}
    for text in decks.values():
        assert "v_vref vref 0 0.9" in text, (
            "the delivered stimulus line was not preserved verbatim")


# ── 5. PRODUCER → GATE OF RECORD ────────────────────────────────────────────

def test_the_gate_of_record_certifies_what_this_producer_now_emits(
        tmp_path: Path, monkeypatch) -> None:
    """End to end: the rule the gate enforces is now SATISFIABLE.

    Before, no input to this program could produce an artefact the gate would
    certify — every path led to `absent` or `builtin_template`. A gate whose
    pass state is unreachable is not a gate.

    The fixture gained the upstream sidecar. Without it the producer inherits
    `undeclared` — an honest statement that it has no record of what its
    netlist contains — and the gate declines to certify that, on purpose: if
    "I have no record" certified, a producer could buy a pass by writing that
    token instead of by inheriting the answer, and silence would be cheap again
    under a new name. Satisfying the gate means the WHOLE chain discloses, so
    the fixture supplies the link the chain was missing.
    """
    S = _sweep(monkeypatch)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    _sidecar(project, "blk_alpha", SIZED)
    assert S.run_block(project, "blk_alpha", "fake", "sky130", "auto") == 0
    r = subprocess.run([sys.executable, str(GATE), str(project),
                        "--block", "blk_alpha"], capture_output=True, text=True)
    assert r.returncode == 0, (
        f"the gate refused a design-derived sweep:\n{r.stdout}\n{r.stderr}")
    assert "PASS" in r.stdout


def test_the_same_run_without_the_upstream_record_is_not_certified(
        tmp_path: Path, monkeypatch) -> None:
    """The negative control for the line above, and the measured inversion.

    Byte-identical inputs except the upstream sidecar. Pre-fix this tree was
    the CHEAPER of the two: the producer wrote `undeclared`, nothing read it,
    and the gate certified — so a chain that disclosed nothing outscored a
    chain that disclosed a library default.
    """
    S = _sweep(monkeypatch)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    assert S.run_block(project, "blk_alpha", "fake", "sky130", "auto") == 0
    # PRECONDITION — the sweep ran and produced a full artefact; only the
    # statement of content is missing from it.
    rec = _record(project, "blk_alpha")
    assert rec.get("corners"), "PRECONDITION: no corners were produced"
    assert rec.get("design_content") == "undeclared", rec.get("design_content")

    r = subprocess.run([sys.executable, str(GATE), str(project),
                        "--block", "blk_alpha"], capture_output=True, text=True)
    assert r.returncode == 1, (
        f"a corner artefact that records no answer about what it simulated "
        f"was certified (rc={r.returncode})")
    assert "A4_DESIGN_CONTENT_UNDECLARED" in (r.stdout + r.stderr)


# ── 6. THE CORNER IS OURS TO CHOOSE; THE MODEL SET IS NOT ───────────────────

def test_the_corner_section_is_restamped_and_the_model_set_is_not(
        tmp_path: Path, monkeypatch) -> None:
    """Selecting a process corner means rewriting the section, and only that.

    A delivered netlist's device names were chosen against a particular model
    set. Silently pointing them at a different one instantiates one family's
    names against another family's models — a wrong number, produced by a real
    simulator, with nothing in the artefact to say so.
    """
    decks: dict = {}
    S = _sweep(monkeypatch, decks=decks)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    delivered = (project / "phase3" / "analog" / "blk_alpha"
                 / "blk_alpha.sp").read_text()
    # PRECONDITION — the delivered netlist really is bound to a named model set
    # at a named section, so "the section changed" is a decision, not a default.
    assert ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt" \
        in delivered

    assert S.run_block(project, "blk_alpha", "fake", "sky130", "auto") == 0
    sl = project / "phase3" / "analog" / "blk_alpha" / "sizing_loop"
    ss = (sl / "pvt_ss_m40c.sp").read_text()
    libs = [ln for ln in ss.splitlines()
            if ln.strip().startswith(".lib ")]
    assert len(libs) == 1, f"expected one corner card, got {libs}"
    assert libs[0].split()[1] == \
        "/foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice", (
        "the model set the delivered netlist was bound to was swapped")
    assert libs[0].split()[2] == "ss", "the corner section was not selected"

    rec = _record(project, "blk_alpha")
    assert rec["netlist_declared_model_lib"].endswith("sky130.lib.spice")
    assert rec["netlist_declared_model_section"] == "tt"
    assert rec["model_lib_path_changed"] is False


def test_a_netlist_bound_to_a_different_model_set_is_refused(
        tmp_path: Path, monkeypatch) -> None:
    """When the delivered binding and the resolved one disagree, refuse.

    Re-stamping the corner is this step's job; re-stamping the model set is
    not, and choosing one of the two silently is the whole failure mode this
    change exists to close.
    """
    calls: list = []
    S = _sweep(monkeypatch, calls=calls)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    sp = project / "phase3" / "analog" / "blk_alpha" / "blk_alpha.sp"
    sp.write_text(sp.read_text().replace(
        "/foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice",
        "/foss/pdks/other_family/libs.tech/ngspice/other.lib.spice"))
    # PRECONDITION — the delivered pair is otherwise complete and usable.
    assert (project / "phase3" / "analog" / "blk_alpha"
            / "tb_blk_alpha.sp").is_file()

    rc = S.run_block(project, "blk_alpha", "fake", "sky130", "auto")
    assert rc == 2
    assert not _decks_on_disk(project, "blk_alpha"), (
        "a deck was written against a model set the netlist was not bound to")
    rec = _record(project, "blk_alpha")
    assert rec["status"] == "BLOCKED"
    assert "other.lib.spice" in rec["deck_unbuildable_reason"]
    assert "sky130.lib.spice" in rec["deck_unbuildable_reason"], (
        "the refusal must name BOTH bindings, or nobody can tell which is "
        "wrong")
