"""phase1_evidence_grounding_check — the missing ANTI-FABRICATION gate for LLM
(and deterministic) Phase-1 L-doc output.

An empirical probe of the 87-spec phase1_parity corpus showed the existing gates
validate the LLM's L-doc output for COMPLETENESS (extraction_coverage_check,
INPUT->OUTPUT) and PROVENANCE PRESENCE + SCHEMA SHAPE (extraction_evidence_schema_
check / phase1_provenance_presence_check), but NONE verifies the OUTPUT->INPUT
direction: that a fact's claimed evidence is actually grounded in the input. A
fabricated `phantom_irq` port whose evidence literal is NOT in the spec passed all
three. This gate closes that hole — every direct input-doc evidence literal must
have its NAME-shaped identifiers grounded in the input.

§4.05 design (no false-fire, no leak):
  * grounds NAME-shaped identifiers (snake_case / ALL-CAPS / letter+digit), NOT
    bare hex/numeric VALUES (synthesized opcodes are gated for correctness
    elsewhere) — so a protocol-synth `0x10` opcode is not a false fire;
  * separator-insensitive (`wake_pulse` grounds against "wake pulse"), so a
    legitimate snake_case name is not a false fire;
  * exempts internal/derived source keys (a `derived_*` / `vN.N.N.*` provenance
    record is not a direct input quote);
  * a literal carrying a NAME-identifier that is NOWHERE in the input (a
    hallucinated signal/register) -> FAIL.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import phase1_evidence_grounding_check as G  # noqa: E402


def _proj(tmp_path, spec: str, evidence: dict, ports=None):
    (tmp_path / "input" / "docs").mkdir(parents=True)
    (tmp_path / "input" / "docs" / "proto_spec.txt").write_text(spec)
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    doc = {"schema_version": 2, "ic_name": "p",
           "ports": ports or [], "extraction_evidence": evidence}
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(doc))
    return tmp_path


_SPEC = ("Simple Protocol. The bus has clock clk, data sda, and a wake pulse "
         "signal. The TSTRB byte qualifier and AWVALID handshake are defined. "
         "Command 0x16 is the read opcode.")


def test_grounded_literal_passes(tmp_path):
    ev = {"input/docs/proto_spec.txt": [
        {"literal": "AWVALID handshake", "label": "ok"},
        {"literal": "TSTRB byte qualifier", "label": "ok"}]}
    assert G.check(_proj(tmp_path, _SPEC, ev))["status"] == "PASS"


def test_fabricated_name_fails(tmp_path):
    # an INVENTED port name whose concept is nowhere in the spec
    ev = {"input/docs/proto_spec.txt": [
        {"literal": "phantom_irq interrupt asserted on completion", "label": "X"}]}
    res = G.check(_proj(tmp_path, _SPEC, ev,
                        ports=[{"name": "phantom_irq", "direction": "output"}]))
    assert res["status"] == "FAIL"
    assert any("phantomirq" in u["missing_identifiers"] for u in res["ungrounded"])


def test_snake_case_name_grounds_separator_insensitive(tmp_path):
    # "wake_pulse" must ground against the spec's "wake pulse" (no false fire)
    ev = {"input/docs/proto_spec.txt": [
        {"literal": "wake_pulse measurement 5.0 us", "label": "vendor"}]}
    assert G.check(_proj(tmp_path, _SPEC, ev))["status"] == "PASS"


def test_bare_hex_value_not_flagged(tmp_path):
    # a synthesized opcode VALUE (not a NAME) is not this gate's job
    ev = {"input/docs/proto_spec.txt": [{"literal": "0x48", "label": "opcode"}]}
    assert G.check(_proj(tmp_path, _SPEC, ev))["status"] == "PASS"


def test_internal_source_exempt(tmp_path):
    # a derived / plugin-internal provenance record is NOT a direct input quote
    ev = {"v1.6.295.class_gate_suppressed": [
              {"literal": "class_path='processor_cpu', hd_signal_count=0", "label": "m"}],
          "derived_no_calibration_source": [{"literal": "INVENTED_TOKEN", "label": "d"}]}
    assert G.check(_proj(tmp_path, _SPEC, ev))["status"] == "PASS"


def test_no_input_silent_skips(tmp_path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
        {"extraction_evidence": {"input/docs/x.txt": [{"literal": "FOO_BAR"}]}}))
    assert G.check(tmp_path)["status"] == "SKIP"
