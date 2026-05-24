# Checkpoint Gate — PRACTICAL_NOTES

> Source: 135-IC v2 Campaign (2026-04-09 ~ 04-10)
> Version: v0.25

---

## 1. Overview

Checkpoint Gate is the quality-gate mechanism in the Vibe-IC flow, organised into three checkpoints:

| Checkpoint | Transition | Threshold |
|:----------:|------|------|
| CP1 | Phase 1 → Phase 2 | DS >= 70, AN >= 56, 0 ERROR mismatch |
| CP2 | Phase 2 → Phase 3 | Synth PASS, Cell > 0, SVA >= 8, DRC <= 5 |
| CP3 | Phase 3 → Production | Quartus map/fit/asm/sta PASS, SOF exists |

---

## 2. Origin of the quality-gate thresholds

### DS >= 70/100

- **Rationale**: 10 criteria worth 10 points each; >=70 means at least 7 criteria meet the basic requirement
- **135-IC measurement**: first-pass rate ~72%. The cutoff sits exactly at "has timing diagram but quality is mediocre"
- **Tuning consideration**: lowering to 65 raises pass rate to ~85% but quality drops noticeably (many lack a block diagram); raising to 75 drops pass rate to ~55% and requires too many iterations

### AN >= 56/80

- **Rationale**: 8 criteria worth 10 points each; >=56 = 70% threshold
- **135-IC measurement**: first-pass rate ~68%. Most failures stuck on Competitive Comparison and Design Calculations
- **Known issue**: SoC-class AN structure differs greatly from discrete ICs; recommend adding a SoC template in the future

### SVA >= 8

- **Rationale**: at least 8 assertions are needed to cover core functionality
- **135-IC measurement**: average SVA count 9.2, min 2, max 20
- **Observation**: the 2-SVA cases were extremely small logic ICs (e.g. buffer) that genuinely have only 2 testable properties
- **Recommendation**: keep >=8 as the universal threshold but allow a "small-IC waiver" (threshold drops to >=4 when cell < 10)

---

## 3. Pass rates in the 135-IC campaign

### Checkpoint 1 (Phase 1 → Phase 2)

| Metric | First attempt | After fix |
|------|:---------:|:------:|
| DS >= 70 | 72% (90/125) | 92% (after 1 fix round) |
| AN >= 56 | 68% (85/125) | 88% (after 1-2 fix rounds) |
| 0 ERROR mismatch | 75% | 95% (after pin-name unification) |
| **CP1 full pass** | **~55%** | **~85%** |

**Average fix rounds**: 1.3. Most ICs pass after a single fix.

### Characteristics of ICs that pass without fixes

- I2C/SPI sensors (standard structure; AI easily generates high-quality DS/AN)
- Basic logic (simple function, criteria easy to meet)
- Designs with an existing reference IC (e.g. TMP117 referencing LM75)

### Characteristics of ICs that need 2+ fix rounds

- Complex SoCs (AST2700, RISC-V BMC SoC)
- Multifunction mixed ICs (SC16IS750: I2C + SPI + UART + GPIO)
- Brand-new architecture ICs (no reference)

### Checkpoint 2 (Phase 2 → Phase 3)

| Metric | Result |
|------|:----:|
| Synth PASS (0 error) | 82% (111/135) |
| Cell count > 0 | 92% (124/135) |
| SVA >= 8 | 78% (105/135) |
| DRC <= 5 | ~95% (among ICs that have a DRC report) |
| **CP2 full pass** | **~70%** |

Most common causes of CP2 failure:
1. Synth FAIL (MULTI_DRIVER issue, requires synth-doctor to repair)
2. Insufficient SVA count (small ICs or SoCs are hard to write assertions for)

---

## 4. Observations from real operation

### 4.1 The "grey zone" of thresholds

Some ICs land at DS scores of 68-72 — the "may or may not pass" grey zone. These ICs are typically:
- Timing-diagram quality is unstable (sometimes AI-generated ASCII art is incomplete)
- Block diagram exists but is over-simplified

**Recommendation**: in the future add a "conditional pass" mechanism that lets 68-70-point ICs pass with an attached improvement commitment.

### 4.2 False positives (passed but should not have)

About ~3% of ICs passed CP1 but some DS sections were AI hallucinations (inaccurate electrical specs). The current scorer only checks "is the structure present" and does not verify "are the values correct".

**Recommendation**: add a plausibility check in the future (e.g. is the voltage range reasonable).

### 4.3 False negatives (should have passed but did not)

About ~5% of ICs lost points on formatting issues (e.g. slight Markdown table differences) even though their content quality was fine.

**Recommendation**: improve parser tolerance.

---

## 5. Known limitations

1. **CP3 not yet validated at scale**: only CD4013B has gone end-to-end through Quartus compile + SOF generation
2. **CP1 threshold unfair to SoC**: the 10-section DS structure is not a fit for SoCs
3. **SVA >= 8 is too strict for trivial ICs**: an AND gate cannot have 8 meaningful assertions written for it
4. **Timing closure not checked**: CP2 only looks at synth/DRC, not whether timing is met
5. **Human-review workload**: checkpoint reports for 135 ICs require manual spot-check

---

## 6. Suggested improvements

1. Add IC-complexity-tiered thresholds: Simple (<50 cells) / Medium (50-10K) / Complex (>10K)
2. Add timing check to CP2: read WNS (Worst Negative Slack) from the STA log
3. Add BIST pass-rate check to CP3: not just SOF existence but also BIST result
4. Add auto-escalation: CP failure automatically triggers the matching repair skill
5. Add historical-trend chart to checkpoint reports: track each IC's quality over time
