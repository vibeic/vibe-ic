# Compliance Testing Strategy — three layers, not one

## The trap we avoided

A naive single-layer `test_good_output_passes_all_required` per skill forces
the test generator to BOTH (a) exercise the compliance engine, AND (b)
synthesise a markdown document that satisfies every required regex. Those
two goals pull in opposite directions: the compliance engine wants tight
patterns, the fixture synthesiser wants loose literal text. As patterns get
more structured (markdown headings, tables, SVA blocks), the synthesiser
cannot keep up, and every test ends in either a false PASS (accepting bad
output) or a silent SKIP. v0.50 audit caught 59/64 skills in the SKIP
state — not because the plugin was broken, but because the test generator
was naive about what "generate good output" means.

The fix is not a smarter generator. It's decoupling fixture quality from
gate correctness.

## Three layers

### Layer 1 — Compliance Engine

**Question**: given an output + compliance.yaml, does the engine correctly
identify missing required elements?

**Test**: feed the engine a known-bad input (empty file, a real Unicode
mix) and a known-good input. Assert engine verdict matches expectation.
This is entirely independent of per-skill pattern complexity.

**Location**: `_shared/test_compliance_engine.py`.

### Layer 2 — Pattern Validity

**Question**: does each regex in each compliance.yaml actually compile,
and does it match what the skill author INTENDED (a small positive
sample) and NOT match what they DID NOT intend (a small negative sample)?

**Test**: parametric across every yaml; requires authors to supply
`positive_sample` and `negative_sample` strings per requirement (short
and focussed, usually one line each).

**Location**: `_shared/test_compliance_patterns.py`.

### Layer 3 — Integration / Golden Fixture

**Question**: for the ~8 critical gatekeeper skills (spec-to-rtl,
integration-spec-gen, flow-orchestrate, phase1-orchestrate,
tapeout-checklist, datasheet-gen, rtl-review, testbench-gen), does a
realistic full-markdown fixture pass all requirements end-to-end?

**Test**: hand-written golden fixtures per skill, run through the
compliance engine with strict PASS expectation. These are the skills
whose failure breaks the whole flow; worth the maintenance cost.

**Location**: `_shared/integration_fixtures/<skill>.md` + a shared
driver test.

## Testability tagging

Each compliance.yaml carries a top-level field:

```yaml
testability: simple | structured | full_markdown
```

- `simple` — patterns are literal keywords or simple alternations the
  auto-fixture can synthesise. Layer 1 + Layer 2 suffice; no Layer 3
  needed. The auto `test_good_output_passes_all_required` runs and
  passes for these.
- `structured` — patterns reference markdown headings, SVA constructs,
  tables, or code blocks. Auto-fixture SKIPs Layer 3 with an explicit
  marker; Layer 2 pattern validity still runs.
- `full_markdown` — critical gatekeeper skill. A hand-written fixture
  lives under `_shared/integration_fixtures/<skill>.md`; a dedicated
  integration test runs it through the engine and asserts full PASS.

## What a regression looks like per layer

| Symptom | Affected layer | Fix |
|---------|---------------|-----|
| New skill ships with non-compiling regex | L2 | skill owner fixes the regex |
| Existing skill's regex breaks on real output | L2 | update positive_sample to current spec, then fix regex |
| Engine miscategorises a requirement as satisfied | L1 | engine bug, debug `skill_compliance_check.py` |
| Critical skill's full-flow output stops satisfying spec | L3 | golden fixture fails → either fix skill or update fixture |

## Why this is better than "auto-generate 63 golden fixtures"

- 63 hand-written files × every spec change is a maintenance sink.
- False confidence: fixture may match regex but not reflect real agent
  output, so passing L3 for a non-critical skill proves nothing useful.
- The L2 regex unit test is tighter: it tests WHAT the regex is meant
  to match (positive sample) and WHAT it must reject (negative sample),
  which is exactly what most compliance checks need — no more.

## Why we still keep Layer 3 for the top-8 skills

Those skills are the ones that, if the compliance.yaml drifts out of
sync with the actual skill output, break the downstream flow (RTL
generation blocked, tapeout refused). For them the extra hand-fixture
cost is justified as continuous verification that the engine + spec +
realistic output still agree end-to-end.

## HARD RULE — always run the FULL suite (both test trees)

The plugin has **two** test trees and a valid run includes **both**:

- `programs/tests/` — unit tests for the deterministic programs.
- `tests/` — integration / regression **gates**: `INDEX.md` freshness
  (every non-helper program registered), every-skill-has-`compliance.yaml`
  + `tests/test_compliance.py`, orchestrator input-branch regressions, and the
  end-to-end skill audit.

`pytest.ini` pins `testpaths = programs/tests tests`, so **bare `pytest` from the
plugin root runs both**. NEVER validate a change with only `pytest programs/tests/`
(or only `tests/`): it silently skips the other tree. This is not hypothetical — an
orchestrator fix once reached `main` green because it was verified against
`programs/tests/` alone, while the matching regression test in `tests/` was never run.

Corollary for new code: a new **program** must be added to `programs/INDEX.md`
(`tools/gen_programs_index.py`); a new **skill** must ship `compliance.yaml` +
`tests/test_compliance.py` (`_shared/bootstrap_compliance.py` +
`_shared/gen_compliance_tests.py`). The `tests/` gates fail until you do.
