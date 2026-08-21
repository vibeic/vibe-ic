"""v0.2.90 — #455: analog-datasheet Phase-1 extraction (the A-track
stub cascade's root feeder).

The u_hawaii-shaped pure-analog datasheet exposed three D1 gaps:
  1. pin hallucination: ALL-CAPS prose words ("ONLY") promoted to
     pin_table while the REAL banked pins (`IN1..IN6`, `OUT1..OUT6`,
     `CK4/CK5/CK6`, `VHI`/`VLO`) were missed;
  2. ic_name truncation (EE628 picked from a substring mention while
     the frontmatter declared the chip name);
  3. L5 spec all null — the per-block `| Spec | Target | Range |`
     tables were never structured, so the A-track had nothing to
     verify and degraded to stubs (#434 upstream cause).

Pins, on a u_hawaii-SHAPED synthetic fixture (no real chip names):
  * banked ranges expand (IN1..IN6 → 6 pins; CK4/CK5/CK6 → 3);
  * ALL-CAPS prose words denied; uncorroborated acronyms denied;
    backtick-corroborated supplies kept;
  * frontmatter `ic:` declaration wins ic_name;
  * spec-table structurer yields typed rows (≥/≤/range coercion)
    and gen_l5-level attach matches block tokens.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase1_doc_one_shot_runner as P1  # noqa: E402

_DATASHEET = """\
---
layer: L1
ic: example_array_adc
---
# Example array ADC front-end

## Product
| Field | Value |
|---|---|
| design origin | github.com/example/XY999 — reference ONLY (not an input) |

## Externally-observable interface (per the chip's top pins)
- Analog inputs `IN1..IN6` (PAD), differential referenced to `VHI`/`VLO`.
- Digital serial outputs `OUT1..OUT6`, modulator clocks `CK4/CK5/CK6`.
- Supplies `IOVDD` (1.8 V), `CORE` (1.2 V); `VLDO`/`VREF` for the LDO channel.
"""

_L5_DOC = """\
# L5 — Analog Spec

## Block A — `delta_sigma` : incremental delta-sigma modulator (×6)
| Spec | Target | Range | Unit | Note |
|---|---|---|---|---|
| OSR | 256 | 64–512 | — | oversampling ratio |
| ENOB | ≥ 14 | ≥ 10 | bit | effective resolution |
| fclk | 1.0 | 0.1–10 | MHz | modulator clock |

## Block B — `ldo` : low-dropout regulator
| Spec | Target | Range | Unit | Note |
|---|---|---|---|---|
| Vout | 1.2 | 1.1–1.3 | V | regulated core |
| Dropout | ≤ 0.5 | — | V | headroom |
| PSRR | ≥ 40 | ≥ 40 | dB | supply rejection |
"""


# ── pins ────────────────────────────────────────────────────────────────────

def test_banked_ranges_expand():
    assert P1._v455_expand_pin_token("IN1..IN6") == [
        "IN1", "IN2", "IN3", "IN4", "IN5", "IN6"]
    assert P1._v455_expand_pin_token("CK4/CK5/CK6") == ["CK4", "CK5", "CK6"]
    assert P1._v455_expand_pin_token("OUT1-OUT6")[0] == "OUT1"
    assert P1._v455_expand_pin_token("IN[1:3]") == ["IN1", "IN2", "IN3"]
    assert P1._v455_expand_pin_token("RESET") == ["RESET"]


def test_interface_pins_extracted_with_ranges():
    pins = P1._v455_interface_pins({"a.md": _DATASHEET})
    names = {p["name"] for p in pins}
    assert {"IN1", "IN6", "OUT1", "OUT6", "CK4", "CK6",
            "VHI", "VLO", "IOVDD", "CORE", "VLDO", "VREF"} <= names
    by = {p["name"]: p for p in pins}
    assert by["IN1"]["mode"] == "input"
    assert by["OUT1"]["mode"] == "output"


def test_allcaps_prose_pin_denied_and_real_pins_merged():
    fake = [{"name": "ONLY", "mode": "unspecified"},
            {"name": "LDO", "mode": "unspecified"},
            {"name": "IOVDD", "mode": "unspecified"}]
    out = P1._v455_sanitize_and_merge_pins(fake, {"a.md": _DATASHEET})
    names = {p["name"] for p in out}
    assert "ONLY" not in names          # ALL-CAPS English prose
    assert "LDO" not in names           # uncorroborated acronym
    assert "IOVDD" in names             # backtick-corroborated supply
    assert "IN3" in names and "CK5" in names   # banked merge


# ── ic_name frontmatter tier ────────────────────────────────────────────────

def test_frontmatter_ic_declaration_wins():
    name = P1._ic_name_from_docs({"a.md": _DATASHEET})
    assert name == "example_array_adc"


# ── L5 spec-table structurer ────────────────────────────────────────────────

def test_block_spec_tables_structured():
    tables = P1._v455_parse_block_spec_tables({"l5.md": _L5_DOC})
    assert set(tables) == {"delta_sigma", "ldo"}
    ds = {r["name"]: r for r in tables["delta_sigma"]["specs"]}
    assert ds["OSR"]["target"] == 256.0
    assert ds["OSR"]["min"] == 64.0 and ds["OSR"]["max"] == 512.0
    assert ds["ENOB"]["min"] == 14.0
    ldo = {r["name"]: r for r in tables["ldo"]["specs"]}
    assert ldo["Dropout"]["max"] == 0.5
    assert ldo["PSRR"]["min"] == 40.0
    assert ldo["Vout"]["target"] == 1.2


def test_attach_block_specs_matches_tokens():
    blocks = [{"name": "adc", "type": "delta_sigma", "spec": None,
               "low_confidence": True},
              {"name": "ldo", "type": "ldo", "spec": None,
               "low_confidence": True},
              {"name": "bandgap", "type": "bandgap", "spec": None,
               "low_confidence": True}]
    P1._v455_attach_block_specs(blocks, {"l5.md": _L5_DOC})
    assert blocks[0]["spec"] and blocks[0]["low_confidence"] is False
    assert blocks[1]["spec"]
    assert {r["name"] for r in blocks[1]["spec"]["specs"]} == {
        "Vout", "Dropout", "PSRR"}
    assert blocks[2]["spec"] is None    # no table → stays honest null
