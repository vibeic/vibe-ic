# tests/fixtures/real_benchmark/

Hand-extracted, license-clean slices of real-world IC documentation
shapes. Each fixture in this directory is named for the **shape class**
it exercises, and links back to the GitHub issue that proved that
shape was missing from prior synthetic-only tests.

## Why this exists (v1.6.593, for #401)

4 consecutive plugin releases (v1.6.576 / .583 / .589 / .591) shipped
with 100% local unit-test PASS but FAILed real-benchmark verification.
In every case the root cause was the same: the unit-test fixture used
the **minimal synthetic shape** the feature author imagined, never the
**real-world shape** the benchmark uses for visual emphasis,
prose-adjacency overwrite, pipeline-stage interaction, or downstream
merge field-strip.

Adding a fixture here when you write a new walker / regex / merge
patch costs ~5 lines. Catching the bug at unit-test stage costs ~5
lines plus 1 minute. Missing it costs an extra core-agent + field-agent
verification cycle (≈30-60 minutes wall time + 1 plugin release).

## Naming convention

```
<shape_class>_<feature_anchor>.<ext>
```

Where `<shape_class>` is a generic structural label (no chip-class
literal in the filename, since the deny-list test would catch it).
`<feature_anchor>` is the walker / regex / merge layer it targets.

Examples (generic — no chip names):

- `csr_block_with_visual_padding_delimiter.adoc` — AsciiDoc block
  delimiter with 23 equals (the shape that broke #392 R1/R2).
- `csr_body_block_with_symbolic_reset.adoc` — body block whose
  Reset value is `DEFINED, according to enabled ...` (the shape
  that broke #399 R1).
- `mmio_register_set_pipeline_late_overwrite.md` — fixture that
  causes `_v1_6_503_lift_scalar_reset_from_prose` to overwrite an
  earlier-classified `reset_value`, exercising the late-walker
  reclassify gate (the shape that broke #400 R1).

## Usage

```python
from tests.conftest import load_real_fixture

def test_v1_6_NEW_walker_handles_real_shape():
    src = load_real_fixture("csr_block_with_visual_padding_delimiter.adoc")
    blocks = list(_V1_6_NEW_RE.finditer(src))
    assert blocks, "real visual-padding shape must match"
```

For pipeline / merge / propagation patches that touch
`gen_l4_regmap`, use an e2e test that calls `gen_l4_regmap` directly
rather than asserting walker-internal output. Walker output PASS is
necessary but NOT sufficient — the field strip / cherry-pick / pipeline-
order bugs only surface end-to-end.

## chip-AGNOSTIC

Every fixture in this directory must be chip-AGNOSTIC: no EXAMPLE_CHIP /
EXAMPLE_PROTOCOL / EXAMPLE_TESTER / cv32e40p / ibex / picorv32 / darkriscv / neorv32 / serv
/ vexriscv / example_university / mychip / examplesoc / benchmark_a / example_vendor string
literals. Where a fixture is conceptually derived from one IC's docs,
the names + numbers are generic-ised (e.g. `0x300` is a generic CSR
address, not specifically RV machine-mode mstatus). The
`test_v1_6_593_*` chip-AGNOSTIC guard scans fixtures alongside source.
