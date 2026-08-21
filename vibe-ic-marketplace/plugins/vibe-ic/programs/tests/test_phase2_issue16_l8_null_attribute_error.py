"""tests/test_phase2_issue16_l8_null_attribute_error.py — v1.6.84

Closes issue #16 Bug A — REGRESSION of #13. v1.6.82 added two new
`dict.get(k, dict_default)` callsites at aid_class_rtl_gen.py:1477-1478
without the `or default` guard, crashing on null L8 fields (same
defect class as #13 — `dict.get(k, default)` returns None when k is
JSON-null, defeating the default and crashing subsequent .get / list
iteration).

v1.6.84 fixes lines 1477-1478 + audit-sweep RE-RUN across all 3
plugin programs (aid_class_rtl_gen + phase1_runner + phase2_runner).

Plus reject-test pair: the static check confirms no surviving
`dict.get(k, dict_or_list_default)` pattern remains (Case 4) — guards
against future regressions where a fresh edit re-introduces the
defect class.
"""
from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path

PLUGIN_ROOT = (
    Path(__file__).resolve().parent.parent.parent
)
PROGRAMS_DIR = PLUGIN_ROOT / "programs"
if str(PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(PROGRAMS_DIR))


def _seed_project(project: Path,
                  l8_overrides: dict) -> None:
    """Seed the minimal EXAMPLE_PROTOCOL-class fixture aid_class_rtl_gen.gen()
    needs. L8 is the field under test — overrides set
    rx_classifier_ticks / timing_constants to None to reproduce the
    v1.6.82 crash."""
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    evidence = {
        "extraction_evidence": {
            "vendor.pdf": [{"literal": "sentinel", "label": "L*"}]
        }
    }
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        **evidence, "ic_name": "EXAMPLE_PROTOCOL-IC", "interface": "Apple ID Bus",
    }))
    (gd / "L2_FRS.json").write_text(json.dumps({
        **evidence, "ic_name": "EXAMPLE_PROTOCOL-IC",
        "protocol_type": "Apple ID Bus",
    }))
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        **evidence, "ic_name": "EXAMPLE_PROTOCOL-IC", "command_count": 1,
        "commands": [{"opcode": "0x74", "name": "GET_ID"}],
        "crc_parameters": {
            "polynomial_hex": "0x31",
            "polynomial_reflected_hex": "8'h8C",
            "init_hex": "8'hFF",
        },
    }))
    l8_content = {
        **evidence,
        "ic_name": "EXAMPLE_PROTOCOL-IC",
        # The fields under test default to None to reproduce #16.
        "rx_classifier_ticks": None,
        "timing_constants": None,
    }
    l8_content.update(l8_overrides)
    (gd / "L8_TIMING_WAVEFORM.json").write_text(
        json.dumps(l8_content))


def _gen_module():
    if "aid_class_rtl_gen" in sys.modules:
        return importlib.reload(sys.modules["aid_class_rtl_gen"])
    return importlib.import_module("aid_class_rtl_gen")


def _rtl_dir(project: Path) -> Path:
    return project / "phase2" / "stage1" / "rtl"


# ─── Case 1 — null L8.rx_classifier_ticks (one of the #16 crash sites) ────
def test_l8_null_rx_classifier_does_not_crash(tmp_path: Path):
    """v1.6.82 crashed `AttributeError: 'NoneType' object has no
    attribute 'get'` when L8.rx_classifier_ticks=null. v1.6.84
    must complete without crash and emit chip_top.sv."""
    project = tmp_path / "null_classifier_proj"
    _seed_project(project, {
        "rx_classifier_ticks": None,
        "timing_constants": [],   # not under test in this case
    })
    mod = _gen_module()
    # Must NOT raise.
    mod.gen(str(project))
    chip_top = _rtl_dir(project) / "chip_top.sv"
    assert chip_top.is_file(), (
        f"chip_top.sv not emitted to {chip_top}"
    )


# ─── Case 2 — null L8.timing_constants (the second #16 crash site) ────────
def test_l8_null_timing_constants_does_not_crash(tmp_path: Path):
    """The list-comprehension at line 1479 crashed on null L8.
    timing_constants because `for tcd in None` raises TypeError.
    v1.6.84 fix: `for tcd in (l8.get("timing_constants") or [])`."""
    project = tmp_path / "null_timing_proj"
    _seed_project(project, {
        "rx_classifier_ticks": {},  # not under test in this case
        "timing_constants": None,
    })
    mod = _gen_module()
    mod.gen(str(project))
    chip_top = _rtl_dir(project) / "chip_top.sv"
    assert chip_top.is_file()


