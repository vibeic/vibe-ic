#!/usr/bin/env python3
"""A "golden" that is the design's own earlier read is not a golden.

`regmap_transaction_tb_gen` was written to close vibe-ic#186 part 2, where the
runner's in-pipeline functional evidence was structurally 0 for any register-map
design. On the very cell #186 reported, it scores 12 vectors and reports
`scored_with_golden: 12`.

MEASURED at land time, on that published design: forcing ALL NINE `read_data`
assignments in the RTL to one constant left the score at **12 of 12 PASS**. A
completely dead read path scored exactly as a correct one.

The cause is in one line. `ro_write_ignore` sets `exp = o["r0"]` — the DUT's own
baseline read — and compares it against the post-write read. That is a
SELF-CONSISTENCY oracle. The module docstring claimed every scored vector
"compares a REAL simulated `read_data` against a golden that comes from the
DESIGN DOCUMENTS", which is true of the other class and false of this one.

Why that matters beyond this program: `scored_with_golden` is consumed by
`benchmark_verify_report` and `bit_level_full_stack_tb_check`, whose own
docstrings call it "the ONLY honest measure" of functional verification. So the
12 flowed into the benchmark's headline honesty number.

THE ORACLE IS NOT REMOVED, and that is deliberate. "A write must not change a
read-only register's read-back" is a real property that really does FAIL when
writes leak into read-only address space — a classic address-decoder defect. It
is counted under its OWN name so a reader can see how much of a coverage figure
is self-referential, which is the same repair shape as v1.6.95's
NOT_APPLICABLE_NO_CITATION: the finding was never wrong, the WORD was.

Consequence, stated rather than buried: on that cell `scored_with_golden` goes
12 -> 0. #186 part 2 is therefore NOT closed by this generator, and the issue
should not be closed on its strength.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import bit_level_full_stack_tb_check as B  # noqa: E402


def _results(tmp_path: Path, per_vector: list, fc: dict | None = None) -> Path:
    import json
    d = tmp_path / "sim_full_stack"
    d.mkdir(parents=True, exist_ok=True)
    payload: dict = {"per_vector": per_vector}
    if fc is not None:
        payload["functional_coverage"] = fc
    (d / "results.json").write_text(json.dumps(payload))
    return d


_RO = {"kind": "ro_write_ignore", "expected_bytes": "0x0", "verdict": "PASS"}
_GOLD = {"kind": "rw_storage_fixed_point", "expected_bytes": "0x5",
         "verdict": "PASS"}


def test_the_fallback_does_not_count_a_self_referential_vector(tmp_path):
    """THE LOAD-BEARING CASE. The producer was corrected to exclude these; a
    fallback that counts them re-inflates the very number one line later."""
    d = _results(tmp_path, [dict(_RO), dict(_RO), dict(_RO)])
    assert B.functional_coverage_scored(d) == 0


def test_the_fallback_still_counts_a_document_derived_vector(tmp_path):
    """The paired half — excluding everything would be its own false measure,
    in the opposite direction."""
    d = _results(tmp_path, [dict(_GOLD), dict(_GOLD)])
    assert B.functional_coverage_scored(d) == 2


def test_a_mixed_set_counts_only_the_document_derived_ones(tmp_path):
    d = _results(tmp_path, [dict(_RO), dict(_GOLD), dict(_RO), dict(_GOLD)])
    assert B.functional_coverage_scored(d) == 2


def test_a_placeholder_vector_is_still_not_evidence(tmp_path):
    """The pre-existing rule this must not disturb: `expected_bytes: null` is a
    bring-up placeholder."""
    d = _results(tmp_path, [{"kind": "regmap_probe", "expected_bytes": None},
                            dict(_GOLD)])
    assert B.functional_coverage_scored(d) == 1


def test_an_explicit_functional_coverage_block_still_wins(tmp_path):
    """The fallback is a fallback. When the producer states the number, that
    number is used — the producer is the one that knows its own oracle kinds."""
    d = _results(tmp_path, [dict(_RO)] * 9,
                 fc={"scored_with_golden": 4})
    assert B.functional_coverage_scored(d) == 4


def test_the_producer_splits_the_two_counts():
    """The producer's own contract, asserted on its constant rather than on a
    simulation: the exclusion list must exist and must name the oracle whose
    expected value is the design's own read."""
    import regmap_transaction_tb_gen as G
    src = Path(G.__file__).read_text()
    assert "scored_self_referential" in src
    assert "_SELF_REF_KINDS" in src
    assert "ro_write_ignore" in src
    # ...and the two programs must agree on WHICH kinds are self-referential,
    # or the producer and the fallback drift apart silently.
    assert "ro_write_ignore" in B._SELF_REFERENTIAL_KINDS
