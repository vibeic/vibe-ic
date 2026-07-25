#!/usr/bin/env python3
"""Smoke tests for l23_security_requirements_typed_check.py (layergate-7).

NEGATIVE CONTROL IS THE POINT
=============================
Both directions are asserted for every behaviour: gutted layer FAILs,
well-formed layer PASSes.

The asymmetry under test is deliberate. L23 has NO consumer anywhere in
the plugin, so:
  * the SELF-CONTRADICTION half (asserting security posture the layer
    cannot back) BLOCKS — it needs no consumer to be wrong;
  * the CROSS-LAYER half (requirement stated in the design's own inputs,
    absent from L23) ADVISES — there is no downstream contract to
    protect by stopping.

All fixtures are SYNTHESISED neutral data.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "l23_security_requirements_typed_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True)


def _mk(tmp_path, l23=None, docs=None, siblings=None, waivers=None):
    proj = tmp_path / "p"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    if l23 is not None:
        (gd / "L23_SECURITY_REQUIREMENTS.json").write_text(
            json.dumps(l23, ensure_ascii=False), encoding="utf-8")
    for code, payload in (siblings or {}).items():
        (gd / f"{code}_SYNTH.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    if docs:
        dd = proj / "phase1" / "input_doc"
        dd.mkdir(parents=True, exist_ok=True)
        for name, text in docs.items():
            (dd / name).write_text(text, encoding="utf-8")
    if waivers:
        (proj / "waivers.json").write_text(json.dumps(waivers),
                                           encoding="utf-8")
    return proj


# The shape observed in 24/24 sampled real runs: honest, asserts nothing.
_SKELETON = {
    "doc_id": "L23",
    "doc_name": "L23_SECURITY_REQUIREMENTS",
    "applicability": "APPLICABLE",
    "fields": {
        "key_handling": {},
        "attack_surface": [],
        "side_channel_mitigation": [],
        "secure_boot": False,
        "security_requirements_present": False,
    },
    "extraction_status": "NOT_YET_EXTRACTED",
    "extraction_evidence": {},
}

_TYPED_RECORDS = {
    "attack_surface": [
        {"name": "host_register_interface",
         "description": "Externally writable configuration registers.",
         "evidence": "synthetic_spec.txt:12"},
    ],
    "side_channel_mitigation": [
        {"name": "masked_datapath",
         "mitigation": "Boolean masking of the round state.",
         "evidence": "synthetic_spec.txt:31"},
    ],
    "key_handling": [
        {"name": "session_key",
         "description": "Loaded over the register interface, cleared on "
                        "reset.",
         "evidence": "synthetic_spec.txt:44"},
    ],
}

# Synthetic requirement text: technology vocabulary + requirement framing.
_SECURITY_REQUIREMENT_DOC = (
    "5. Security Requirements\n"
    "The design shall implement side-channel countermeasures against\n"
    "differential power analysis. Secure boot is required before the\n"
    "application image is executed. Key storage must be inaccessible to\n"
    "the host after provisioning.\n"
)
_NO_SECURITY_DOC = (
    "5. Operating Requirements\n"
    "The design shall accept a 32-bit operand and must complete within\n"
    "four cycles at the target frequency.\n"
)
# A passing mention with no requirement framing — must NOT trigger.
_PASSING_MENTION_DOC = (
    "Appendix A. Pin descriptions\n"
    "| alert_o | out | 1 | Asserted when on-chip monitors detect\n"
    "  tampering / attack. This signal is informational. |\n"
)


# ── skips ────────────────────────────────────────────────────────────

def test_skip_when_no_l23(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    assert _run(proj).returncode == 2


def test_skip_when_not_applicable(tmp_path):
    doc = dict(_SKELETON, applicability="NOT_APPLICABLE")
    r = _run(_mk(tmp_path, l23=doc,
                 docs={"spec.txt": _SECURITY_REQUIREMENT_DOC}))
    assert r.returncode == 2, r.stdout + r.stderr


def test_honest_skeleton_on_nonsecurity_design_skips(tmp_path):
    """The 123/136 fleet shape: SKIP, not a flow-stopper."""
    r = _run(_mk(tmp_path, l23=_SKELETON, docs={"spec.txt": _NO_SECURITY_DOC}))
    assert r.returncode == 2, r.stdout + r.stderr


def test_passing_mention_without_framing_does_not_fire(tmp_path):
    """"detect tampering / attack" in a pin table is not a requirement."""
    r = _run(_mk(tmp_path, l23=_SKELETON,
                 docs={"pins.txt": _PASSING_MENTION_DOC}))
    assert r.returncode == 2, r.stdout + r.stderr


# ── F1 VACUOUS_SECURITY_ASSERTION — BLOCKS, negative control pair ────

def test_NEGATIVE_CONTROL_fail_secure_boot_asserted_with_no_records(tmp_path):
    """GUTTED: claims secure boot, backs it with nothing."""
    doc = json.loads(json.dumps(_SKELETON))
    doc["fields"]["secure_boot"] = True
    doc["fields"]["security_requirements_present"] = True
    r = _run(_mk(tmp_path, l23=doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "VACUOUS_SECURITY_ASSERTION" in r.stdout


def test_POSITIVE_CONTROL_pass_assertion_backed_by_typed_records(tmp_path):
    """WELL-FORMED: same claim, backed by typed records with evidence."""
    doc = json.loads(json.dumps(_SKELETON))
    doc["fields"]["secure_boot"] = True
    doc["fields"]["security_requirements_present"] = True
    doc["fields"].update(json.loads(json.dumps(_TYPED_RECORDS)))
    r = _run(_mk(tmp_path, l23=doc))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_NEGATIVE_CONTROL_fail_record_without_evidence(tmp_path):
    """GUTTED: an unsourced security claim is read downstream as fact."""
    doc = json.loads(json.dumps(_SKELETON))
    doc["fields"]["security_requirements_present"] = True
    doc["fields"]["attack_surface"] = [
        {"name": "host_register_interface",
         "description": "Externally writable configuration registers."},
    ]
    r = _run(_mk(tmp_path, l23=doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "VACUOUS_SECURITY_ASSERTION" in r.stdout
    assert "evidence" in r.stdout


def test_extraction_claimed_with_no_records_fails(tmp_path):
    doc = json.loads(json.dumps(_SKELETON))
    doc["extraction_status"] = "EXTRACTED"
    r = _run(_mk(tmp_path, l23=doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "VACUOUS_SECURITY_ASSERTION" in r.stdout


# ── F2 REQUIREMENT_OUTSIDE_CONSUMING_LAYER — ADVISES ─────────────────

def test_requirement_in_docs_absent_from_l23_advises(tmp_path):
    """The L21 shape, but ADVISE: L23 has no consumer to protect.

    If this assertion ever flips to returncode == 1, some step has
    started reading L23 and the finding must be promoted deliberately.
    """
    r = _run(_mk(tmp_path, l23=_SKELETON,
                 docs={"spec.txt": _SECURITY_REQUIREMENT_DOC}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[ADVISE]" in r.stdout
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" in r.stdout
    assert "[FAIL]" not in r.stdout


def test_POSITIVE_CONTROL_no_advisory_once_l23_carries_it(tmp_path):
    """WELL-FORMED: same doc, requirement now typed in L23."""
    doc = json.loads(json.dumps(_SKELETON))
    doc["fields"]["security_requirements_present"] = True
    doc["fields"].update(json.loads(json.dumps(_TYPED_RECORDS)))
    r = _run(_mk(tmp_path, l23=doc,
                 docs={"spec.txt": _SECURITY_REQUIREMENT_DOC}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" not in r.stdout
    assert "PASS" in r.stdout


def test_requirement_in_sibling_l_doc_advises(tmp_path):
    """Derived from the sibling's OWN declared semantics, not a chip's
    register literal."""
    sib = {"doc_id": "L11", "fields": {"otp_records": [
        {"name": "provisioned_secret",
         "description": "Device key material; the host must not be able "
                        "to read this back after lock."}]}}
    r = _run(_mk(tmp_path, l23=_SKELETON, siblings={"L11": sib}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" in r.stdout


# ── waiver ───────────────────────────────────────────────────────────

def test_waiver_suppresses_blocking_finding(tmp_path):
    doc = json.loads(json.dumps(_SKELETON))
    doc["fields"]["secure_boot"] = True
    proj = _mk(tmp_path, l23=doc,
               waivers=[{"id": "l23_security_scope_deferred_to_"
                               "system_integrator",
                         "rationale": "Boot authentication is performed by "
                                      "the system controller outside this "
                                      "block; the block exposes no key "
                                      "material."}])
    assert _run(proj).returncode == 2


def test_short_waiver_rationale_does_not_waive(tmp_path):
    doc = json.loads(json.dumps(_SKELETON))
    doc["fields"]["secure_boot"] = True
    proj = _mk(tmp_path, l23=doc,
               waivers=[{"id": "l23_security_scope_deferred_to_"
                               "system_integrator", "rationale": "tbd"}])
    assert _run(proj).returncode == 1


# ── report emission ──────────────────────────────────────────────────

def test_writes_machine_readable_report(tmp_path):
    proj = _mk(tmp_path, l23=_SKELETON,
               docs={"spec.txt": _SECURITY_REQUIREMENT_DOC})
    _run(proj)
    rpt = (proj / "reports" / "phase1"
           / "l23_security_requirements_typed_check.json")
    assert rpt.is_file()
    data = json.loads(rpt.read_text())
    assert data["verdict"] == "PASS_WITH_ADVISORY"
    assert data["advisory_findings"][0]["evidence"]
