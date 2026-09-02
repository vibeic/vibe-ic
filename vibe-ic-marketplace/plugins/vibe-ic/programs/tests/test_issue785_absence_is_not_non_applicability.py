#!/usr/bin/env python3
"""vibe-ic#785 — an empty scan is not a clean bill, in FOUR more places.

#774 fixed `l21_macro_supply_rail_declared_check`: it keyed on hard-macro pins
typed `USE POWER`/`USE GROUND` and SKIPped when it found none, so regenerating
an abstract HONESTLY with `magic`'s `lef write` — which emits neither
`DIRECTION` nor `USE` on any PIN — turned a FAIL into a SKIP byte-identical to
the SKIP a design with no macro at all gets. The run got more honest and the
gate got quieter.

Four more carried the same shape, and this file pins all four:

  1. `hardmacro_supply_intent.assess`      pins=0 gaps=0 accounted=0
  2. `ip_integration_check`                inherits (1) verbatim, goes silent
  3. `l21_macro_supply_rail_synth`         NOT_APPLICABLE ... and its PRIVATE
                                           `_parse_lef` never got the #316/#329
                                           one-line-pin fix, so it disagreed
                                           with its own consumer about the same
                                           file
  4. `nvm_program_supply_intent`           applicable: False, indistinguishable
                                           from a genuinely single-supply macro

EXPLICIT NEGATIVE CONTROL. Every behavioural test asserts BOTH directions: the
untyped abstract must be reported AND the two genuinely-nothing-to-say cases (no
macro staged; an abstract that types its pins and declares no supply terminal)
must stay clean. A gate that reddens everything has not been fixed.

All fixtures are SYNTHESIZED neutral data — invented macro names, invented pin
names, invented net names. No PDK, vendor or part number appears anywhere. The
ONE test that reads published data copies it read-only and skips when absent.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import hardmacro_supply_intent as H          # noqa: E402
import nvm_program_supply_intent as N        # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

SYNTH = PROGRAMS / "l21_macro_supply_rail_synth.py"
DECLARED = PROGRAMS / "l21_macro_supply_rail_declared_check.py"
IPCHECK = PROGRAMS / "ip_integration_check.py"

# --- SYNTHESIZED neutral fixtures ------------------------------------------ #
# A hard macro whose abstract TYPES its pins.
TYPED_LEF = """VERSION 5.7 ;
MACRO NEUTRAL_BLOCK_A
  CLASS BLOCK ;
  SIZE 40.0 BY 20.0 ;
  PIN DATA_Q0
    DIRECTION OUTPUT ;
    USE SIGNAL ;
  END DATA_Q0
  PIN SUPPLY_HI_A
    DIRECTION INOUT ;
    USE POWER ;
  END SUPPLY_HI_A
  PIN SUPPLY_LO_A
    DIRECTION INOUT ;
    USE GROUND ;
  END SUPPLY_LO_A
END NEUTRAL_BLOCK_A
END LIBRARY
"""

# THE SAME MACRO, written by a tool. `magic`'s `lef write` emits neither
# DIRECTION nor USE on any PIN. Identical pin names, identical geometry — only
# the typing is gone.
UNTYPED_LEF = """VERSION 5.7 ;
MACRO NEUTRAL_BLOCK_A
  CLASS BLOCK ;
  FOREIGN NEUTRAL_BLOCK_A ;
  SIZE 40.0 BY 20.0 ;
  PIN DATA_Q0
    PORT
      LAYER MX1 ;
        RECT 1.0 1.0 1.4 1.4 ;
    END
  END DATA_Q0
  PIN SUPPLY_HI_A
    PORT
      LAYER MX1 ;
        RECT 0.0 0.0 40.0 0.5 ;
    END
  END SUPPLY_HI_A
  PIN SUPPLY_LO_A
    PORT
      LAYER MX1 ;
        RECT 0.0 19.5 40.0 20.0 ;
    END
  END SUPPLY_LO_A
END NEUTRAL_BLOCK_A
END LIBRARY
"""

# An abstract that DOES type its pins and declares no supply terminal. An
# AFFIRMATIVE statement, not missing evidence — it must stay clean.
SIGNAL_ONLY_LEF = """VERSION 5.8 ;
MACRO NEUTRAL_BLOCK_A
  CLASS BLOCK ;
  SIZE 40.0 BY 20.0 ;
  PIN DATA_Q0
    DIRECTION OUTPUT ;
    USE SIGNAL ;
  END DATA_Q0
  PIN CLK_A
    DIRECTION INPUT ;
    USE CLOCK ;
  END CLK_A
END NEUTRAL_BLOCK_A
END LIBRARY
"""

# LEF is newline-tolerant: a whole PIN block is legal on ONE line. This is the
# form `l21_macro_supply_rail_synth`'s private line walk could not read, and it
# is the form the published mixed-signal cell in this repo stages.
ONE_LINE_PIN_LEF = """VERSION 5.8 ;
MACRO NEUTRAL_BLOCK_A
  CLASS BLOCK ;
  SIZE 40.000 BY 20.000 ;
  PIN SUPPLY_HI_A  DIRECTION INOUT ; USE POWER  ; PORT LAYER MX1 ; RECT 0 0 2 2 ; END END SUPPLY_HI_A
  PIN SUPPLY_LO_A  DIRECTION INOUT ; USE GROUND ; PORT LAYER MX1 ; RECT 0 4 2 6 ; END END SUPPLY_LO_A
  PIN DATA_Q0      DIRECTION OUTPUT; USE SIGNAL ; PORT LAYER MX1 ; RECT 0 8 2 10 ; END END DATA_Q0
