# Spec Validator — PRACTICAL_NOTES

> Source: 135-IC v2 Campaign Regression (2026-04-09 ~ 04-10)
> Version: v0.25

---

## 1. Overview

In the 135-IC campaign, Spec Validator ran Datasheet quality scoring (ds_quality_check.py), Application Note scoring (an_validator.py), and cross-document consistency check (spec_validator.py). Most ICs had Phase 1 documents generated in batch by AI Agents, so quality is consistent but exhibits specific systematic issues.

---

## 2. Datasheet quality-score distribution

In this campaign, 125+ of the 135 ICs produced `04_datasheet.md`.

| Score range | IC count | Share | Notes |
|----------|:-----:|:----:|------|
| 90-100 | ~5 | 4% | full 10 sections, all tables present |
| 80-89 | ~25 | 20% | missing minor details (e.g. timing diagram) |
| 70-79 | ~60 | 48% | **most common**: meets threshold (>=70) but lacks depth in 1-2 sections |
| 60-69 | ~20 | 16% | below threshold, needs reinforcement |
| <60 | ~15 | 12% | mostly SoC/BMC, datasheet structure does not fit |

**Checkpoint 1 threshold: DS >= 70/100**

**First-pass rate**: ~72% (~90/125 ICs meet threshold on first attempt).

### Most-deducted criteria

| Rank | Criterion | Avg score | Deduction reason |
|:----:|-----------|:--------:|----------|
| 1 | Timing Diagrams (Criterion 7) | 4.2/10 | AI-generated ASCII timing diagrams have unstable quality |
| 2 | Block Diagram (Criterion 8) | 5.5/10 | block diagrams of complex ICs are over-simplified |
| 3 | Application Information (Criterion 10) | 5.8/10 | schematics and component values are not concrete enough |
| 4 | Electrical Characteristics (Criterion 6) | 6.5/10 | AC specs frequently omitted |

### Easiest criteria to score full marks

| Rank | Criterion | Avg score |
|:----:|-----------|:--------:|
| 1 | Features (Criterion 1) | 9.2/10 |
| 2 | Description (Criterion 2) | 8.8/10 |
| 3 | Pin Configuration (Criterion 3) | 8.5/10 |
| 4 | Detailed Description (Criterion 9) | 7.8/10 |

---

## 3. Application Note quality-score distribution

| Score range | IC count | Share |
|----------|:-----:|:----:|
| 70-80 | ~10 | 8% |
| 56-69 | ~75 | 60% |
| 40-55 | ~30 | 24% |
| <40 | ~10 | 8% |

**Checkpoint 1 threshold: AN >= 56/80**

**First-pass rate**: ~68%.

### Most-deducted criteria

| Criterion | Avg score | Issue |
|-----------|:--------:|------|
| Competitive Comparison (8) | 3.5/10 | often lists only 1-2 competitors; need >=3 |
| PCB Layout (4) | 4.0/10 | lacks concrete layout figure |
| Design Calculations (6) | 4.5/10 | insufficient formulas (need >=3) |

---

## 4. Cross-document consistency-check results

spec_validator.py ran cross-doc comparison on 125+ ICs:

### Most common inconsistencies

| Inconsistency type | Frequency | Severity | Notes |
|-----------|:--------:|:--------:|------|
| Pin name case mismatch | ~30% | WARNING | DS uses `SDA`, AN uses `sda` |
| Register address missing | ~15% | ERROR | AN firmware example references a register not defined in DS |
| TBD/TODO leftovers | ~10% | ERROR | placeholders from generation not replaced |
| Timing parameter missing | ~20% | WARNING | DS has t_setup but AN does not reference it |
| Package pin count mismatch | ~5% | ERROR | DS says 14-pin but AN schematic shows 16-pin |

### Fix cost

- Pin-name case: auto-fix (unify to lowercase)
- Register address: requires manual confirmation and DS register-map patch
- TBD/TODO: search-and-replace (but correct values must be filled in)
- Package mismatch: requires going back to the original spec to confirm

---

## 5. Correlation between IC type and quality

| IC type | Avg DS score | Avg AN score | Notes |
|---------|:----------:|:----------:|------|
| Basic logic (gates, FF) | 78 | 62 | simple structure, AN content is thin |
| I2C/SPI sensors | 75 | 60 | most standard format, stable quality |
| ADC/DAC | 72 | 58 | needs more electrical specs |
| LED/PWM driver | 74 | 61 | application-circuit content is rich |
| Complex SoC | 55 | 42 | 10-section datasheet structure is not a great fit |
| Aspeed BMC | 52 | 38 | needs a dedicated SoC datasheet template |

---

## 6. Known limitations

1. **DS scorer is unfriendly to SoC**: the 10 criteria favour discrete ICs (with pin diagram, package); SoC datasheet structure is fundamentally different
2. **AN scorer's Competitive Comparison does not fit brand-new designs**: if the IC is a brand-new architecture (e.g. RISC-V BMC SoC), there is no direct competitor to compare against
3. **Cross-check does not detect semantic inconsistency**: it only does string comparison, does not understand semantics like "SCL is the I2C clock"
4. **TBD check is too strict**: some TBDs are intentionally retained (e.g. "TBD by customer") and should not be counted as errors

---

## 7. Suggested improvements

1. Add a dedicated SoC scoring template (criteria adapted to CPU architecture, bus matrix, peripheral list, etc.)
2. Add fuzzy matching to cross-check: `SDA` / `sda` / `SDA_PIN` should be treated as the same signal
3. Add an auto-fix function: auto-unify pin-name case, fill in missing TBD values
4. Make AN Competitive Comparison "optional" rather than required to avoid penalising innovative designs
