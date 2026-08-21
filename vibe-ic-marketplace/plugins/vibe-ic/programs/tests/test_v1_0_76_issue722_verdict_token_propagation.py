#!/usr/bin/env python3
"""ORGANIC #722 — META-audit: producer->consumer verdict-token propagation
guard. When a producer G gains a NEW verdict token but a downstream consumer
C's mapper only knows the OLD token set, the new token falls through the
mapper's trailing `else` to FAIL silently — MIGRATING a FAIL from G's step to
C's step (a spurious defect of a different category).

The rule (pure set membership, chip-AGNOSTIC):  T_G subset-of R_C, else FLAG
the tokens in `T_G - R_C` (emitted-but-unrecognized).

This test:
  * CLEAN case — runs the REAL program on the current HEAD tree → exit 0.
  * #698 defect-shape — a FIXTURE producer emits BENIGN-ERC, a FIXTURE
    consumer mapper recognizes only {PASS, REVIEW, MEASURED} → the audit
    FLAGS BENIGN-ERC (exit 1), reproducing the historical migration.
  * #648/#649 defect-shape — a FIXTURE producer emits VACUOUS_PASS, a
    FIXTURE consumer recognizes only {PASS, FAIL} → the audit FLAGS
    VACUOUS_PASS (exit 1).
  * §4.05 NO-LEAK (two directions, both must hold):
      (a) a consumer that DELIBERATELY routes an UNKNOWN token to else->FAIL
          is correct — if NO producer emits that token it is NOT flagged.
      (b) the post-#698-fix edge (consumer recognizes BENIGN-ERC) is CLEAN.

Fixtures are written to tmp_path; NO real plugin file is mutated.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "verdict_token_propagation_check.py"
_PLUGIN_ROOT = _PROGRAMS.parent          # .../plugins/vibe-ic
sys.path.insert(0, str(_PROGRAMS))
import verdict_token_propagation_check as V  # noqa: E402


# --------------------------------------------------------------------------
# Fixture builders — defect-shaped producer/consumer source (NOT real files).
# --------------------------------------------------------------------------
# The #698 producer emits BENIGN-ERC alongside PASS/REVIEW (exactly the shape
# #696 introduced).
_PRODUCER_BENIGN_ERC = '''
def emit_erc_report():
    floating = _count()
    _benign = _classify()
    verdict = ("PASS" if floating == 0
               else "BENIGN-ERC" if _benign else "REVIEW")
    d = {"tool": "openroad", "verdict": verdict}
    return d
'''

# The PRE-#698-fix consumer: its mapper recognizes only PASS/REVIEW/MEASURED,
# so BENIGN-ERC silently falls to else->FAIL (the historical bug).
_CONSUMER_PREFIX_698 = '''
def emit_perc_equivalent(erc_v):
    def _auto(name, verdict, tool, evidence):
        result = "PASS" if verdict == "PASS" else (
            "REVIEW" if verdict == "REVIEW" else
            "INCOMPLETE" if verdict == "MEASURED" else "FAIL")
        return {"category": name, "result": result}
    return _auto("Floating nets", erc_v, "openroad", "erc.json")
'''

# The POST-#698-fix consumer: mapper now recognizes BENIGN-ERC too → clean.
_CONSUMER_FIXED_698 = '''
def emit_perc_equivalent(erc_v):
    def _auto(name, verdict, tool, evidence):
        result = "PASS" if verdict == "PASS" else (
            "REVIEW" if verdict in ("REVIEW", "BENIGN-ERC") else
            "INCOMPLETE" if verdict == "MEASURED" else "FAIL")
        return {"category": name, "result": result}
    return _auto("Floating nets", erc_v, "openroad", "erc.json")
'''

# #648/#649 producer emits VACUOUS_PASS (the inline-yosys vacuous token).
_PRODUCER_VACUOUS = '''
def yosys_hilomap_required_check():
    if _has_ys_script():
        verdict = "PASS" if _ok() else "FAIL"
    else:
        verdict = "VACUOUS_PASS"
    return {"gate": "yosys_hilomap", "verdict": verdict}
'''

# #648/#649 consumer only knows PASS/FAIL → VACUOUS_PASS falls to else->FAIL.
_CONSUMER_VACUOUS_NAIVE = '''
def flow_consume(yosys_v):
    if yosys_v == "PASS":
        return "PASS"
    elif yosys_v == "FAIL":
        return "FAIL"
    else:
        return "FAIL"
'''


def _run_binary(plugin_root: Path, registry_json: Path):
    return subprocess.run(
        [sys.executable, str(_PROG), str(plugin_root),
         "--registry-json", str(registry_json)],
        capture_output=True, text=True)


# --------------------------------------------------------------------------
# 1. CLEAN on HEAD (real program, real tree, default in-source REGISTRY).
# --------------------------------------------------------------------------
def test_clean_on_head_real_binary():
    res = subprocess.run(
        [sys.executable, str(_PROG), str(_PLUGIN_ROOT)],
        capture_output=True, text=True)
    assert res.returncode == 0, \
        "META-audit MUST be CLEAN on HEAD; stdout=%r stderr=%r" % (
            res.stdout, res.stderr)
    assert "CLEAN" in res.stdout


def test_clean_on_head_no_syntax_warning():
    """The program itself must import without SyntaxWarning (docstring escapes)."""
    res = subprocess.run(
        [sys.executable, "-W", "error::SyntaxWarning", str(_PROG),
         str(_PLUGIN_ROOT)],
        capture_output=True, text=True)
    assert res.returncode == 0, (res.stdout, res.stderr)


# --------------------------------------------------------------------------
# 2. #698 defect-shape — BENIGN-ERC unhandled → FLAG (exit 1), via REAL binary.
# --------------------------------------------------------------------------
def test_issue698_benign_erc_unhandled_flags(tmp_path):
    # combine producer + consumer in ONE fixture file (mirrors the real edge
    # where _emit_erc_report and _emit_perc_equivalent live in the same module)
    (tmp_path / "programs").mkdir(exist_ok=True)
    combined = tmp_path / "programs" / "fix_edge.py"
    combined.write_text(_PRODUCER_BENIGN_ERC + "\n" + _CONSUMER_PREFIX_698)
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps([{
        "edge_id": "erc->perc(prefix698)",
        "file": "programs/fix_edge.py",
        "producer": "emit_erc_report",
        "consumer": "emit_perc_equivalent",
        "consumer_nested": "_auto",
    }]))
    res = _run_binary(tmp_path, reg)
    assert res.returncode == 1, \
        "pre-#698 shape must FLAG; stdout=%r stderr=%r" % (res.stdout, res.stderr)
    assert "BENIGN-ERC" in res.stdout
    assert "FLAG" in res.stdout


def test_issue698_fixed_edge_is_clean(tmp_path):
    """Post-fix: consumer recognizes BENIGN-ERC → no gap → exit 0 (no-leak (b))."""
    combined = tmp_path / "programs" / "fix_edge.py"
    (tmp_path / "programs").mkdir(exist_ok=True)
    combined.write_text(_PRODUCER_BENIGN_ERC + "\n" + _CONSUMER_FIXED_698)
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps([{
        "edge_id": "erc->perc(fixed698)",
        "file": "programs/fix_edge.py",
        "producer": "emit_erc_report",
        "consumer": "emit_perc_equivalent",
        "consumer_nested": "_auto",
    }]))
    res = _run_binary(tmp_path, reg)
    assert res.returncode == 0, (res.stdout, res.stderr)
    assert "CLEAN" in res.stdout


# --------------------------------------------------------------------------
# 3. #648/#649 defect-shape — VACUOUS_PASS unhandled → FLAG (exit 1).
# --------------------------------------------------------------------------
def test_issue648_649_vacuous_pass_unhandled_flags(tmp_path):
    combined = tmp_path / "programs" / "fix_yosys.py"
    (tmp_path / "programs").mkdir(exist_ok=True)
    combined.write_text(_PRODUCER_VACUOUS + "\n" + _CONSUMER_VACUOUS_NAIVE)
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps([{
        "edge_id": "yosys->flow(vacuous)",
        "file": "programs/fix_yosys.py",
        "producer": "yosys_hilomap_required_check",
        "consumer": "flow_consume",
    }]))
    res = _run_binary(tmp_path, reg)
    assert res.returncode == 1, (res.stdout, res.stderr)
    assert "VACUOUS_PASS" in res.stdout


# --------------------------------------------------------------------------
# 4. §4.05 NO-LEAK (a): a consumer's deliberate else->FAIL for a token NO
#    producer emits is CORRECT and must NOT be flagged. Only emitted-but-
#    unrecognized tokens are findings (strict one-way set difference).
# --------------------------------------------------------------------------
def test_no_leak_consumer_only_token_not_flagged():
    # producer emits exactly {PASS, BENIGN-ERC, REVIEW}; consumer recognizes a
    # SUPERSET incl. a token (DANGER) NO producer emits.
    edge = V.Edge(
        edge_id="t",
        producer_emitted={"PASS", "BENIGN-ERC", "REVIEW"},
        consumer_recognized={"PASS", "BENIGN-ERC", "REVIEW", "MEASURED", "DANGER"},
        producer_ref="p", consumer_ref="c")
    findings = V.audit_edges([edge])
    assert findings == [], \
        "a token only the consumer mentions (no producer emits it) is NOT a gap"


def test_no_leak_producer_emitted_FAIL_via_else_is_not_a_gap():
    """§4.05 (exact): a producer that emits the literal FAIL token, consumed by
    a mapper that routes it via else->FAIL, is an IDENTITY mapping (FAIL stays
    FAIL) — NOT a silent migration. It must NOT be flagged, otherwise the audit
    would force consumers to enumerate FAIL and would itself become a leak. A
    GENUINE FAIL still ends up FAIL: that is correct, not a finding."""
    edge = V.Edge(
        edge_id="t",
        producer_emitted={"PASS", "FAIL"},     # producer can emit FAIL
        consumer_recognized={"PASS"},          # FAIL handled only by else->FAIL
        producer_ref="p", consumer_ref="c")
    findings = V.audit_edges([edge])
    assert findings == [], \
        "producer-emitted FAIL routed via else->FAIL is an identity, not a gap"


def test_no_leak_non_fail_token_still_flagged_alongside_FAIL():
    """The FAIL carve-out must NOT mask a real non-FAIL gap on the same edge:
    REVIEW (a non-FAIL producer token unrecognized by the consumer) is STILL a
    finding even when FAIL is also emitted-and-else-handled."""
    edge = V.Edge(
        edge_id="t",
        producer_emitted={"PASS", "FAIL", "REVIEW"},
        consumer_recognized={"PASS"},
        producer_ref="p", consumer_ref="c")
    findings = V.audit_edges([edge])
    assert len(findings) == 1
    assert findings[0].unhandled_tokens == ["REVIEW"]   # FAIL exempt, REVIEW flagged


def test_no_leak_real_fail_token_still_fails_by_design():
    """§4.05: a consumer DELIBERATELY mapping an unknown / genuine-FAIL token to
    FAIL via its else branch is correct. The audit does NOT require the consumer
    to enumerate FAIL-y tokens. If the producer NEVER emits 'GENUINE_FAIL', the
    consumer's else->FAIL handling of it is fine and unflagged."""
    edge = V.Edge(
        edge_id="t",
        producer_emitted={"PASS", "REVIEW"},     # producer never emits a FAIL token
        consumer_recognized={"PASS"},            # only PASS recognized; REVIEW -> else
        producer_ref="p", consumer_ref="c")
    findings = V.audit_edges([edge])
    # REVIEW is emitted-but-unrecognized → IS a gap (genuine propagation defect)
    assert len(findings) == 1
    assert findings[0].unhandled_tokens == ["REVIEW"]
    # but a hypothetical 'GENUINE_FAIL' that no producer emits would never be a
    # finding — proven by the previous test's superset case.


