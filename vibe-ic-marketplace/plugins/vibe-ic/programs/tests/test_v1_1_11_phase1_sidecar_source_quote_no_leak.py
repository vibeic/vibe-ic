"""Step-2.7 §4.05 guard for the PR #6 phase1 completeness sidecar credit.

PR #6 added an AI deep-review sidecar credit to
phase1_input_vs_generated_completeness_check. The original form serialised the
ENTIRE patch dict (via _load_ai_patches_sidecar) into the completeness haystack
— including each patch's `source_quote`, which is a VERBATIM copy of prompt
text. So a single patch whose source_quote echoed the whole prompt auto-credited
every quoted design token, and a generated doc set that captured NONE of the
prompt facts (0/20) was wrongly credited 100% complete (Step-2.7 HIGH leak).

FIX: credit ONLY the recovered `value`/`field` of each patch
(_load_sidecar_recovered_values), never the source_quote provenance. This file
PINS: (1) a prompt-echoing source_quote does NOT blanket-pass an empty doc set;
(2) a genuine recovered value IS still credited.

chip-AGNOSTIC: design-token completeness over the project's own files.
"""
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase1_input_vs_generated_completeness_check as M  # noqa: E402

_PROMPT = ("Registers @0x40 @0x44 @0x48 @0x4C run at 100 MHz on 1.8 V. "
           "REG_CTRL STATUS ENABLE DATABUS ADDRBUS CONFIG RESET IRQVEC. "
           "Timeout window is 250 ns. Signature address 0x8ffffffc.")


def _mkproj(tmp_path, patch_value, *, gen_blob='{"summary":"placeholder, no facts"}'):
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "prompt.md").write_text(_PROMPT)
    gen = M._pl.generated_docs_dir(proj)
    gen.mkdir(parents=True)
    (gen / "L22_VERIFICATION_PLAN.json").write_text(gen_blob)
    side = {"patches": {"L22_VERIFICATION_PLAN": [{
        "extraction_strategy": "ai_deep_review_patch",
        "field": "handshake_signature_address",
        "value": patch_value,
        "source_quote": _PROMPT,            # verbatim prompt echo
    }]}}
    (proj / "phase1" / "ai_deep_review_patches.json").write_text(json.dumps(side))
    return proj


def test_source_quote_echo_does_not_blanket_pass(tmp_path):
    # value recovers only the signature address; source_quote echoes the whole
    # prompt but must NOT be credited → the 0-fact doc set still FAILs.
    proj = _mkproj(tmp_path, "0x8ffffffc")
    rc = M.main([str(proj)])
    assert rc == 1   # FAIL — only ~1/20 credited, not 20/20


def test_useless_value_with_prompt_echo_credits_nothing(tmp_path):
    # value="n/a" recovers nothing; source_quote echo must not rescue it.
    proj = _mkproj(tmp_path, "n/a")
    rc = M.main([str(proj)])
    assert rc == 1   # FAIL — 0/20 credited


def test_recovered_value_is_credited(tmp_path):
    # §4.05 no OVER-correction: a genuine recovered value IS credited into the
    # haystack (the sidecar remains a real AI-recovery channel).
    hay = M._load_generated_haystacks(_mkproj(tmp_path, "0x8ffffffc"))
    blob = hay["L22_VERIFICATION_PLAN.json"]
    raw = blob["raw"] if isinstance(blob, dict) else str(blob)
    assert "0x8ffffffc" in raw          # the recovered value is present
    assert "IRQVEC" not in raw          # but a prompt-only token (quote) is NOT


def test_sidecar_recovered_values_excludes_source_quote(tmp_path):
    proj = _mkproj(tmp_path, "0x8ffffffc")
    rec = M._load_sidecar_recovered_values(proj)
    text = rec.get("L22_VERIFICATION_PLAN", "")
    assert "0x8ffffffc" in text
    assert "handshake_signature_address" in text
    assert "REG_CTRL" not in text and "Timeout" not in text  # no quote tokens


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
