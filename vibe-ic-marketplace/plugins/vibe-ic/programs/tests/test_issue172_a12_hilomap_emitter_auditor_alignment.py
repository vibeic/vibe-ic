"""#172 (A12) — the runner's OWN emitted synth command must pass the runner's
OWN yosys hilomap audit.

The step-14 auditor (`yosys_hilomap_required_check`) FAILs a real-PDK synth
script that carries no `hilomap`. The EMITTER
(`_v1_6_596_build_hilomap_directive`) only emits `hilomap` when the PDK's tie
cells are DISCOVERABLE. On ASAP7 the tie cells are `TIEHIx1_ASAP7_75t_R` /
`TIELOx1_ASAP7_75t_R`, which the pre-#168 `$`-anchored tie-name patterns did
NOT match — so the emitter returned "" (no hilomap) and the runner's own synth
command was flagged non-conformant by its own auditor. #168 (A8) broadened the
tie-name patterns; these tests pin the end-to-end alignment: for an ASAP7-style
PDK the emitter now produces a hilomap directive, and a synth script carrying
that emitted directive PASSES `yosys_hilomap_required_check` — while a synth
script that genuinely OMITS hilomap still FAILs (the gate is not weakened).

chip-AGNOSTIC: a synthetic ASAP7-style liberty with the real TIE token +
drive-strength + library suffix shape; no chip / SKU literal.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402
import yosys_hilomap_required_check as H  # noqa: E402


_ASAP7_TIE_LIB = """\
library(asap7_tie) {
  cell (TIEHIx1_ASAP7_75t_R) {
    area : 0.1 ;
    pg_pin (VDD) { pg_type : primary_power ; }
    pg_pin (VSS) { pg_type : primary_ground ; }
    pin (H) { direction : output ; function : "1" ; }
  }
  cell (TIELOx1_ASAP7_75t_R) {
    area : 0.1 ;
    pg_pin (VDD) { pg_type : primary_power ; }
    pg_pin (VSS) { pg_type : primary_ground ; }
    pin (L) { direction : output ; function : "0" ; }
  }
}
"""


def _write(tmp, name, text):
    p = tmp / name
    p.write_text(text)
    return p


def test_emitter_produces_hilomap_for_asap7_style_pdk(tmp_path):
    lib = _write(tmp_path, "asap7_tie.lib", _ASAP7_TIE_LIB)
    directive = R._v1_6_596_build_hilomap_directive(str(lib))
    assert directive, "emitter returned no hilomap directive for ASAP7 tie cells"
    # The directive names the discovered tie cells + their real output pins.
    assert "hilomap" in directive
    assert "TIEHIx1_ASAP7_75t_R" in directive and " H " in directive
    assert "TIELOx1_ASAP7_75t_R" in directive and directive.rstrip().endswith("L")


def test_runner_emitted_command_passes_its_own_audit(tmp_path):
    # The runner's OWN synth command (inline `yosys -p`) for an ASAP7 PDK now
    # carries the emitted hilomap; a .ys with that exact directive AUDITS clean.
    lib = _write(tmp_path, "asap7_tie.lib", _ASAP7_TIE_LIB)
    directive = R._v1_6_596_build_hilomap_directive(str(lib))
    ys = _write(tmp_path, "synth.ys",
                "read_verilog -sv top.v\n"
                "synth -top top -flatten\n"
                "techmap\n"
                f"{directive}\n"
                "write_verilog out.v\n")
    rc, msgs = H.audit(str(ys))
    assert rc == 0, f"runner's own emitted synth command failed its own audit: {msgs}"


def test_auditor_still_fails_a_genuinely_missing_hilomap(tmp_path):
    # Gate not weakened: a synth script that omits hilomap entirely still FAILs.
    ys = _write(tmp_path, "synth_no_hilomap.ys",
                "read_verilog -sv top.v\n"
                "synth -top top -flatten\n"
                "techmap\n"
                "write_verilog out.v\n")
    rc, msgs = H.audit(str(ys))
    assert rc == 1
    assert any("MISSING hilomap" in m for m in msgs)


def test_sky130_conb_emitter_unchanged(tmp_path):
    # Regression guard: sky130's dual-output conb_1 still yields a hilomap
    # directive (byte-identical emitter behaviour for the pre-#168 case).
    sky_lib = _write(tmp_path, "sky130_tie.lib",
                     "library(sky130){\n"
                     "  cell (sky130_fd_sc_hd__conb_1){\n"
                     "    pin (HI){ direction:output; function:\"1\"; }\n"
                     "    pin (LO){ direction:output; function:\"0\"; }\n"
                     "  }\n"
                     "}\n")
    directive = R._v1_6_596_build_hilomap_directive(str(sky_lib))
    assert directive and "sky130_fd_sc_hd__conb_1" in directive
