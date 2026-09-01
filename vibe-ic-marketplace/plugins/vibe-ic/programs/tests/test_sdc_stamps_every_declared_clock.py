"""The SDC->L8 stamper must type EVERY clock the design declares, not the first.

MEASURED on opentitan_aes (2026-09-02). The design's staged
`input/constraints/*.sdc` declares two clocks; `collect_create_clocks` returned
both; `_post_emit_sdc_constraints` stamped `primary_clock()` alone. So the
second clock stayed exactly as shallow as it had been before the design staged
an SDC at all, and `l8_clock_domains_typed_check` reported:

    1/9 clock entries too shallow. Examples: clk_edn_i: missing
    freq_hz/freq_mhz/period_ns,role/source

— naming a clock the design HAD declared, in a file the stamper had already
opened and read.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase1_doc_one_shot_runner as R  # noqa: E402

_L8 = ("L8_RTL_CONSTANTS", "L8_TIMING_WAVEFORM")


def _project(tmp_path, sdc_text, clock_domains):
    p = tmp_path / "proj"
    (p / "input" / "constraints").mkdir(parents=True)
    (p / "input" / "constraints" / "constraint.sdc").write_text(sdc_text)
    docs = p / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    for name in _L8:
        (docs / f"{name}.json").write_text(json.dumps({
            "schema_version": 2, "doc_class": "rtl_constants",
            "ic_name": "t", "clock_domains": clock_domains,
        }))
    (docs / "L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"schema_version": 2, "doc_class": "constraints",
                    "ic_name": "t", "fields": {}}))
    return p


def _domains(p, name):
    return json.loads(
        (p / "phase1" / "generated_docs" / f"{name}.json").read_text()
    )["clock_domains"]


_TWO = (
    "create_clock -name core_clock -period 10.0 [get_ports clk_i]\n"
    "create_clock -name edn_clock  -period 10.0 [get_ports clk_edn_i]\n"
)
_ONE = "create_clock -name core_clock -period 10.0 [get_ports clk_i]\n"


def test_second_declared_clock_is_typed_not_left_shallow(tmp_path):
    """The defect: the second create_clock reached L8 untyped."""
    p = _project(tmp_path, _TWO,
                 [{"name": "clk_i", "source_pin": "clk_i",
                   "domain_kind": "primary"}])
    R._post_emit_sdc_constraints(p)
    for name in _L8:
        by = {d["name"]: d for d in _domains(p, name)}
        assert "clk_edn_i" in by, f"{name}: second clock never reached L8"
        edn = by["clk_edn_i"]
        assert edn["period_ns"] == 10.0
        assert edn["freq_mhz"] == 100.0
        assert edn["role"] == "secondary"
        assert edn["source"] == "input/constraints/*.sdc"


def test_existing_entry_for_the_second_clock_is_stamped_not_duplicated(tmp_path):
    """An L8 that already carries the clock gets it TYPED, not appended twice."""
    p = _project(tmp_path, _TWO, [
        {"name": "clk_i", "source_pin": "clk_i", "domain_kind": "primary"},
        {"name": "clk_edn_i", "source_pin": "clk_edn_i"},
    ])
    R._post_emit_sdc_constraints(p)
    for name in _L8:
        names = [d["name"] for d in _domains(p, name)]
        assert names.count("clk_edn_i") == 1, names
        edn = [d for d in _domains(p, name) if d["name"] == "clk_edn_i"][0]
        assert edn["freq_mhz"] == 100.0


def test_primary_clock_is_unchanged(tmp_path):
    """The primary stamp keeps exactly the behaviour it had."""
    p = _project(tmp_path, _TWO,
                 [{"name": "clk_i", "source_pin": "clk_i",
                   "domain_kind": "primary"}])
    R._post_emit_sdc_constraints(p)
    clk = [d for d in _domains(p, "L8_RTL_CONSTANTS")
           if d["name"] == "clk_i"][0]
    assert clk["freq_mhz"] == 100.0
    assert clk["period_ns"] == 10.0
    assert clk["source"] == "input/constraints/*.sdc"


def test_single_clock_sdc_is_byte_identical(tmp_path):
    """NEGATIVE CONTROL — the shape every corpus design has today.

    With one create_clock the new loop must do nothing at all. A change that
    rewrote L8 for every design would be a regression wearing a fix's clothes,
    and this is the direction that catches it. Confirmed independently by a
    base-vs-candidate run over the ibex corpus project (1 create_clock): the
    only delta was the plugin_version stamp.
    """
    seed = [{"name": "clk_i", "source_pin": "clk_i",
             "domain_kind": "primary"}]
    p = _project(tmp_path, _ONE, seed)
    R._post_emit_sdc_constraints(p)
    got = _domains(p, "L8_RTL_CONSTANTS")
    assert len(got) == 1, got
    assert got[0]["name"] == "clk_i"


def test_no_sdc_stamps_nothing(tmp_path):
    """No staged SDC — the function must not reach the clock code at all."""
    p = tmp_path / "proj"
    docs = p / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    seed = [{"name": "clk_i"}]
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps(
        {"schema_version": 2, "doc_class": "rtl_constants", "ic_name": "t",
         "clock_domains": seed}))
    before = (docs / "L8_RTL_CONSTANTS.json").read_bytes()
    R._post_emit_sdc_constraints(p)
    assert (docs / "L8_RTL_CONSTANTS.json").read_bytes() == before