END NEUTRAL_BLOCK_A
END LIBRARY
"""

# A CLASS COVER macro — a hard macro by the CONSUMER's own class list, which the
# producer's private tuple did not include.
COVER_CLASS_LEF = """VERSION 5.8 ;
MACRO NEUTRAL_COVER_A
  CLASS COVER ;
  SIZE 10.0 BY 10.0 ;
  PIN SUPPLY_HI_A
    DIRECTION INOUT ;
    USE POWER ;
  END SUPPLY_HI_A
  PIN SUPPLY_LO_A
    DIRECTION INOUT ;
    USE GROUND ;
  END SUPPLY_LO_A
END NEUTRAL_COVER_A
END LIBRARY
"""

# The macro's OWN Liberty view. `pg_pin`/`pg_type` survive a `lef write` that
# drops the LEF `USE` records.
MACRO_LIB = """library (neutral_block_a) {
  technology (cmos) ;
  delay_model : table_lookup ;
  cell (NEUTRAL_BLOCK_A) {
    area : 800 ;
    pg_pin (SUPPLY_HI_A) { pg_type : primary_power ; voltage_name : "VIN_A" ; }
    pg_pin (SUPPLY_LO_A) { pg_type : primary_ground ; voltage_name : "VGND_A" ; }
    pin (DATA_Q0) { direction : output ; }
  }
}
"""

GUTTED_L21 = {
    "doc_id": "L21", "doc_name": "L21_POWER_INTENT",
    "fields": {"power_domains": [], "isolation_cells": [],
               "level_shifters": [], "upf_path": None},
    "extraction_status": "NOT_YET_EXTRACTED",
    "emitted_by": "test_fixture.skeleton",
}

RTL = """module neutral_top (input wire clk_a, output wire q_a);
  NEUTRAL_BLOCK_A u_block_a (.DATA_Q0 (q_a));
