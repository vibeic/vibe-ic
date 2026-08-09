"""Tests for input_docs_coverage_check.py (v0.50).

Covers: all-covered pass, missing-doc fail, manifest-only coverage, layer-only
coverage, mixed coverage.
"""
from __future__ import annotations
import json, subprocess, sys, tempfile
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "input_docs_coverage_check.py"


def _setup(tmp: Path, doc_names, layers: dict = None, manifest_text: str = None):
    (tmp / "input" / "docs").mkdir(parents=True)
    for n in doc_names:
        (tmp / "input" / "docs" / n).write_text("dummy")
    (tmp / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    for name, obj in (layers or {}).items():
        (tmp / "phase1" / "generated_docs" / f"{name}.json").write_text(json.dumps(obj))
    if manifest_text is not None:
        (tmp / "input_docs_coverage.md").write_text(manifest_text)


def _run(tmp: Path, *extra: str):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp), *extra],
        capture_output=True, text=True,
    )
    try:
        return r.returncode, json.loads(r.stdout)
    except json.JSONDecodeError:
        return r.returncode, {"_raw": r.stdout, "_err": r.stderr}


def test_all_covered_via_layers_passes(tmp_path):
    _setup(tmp_path,
           doc_names=["spec.pdf", "registers.xlsx"],
           layers={
               "L1_DATASHEET": {"provenance": {"sources": ["input/docs/spec.pdf"]}},
               "L4_REGMAP":    {"provenance": {"sources": ["input/docs/registers.xlsx"]}},
           })
    code, out = _run(tmp_path)
    assert out.get("pass") is True, out
    assert code == 0


def test_one_doc_missing_fails(tmp_path):
    _setup(tmp_path,
           doc_names=["spec.pdf", "registers.xlsx"],
           layers={"L1_DATASHEET": {"provenance": {"sources": ["input/docs/spec.pdf"]}}})
    code, out = _run(tmp_path)
    assert out.get("pass") is False
    rules = [f["rule"] for f in out["findings"]]
    assert "input_doc_coverage" in rules
    missing = [f["doc"] for f in out["findings"]]
    assert "registers.xlsx" in missing


def test_manifest_md_only_passes(tmp_path):
    _setup(tmp_path,
           doc_names=["timing.txt"],
           layers={},
           manifest_text="# Coverage\n- timing.txt → pulse widths, verified by rx_phy tb")
    code, out = _run(tmp_path)
    assert out.get("pass") is True, out


def test_stem_match_works(tmp_path):
    """Doc name 'CMD_protocol.xlsx' cited only as 'CMD_protocol' should match."""
    _setup(tmp_path,
           doc_names=["CMD_protocol.xlsx"],
           layers={"L3_CMD_PROTOCOL": {"derived_from": "CMD_protocol table"}})
    code, out = _run(tmp_path)
    assert out.get("pass") is True, out


def test_empty_docs_dir_fails(tmp_path):
    (tmp_path / "input" / "docs").mkdir(parents=True)
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    code, out = _run(tmp_path)
    assert out.get("pass") is False
    assert "no files found" in out.get("error", "")


def test_weak_contribution_phrase_warns(tmp_path):
    """v0.50.1 — 'reviewed for context' phrase must be flagged even if doc
    is technically cited in the coverage manifest."""
    _setup(tmp_path,
           doc_names=["measure_timing.pptx"],
           layers={},
           manifest_text=(
               "| measure_timing.pptx | Measurement sequence diagrams. "
               "Reviewed for context; did not contribute RTL constants. |"
           ))
    code, out = _run(tmp_path)
    # coverage is satisfied (filename in manifest), but WARN must fire
    rules = [f["rule"] for f in out.get("findings", [])]
    assert "weak_contribution_claim" in rules


def test_detailed_contribution_passes(tmp_path):
    """A proper per-item contribution description must NOT trigger the WARN."""
    _setup(tmp_path,
           doc_names=["timing.pptx"],
           layers={},
           manifest_text=(
               "| timing.pptx | Slide 2 table: IBT=22.7us, RSP_Time=22.7us, "
               "BR range 9.4-18.4us. | rtl/params.vh CYC_IBT=91 |"
           ))
    code, out = _run(tmp_path)
    rules = [f["rule"] for f in out.get("findings", [])]
    assert "weak_contribution_claim" not in rules


