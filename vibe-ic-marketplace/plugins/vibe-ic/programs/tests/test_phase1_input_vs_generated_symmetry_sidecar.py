#!/usr/bin/env python3
"""Regression — phase1_input_vs_generated_completeness_check must be
SYMMETRIC with its sibling phase1_doc_input_completeness_check on two
axes that previously diverged:

  (1) PATH RESOLUTION — resolve generated_docs via
      `_path_layout.generated_docs_dir` (canonical
      `<project>/phase1/generated_docs`) instead of a hard-coded
      `<project>/generated_docs`. The old hard path made the gate emit
      a spurious "no Phase 1 output" SKIP when invoked with the project
      ROOT (the canonical invocation), even though L*.json existed.

  (2) AI DEEP-REVIEW SIDECAR — honour
      `<project>/phase1/ai_deep_review_patches.json` by REUSING the
      sibling's `_load_ai_patches_sidecar` mechanism. AI-recovered
      cells live only in the durable sidecar (the runner rewrites
      generated_docs/L*.json each run), so a prompt token recovered
      into the sidecar must be credited.

§4.05-SAFETY — being sidecar-aware must NOT let the gate blanket-pass:
the sidecar text is appended to the haystack, so a token is creditable
iff it literally appears in the L doc OR the sidecar. The NEG cases
below pin that genuinely-uncaptured tokens still FAIL.

chip-AGNOSTIC: structural path/sidecar behaviour only; no chip/vendor
literal drives a verdict.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_PROG = _PROGRAMS / "phase1_input_vs_generated_completeness_check.py"
_spec = importlib.util.spec_from_file_location(
    "phase1_input_vs_generated_completeness_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

import _path_layout as _pl  # noqa: E402

_AI = "ai_deep_review_patch"

# >=10 distinct design tokens so we clear the SKIP_LOW_TOKENS floor.
# One token (the magic address) is the "AI-recovered" cell we route via
# the sidecar; everything else is present in the L doc.
_PROMPT = (
    "Registers @0x40 @0x44 @0x48 run at 100 MHz on 1.8 V. "
    "REG_CTRL STATUS ENABLE DATA[7] ADDR[3] CONFIG RESET. "
    "Handshake signature at 0x8ffffffc."
)
# The L doc echoes everything EXCEPT the 0x8ffffffc handshake address.
_L_DOC_BODY = (
    "Registers @0x40 @0x44 @0x48 run at 100 MHz on 1.8 V. "
    "REG_CTRL STATUS ENABLE DATA[7] ADDR[3] CONFIG RESET."
)


def _project(tmp_path: Path, *, l_doc: str, sidecar: dict | None,
             prompt: str = _PROMPT) -> Path:
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "prompt.md").write_text(prompt)
    gen = _pl.generated_docs_dir(proj)
    gen.mkdir(parents=True)
    (gen / "L22_VERIFICATION_PLAN.json").write_text(l_doc)
    if sidecar is not None:
        side = _pl.phase1_ai_deep_review_patches_file(proj)
        side.parent.mkdir(parents=True, exist_ok=True)
        side.write_text(json.dumps(sidecar))
    return proj


def _report(proj: Path) -> dict:
    # The gate writes to the flat `<project>/reports/` (see
    # _write_reports), matching the existing completeness test helper.
    p = proj / "reports" / "phase1_input_vs_generated_completeness.json"
    return json.loads(p.read_text())


# ── (1) PATH RESOLUTION — root invocation finds phase1/generated_docs ───────
def test_resolves_canonical_phase1_path_not_root(tmp_path):
    """Invoked with the project ROOT, the gate must FIND the canonical
    phase1/generated_docs/ haystack — NOT spuriously SKIP."""
    proj = _project(
        tmp_path,
        l_doc=json.dumps({"summary": _L_DOC_BODY + " 0x8ffffffc"}),
        sidecar=None,
    )
    # Sanity: nothing at the legacy ROOT path.
    assert not (proj / "generated_docs").exists()
    rc = mod.main([str(proj)])
    assert rc == 0
    rep = _report(proj)
    assert rep["verdict"] != "SKIP", \
        "must not SKIP — phase1/generated_docs exists"
    # All prompt tokens land in the L doc → full capture.
    assert rep["verdict"] == "PASS"
    assert rep["captured_pct"] == 1.0


# ── (2) SIDECAR CREDIT — token recovered only in sidecar is credited ────────
def test_sidecar_token_is_credited(tmp_path):
    """The 0x8ffffffc handshake token is absent from the L doc but
    present in the sidecar; with sidecar-awareness it is captured."""
    sidecar = {"patches": {"L22_VERIFICATION_PLAN": [{
        "extraction_strategy": _AI,
        "field": "handshake_signature_address",
        "value": "0x8ffffffc",
        "source_quote": "signature address ... 0x8ffffffc",
    }]}}
    proj = _project(
        tmp_path,
        l_doc=json.dumps({"summary": _L_DOC_BODY}),  # NO 0x8ffffffc here
        sidecar=sidecar,
    )
    rc = mod.main([str(proj)])
    assert rc == 0
    rep = _report(proj)
    assert rep["verdict"] == "PASS"
    assert rep["captured_pct"] == 1.0
    # The recovered token is attributed to the L22 layer haystack.
    assert any(tok.lower().endswith("8ffffffc")
               for tok in (rep.get("missing_sample") or [])) is False
    assert rep["missing"] == 0


# ── §4.05 NEG (1) — genuinely-missing tokens, NO sidecar → still FAIL ───────
def test_neg_missing_tokens_no_sidecar_still_fails(tmp_path):
    """A near-empty L doc + no sidecar: the prompt tokens are genuinely
    dropped. The gate must FAIL — sidecar-awareness must not soften the
    miss when there is no sidecar."""
    proj = _project(
        tmp_path,
        l_doc=json.dumps({"x": "unrelated content, no overlap"}),
        sidecar=None,
    )
    rc = mod.main([str(proj)])
    assert rc == 1
    rep = _report(proj)
    assert rep["verdict"] == "FAIL"
    assert rep["captured_pct"] < mod._DEFAULT_FAIL_PCT
    assert rep["missing_sample"], "FAIL must surface the dropped tokens"


# ── §4.05 NEG (2) — sidecar covers SOME but not all → still FAIL on rest ────
def test_neg_sidecar_partial_does_not_blanket_pass(tmp_path):
    """The sidecar carries ONLY the handshake token. The rest of the
    prompt tokens are absent from both the (empty) L doc and the
    sidecar, so capture stays below the FAIL floor → FAIL. The sidecar
    can only credit what it literally contains; it cannot blanket-pass.
    """
    sidecar = {"patches": {"L22_VERIFICATION_PLAN": [{
        "extraction_strategy": _AI,
        "value": "0x8ffffffc",
    }]}}
    proj = _project(
        tmp_path,
        l_doc=json.dumps({"x": "no design-token overlap here at all"}),
        sidecar=sidecar,
    )
    rc = mod.main([str(proj)])
    assert rc == 1
    rep = _report(proj)
    assert rep["verdict"] == "FAIL"
    # The sidecar token IS credited (not in missing); the rest are not.
    assert "0x8ffffffc" not in rep["missing_sample"]
    assert rep["missing"] >= mod._MIN_TOKENS - 1
    assert rep["captured"] >= 1  # the sidecar token was credited


# ── §4.05 NEG (3) — no phase1/generated_docs at all → honest SKIP ───────────
def test_neg_no_generated_docs_honest_skip(tmp_path):
    """No phase1/generated_docs and no sidecar: honest SKIP (rc 0), a
    clear "run phase1 first" signal — NOT a vacuous PASS."""
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "prompt.md").write_text(_PROMPT)
    rc = mod.main([str(proj)])
    assert rc == 0  # SKIP, never a false PASS
    # No report verdict claims PASS.
    rep_path = proj / "reports" / "phase1_input_vs_generated_completeness.json"
    if rep_path.is_file():
        assert json.loads(rep_path.read_text()).get("verdict") != "PASS"


# ── §4.05 NEG (4) — sidecar-only layer (no matching L doc) still counts ─────
def test_sidecar_only_layer_surfaced(tmp_path):
    """A sidecar layer with NO matching generated_docs/L*.json is still
    surfaced so its tokens count (pre-staged-patch case). Mirrors the
    sibling's sidecar-only handling — does not crash, does not skip."""
    sidecar = {"patches": {"L99_PRESTAGED": [{
        "extraction_strategy": _AI,
        "value": "0x8ffffffc",
    }]}}
    proj = _project(
        tmp_path,
        l_doc=json.dumps({"summary": _L_DOC_BODY}),  # no 0x8ffffffc
        sidecar=sidecar,
    )
    rc = mod.main([str(proj)])
    assert rc == 0
    rep = _report(proj)
    assert rep["verdict"] == "PASS"
    assert "0x8ffffffc" not in rep.get("missing_sample", [])