endmodule
"""


def _project(tmp_path: Path, *, lef: str | None = None, lib: str | None = None,
             l21: dict | None = None, rtl: bool = True,
             extra_lef: str | None = None) -> Path:
    p = tmp_path / "proj"
    g = p / "phase1" / "generated_docs"
    g.mkdir(parents=True, exist_ok=True)
    (g / "L21_POWER_INTENT.json").write_text(
        json.dumps(GUTTED_L21 if l21 is None else l21, indent=1))
    d = p / "input" / "pdk_local" / "neutral_vendor"
    d.mkdir(parents=True, exist_ok=True)
    if lef is not None:
        (d / "neutral_block_a.lef").write_text(lef)
    if extra_lef is not None:
        (d / "neutral_extra.lef").write_text(extra_lef)
    if lib is not None:
        (d / "neutral_block_a.lib").write_text(lib)
    if rtl:
        r = p / "phase2" / "stage1" / "rtl"
        r.mkdir(parents=True, exist_ok=True)
        (r / "neutral_top.v").write_text(RTL)
    return p


def _run(prog: Path, *args) -> tuple[int, str]:
    pr = _pr.run([sys.executable, str(prog), *args],
                        capture_output=True, text=True,
                        cwd=str(PROGRAMS))
    return pr.returncode, pr.stdout + pr.stderr


# =========================================================================== #
# 1 — hardmacro_supply_intent.assess
# =========================================================================== #
def test_assess_untyped_abstract_is_not_the_answer_no_macro_gets(tmp_path):
    """NEGATIVE CONTROL PAIR. `assess` used to return the SAME clean bill for a
    design with no macro and for a hard macro whose abstract types nothing."""
    none_at_all = H.assess([], GUTTED_L21)
    untyped = H.assess([UNTYPED_LEF], GUTTED_L21,
                       project=_project(tmp_path, lef=UNTYPED_LEF))

    # The pre-#785 discriminators are identical for both — that IS the defect.
    assert (len(none_at_all["pins"]), len(none_at_all["gaps"])) == (0, 0)
    assert (len(untyped["pins"]), len(untyped["gaps"])) == (0, 0)

    # ...so the two answers have to differ somewhere else, and they now do.
    assert none_at_all["untyped_abstracts"] == [], none_at_all
    assert none_at_all["inconclusive"] is False
    assert [a["master"] for a in untyped["untyped_abstracts"]] == \
        ["NEUTRAL_BLOCK_A"], untyped
    assert untyped["inconclusive"] is True, (
        "an abstract that types nothing and that no independent view "
        "corroborates is UNVERIFIABLE, not clean")
    assert untyped["scanned"]["lef_texts"] == 1
    assert untyped["scanned"]["untyped_masters"] == ["NEUTRAL_BLOCK_A"]


def test_assess_typed_abstract_is_unchanged(tmp_path):
    """The measured pre-#785 answer for a TYPED abstract: pins=2 gaps=2. It must
    not move — this fix adds a fact, it does not re-type the blocking path."""
    rep = H.assess([TYPED_LEF], GUTTED_L21,
                   project=_project(tmp_path, lef=TYPED_LEF))
    assert len(rep["pins"]) == 2 and len(rep["gaps"]) == 2
    assert rep["untyped_abstracts"] == [] and rep["inconclusive"] is False


def test_assess_recovers_the_typing_from_the_macros_own_liberty(tmp_path):
    """A LOUDER SKIP IS WEAKER THAN A PARTIAL CHECK. With the macro's own
    Liberty staged beside the abstract, the real finding comes back."""
    proj = _project(tmp_path, lef=UNTYPED_LEF, lib=MACRO_LIB)
    rep = H.assess([UNTYPED_LEF], GUTTED_L21, project=proj)
    assert rep["inconclusive"] is False, "corroborated, so not unverifiable"
    got = {(p["pin"], p["use"]) for p in rep["recovered_gaps"]}
    assert got == {("SUPPLY_HI_A", "POWER"), ("SUPPLY_LO_A", "GROUND")}, rep
    for p in rep["recovered_gaps"]:
        assert "Liberty" in p["typing_source"], p
    # and the abstract itself is still reported, now as UNDER-declared.
    assert rep["untyped_abstracts"][0]["corroborated"] is True

    # NEGATIVE CONTROL for the recovery: without the Liberty, nothing is
    # recovered and the abstract is reported as unverifiable instead.
    bare = H.assess([UNTYPED_LEF], GUTTED_L21,
                    project=_project(tmp_path / "b", lef=UNTYPED_LEF))
    assert bare["recovered_gaps"] == [] and bare["inconclusive"] is True


def test_assess_affirmative_no_supply_terminal_stays_clean(tmp_path):
    """NEGATIVE CONTROL: an abstract that TYPES its pins and declares no supply
    terminal is evidence, not its absence. It must not be reported."""
    rep = H.assess([SIGNAL_ONLY_LEF], GUTTED_L21,
                   project=_project(tmp_path, lef=SIGNAL_ONLY_LEF))
    assert rep["untyped_abstracts"] == [] and rep["inconclusive"] is False
    assert rep["pins"] == [] and rep["gaps"] == []


def test_untyped_walk_excludes_std_cells_by_lef_grammar():
    """A CLASS CORE library staged under a macro root is not a hard macro —
    excluded by grammar, not by filename. Both directions."""
    core = UNTYPED_LEF.replace("CLASS BLOCK ;", "CLASS CORE ;")
    assert H.lef_untyped_masters(core) == {}
    assert sorted(H.lef_untyped_masters(UNTYPED_LEF)) == ["NEUTRAL_BLOCK_A"]


def test_untyped_walk_is_not_fooled_by_a_partially_typed_abstract():
    """A macro that types a supply pin ANYWHERE is not an untyped abstract —
    the conservative reading."""
    half = UNTYPED_LEF.replace(
        "  PIN SUPPLY_HI_A\n", "  PIN SUPPLY_HI_A\n    USE POWER ;\n")
    assert H.lef_untyped_masters(half) == {}


# =========================================================================== #
# 2 — ip_integration_check
# =========================================================================== #
def _rules(project: Path) -> tuple[int, list[str]]:
    rc, out = _run(IPCHECK, str(project))
    try:
        doc = json.loads(out)
    except ValueError:  # pragma: no cover - diagnostics
        raise AssertionError(f"non-JSON output rc={rc}:\n{out}")
    return rc, sorted({f["rule"] for f in doc["findings"]})


def test_ip_integration_check_does_not_go_silent_on_an_untyped_abstract(tmp_path):
    """MEASURED, both directions: the SAME macro, two abstracts of one layout.
    The checklist spoke about the hand-written one and said NOTHING about the
    tool-written one."""
    _rc_t, typed = _rules(_project(tmp_path / "typed", lef=TYPED_LEF))
    assert "IP_MACRO_SUPPLY_UNDECLARED" in typed, typed

    _rc_u, untyped = _rules(_project(tmp_path / "untyped", lef=UNTYPED_LEF))
    assert "IP_MACRO_ABSTRACT_UNTYPED" in untyped, (
        "regenerating the abstract honestly must not silence the checklist; "
        f"got {untyped}")

    # ...and with the macro's own Liberty staged, the SUPPLY finding itself
    # comes back — a partial check, not merely a louder complaint.
    _rc_r, recovered = _rules(
        _project(tmp_path / "rec", lef=UNTYPED_LEF, lib=MACRO_LIB))
    assert "IP_MACRO_SUPPLY_UNDECLARED" in recovered, recovered
    assert "IP_MACRO_ABSTRACT_UNTYPED" in recovered, recovered


def test_ip_integration_check_stays_quiet_when_there_is_nothing_to_say(tmp_path):
    """NEGATIVE CONTROL, both genuine-silence cases."""
    empty = tmp_path / "empty"
    (empty / "phase1" / "generated_docs").mkdir(parents=True)
    rc, out = _run(IPCHECK, str(empty))
    assert rc == 2 and "SKIP" in out, out

    _rc, affirmative = _rules(
        _project(tmp_path / "sig", lef=SIGNAL_ONLY_LEF))
    assert not [r for r in affirmative if "MACRO_SUPPLY" in r
                or "ABSTRACT_UNTYPED" in r], affirmative


def test_ip_integration_check_untyped_finding_never_raises_the_exit_code(tmp_path):
    """Phase 1 WARNS so the requirement flows into the power-intent layer now;
    Phase 3 is where it blocks. A new advisory must not redden an exit code."""
    proj = _project(tmp_path, lef=UNTYPED_LEF, lib=MACRO_LIB)
    # Complete the handoff set so IP_FILESET_INCOMPLETE (the only ERROR this
    # gate has) cannot be what we are measuring.
    d = proj / "input" / "pdk_local" / "neutral_vendor"
    (d / "neutral_block_a.gds").write_text("gds")
    (d / "neutral_block_a.v").write_text("module NEUTRAL_BLOCK_A(); endmodule\n")
    rc, rules = _rules(proj)
    assert "IP_MACRO_ABSTRACT_UNTYPED" in rules, rules
    assert rc == 0, f"an advisory must stay rc=0; got {rc} with {rules}"


# =========================================================================== #
# 3 — l21_macro_supply_rail_synth
# =========================================================================== #
def test_synth_reads_a_one_line_pin_block(tmp_path):
    """3(b). The private line walk consumed the line at its `PIN` token, so the
    same-line `USE` was never read and the pin came out `{'<name>': None}`."""
    import l21_macro_supply_rail_synth as S
    parsed = S._parse_lef(ONE_LINE_PIN_LEF)["NEUTRAL_BLOCK_A"]["pins"]
    assert parsed["SUPPLY_HI_A"] == "POWER", parsed
    assert parsed["SUPPLY_LO_A"] == "GROUND", parsed

    # NEGATIVE CONTROL — the walk that is still there as the fallback really
    # does carry the blind spot, so the delegation is what fixed it, not luck.
    stale = S._parse_lef_line_walk(ONE_LINE_PIN_LEF)["NEUTRAL_BLOCK_A"]["pins"]
    assert stale["SUPPLY_HI_A"] is None, (
        "if the line walk can read this, the test proves nothing")


def test_synth_and_its_consumer_agree_about_the_same_file(tmp_path):
    """A PRODUCER AND ITS CONSUMER MUST NOT DISAGREE ABOUT THE SAME FILE.
    Measured, both directions: the consumer FAILs on N pins, the producer must
    derive rails for exactly those N pins, and applying them must clear it."""
    proj = _project(tmp_path, lef=ONE_LINE_PIN_LEF)

    rc_c, out_c = _run(DECLARED, str(proj))
    assert rc_c == 1, f"the consumer must FAIL first\n{out_c}"
    consumer_pins = {p for p in ("SUPPLY_HI_A", "SUPPLY_LO_A") if p in out_c}
    assert consumer_pins == {"SUPPLY_HI_A", "SUPPLY_LO_A"}

    rc_p, out_p = _run(SYNTH, str(proj))
    assert rc_p == 0, out_p
    assert "NOT_APPLICABLE" not in out_p, (
        "the producer reported nothing to do about the very pins its consumer "
        f"is failing on:\n{out_p}")
    for pin in consumer_pins:
        assert f"rail {pin}" in out_p, f"{pin} missing from producer\n{out_p}"

    # ...and the loop closes: apply, and the consumer PASSes.
    rc_a, _ = _run(SYNTH, str(proj), "--apply")
    assert rc_a == 0
    rc_c2, out_c2 = _run(DECLARED, str(proj))
    assert rc_c2 == 0, f"producer output must clear the consumer\n{out_c2}"
    assert "[PASS]" in out_c2


def test_synth_untyped_abstract_is_not_not_applicable(tmp_path):
    """3(a). Three outcomes, all asserted."""
    # (i) nothing staged -> still NOT_APPLICABLE.
    bare = tmp_path / "bare"
    (bare / "phase1" / "generated_docs").mkdir(parents=True)
    (bare / "phase1" / "generated_docs" / "L21_POWER_INTENT.json").write_text(
        json.dumps(GUTTED_L21))
    rc, out = _run(SYNTH, str(bare))
    assert rc == 0 and "NOT_APPLICABLE" in out, out

    # (ii) an abstract that types nothing -> its OWN verdict, macro named.
    rc, out = _run(SYNTH, str(_project(tmp_path / "u", lef=UNTYPED_LEF)))
    assert rc == 0, out
    assert "UNTYPED_ABSTRACT" in out, f"still non-applicability:\n{out}"
    assert "NEUTRAL_BLOCK_A" in out and "none typed" in out, out

    # (iii) ...and with the macro's own Liberty, the rails are DERIVED.
    rc, out = _run(SYNTH, str(_project(tmp_path / "r", lef=UNTYPED_LEF,
                                       lib=MACRO_LIB)))
    assert rc == 0, out
    assert "rail SUPPLY_HI_A" in out and "rail SUPPLY_LO_A" in out, out
    assert "RECOVERED from the macro's OWN Liberty" in out, out


def test_synth_affirmative_no_supply_terminal_stays_not_applicable(tmp_path):
    """NEGATIVE CONTROL: a macro that types its pins and declares no supply
    terminal has genuinely nothing to derive."""
    rc, out = _run(SYNTH, str(_project(tmp_path, lef=SIGNAL_ONLY_LEF)))
    assert rc == 0 and "NOT_APPLICABLE" in out, out
    assert "UNTYPED_ABSTRACT" not in out


def test_synth_recovered_rail_does_not_claim_a_lef_record_that_is_absent(tmp_path):
    """A provenance field that quotes a record the file does not contain is the
    same defect one layer down."""
    proj = _project(tmp_path, lef=UNTYPED_LEF, lib=MACRO_LIB)
    rc, _ = _run(SYNTH, str(proj), "--apply")
    assert rc == 0
    doms = json.loads(
        (proj / "phase1" / "generated_docs" / "L21_POWER_INTENT.json")
        .read_text())["fields"]["power_domains"]
    assert doms, "nothing was derived"
    for e in doms:
        src = e["derived_from"]
        assert src["macro_lef_pin_use"] is None, (
            f"the LEF types no pin at all; provenance must not claim it: {src}")
        assert "Liberty" in src["recovered_from"], src
    # NEGATIVE CONTROL — a LEF-typed rail still records the LEF as its source.
    typed = _project(tmp_path / "t", lef=TYPED_LEF)
    _run(SYNTH, str(typed), "--apply")
    tdoms = json.loads(
        (typed / "phase1" / "generated_docs" / "L21_POWER_INTENT.json")
        .read_text())["fields"]["power_domains"]
    assert all(e["derived_from"]["macro_lef_pin_use"] in ("POWER", "GROUND")
               for e in tdoms), tdoms


def test_synth_hard_macro_class_policy_matches_its_consumer(tmp_path):
    """The producer's private class tuple excluded COVER and required the record
    to be present; the consumer's includes COVER and treats a missing record as
    a hard macro. Same file, two scopes."""
    import l21_macro_supply_rail_synth as S
    assert S._is_hard_macro("COVER") is True
    assert S._is_hard_macro(None) is True, "a class-less vendor macro is in scope"
    assert S._is_hard_macro("CORE") is False, "a std cell is still excluded"

    proj = _project(tmp_path, lef=COVER_CLASS_LEF, rtl=False)
    rc, out = _run(SYNTH, str(proj))
    assert rc == 0 and "rail SUPPLY_HI_A" in out, out


# =========================================================================== #
# 4 — nvm_program_supply_intent
# =========================================================================== #
NVM_TYPED = """VERSION 5.7 ;
MACRO NEUTRAL_NVM_A
  CLASS BLOCK ;
  SIZE 40.0 BY 20.0 ;
  PIN SUPPLY_HI_A
    DIRECTION INOUT ; USE POWER ;
  END SUPPLY_HI_A
  PIN SUPPLY_BURN_A
    DIRECTION INOUT ; USE POWER ;
  END SUPPLY_BURN_A
  PIN SUPPLY_LO_A
    DIRECTION INOUT ; USE GROUND ;
  END SUPPLY_LO_A
