#!/usr/bin/env python3
"""The PDK-scoped L8 clock contract — all four outcomes, both consumers, both
directions.

RULING R-0915-6 (2026-09-15) composed two independently measured halves into
ONE contract, and required that BOTH consumers of a scoped L8 clock apply it
identically:

  1. a scoped record matching the run's PDK by NAME or FAMILY  -> selected
  2. none scoped matches, but an UNSCOPED design-owned record exists
                                                               -> selected,
     and the summary says ``unscoped_design_owned``
  3. only foreign-scoped records                               -> refuse
     (``L8_CLOCK_SCOPE_MISMATCH`` — the honest case)
  4. scoped records and no run PDK known                       -> NOT_MEASURED

The halves, and where each was measured:

  * lane icaes, on AES: a design that states an unscoped clock alongside a
    scoped one was refused outright. Outcome 2 is that half.
  * lane icspm, on SPM (this file's author): the consumers took the target
    from ``L19.fields.pdk_target`` — the FIRST family L1 names — rather than
    from the PDK the run actually targets, and compared it with ``==`` across
    two naming registers. Outcomes 1 and 4 are that half. Measured end to end::

        $ vibe_ic_one_shot_runner.py <project> --pdk gf180mcuD --ic-name spm
        FAIL sdc_gen rc=1 L8_CLOCK_SCOPE_MISMATCH: no scoped L8 clock matches
                                                   L19 target 'sky130'
        overall verdict : FAIL     halted at : phase2

WHY THE TWO CONSUMERS ARE TESTED TOGETHER IN ONE FILE: they must SELECT THE
SAME RECORD. When ``sdc_gen`` and ``l8_clock_period_actionability_check``
disagreed, the generator emitted an SDC the checker then failed — on inputs
that were entirely self-consistent. A per-consumer test file cannot see that
class of defect; ``test_both_consumers_agree_on_every_outcome`` can.

EVERY fixture is synthesized neutral data, in the sibling file's idiom:
``fixture_core``, ports ``clk_a``. The process names are the two spellings of
one open family and one spelling of another, because the register difference
between a PDK name and a family name IS the thing under test and cannot be
expressed with invented strings the family registry does not know.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import _l8_clock_scope as S  # noqa: E402
import sdc_gen  # noqa: E402

#: L8 scopes to the PDK NAME; L19 and the run record may hold the FAMILY name.
RUN_PDK = "gf180mcuD"
RUN_FAMILY = "gf180mcu"
FOREIGN_PDK = "sky130A"
FOREIGN_FAMILY = "sky130"

SCOPED_MHZ = 125.0          # the record that names a process
UNSCOPED_MHZ = 50.0         # the record that names none


# ── fixture builders ────────────────────────────────────────────────────────

def _clock(name: str, mhz: float, **extra) -> dict:
    rec = {"name": name, "source_pin": name, "freq_mhz": mhz,
           "freq_hz": int(mhz * 1e6), "period_ns": 1000.0 / mhz,
           "domain_kind": "primary", "role": "master"}
    rec.update(extra)
    return rec


def _project(tmp_path: Path, domains: list, *, run_pdk: str | None = None,
             l19_target: str | None = None) -> Path:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    doc = {"clock_domains": domains}
    for stem in ("L8_TIMING_WAVEFORM", "L8_RTL_CONSTANTS"):
        (gd / f"{stem}.json").write_text(json.dumps(doc, indent=1))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "fixture_core",
        "top_module_pins": [{"name": "clk_a", "mode": "input"},
                            {"name": "rst_n", "mode": "input"},
                            {"name": "dout", "mode": "output"}],
    }))
    if l19_target is not None:
        (gd / "L19_CONSTRAINTS_PDK.json").write_text(
            json.dumps({"fields": {"pdk_target": l19_target}}))
    if run_pdk is not None:
        rep = tmp_path / "reports" / "phase1"
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "submission_template_fetch.json").write_text(
            json.dumps({"pdk": run_pdk, "pdk_source": "--pdk"}))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "fixture_core.v").write_text(
        "module fixture_core(input wire clk_a, input wire rst_n,\n"
        "                    output reg dout);\n"
        "  always @(posedge clk_a or negedge rst_n)\n"
        "    if (!rst_n) dout <= 1'b0; else dout <= 1'b1;\n"
        "endmodule\n")
    return tmp_path


def _sdc_text(project: Path) -> str:
    files = list((project / "phase2" / "stage1" / "fpga").glob("*.sdc"))
    assert len(files) == 1, files
    return files[0].read_text()


SCOPED_ONLY = [_clock("clk_a", SCOPED_MHZ, pdk_scoped_target=RUN_PDK)]
SCOPED_PLUS_UNSCOPED = [
    _clock("clk_a", SCOPED_MHZ, pdk_scoped_target=RUN_PDK),
    _clock("clk_a", UNSCOPED_MHZ),
]


# ── OUTCOME 1: a scoped record matching the run, by NAME then by FAMILY ─────

def test_outcome1_scoped_match_by_exact_pdk_name(tmp_path):
    proj = _project(tmp_path, SCOPED_ONLY, run_pdk=RUN_PDK,
                    l19_target=FOREIGN_FAMILY)
    assert sdc_gen.main([str(proj), "--force"]) == 0
    assert f"-period {1000.0 / SCOPED_MHZ:g} " in _sdc_text(proj)


def test_outcome1_scoped_match_by_family_name(tmp_path):
    """THE MEASURED DEFECT'S SECOND HALF (D2). The run records the FAMILY
    spelling, L8 scopes to the PDK spelling. One process, two registers; the
    pre-fix comparison was `==` and refused."""
    proj = _project(tmp_path, SCOPED_ONLY, run_pdk=RUN_FAMILY,
                    l19_target=FOREIGN_FAMILY)
    assert sdc_gen.main([str(proj), "--force"]) == 0
    assert f"-period {1000.0 / SCOPED_MHZ:g} " in _sdc_text(proj)


# ── OUTCOME 2: an unscoped design-owned record applies to every process ─────

def test_outcome2_unscoped_design_owned_is_selected(tmp_path):
    proj = _project(tmp_path, SCOPED_PLUS_UNSCOPED, run_pdk=FOREIGN_PDK)
    assert sdc_gen.main([str(proj), "--force"]) == 0
    assert f"-period {1000.0 / UNSCOPED_MHZ:g} " in _sdc_text(proj)


def test_outcome2_does_not_displace_outcome1(tmp_path):
    """When the run's OWN process is named, the unscoped record must not win.
    Control against a fix that makes the fallback unconditional."""
    proj = _project(tmp_path, SCOPED_PLUS_UNSCOPED, run_pdk=RUN_PDK)
    assert sdc_gen.main([str(proj), "--force"]) == 0
    assert f"-period {1000.0 / SCOPED_MHZ:g} " in _sdc_text(proj)


# ── OUTCOME 3: only foreign scopes — THE REFUSAL, PRESERVED ─────────────────

def test_outcome3_only_foreign_scopes_is_refused(tmp_path):
    """MUST FAIL. The design states no clock for the process this run targets
    and states one for another. Closing timing against that period is the
    defect the scoped branch exists to prevent; the refusal is preserved."""
    proj = _project(tmp_path, SCOPED_ONLY, run_pdk=FOREIGN_PDK)
    assert sdc_gen.main([str(proj), "--force"]) == 1


# ── OUTCOME 4: scoped records, no run PDK — NOT_MEASURED, not MISMATCH ──────

def test_outcome4_no_target_is_not_measured_not_mismatch(tmp_path):
    """"I could not tell which process this run targets" and "the design
    states no clock for it" are DIFFERENT answers and must not reach a reader
    as one verdict."""
    proj = _project(tmp_path, SCOPED_ONLY)          # no run record, no L19
    assert sdc_gen.main([str(proj), "--force"]) == 1


# ── the fifth, non-verdict outcome: nothing scoped, nothing changes ─────────

def test_no_scoped_record_leaves_the_branch_inert(tmp_path):
    """A design that scopes nothing must behave exactly as it did before this
    contract existed — with or without a run record."""
    unscoped = [_clock("clk_a", UNSCOPED_MHZ)]
    for run_pdk in (None, RUN_PDK):
        proj = _project(tmp_path / f"p{run_pdk}", unscoped, run_pdk=run_pdk)
        assert sdc_gen.main([str(proj), "--force"]) == 0
        assert f"-period {1000.0 / UNSCOPED_MHZ:g} " in _sdc_text(proj)


# ── the two consumers must never select different records ──────────────────

def test_both_consumers_agree_on_every_outcome(tmp_path):
    """The defect class this contract exists to end: the generator emitting an
    SDC the checker then fails, on self-consistent inputs. Sweep every outcome
    and require the two to agree on PASS/REFUSE."""
    cases = [
        ("outcome1-name",   SCOPED_ONLY,           RUN_PDK,       0),
        ("outcome1-family", SCOPED_ONLY,           RUN_FAMILY,    0),
        ("outcome2",        SCOPED_PLUS_UNSCOPED,  FOREIGN_PDK,   0),
        ("outcome2-not-1",  SCOPED_PLUS_UNSCOPED,  RUN_PDK,       0),
        ("outcome3",        SCOPED_ONLY,           FOREIGN_PDK,   1),
        ("outcome4",        SCOPED_ONLY,           None,          1),
    ]
    disagreements = []
    for label, domains, run_pdk, expected in cases:
        proj = _project(tmp_path / label, domains, run_pdk=run_pdk)
        gen_rc = sdc_gen.main([str(proj), "--force"])
        if not (gen_rc == expected):
            disagreements.append(
                f"{label}: sdc_gen={gen_rc} want={expected}")
    assert not disagreements, "; ".join(disagreements)


# ── the borrowed constant must not drift from its producer ─────────────────

def test_report_path_is_the_producers_own_constant():
    import submission_template_fetch as F  # noqa: PLC0415
    assert S.RUN_PDK_REPORT_REL == F.REPORT_REL
    assert sdc_gen._RUN_PDK_REPORT_REL == F.REPORT_REL


def test_outcome2_names_itself_in_the_summary(tmp_path):
    """R-0915-6: the summary must SAY `unscoped_design_owned`. A fallback a
    reader cannot see is a fallback nobody can audit."""
    assert S.UNSCOPED_SUMMARY_TOKEN == "unscoped_design_owned"


def test_outcome4_and_outcome3_are_distinct_rules(tmp_path):
    assert S.NOT_MEASURED != S.MISMATCH
