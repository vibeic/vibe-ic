"""Steps 7/8/10 (pre-layout, stage-2) must be emittable BEFORE PnR.

ORGANIC (opentitan_aes r7). Steps 7 (SDC + PVT matrix) and 10 (pre-layout
multi-corner STA) are STAGE-2 / PRE-LAYOUT steps: their inputs are the
technology-mapped synth netlist + SDC + PDK liberty corners, none post-layout.
Their only producer was ``step_canonicalize_artefacts``, which runs at the TAIL
of phase-3 after step_pnr/step_gds/step_drc/step_lvs — so a route that did not
converge (killed on a 4 h wall-clock cap, measured on opentitan_aes) left the
three pre-layout artefacts UNWRITTEN and Steps 7/8/10 scored MISSING.

``step_prelayout_signoff`` closes this by emitting them right after synth,
before step_pnr, and main() wires it there. This test proves:

  1. NEGATIVE CONTROL — a project that does NOT stage >=2 corner libs is a
     NO-OP (SKIP), so the change cannot regress the container-built-in-PDK
     path (its post-route canonicalize emit is untouched).
  2. WIRING — main() calls step_prelayout_signoff, and does so BEFORE it calls
     step_pnr (the whole point: the pre-layout emit must not sit behind PnR).

Firing this step on the majority case also promotes everything it does to the
DEFAULT path, so the second half of this file pins the SDC it emits:

  3. the design's OWN SDC (``input/constraints``, via the shared
     ``_resolve_staged_silicon_sdc``) reaches BOTH emitted decks, rather than
     the runner's fabricated one;
  4. the same unit-rescale + DRV + I/O parity chain ``step_pnr`` applies is
     applied here, and never OVERRIDES a design-declared value;
  5. a deck this step FABRICATED is never copied to the canonical path, where
     the shared resolver would hand it back to ``step_pnr`` as "design-staged".
"""
import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as R  # noqa: E402

_SRC = (Path(__file__).resolve().parents[1] / "phase3_one_shot_runner.py").read_text()


def test_no_op_skip_when_no_staged_corners(tmp_path):
    """Negative control: <2 staged corner libs → SKIP, writes nothing.

    A test that could not fail against the pre-fix code proves nothing; this
    asserts the additive guard so a container-PDK project is provably untouched.
    """
    proj = tmp_path / "proj"
    (proj / "input" / "pdk" / "liberty").mkdir(parents=True)
    # zero staged libs → must SKIP

    class _Pdk:  # minimal stand-in; the SKIP path reads nothing off it
        name = "sky130A"
        liberty = "/foss/pdks/x/nom.lib"

    res = R.step_prelayout_signoff(proj, "chip_top", _Pdk(), "no-such-container")
    assert res.status == "SKIP", res.status
    assert res.output_files == []
    # exactly one staged lib is still a SKIP (a single corner is not a matrix)
    (proj / "input" / "pdk" / "liberty" / "tt.lib").write_text("library(tt){}")
    res1 = R.step_prelayout_signoff(proj, "chip_top", _Pdk(), "no-such-container")
    assert res1.status == "SKIP", res1.status


def test_container_builtin_corners_are_used_when_none_are_staged(tmp_path,
                                                                 monkeypatch):
    """ORGANIC #565 — a project that stages NO corners must still get Step 10.

    Pre-fix this step required >=2 libs under ``input/pdk/liberty`` and SKIPped
    otherwise, so it was inert on every container-built-in-PDK project — the
    majority case, and precisely the case its own docstring exists to cover (a
    backend that dies before ``step_canonicalize_artefacts`` leaves Step 10
    MISSING, VOIDING every step that depends on it).

    MEASURED (subservient x sky130A, plugin 1.9.76): the container shipped 18
    ``sky130_fd_sc_hd`` corner libs resolving to distinct SS/TT/FF, the
    ``pvt_matrix`` emitter in the SAME run recorded ``multi_corner: true,
    corner_count: 3`` from them — and this step still reported "no >=2 staged
    corner libs" and skipped.

    NEGATIVE CONTROL: against the pre-fix body this asserts SKIP and FAILS.
    """
    proj = tmp_path / "proj"
    (proj / "input" / "pdk" / "liberty").mkdir(parents=True)  # staged: ZERO

    class _Pdk:
        name = "sky130A"
        liberty = "/foss/pdks/sky130A/libs.ref/lib/x__tt_025C_1v80.lib"
        macro_libs: list = []

    # The container exposes two distinct process corners. Patch the SAME
    # discovery pair the pvt_matrix emitter uses, so the test proves the step
    # consults it — without needing a live container.
    monkeypatch.setattr(R, "_discover_container_corner_libs",
                        lambda c, d: [("x__ss_100C_1v60", d + "/x__ss.lib"),
                                      ("x__tt_025C_1v80", d + "/x__tt.lib")])
    # Keep the step hermetic: no container round-trips past the gate.
    monkeypatch.setattr(R, "_liberty_drv_limits", lambda *a, **k: {})
    monkeypatch.setattr(R, "_emit_multi_corner_sta", lambda *a, **k: False)

    res = R.step_prelayout_signoff(proj, "chip_top", _Pdk(), "some-container")

    assert res.status != "SKIP", (
        "step SKIPped despite the container exposing >=2 sign-off corners — "
        f"detail={res.detail!r}")
    pvt = proj / "phase2" / "stage2" / "constraints" / "pvt_matrix.json"
    assert pvt.is_file(), "no pvt_matrix.json emitted from built-in corners"
    labels = {c["label"] for c in json.loads(pvt.read_text())["corners"]}
    assert {"SS", "TT"} <= labels, labels