END NEUTRAL_NVM_A
END LIBRARY
"""
NVM_UNTYPED = """VERSION 5.7 ;
MACRO NEUTRAL_NVM_A
  CLASS BLOCK ;
  SIZE 40.0 BY 20.0 ;
  PIN SUPPLY_HI_A
    PORT LAYER MX1 ; RECT 0 0 1 1 ; END
  END SUPPLY_HI_A
  PIN SUPPLY_BURN_A
    PORT LAYER MX1 ; RECT 0 2 1 3 ; END
  END SUPPLY_BURN_A
  PIN SUPPLY_LO_A
    PORT LAYER MX1 ; RECT 0 4 1 5 ; END
  END SUPPLY_LO_A
END NEUTRAL_NVM_A
END LIBRARY
"""
NVM_SINGLE_SUPPLY = """VERSION 5.7 ;
MACRO NEUTRAL_NVM_A
  CLASS BLOCK ;
  SIZE 40.0 BY 20.0 ;
  PIN SUPPLY_HI_A
    DIRECTION INOUT ; USE POWER ;
  END SUPPLY_HI_A
  PIN SUPPLY_LO_A
    DIRECTION INOUT ; USE GROUND ;
  END SUPPLY_LO_A
END NEUTRAL_NVM_A
END LIBRARY
"""
NVM_LIB = """library (neutral_nvm_a) {
  cell (NEUTRAL_NVM_A) {
    pg_pin (SUPPLY_HI_A)   { pg_type : primary_power ; }
    pg_pin (SUPPLY_BURN_A) { pg_type : backup_power ; }
    pg_pin (SUPPLY_LO_A)   { pg_type : primary_ground ; }
  }
}
"""
NVM_RTL = """module neutral_top (
  input  wire clk_a,
  input  wire prog_req_a,
  input  wire [7:0] prog_addr_a,
  input  wire [7:0] prog_data_a,
  output wire prog_busy_a,
  inout  wire SUPPLY_HI_A,
  inout  wire SUPPLY_LO_A
);
  NEUTRAL_NVM_A u_nvm_a (.Q (prog_busy_a));
