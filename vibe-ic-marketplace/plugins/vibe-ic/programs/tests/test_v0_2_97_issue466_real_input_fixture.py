"""v0.2.97 — ORGANIC-20260606 #466 R3 (REOPENED a SECOND time;
field-agent SECOND counter-evidence) — REAL-input acceptance.

The R2 fix (test_v0_2_96_issue466_spurious_block.py) used a SYNTHETIC
fixture that made the converter acronym appear ONLY inside the product
H1 / SKU and nowhere else as free-standing prose. The field agent's
second round proved that is exactly the shape real L1 datasheets do NOT
have: a chip whose product IS named by a converter acronym has
FREE-STANDING prose occurrences of that acronym describing the chip as
a whole ("…-ADC front-end"). The R2 guard
(`_v466_evidence_is_product_name_only`) then saw those prose mentions
as independent non-SKU evidence and KEPT the spurious block — so for
such a chip the guard could never fire and `gen_l5_adi_spec` emitted 3
blocks (a spurious converter-acronym block survived;
`spurious_analog_blocks` was empty).

R3 replaces the SKU-embedding test with an L5 BLOCK-LAYER evidence
test: a candidate whose spec==null survives ONLY if its keyword has
evidence at the designable-block layer — a markdown ``## … Block …``
heading or a spec-table block-type row naming it. A converter acronym
that lives only in L1 product-narrative prose (plus the SKU), with NO
L5 Block heading and NO spec-table block-type row, has zero block-layer
evidence → spurious / excluded.

ACCEPTANCE (tightened by the field agent): the self-test MUST use the
REAL benchmark input docs as fixture and assert EXACTLY 2 blocks.

DENY-LIST DISCIPLINE: the real project's name token is in
``programs/tests/chip_deny_list.txt`` and the source guard scans
``programs/``. So this test NEVER writes a denied literal — it
DISCOVERS the real input docs dynamically/structurally by globbing
``benchmark_clean/*/input/docs/L5_ANALOG_SPEC.md`` (repo root resolved
robustly by walking up for a ``benchmark_clean`` dir), selecting the
project whose L5 has an explicit two-block-type enumeration AND whose
sibling ``L1_DATASHEET.md`` product narrative carries a free-standing
converter acronym OUTSIDE any Block heading. It ``pytest.skip``s
honestly when no such project exists on disk (dormant-test discipline),
and ALSO keeps a synthetic free-standing-prose fixture so the guard is
pinned even where the benchmark dir is absent.
"""
import json
import re
import sys
from pathlib import Path

import pytest

_THIS = Path(__file__).resolve()
_PLUGIN_ROOT = _THIS.parent.parent.parent          # …/plugins/vibe-ic
sys.path.insert(0, str(_PLUGIN_ROOT / "programs"))
import phase1_doc_one_shot_runner as P1  # noqa: E402


# ── structural converter-acronym vocabulary (NOT a denied literal) ──
# The data-converter analog class whose acronym commonly DOUBLES as a
# product-family name. Pure open-standard analog vocabulary; no chip /
# vendor / SKU literal. Mirrors the `adc`/`dac` keyword families.
_CONVERTER_ACRONYM_RE = re.compile(
    r"\b(ADC|DAC)\b|\banalog[\s\-]?to[\s\-]?digital\b|"
    r"\bdigital[\s\-]?to[\s\-]?analog\b",
    re.IGNORECASE)


def _candidate_benchmark_dirs() -> list:
    """Every ``benchmark_clean`` dir on the ancestor chain from the
    plugin root up to the filesystem root. The marketplace nesting means
    a (possibly empty) ``benchmark_clean`` can exist at the plugin root
    AND the real one lives at the actual repo root (~3 parents up). We
    resolve by STRUCTURE, not a hard-coded parent count, and search all
    of them so whichever holds the real input docs is found."""
    seen = set()
    out = []
    for cand in [_PLUGIN_ROOT, *_PLUGIN_ROOT.parents]:
        bench = cand / "benchmark-data" / "ic"
        if bench.is_dir() and bench not in seen:
            seen.add(bench)
            out.append(bench)
    return out


def _line_of(text: str, pos: int) -> str:
    ls = text.rfind("\n", 0, pos) + 1
    le = text.find("\n", pos)
    if le < 0:
        le = len(text)
    return text[ls:le]


def _l5_enumerates_two_block_types(l5_text: str) -> bool:
    """True iff L5 explicitly enumerates the analog block types
    (a count statement OR ≥2 distinct ``Block <tag>`` headers)."""
    return P1._v466_l5_enumerates_block_types({"L5": l5_text})