def test_skip_message_names_both_corner_sources(tmp_path):
    """When it DOES defer, the message must state what it searched.

    A bare "no staged corner libs" reads as "this PDK has no corners"; the
    measured defect was that the container had 18. The deferral must name both
    sources and both counts so the reader can tell which one was empty.
    """
    proj = tmp_path / "proj"
    (proj / "input" / "pdk" / "liberty").mkdir(parents=True)

    class _Pdk:
        name = "sky130A"
        liberty = "/foss/pdks/x/nom.lib"

    res = R.step_prelayout_signoff(proj, "chip_top", _Pdk(), "no-such-container")
    assert res.status == "SKIP"
    assert "staged" in res.detail and "container built-in" in res.detail, res.detail


def _corner_pdk(monkeypatch, liberty: str):
    """Two container corners + no container round-trips. Returns the PdkConfig
    stand-in the step is called with."""
    monkeypatch.setattr(R, "_discover_container_corner_libs",
                        lambda c, d: [("x__ss_100C_1v60", d + "/x__ss.lib"),
                                      ("x__tt_025C_1v80", d + "/x__tt.lib")])
    monkeypatch.setattr(R, "_liberty_drv_limits", lambda *a, **k: {})
    monkeypatch.setattr(R, "_emit_multi_corner_sta", lambda *a, **k: False)

    class _Pdk:
        name = "sky130A"
        macro_libs: list = []

    _Pdk.liberty = liberty
    return _Pdk()


# The DESIGN's own SDC, copied verbatim from the tracked benchmark project
# `benchmark-data/ic/edge_llm_accel/input/constraints/clock.sdc`. It stages at
# the canonical ground-truth path and names its clock `core_clock` — a name the
# runner's auto-SDC (`create_clock -name clk`) cannot produce by accident, so
# the assertion below cannot pass on a fabricated deck.
_EDGE_LLM_ACCEL_SDC = (
    "# edge_llm_accel — L9 §9.1 SDC (100 MHz)\n"
    "set_units -time ns\n"
    "create_clock [get_ports clk] -name core_clock -period 10.0\n")


