"""Regression tests for the 2 OPEN residuals found triaging the 279 pre-reset
backlog filings against current 0.2.x code:

  * ORGANIC-20260521-phase2a-pin-aliases-auto-synthesized-... — the AsciiDoc
    top-entity-ports route must emit ONLY doc-declared aliases (pipe / paren),
    never the useless [name.lower(), name.replace("_","")] auto-synth.
  * ORGANIC-20260522-phase2a-runner-per-step-watchdog-timeout-silent-incomplete
    — a generator step that RAISES must write a recoverable <layer>.json stub
    and let the runner CONTINUE (the _v1_6_580 watchdog, now wired into main()).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase1_doc_one_shot_runner as p1doc  # noqa: E402


# ── ORGANIC-20260521: doc-declared aliases only (no auto-synth) ──────────

def test_plain_pin_yields_no_auto_synth_aliases():
    # a plain pin name must NOT get [name.lower(), name.replace("_","")]
    assert p1doc._v1_6_363_extract_doc_declared_aliases("debug_req_i") == []
    assert p1doc._v1_6_363_extract_doc_declared_aliases(
        "VCCD1", source_row="core digital supply") == []


def test_pipe_alias_in_name_extracted():
    assert p1doc._v1_6_363_extract_doc_declared_aliases("PAD|RES") == ["RES"]
    assert p1doc._v1_6_363_strip_pipe_from_name("PAD|RES") == "PAD"


def test_paren_alias_in_description_extracted():
    al = p1doc._v1_6_363_extract_doc_declared_aliases(
        "RESET_N", source_row="active-low reset (aka NRST)")
    assert "NRST" in al


def test_adoc_route_site_uses_helper_not_auto_synth():
    # structural guard: the AsciiDoc top-entity-ports site must route aliases
    # through the helper, not the legacy [_port_name.lower(), ...] auto-synth.
    src = (Path(p1doc.__file__).read_text())
    # the legacy auto-synth literal must be gone from the adoc route
    assert "[_port_name.lower(),\n                        _port_name.replace" \
        not in src
    assert "_v1_6_363_row_aliases" in src  # the fix's variable is present


# ── ORGANIC-20260522: per-step watchdog writes a stub on failure ─────────

def _gd(project):
    return p1doc._pl.generated_docs_dir(project)


def test_watchdog_raising_step_writes_stub_and_continues(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()

    def boom():
        raise ValueError("synthetic step crash")

    ok, r = p1doc._v1_6_580_run_step_with_watchdog(
        boom, step_name="gen_lX", layer_name="L4_REGMAP",
        project=project, timeout_s=30)
    assert ok is False and r is None
    stub = _gd(project) / "L4_REGMAP.json"
    assert stub.is_file(), "failure stub must be written"
    data = json.loads(stub.read_text())
    assert data.get("phase1_step_error") is True
    assert data.get("layer") == "L4_REGMAP"


def test_watchdog_success_passes_through(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    sentinel = {"ok": 1}
    ok, r = p1doc._v1_6_580_run_step_with_watchdog(
        lambda: sentinel, step_name="gen_lX", layer_name="L5_ADI_SPEC",
        project=project, timeout_s=30)
    assert ok is True and r is sentinel
    # no stub written on success
    assert not (_gd(project) / "L5_ADI_SPEC.json").is_file()


def test_watchdog_does_not_clobber_a_real_doc(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    gd = _gd(project)
    gd.mkdir(parents=True, exist_ok=True)
    real = gd / "L6_CONTROL_LOGIC.json"
    real.write_text(json.dumps({"real": True, "fsm": []}))  # non-stub content

    def boom():
        raise RuntimeError("late crash")

    ok, _ = p1doc._v1_6_580_run_step_with_watchdog(
        boom, step_name="gen_lX", layer_name="L6_CONTROL_LOGIC",
        project=project, timeout_s=30)
    assert ok is False
    # the real doc must survive (skip-write guard) — not overwritten by a stub
    kept = json.loads(real.read_text())
    assert kept.get("real") is True and "phase1_step_error" not in kept


def test_main_routes_every_layer_through_watchdog():
    # structural guard: main() must wrap all 14 L-doc gens via _run_layer, with
    # no direct `r = gen_lN(...); results.append(r)` left behind.
    src = Path(p1doc.__file__).read_text()
    assert src.count("_run_layer(") >= 15  # 1 def + 14 call sites
    import re
    leftover = re.findall(r"r = gen_l\d.*results\.append\(r\)", src)
    assert not leftover, f"unwrapped direct gen calls remain: {leftover}"