def _l1_has_freestanding_converter_acronym(l1_text: str) -> bool:
    """True iff the L1 product narrative carries a converter acronym on a
    line that is NOT a markdown Block heading — i.e. the acronym
    describes the PRODUCT as a whole, the exact shape that broke the R2
    guard. We require at least ONE such free-standing occurrence."""
    for m in _CONVERTER_ACRONYM_RE.finditer(l1_text or ""):
        line = _line_of(l1_text, m.start())
        if not P1._V466_RE_BLOCK_HEADER_LINE.match(line):
            return True
    return False


def _discover_real_project():
    """Return (l1_text, l5_text, l9_text_or_None) for the first
    benchmark project that matches the field-shaped criteria, or None
    when no such project is on disk. Discovery is purely structural —
    no denied literal appears in this test."""
    for bench in _candidate_benchmark_dirs():
        for l5_path in sorted(bench.glob("*/input/docs/L5_ANALOG_SPEC.md")):
            docs_dir = l5_path.parent
            l1_path = docs_dir / "L1_DATASHEET.md"
            if not l1_path.is_file():
                continue
            try:
                l5_text = l5_path.read_text(encoding="utf-8")
                l1_text = l1_path.read_text(encoding="utf-8")
            except OSError:
                continue
            if not _l5_enumerates_two_block_types(l5_text):
                continue
            if not _l1_has_freestanding_converter_acronym(l1_text):
                continue
            # Collect every sibling L*.md so the run sees the real set.
            all_docs = {}
            for p in sorted(docs_dir.glob("*.md")):
                try:
                    all_docs[p.name] = p.read_text(encoding="utf-8")
                except OSError:
                    continue
            return all_docs
    return None


def _run_gen_l5(tmp_path: Path, docs: dict):
    """Copy `docs` into a fresh project under `tmp_path` and run the REAL
    `gen_l5_adi_spec` end-to-end. Returns (l5_json, block_list)."""
    proj = tmp_path / "chip"
    ddir = proj / "input" / "docs"
    ddir.mkdir(parents=True)
    for name, text in docs.items():
        (ddir / name).write_text(text, encoding="utf-8")
    res = P1.gen_l5_adi_spec(proj, dict(docs))
    l5_json = json.loads(Path(res.path).read_text(encoding="utf-8"))
    blp = P1._pl.analog_dir(proj) / "analog_block_list.json"
    block_list = (json.loads(blp.read_text(encoding="utf-8"))["blocks"]
                  if blp.exists() else [])
    return l5_json, block_list


# ─────────────────── REAL-input end-to-end acceptance ───────────────

def test_real_input_exactly_two_blocks_no_spurious_survivor(tmp_path):
    """ACCEPTANCE (field-agent tightened): run the REAL gen_l5_adi_spec
    on the REAL benchmark input docs. The L5 enumerates two block types;
    the L1 product narrative carries a free-standing converter acronym.
    Assert EXACTLY 2 emitted (non-spurious) blocks; the regulator-class
    block multiplicity ×1; the product-acronym candidate is absent or
    marked spurious:true and excluded from analog_block_list.json."""
    docs = _discover_real_project()
    if docs is None:
        pytest.skip(
            "no benchmark project on disk with an L5 two-block-type "
            "enumeration + an L1 free-standing converter acronym "
            "(dormant-test discipline)")

    l5_json, block_list = _run_gen_l5(tmp_path, docs)

    blocks = l5_json["analog_blocks"]
    # EXACTLY 2 emitted (non-spurious) blocks.
    assert len(blocks) == 2, [b.get("type") for b in blocks]
    types = sorted(b["type"] for b in blocks)
    # The converter-acronym candidate must NOT be among the emitted
    # (sizing-consuming) blocks.
    assert "adc" not in types
    assert "dac" not in types

    # Regulator-class block multiplicity ×1 (own L5 Block heading).
    ldo = [b for b in blocks if b["type"] == "ldo"]
    assert ldo, "expected a regulator-class block in the real fixture"
    assert ldo[0].get("count") == 1
    assert ldo[0].get("multiplicity") == 1

    # The product-acronym candidate is either absent entirely OR present
    # only as spurious:true in the audit surface (never in the live list).
    spurious = l5_json.get("spurious_analog_blocks", [])
    acro = [b for b in spurious if b.get("type") in ("adc", "dac")]
    if acro:
        assert all(b.get("spurious") is True for b in acro)

    # Excluded from the canonical sizing block list.
    bl_types = sorted(b["type"] for b in block_list)
    assert "adc" not in bl_types
    assert "dac" not in bl_types
    assert len(block_list) == 2
    assert bl_types == types


def test_real_input_no_internal_fields_leak(tmp_path):
    """The private #466 bookkeeping keys must never reach the serialised
    real-input L5 doc (analog_blocks OR spurious_analog_blocks)."""
    docs = _discover_real_project()
    if docs is None:
        pytest.skip("no matching benchmark project on disk")
    l5_json, _ = _run_gen_l5(tmp_path, docs)
    for b in (l5_json["analog_blocks"]
              + l5_json.get("spurious_analog_blocks", [])):
        assert "_v466_kw_literal" not in b
        assert "_v466_src_fname" not in b