def test_design_staged_sdc_reaches_the_canonical_step7_artefact(tmp_path,
                                                                monkeypatch):
    """The design's OWN clock must reach BOTH SDC artefacts this step writes.

    THE DEFECT. This step resolved the design SDC with a private probe —
    ``phase2/stage2/constraints/*.sdc`` then the project-root
    ``constraints/*.sdc`` — and never read ``input/constraints``, the shared
    ground truth ``_resolve_staged_silicon_sdc`` exists to enforce. That
    resolver's docstring records what the miss costs: it LAUNDERS the runner's
    fabricated SDC into "design-staged" and "a design's real SDC never reached
    PnR or STA at any point". While this step SKIPped on built-in-PDK projects
    the stale probe was unreachable in the majority case; firing the step there
    promotes it to the DEFAULT path.

    MEASURED on a fixture carrying `benchmark-data/ic/edge_llm_accel`'s own
    staged SDC (no `input/pdk/liberty`, so it is a built-in-PDK project):
    both emitted decks carried `create_clock -name clk` under an
    "# Auto-generated minimal SDC ... (no constraints/*.sdc supplied" header
    while the design supplied one. And it is PERMANENT, not transient:
    `step_pnr` overwrites `pnr/constraint.sdc` unconditionally but
    `step_canonicalize_artefacts` guards on `not canon_sdc.is_file()`, so the
    canonical Step-7 copy is never refreshed and disagrees with
    `pnr/constraint.sdc` for the rest of the run.

    NEGATIVE CONTROL: against the pre-fix body both assertions FAIL."""
    proj = tmp_path / "proj"
    (proj / "input" / "constraints").mkdir(parents=True)
    (proj / "input" / "constraints" / "clock.sdc").write_text(
        _EDGE_LLM_ACCEL_SDC)

    res = R.step_prelayout_signoff(
        proj, "chip_top", _corner_pdk(monkeypatch, "/foss/pdks/x/nom.lib"),
        "some-container")
    assert res.status == "PASS", res.detail

    runner_sdc = proj / "phase3" / "stage3" / "pnr" / "constraint.sdc"
    canon_sdc = proj / "phase2" / "stage2" / "constraints" / "chip_top.sdc"
    for f in (runner_sdc, canon_sdc):
        text = f.read_text()
        assert "core_clock" in text, (
            f"{f.name} does not carry the design's own clock name; it reads:\n"
            f"{text[:400]}")
        assert "-period 10.0" in text, text[:400]
        assert "# Auto-generated minimal SDC" not in text, (
            f"{f.name} claims the design supplied no SDC while "
            f"input/constraints/clock.sdc is staged:\n{text[:400]}")
    # The two artefacts must AGREE. `step_canonicalize_artefacts` never
    # refreshes the canonical copy, so a disagreement written here is
    # permanent for the rest of the run.
    assert (canon_sdc.read_text().replace(
        R._stamp_sdc_provenance("", "sky130A"), "") == runner_sdc.read_text())


def test_a_design_declared_io_delay_is_never_replaced(tmp_path, monkeypatch):
    """The unit/DRV/IO chain must SUPPLY only what the design omitted.

    `step_pnr` puts a staged SDC through `_scale_sdc_to_liberty_units` ->
    `_reconcile_staged_sdc_drv` -> `_ensure_staged_sdc_drv` ->
    `_ensure_staged_sdc_io_delay`; this step applied NONE of it, so the deck
    the pre-layout STA read was not the deck PnR reads. Applying the chain must
    not OVERRIDE a design-declared value — `set_input_delay 1.0` must survive
    and must not be replaced by the auto `2`."""
    proj = tmp_path / "proj"
    (proj / "input" / "constraints").mkdir(parents=True)
    (proj / "input" / "constraints" / "clock.sdc").write_text(
        _EDGE_LLM_ACCEL_SDC
        + "set_input_delay 1.0 -clock core_clock [get_ports rst_n]\n")

    R.step_prelayout_signoff(
        proj, "chip_top", _corner_pdk(monkeypatch, "/foss/pdks/x/nom.lib"),
        "some-container")

    for rel in ("phase3/stage3/pnr/constraint.sdc",
                "phase2/stage2/constraints/chip_top.sdc"):
        text = (proj / rel).read_text()
        assert "set_input_delay 1.0 -clock core_clock" in text, text[:400]
        assert "set_input_delay  2 " not in text, (
            f"{rel}: the design's own input delay was replaced by the auto "
            f"value:\n{text[:400]}")
        # the OTHER half is still supplied, so honoring the design's SDC does
        # not leave the output boundary untimed
        assert "set_output_delay" in text, text[:400]