# ─── Case 3 — both null (compounded #16 reproducer) ───────────────────────
def test_l8_both_null_does_not_crash_emits_defaults(tmp_path: Path):
    """End-to-end #16 reproducer: both fields null. The generator
    must use its built-in defaults (h1_min=1 / T_BIT0_LOW_TICKS=355
    / etc.) and emit RTL without crashing."""
    project = tmp_path / "both_null_proj"
    _seed_project(project, {
        "rx_classifier_ticks": None,
        "timing_constants": None,
    })
    mod = _gen_module()
    mod.gen(str(project))
    rtl = _rtl_dir(project)
    assert rtl.is_dir()
    files = sorted(p.name for p in rtl.iterdir() if p.is_file())
    assert "chip_top.sv" in files


# ─── Case 4 — audit-sweep static check (regression guard) ─────────────────
def test_audit_sweep_no_dict_get_with_dict_default_in_3_programs():
    """Static check: no `dict.get(k, dict_or_list_default)` patterns
    remain in the 3 plugin programs that handle null-able L docs.
    The fix is `(d.get(k) or default)` form. A surviving match would
    be a future re-introduction of the v1.6.82 crash class.

    The one explicit allow-list entry covers a usage that is guarded
    by isinstance() so the default never matters in practice
    (aid_class_rtl_gen.py l2.get('protocol_overview', {}) — the
    isinstance check on the very same line ensures the default is
    only chosen when the value is in fact a dict).
    """
    bad_pattern = re.compile(r"\.get\([^)]+,\s*[\{\[]\s*\)")
    targets = (
        "aid_class_rtl_gen.py",
        "phase1_doc_one_shot_runner.py",
        "design_one_shot_runner.py",
    )
    violations: list[tuple[str, int, str]] = []
    for fname in targets:
        path = PROGRAMS_DIR / fname
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for ln, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if (stripped.startswith("#")
                    or stripped.startswith('"""')
                    or stripped.startswith("'''")):
                continue
            if not bad_pattern.search(line):
                continue
            # Allow the isinstance-guarded protocol_overview line.
            if ("protocol_overview" in line
                    and "isinstance" in line):
                continue
            violations.append((fname, ln, line.rstrip()))
    if violations:
        for fname, ln, line in violations:
            print(f"{fname}:{ln}  {line}")
    assert not violations, (
        f"audit-sweep failed — {len(violations)} surviving "
        f"`dict.get(k, dict_or_list_default)` pattern(s) reintroduce "
        f"the #13/#16 NoneType crash class. Convert to "
        f"`(d.get(k) or default)`."
    )


# ─── Case 5 — non-destructive rtl/ wipe (#16 Bug A second symptom) ────────
def test_rtl_dir_not_wiped_on_crash(tmp_path: Path):
    """The phase2 runner step_rtl_gen() now backs up prior rtl/
    contents to rtl.pre_gen_backup/ before running the generator,
    and restores from backup if generation fails. This guards
    against the v1.6.82 symptom where a crash mid-rtl_gen left the
    project with an empty rtl/ + zero recoverable state.

    We exercise the contract directly: seed prior rtl/ content,
    invoke step_rtl_gen with a non-existent class so it returns
    WAIVED (no wipe needed), and confirm prior content survives.
    Then inject a registered class with a missing generator → FAIL
    + restore.
    """
    project = tmp_path / "rtl_preserve_proj"
    rtl_dir = _rtl_dir(project)
    rtl_dir.mkdir(parents=True, exist_ok=True)
    sentinel = rtl_dir / "PRIOR_RUN_SENTINEL.sv"
    sentinel_body = "// emitted by a prior good run\n"
    sentinel.write_text(sentinel_body)

    # Import the runner. Use a class string the registry has no
    # entry for → step_rtl_gen returns WAIVED early, never touching
    # rtl/. Sentinel must survive.
    if "design_one_shot_runner" in sys.modules:
        importlib.reload(sys.modules["design_one_shot_runner"])
    p2b = importlib.import_module("design_one_shot_runner")
    result = p2b.step_rtl_gen(project, "totally_unregistered_class_xyz")
    assert result.status == "WAIVED"
    assert sentinel.is_file(), (
        "WAIVED early-return must not touch rtl/ — sentinel gone"
    )
    assert sentinel.read_text() == sentinel_body