# ─────────────────── synthetic free-standing-prose pin ──────────────
# Same SHAPE as the real input (synthetic names) so the R3 guard stays
# pinned even where the benchmark dir is absent. The key difference vs
# the R2 synthetic fixture: the converter acronym appears as
# FREE-STANDING product-narrative prose ("delta-sigma ADC front-end",
# "incremental-ADC front-end"), NOT only inside the SKU/H1 — exactly the
# shape that defeated the R2 SKU-embedding guard.

_L1_PROSE = """\
---
layer: L1
ic: gizmo_adc
---

# L1 — Datasheet

## Product
| Field | Value |
|---|---|
| product_name | `gizmo_adc` (GZM900) |
| product_family | mixed-signal incremental delta-sigma ADC front-end |
| one-line | An array of delta-sigma modulator channels; one core supplied by an on-chip LDO. |
| application | sensor/instrumentation incremental-ADC front-end at analog 1.2 V Vref |

## Interface
- Analog inputs referenced to VHI/VLO; on-chip LDO regulator for one core.
"""

_L5_PROSE = """\
---
layer: L5
ic: gizmo_adc
---

# L5 — Analog Spec

This chip has **two analog block types** to design.

## Block A — `delta_sigma` : incremental delta-sigma modulator (×6 copies)
| Spec | Target | Range | Unit |
|---|---|---|---|
| ENOB | 14 | 10-16 | bit |
| Vref | 1.0 | 0.8-1.2 | V |

analog 1.2 V Vref converters.

## Block B — `ldo` : low-dropout regulator (×1, supplies one modulator core)
| Spec | Target | Range | Unit |
|---|---|---|---|
| Vout | 1.2 | 1.1-1.3 | V |
| Dropout | 0.5 | — | V |

analog 1.8 V Vdd supply. (one copy from the LDO)
"""


def test_synthetic_freestanding_prose_drops_converter_acronym(tmp_path):
    """PIN: even when the converter acronym appears as FREE-STANDING
    product-narrative prose (the shape that defeated R2), the R3
    block-layer guard drops it — exactly 2 emitted blocks, regulator
    ×1, the `adc` candidate spurious + excluded from the sizing list."""
    docs = {"L1_DATASHEET.md": _L1_PROSE, "L5_ANALOG_SPEC.md": _L5_PROSE}
    # Sanity: this synthetic fixture really has the field-shaped
    # free-standing prose acronym (not just a SKU-embedded one).
    assert _l1_has_freestanding_converter_acronym(_L1_PROSE)
    assert _l5_enumerates_two_block_types(_L5_PROSE)

    l5_json, block_list = _run_gen_l5(tmp_path, docs)
    blocks = l5_json["analog_blocks"]
    types = sorted(b["type"] for b in blocks)
    assert types == ["delta_sigma", "ldo"], types
    assert len(blocks) == 2
    assert "adc" not in types

    ldo = [b for b in blocks if b["type"] == "ldo"][0]
    assert ldo.get("count") == 1
    assert ldo.get("multiplicity") == 1
    ds = [b for b in blocks if b["type"] == "delta_sigma"][0]
    assert ds.get("count") == 6

    spurious = l5_json.get("spurious_analog_blocks", [])
    assert any(b.get("type") == "adc" and b.get("spurious") is True
               for b in spurious)
    bl_types = sorted(b["type"] for b in block_list)
    assert bl_types == ["delta_sigma", "ldo"]


def test_synthetic_block_layer_evidence_helper():
    """Unit pin for the new R3 helper: the converter acronym has NO
    block-layer evidence (prose-only); ldo / delta_sigma DO (Block
    headings)."""
    extracted = {"L1": _L1_PROSE, "L5": _L5_PROSE}
    assert not P1._v466_has_l5_block_layer_evidence(
        extracted, P1._ANALOG_KEYWORDS["adc"])
    assert P1._v466_has_l5_block_layer_evidence(
        extracted, P1._ANALOG_KEYWORDS["ldo"])
    assert P1._v466_has_l5_block_layer_evidence(
        extracted, P1._ANALOG_KEYWORDS["delta_sigma"])


def test_synthetic_block_layer_multiplicity_helper():
    """Unit pin: the regulator-class Block heading declares ×1; the
    converter-class Block heading declares ×6; a prose-only class
    returns None."""
    extracted = {"L1": _L1_PROSE, "L5": _L5_PROSE}
    assert P1._v466_block_layer_multiplicity(
        extracted, P1._ANALOG_KEYWORDS["ldo"]) == 1
    assert P1._v466_block_layer_multiplicity(
        extracted, P1._ANALOG_KEYWORDS["delta_sigma"]) == 6
    assert P1._v466_block_layer_multiplicity(
        extracted, P1._ANALOG_KEYWORDS["adc"]) is None