endmodule
"""
NVM_L1 = {"doc_id": "L1", "fields": {"pinout": {
    "SUPPLY_HI_A": {"type": "power"}, "SUPPLY_LO_A": {"type": "ground"},
    "clk_a": {"type": "digital"}}}}


def _nvm_project(tmp_path: Path, lef: str | None, lib: str | None = None) -> Path:
    p = tmp_path / "nvm"
    d = p / "input" / "pdk_local" / "neutral_vendor"
    d.mkdir(parents=True, exist_ok=True)
    if lef is not None:
        (d / "neutral_nvm_a.lef").write_text(lef)
    if lib is not None:
        (d / "neutral_nvm_a.lib").write_text(lib)
    r = p / "input" / "rtl"
    r.mkdir(parents=True, exist_ok=True)
    (r / "neutral_top.v").write_text(NVM_RTL)
    g = p / "phase1" / "generated_docs"
    g.mkdir(parents=True, exist_ok=True)
    (g / "L1_DATASHEET.json").write_text(json.dumps(NVM_L1))
    return p


def test_nvm_untyped_abstract_is_not_a_single_supply_macro(tmp_path):
    """Both `applicable: False` reasons used to be the same verdict. A macro
    that DECLARED one supply and a macro whose abstract states nothing are
    different facts."""
    typed = N.assess(_nvm_project(tmp_path / "t", NVM_TYPED))
    assert typed["applicable"] is True
    assert [g["pin"] for g in typed["gaps"]] == ["SUPPLY_BURN_A"], typed

    untyped = N.assess(_nvm_project(tmp_path / "u", NVM_UNTYPED))
    assert untyped["applicable"] is False
    assert untyped["inconclusive"] is True, (
        "an abstract that types nothing cannot be placed on either side of the "
        f"multi-supply discriminator; got {untyped['reason']!r}")
    assert untyped["untyped_abstracts_unverifiable"] == ["NEUTRAL_NVM_A"]

    # NEGATIVE CONTROL — a genuinely single-supply macro is still a clean,
    # DECIDED non-applicability, not an inconclusive one.
    single = N.assess(_nvm_project(tmp_path / "s", NVM_SINGLE_SUPPLY))
    assert single["applicable"] is False and single["inconclusive"] is False
    assert single["untyped_abstracts"] == {}

    # ...and neither is a design with no macro at all.
    none_ = N.assess(_nvm_project(tmp_path / "n", None))
    assert none_["applicable"] is False and none_["inconclusive"] is False


def test_nvm_recovers_the_discriminator_from_the_macros_own_liberty(tmp_path):
    """A PARTIAL CHECK, not a louder skip: with the Liberty staged, the untyped
    abstract yields the SAME finding as the typed one."""
    rec = N.assess(_nvm_project(tmp_path / "r", NVM_UNTYPED, NVM_LIB))
    assert rec["applicable"] is True and rec["inconclusive"] is False
    assert [g["pin"] for g in rec["gaps"]] == ["SUPPLY_BURN_A"], rec
    assert rec["recovered_supply_pins"]["NEUTRAL_NVM_A"]["SUPPLY_BURN_A"] == \
        "POWER"

    typed = N.assess(_nvm_project(tmp_path / "t", NVM_TYPED))
    assert [g["pin"] for g in rec["gaps"]] == [g["pin"] for g in typed["gaps"]]


def test_nvm_liberty_that_shows_one_supply_does_not_manufacture_a_finding(
        tmp_path):
    """ANTI-CHEAT for the recovery: recovering the typing must not promote a
    single-supply macro into the finding set."""
    one_supply_lib = NVM_LIB.replace(
        "pg_pin (SUPPLY_BURN_A) { pg_type : backup_power ; }",
        "pg_pin (SUPPLY_BURN_A) { pg_type : primary_ground ; }")
    rep = N.assess(_nvm_project(tmp_path, NVM_UNTYPED, one_supply_lib))
    assert rep["applicable"] is False and rep["inconclusive"] is False
    assert rep["gaps"] == []


# =========================================================================== #
# The published cell — measured, not asserted.
# =========================================================================== #
_FLEET = PROGRAMS.parents[3] / "benchmark-data" / "ic"

#: THE ONE-LINE PIN GRAMMAR. Discovery is by LEF GRAMMAR, not by name, so the
#: point survives a rename. Lifted to module scope because the POSITIVE
#: CONTROL below feeds it a cell it MUST find: a detector that can no longer
#: detect produces the same empty result as a corpus that has no such cell,
#: and those are opposite findings.
_ONE_LINE_PIN_RE = re.compile(
    r"^\s*PIN\s+\S+.*\bUSE\s+(?:POWER|GROUND)\b.*\bEND\b.*\bEND\s+\S+",
    re.M | re.IGNORECASE)


def _fleet_roots():
    """Every root this discovery reads, and whether each is there.

    Two entries, and BOTH are named in the census so a reader can tell which
    one was missing. `_FLEET` is the in-repo path the corpus used to live at;
    it left this repository in v1.10.56, so on a plain checkout it does not
    exist. `VIBE_IC_BENCHMARK_DATA` is the one seam every corpus-reading gate
    in this tree uses to be pointed at a clone.
    """
    roots = [("in-repo", _FLEET)]
    env = os.environ.get("VIBE_IC_BENCHMARK_DATA")
    if env:
        # `<pointer>/ic` when it is there, `<pointer>` otherwise — NEVER both.
        # Adding both walks every design twice and reports a design count that
        # is double what was opened, which is the class of lie this whole file
        # is about. MEASURED while writing this: a pointer at a two-file tree
        # reported `2 design(s), 2 LEF file(s)` over one design and one file.
        base = Path(env)
        roots.append(("VIBE_IC_BENCHMARK_DATA/ic", base / "ic")
                     if (base / "ic").is_dir()
                     else ("VIBE_IC_BENCHMARK_DATA", base))
    out, seen = [], set()
    for label, path in roots:
        key = str(path.resolve()) if path.is_dir() else str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append((label, path, path.is_dir()))
    return out


def _scan_for_one_line_pin_cell(roots):
    """(hit, designs_scanned, lefs_scanned) over `roots`.

    Counts are returned WITH the hit because "no cell was found" and "no file
    was opened" are different findings and the skip below has to say which.
    """
    designs = lefs = 0
    hit = None
    for _label, root, present in roots:
        if not present:
            continue
        for design in sorted(p for p in root.iterdir() if p.is_dir()):
            designs += 1
            for lef in sorted(design.rglob("*.lef")):
                lefs += 1
                try:
                    if hit is None and _ONE_LINE_PIN_RE.search(
                            lef.read_text(errors="replace")):
                        hit = design
                except OSError:
                    continue
    return hit, designs, lefs


def _census():
    roots = _fleet_roots()
    hit, designs, lefs = _scan_for_one_line_pin_cell(roots)
    return {"roots": roots,
            "readable": [(l, str(p)) for l, p, ok in roots if ok],
            "unreadable": [(l, str(p)) for l, p, ok in roots if not ok],
            "designs": designs, "lefs": lefs, "hit": hit}


def _skip_reason(c):
    """WHY this measurement did not run — and never the same sentence twice.

    A test that skips forever and a test that passes look identical on a
    failure list, so this reason has to carry the state it measured. There
    are two skips and they are opposite findings:

      NOT BOUND    no root was readable, so nothing was opened. "I could not
                   look" — never "there is no such cell".
      NO SUCH CELL every readable root was walked and the grammar matched
                   nothing, with the counts to prove the walk happened.

    OWNER DECISION 2026-09-02: the corpus is NOT to gain a cell so that this
    test can run. The remedy for the second state is to say so, loudly, with
    numbers — which is what this does.
    """
    roots = ", ".join(f"{l}={p}" for l, p in c["unreadable"]) or "(none)"
    if not c["readable"]:
        return ("NOT BOUND — no corpus root is readable (looked at: "
                f"{roots}), so 0 LEF file(s) were opened and NOTHING WAS "
                "MEASURED. This is 'I could not look', not 'the published "
                "corpus has no such cell'. Point VIBE_IC_BENCHMARK_DATA at a "
                "clone to turn this skip into a measurement.")
    seen = ", ".join(f"{l}={p}" for l, p in c["readable"])
    return (f"NO SUCH CELL — walked {seen}: {c['designs']} design(s), "
            f"{c['lefs']} LEF file(s) opened, 0 staging a one-line PIN block. "
            "The corpus was READ and does not carry one. OWNER DECISION "
            "2026-09-02: a cell is NOT to be added to the corpus to make this "
            "test run. The detector itself is proven live by "
            "`test_the_one_line_pin_detector_fires_on_a_synthetic_cell`.")


_CENSUS = _census()


def _published_one_line_pin_cell():
    """A published project whose macro LEFs stage a one-line PIN block."""
    return _CENSUS["hit"]


# --- the three states, told apart ------------------------------------------ #
def test_the_published_cell_census_is_stated_whether_or_not_it_runs():
    """THREE STATES, AND UNTIL THIS TEST THEY WERE TWO.

    `test_producer_and_consumer_agree_on_a_published_cell` skips when no
    published cell stages a one-line PIN block. On a failure list a permanent
    skip and a pass are the same row, and a file that was never COLLECTED is
    no row at all. This test is always collected and always runs, so:

        this test present, the measurement SKIPPED  -> read its reason, which
                                                       says NOT BOUND or NO
                                                       SUCH CELL and cannot
                                                       say both
        this test present, the measurement PASSED   -> it ran
        this test ABSENT                            -> the file was not
                                                       collected at all

    It asserts the reason cannot drift from the census it describes: a
    sentence that says "walked 12 designs" while nothing was opened is the
    failure this whole file is about, one level up.
    """
    c = _CENSUS
    reason = _skip_reason(c)
    print("published-cell census:", {k: v for k, v in c.items()
                                     if k != "roots"})
    assert c["roots"], "the discovery names no root at all"
    if not c["readable"]:
        assert c["designs"] == 0 and c["lefs"] == 0, c
        assert c["hit"] is None, c
        assert reason.startswith("NOT BOUND"), reason
    else:
        assert reason.startswith("NO SUCH CELL") or c["hit"] is not None, \
            reason
    if c["hit"] is not None:
        assert c["lefs"] > 0, c


def test_the_one_line_pin_detector_fires_on_a_synthetic_cell(tmp_path):
    """POSITIVE CONTROL ON THE INSTRUMENT — the half a skip cannot supply.

    `NO SUCH CELL` is only worth reading if the detector can still detect. A
    broken grammar and an absent cell produce the same empty scan, and the
    broken one reads as coverage. So the grammar is fed a cell it MUST find,
    in a root shaped like the corpus, and the surrounding NEGATIVE cell must
    NOT match: a detector that fires on everything proves nothing either.
    """
    root = tmp_path / "ic"
    # The POSITIVE cell is this file's own `ONE_LINE_PIN_LEF` — the fixture
    # every behavioural test above treats as the one-line form — so the
    # detector and the fixtures cannot come to disagree about what the shape
    # IS. The NEGATIVE cell is `TYPED_LEF`, whose PIN blocks span lines.
    (root / "synthetic_design" / "macros").mkdir(parents=True)
    (root / "synthetic_design" / "macros" / "hit.lef").write_text(
        ONE_LINE_PIN_LEF, encoding="utf-8")
    (root / "other_design" / "macros").mkdir(parents=True)
    (root / "other_design" / "macros" / "miss.lef").write_text(
        TYPED_LEF, encoding="utf-8")

    hit, designs, lefs = _scan_for_one_line_pin_cell([("synthetic", root, True)])
    assert lefs == 2 and designs == 2, (designs, lefs)
    assert hit is not None and hit.name == "synthetic_design", hit
    miss, _d, _l = _scan_for_one_line_pin_cell(
        [("synthetic", root / "..", False)])
    assert miss is None, "an unreadable root must contribute nothing"
    only_negative = tmp_path / "neg"
    (only_negative / "other_design" / "macros").mkdir(parents=True)
    (only_negative / "other_design" / "macros" / "miss.lef").write_text(
        TYPED_LEF, encoding="utf-8")
    neg, nd, nl = _scan_for_one_line_pin_cell([("neg", only_negative, True)])
    assert neg is None and (nd, nl) == (1, 1), (neg, nd, nl)


@pytest.mark.skipif(_CENSUS["hit"] is None, reason=_skip_reason(_CENSUS))
def test_producer_and_consumer_agree_on_a_published_cell(tmp_path):
    """THE MEASUREMENT THAT NAMED THE DEFECT. On a published cell the producer
    printed `NOT_APPLICABLE / 0 hard macro(s) with PG pins across 2 LEF file(s)`
    while the consumer FAILED on four pins in those same two files.

    The published tree is COPIED, never read in place and never written."""
    src = _published_one_line_pin_cell()
    proj = tmp_path / "published_copy"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L21_POWER_INTENT.json").write_text(
        json.dumps(GUTTED_L21))
    n = 0
    for lef in sorted(src.rglob("*.lef")):
        rel = lef.relative_to(src)
        if not any(seg in str(rel) for seg in
                   ("pdk_local", "macros", "hardmacro")):
            continue
        dst = proj / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lef, dst)
        for sib in (".lib", ".v"):
            s = lef.with_suffix(sib)
            if s.is_file():
                shutil.copy2(s, dst.with_suffix(sib))
        n += 1
    if not n:
        pytest.skip("no macro LEF under a root both programs read")

    rc_c, out_c = _run(DECLARED, str(proj))
    assert rc_c == 1, f"expected the consumer to FAIL on these pins\n{out_c}"
    consumer_pins = sorted({ln.split("pin `")[1].split("`")[0]
                            for ln in out_c.splitlines() if "pin `" in ln})
    assert consumer_pins, out_c

    rc_p, out_p = _run(SYNTH, str(proj))
    assert rc_p == 0, out_p
    assert "NOT_APPLICABLE" not in out_p, (
        "the producer must not report nothing to do about the pins its own "
        f"consumer is failing on:\n{out_p}")
    for pin in consumer_pins:
        assert f"rail {pin}" in out_p or f"ground={pin}" in out_p, (
            f"producer did not derive a rail for {pin}\n{out_p}")

    _run(SYNTH, str(proj), "--apply")
    rc_c2, out_c2 = _run(DECLARED, str(proj))
    assert rc_c2 == 0 and "[PASS]" in out_c2, out_c2


def test_no_pdk_vendor_or_design_literal_in_the_changed_programs():
    """chip-AGNOSTIC guard. Every rule here is LEF/Liberty grammar."""
    import re
    banned = re.compile(
        r"\b(sky130|gf180|ihp[-_]?sg13|tsmc|samsung|globalfoundries|"
        r"hawaii|caravel|openram|sram22)\b", re.IGNORECASE)
    for name in ("hardmacro_supply_intent.py", "ip_integration_check.py",
                 "l21_macro_supply_rail_synth.py",
                 "nvm_program_supply_intent.py"):
        src = (PROGRAMS / name).read_text(encoding="utf-8")
        hit = banned.search(src)
        assert hit is None, f"{name}: PDK/design literal {hit.group(0)!r}"