# ---------------------------------------------------------------------------
# `--strict` reachability (vibe-ic unreachable-verdict campaign)
#
# The program documents a FAIL severity for `weak_contribution_claim` under
# --strict, but the flag was parsed by argparse and then never read: `check()`
# took no `strict` parameter and hard-coded severity "WARN". Since `pass` is
# `not any(severity == "FAIL")`, no input and no flag combination could make a
# weak contribution claim blocking. `prog dir` and `prog dir --strict` emitted
# byte-identical JSON and both exited 0.
#
# Both directions are asserted below: the FAIL verdict must be reachable, and
# the PASS verdict must still be reachable in the same --strict mode.
# ---------------------------------------------------------------------------

_WEAK_MANIFEST = (
    "| measure_timing.pptx | Measurement sequence diagrams. "
    "Reviewed for context; did not contribute RTL constants. |"
)

_STRONG_MANIFEST = (
    "| measure_timing.pptx | Slide 2 table: response IBT=22.7us -> "
    "rtl/params.vh CYC_IBT=91, verified by tb/tb_link_timing.v case 4. |"
)


def test_strict_makes_weak_contribution_claim_blocking(tmp_path):
    """DIRECTION 1 — the FAIL verdict must be reachable.

    Fails against the unfixed program, which returns pass=True / exit 0 here
    because --strict was discarded.
    """
    _setup(tmp_path,
           doc_names=["measure_timing.pptx"],
           layers={},
           manifest_text=_WEAK_MANIFEST)
    code, out = _run(tmp_path, "--strict")

    assert out.get("strict") is True, out
    weak = [f for f in out["findings"] if f["rule"] == "weak_contribution_claim"]
    assert weak, out
    assert [f["severity"] for f in weak] == ["FAIL"], out
    assert out.get("pass") is False, out
    assert code == 1, out
    # the doc IS cited, so it is not a *missing* doc — the strict FAIL must not
    # be laundered into the missing-doc counter.
    assert out.get("docs_missing") == 0, out
    assert out.get("docs_covered") == 1, out


def test_strict_still_passes_a_well_documented_manifest(tmp_path):
    """DIRECTION 2 — the PASS verdict must still be reachable under --strict.

    Guards against 'fixing' the gate by making it always red. Asserts only on
    the verdict, so it holds before AND after the fix — an always-fail
    regression is the only thing that can break it.
    """
    _setup(tmp_path,
           doc_names=["measure_timing.pptx"],
           layers={},
           manifest_text=_STRONG_MANIFEST)
    code, out = _run(tmp_path, "--strict")

    assert out.get("weak_contributions") == 0, out
    assert out.get("findings") == [], out
    assert out.get("pass") is True, out
    assert code == 0, out


def test_default_mode_keeps_weak_contribution_claim_advisory(tmp_path):
    """BLAST-RADIUS GUARD — without --strict the verdict is unchanged.

    Same fixture as direction 1: still WARN, still pass, still exit 0, so no
    existing caller (none of which pass --strict) changes colour. This must
    hold identically before and after the fix.
    """
    _setup(tmp_path,
           doc_names=["measure_timing.pptx"],
           layers={},
           manifest_text=_WEAK_MANIFEST)
    code, out = _run(tmp_path)

    weak = [f for f in out["findings"] if f["rule"] == "weak_contribution_claim"]
    assert [f["severity"] for f in weak] == ["WARN"], out
    assert out.get("pass") is True, out
    assert code == 0, out


def test_strict_reports_missing_docs_and_weak_claims_separately(tmp_path):
    """A missing doc and a weak claim are both FAIL under --strict but must
    stay distinguishable in the emitted JSON."""
    _setup(tmp_path,
           doc_names=["measure_timing.pptx", "uncited_register_map.xlsx"],
           layers={},
           manifest_text=_WEAK_MANIFEST)
    code, out = _run(tmp_path, "--strict")

    by_rule = {}
    for f in out["findings"]:
        by_rule.setdefault(f["rule"], []).append(f)
    assert [f["severity"] for f in by_rule["input_doc_coverage"]] == ["FAIL"], out
    assert by_rule["input_doc_coverage"][0]["doc"] == "uncited_register_map.xlsx", out
    assert [f["severity"] for f in by_rule["weak_contribution_claim"]] == ["FAIL"], out
    assert out.get("docs_missing") == 1, out
    assert out.get("weak_contributions") == 1, out
    assert out.get("pass") is False, out
    assert code == 1, out