# --------------------------------------------------------------------------
# 5. Engine-level reproduction of the exact #698 / #648 token sets.
# --------------------------------------------------------------------------
def test_engine_issue698_token_sets():
    edge = V.Edge(
        edge_id="698",
        producer_emitted={"PASS", "BENIGN-ERC", "REVIEW"},
        consumer_recognized={"PASS", "REVIEW", "MEASURED"},   # pre-fix R_C
        producer_ref="erc", consumer_ref="perc._auto")
    f = V.audit_edges([edge])
    assert len(f) == 1 and f[0].unhandled_tokens == ["BENIGN-ERC"]


def test_engine_issue648_token_sets():
    edge = V.Edge(
        edge_id="648",
        producer_emitted={"PASS", "FAIL", "VACUOUS_PASS"},
        consumer_recognized={"PASS", "FAIL"},
        producer_ref="yosys", consumer_ref="flow")
    f = V.audit_edges([edge])
    assert len(f) == 1 and f[0].unhandled_tokens == ["VACUOUS_PASS"]


# --------------------------------------------------------------------------
# 6. The live registry edge (HEAD) re-derives the real token sets and is clean.
# --------------------------------------------------------------------------
def test_live_registry_edge_extracted_and_subset():
    edges, warnings = V.build_registry_edges(_PLUGIN_ROOT)
    assert edges, "the ERC->PERC registry edge must materialise on HEAD"
    erc = next(e for e in edges if e.edge_id == "erc_screen->perc_equivalent")
    # producer emits BENIGN-ERC; consumer must recognize it (the #698 fix).
    assert "BENIGN-ERC" in erc.producer_emitted
    assert "BENIGN-ERC" in erc.consumer_recognized
    assert erc.producer_emitted <= erc.consumer_recognized
    assert V.audit_edges(edges) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
