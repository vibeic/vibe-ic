"""ORGANIC #779 (P3, cosmetic message-accuracy) — the Step-4 connectivity-waiver
PASS_WITH_WAIVERS message in cpu_functional_oracle_waiver_check.py hardcoded a
'generic_full_stack no-oracle CPU/SoC class' literal. After #745 made
arith_oracle_tb_gen DEFER for serial-parallel multipliers, a
`digital_arithmetic_primitive` IC routes into this same #654 gate — so the
message mislabelled it as CPU/SoC even though every STRUCTURED field
(verdict / capability_gap / functional_verified / waiver_reason) was correct.

Fix: derive `<track> no-oracle <ic_class> class` from the structured results.xml
(<verification_track> + the `class '<name>'` token in <waiver_reason>).

§4.05: the verdict / exit-code / capability_gap / evidence / functional_verified
are byte-identical after the fix — ONLY the human-readable string changes; a
genuine CPU/SoC class still reads correctly.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import cpu_functional_oracle_waiver_check as W  # noqa: E402

_GATE = _PROGRAMS / "cpu_functional_oracle_waiver_check.py"


def _bridge_xml(ic_class, track="generic_full_stack",
                evidence="phase2/stage1/sim/full_stack.log"):
    return (
        "<results><verdict>CONNECTIVITY_PASS</verdict>"
        "<functional_verified>false</functional_verified>"
        f"<verification_track>{track}</verification_track>"
        "<capability_gap>cap:cpu_functional_oracle</capability_gap>"
        f"<evidence>{evidence}</evidence>"
        "<source>step_reference_tb connectivity full-stack TB transcript "
        "(#654)</source>"
        f"<waiver_reason>class '{ic_class}' verification_track='{track}' "
        "half_duplex_bus=False — the AID half-duplex single-wire reference TB "
        "(3-port clk/reset_n/id_bus) cannot bind this interface family; no "
        "command/opcode oracle and no L10 golden vectors for this "
        "class.</waiver_reason></results>\n")


def _mk_project(tmp_path, xml):
    sim = tmp_path / "phase2/stage1/sim"
    sim.mkdir(parents=True)
    (sim / "full_stack.log").write_text(
        "FULL_STACK_TB_INIT\nFULL_STACK_TB_DONE bytes=0 bits=0\n")
    (sim / "results.xml").write_text(xml)
    return tmp_path


def _run(project):
    return subprocess.run([sys.executable, str(_GATE), str(project)],
                          capture_output=True, text=True)


# ── the label helper (pure) ──────────────────────────────────────────────────
def test_779_label_names_real_class():
    lbl = W._waiver_track_class_label(_bridge_xml("digital_arithmetic_primitive"))
    assert lbl == "generic_full_stack no-oracle digital_arithmetic_primitive class"
    assert "CPU/SoC" not in lbl


def test_779_label_genuine_cpu_reads_correctly():
    lbl = W._waiver_track_class_label(_bridge_xml("processor_cpu"))
    assert lbl == "generic_full_stack no-oracle processor_cpu class"


def test_779_label_dedicated_ic_class_tag_preferred():
    xml = _bridge_xml("digital_arithmetic_primitive").replace(
        "</results>", "<ic_class>memory_controller</ic_class></results>")
    assert "memory_controller class" in W._waiver_track_class_label(xml)


def test_779_label_graceful_fallback_when_fields_absent():
    xml = ("<results><verdict>CONNECTIVITY_PASS</verdict>"
           "<functional_verified>false</functional_verified>"
           "<capability_gap>cap:cpu_functional_oracle</capability_gap>"
           "<evidence>phase2/stage1/sim/full_stack.log</evidence></results>\n")
    lbl = W._waiver_track_class_label(xml)
    assert "CPU/SoC" not in lbl                       # no longer hardcoded
    assert lbl.startswith("generic_full_stack no-oracle")


# ── NEW-PATH end-to-end: message names the real non-CPU class, rc unchanged ──
def test_779_endstate_message_real_class_rc3(tmp_path):
    proj = _mk_project(tmp_path, _bridge_xml("digital_arithmetic_primitive"))
    r = _run(proj)
    assert r.returncode == 3, r.stdout
    assert "digital_arithmetic_primitive class" in r.stdout
    assert "CPU/SoC" not in r.stdout


# ── §4.05: verdict/cap/evidence path unchanged — a genuine CPU still rc=3 ────
def test_779_noleak_genuine_cpu_still_rc3(tmp_path):
    proj = _mk_project(tmp_path, _bridge_xml("processor_cpu"))
    r = _run(proj)
    assert r.returncode == 3, r.stdout
    assert "processor_cpu class" in r.stdout


# ── §4.05: a forged waiver (functional_verified=true) still FAILs (rc=1) ─────
def test_779_noleak_forged_waiver_still_fails(tmp_path):
    xml = _bridge_xml("digital_arithmetic_primitive").replace(
        "<functional_verified>false</functional_verified>",
        "<functional_verified>true</functional_verified>")
    proj = _mk_project(tmp_path, xml)
    r = _run(proj)
    assert r.returncode == 1, r.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