def test_staged_sdc_is_rescaled_into_the_liberty_units(tmp_path, monkeypatch):
    """A pre-layout STA against an UNSCALED SDC is a wrong number.

    OpenSTA reads SDC numerics in the LIBERTY's declared `time_unit`. A design
    SDC authored in ns, copied verbatim under a liberty declaring `1ps`, signs
    off 1000x too tight. `step_pnr` has rescaled since benchmark-spm-asap7;
    this step copied the file byte-for-byte.

    Asserted on the DESIGN's OWN numerics, not just the period. `-period
    10000` alone proves nothing: the fabricated auto-SDC reaches the same
    digits because `_resolve_clock_spec` independently reads the same staged
    file for the NUMBER and `_build_auto_silicon_sdc` does its own unit scale
    — which is exactly the coincidence `_resolve_staged_silicon_sdc`'s
    docstring names as what hid the original defect from review. The
    `set_output_delay 3.5` below is a value no auto-SDC emits."""
    lib = tmp_path / "ps.lib"
    lib.write_text('library (ps_lib) {\n  time_unit : "1ps";\n'
                   '  capacitive_load_unit (1,ff);\n}\n')
    proj = tmp_path / "proj"
    (proj / "input" / "constraints").mkdir(parents=True)
    (proj / "input" / "constraints" / "clock.sdc").write_text(
        _EDGE_LLM_ACCEL_SDC
        + "set_output_delay 3.5 -clock core_clock [all_outputs]\n")

    R.step_prelayout_signoff(
        proj, "chip_top", _corner_pdk(monkeypatch, str(lib)), "some-container")

    text = (proj / "phase3" / "stage3" / "pnr" / "constraint.sdc").read_text()
    clk = [ln for ln in text.splitlines() if "create_clock" in ln][0]
    assert "core_clock" in clk and "10000" in clk, (
        f"the DESIGN's clock was not rescaled into the liberty's ps units: "
        f"{clk!r}")
    out = [ln for ln in text.splitlines()
           if ln.strip().startswith("set_output_delay")]
    assert out and "3500" in out[0], (
        f"the design's own 3.5 ns output delay was not rescaled to ps: "
        f"{out!r}\n{text[:400]}")


def test_a_fabricated_sdc_is_never_promoted_to_design_staged(tmp_path,
                                                             monkeypatch):
    """Writing the runner's OWN auto-SDC to the canonical path LAUNDERS it.

    `phase2/stage2/constraints` is the LAST directory
    `_resolve_staged_silicon_sdc` searches. Copying the auto-SDC there hands
    `step_pnr`, later in the SAME run, a file it resolves as "design-staged"
    and puts through the staged branch. MEASURED on a liberty declaring
    `time_unit : "1ps"`: `_build_auto_silicon_sdc` already scales into lib
    units and emits `-period 20000`; re-resolved as staged,
    `_scale_sdc_to_liberty_units` scales it a SECOND time to `-period 2e+07` —
    1000x too LOOSE, i.e. every path passes. So when the DESIGN staged
    nothing, the canonical copy is left to `step_canonicalize_artefacts`, the
    step that owns it and runs after step_pnr has settled what the SDC is.

    NEGATIVE CONTROL: against the pre-fix body the resolver comes back
    pointing at the runner's own fabrication and this FAILS."""
    lib = tmp_path / "ps.lib"
    lib.write_text('library (ps_lib) {\n  time_unit : "1ps";\n'
                   '  capacitive_load_unit (1,ff);\n}\n')
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)          # design stages NO sdc

    assert R._resolve_staged_silicon_sdc(proj) is None
    res = R.step_prelayout_signoff(
        proj, "chip_top", _corner_pdk(monkeypatch, str(lib)), "some-container")
    # the step still does its job: the deck the pre-layout STA reads exists
    assert res.status == "PASS", res.detail
    assert (proj / "phase3" / "stage3" / "pnr" / "constraint.sdc").is_file()
    assert (proj / "phase2" / "stage2"
            / "constraints" / "pvt_matrix.json").is_file()

    after = R._resolve_staged_silicon_sdc(proj)
    assert after is None, (
        "step_pnr's shared resolver now points at a file THIS step "
        f"fabricated: {after} — the runner's own auto-SDC has been laundered "
        "into 'design-staged' inside one run")
    assert not (proj / "phase2" / "stage2"
                / "constraints" / "chip_top.sdc").exists()


def test_function_exists_and_returns_stepresult():
    assert hasattr(R, "step_prelayout_signoff")
    fn = R.step_prelayout_signoff
    # 4 positional params: project, top, pdk, container
    code = fn.__code__
    assert code.co_argcount == 4, code.co_varnames[:4]


def test_main_calls_prelayout_signoff_before_pnr():
    """WIRING + ORDER: main() must call step_prelayout_signoff and it must
    appear textually before the step_pnr call (the emit must precede PnR)."""
    tree = ast.parse(_SRC)
    main_fn = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "main")

    def _first_call_line(name):
        for node in ast.walk(main_fn):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == name):
                return node.lineno
        return None

    pls = _first_call_line("step_prelayout_signoff")
    pnr = _first_call_line("step_pnr")
    assert pls is not None, "main() never calls step_prelayout_signoff"
    assert pnr is not None, "main() never calls step_pnr"
    assert pls < pnr, (
        f"step_prelayout_signoff (line {pls}) must be called BEFORE "
        f"step_pnr (line {pnr}) — the pre-layout emit must not sit behind PnR")
