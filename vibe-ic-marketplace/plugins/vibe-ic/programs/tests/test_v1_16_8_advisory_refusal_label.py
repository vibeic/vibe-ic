"""The evidence line said `enforcement=BLOCKING` for clauses that gate nothing.

`_advisory_execution_record` derived the word from the program's own rc and
never read how the clause was wired, so three refusing `advisory_program_exit_
zero` gates inside step D1 (`l_doc_cross_consistency_check`, `spec_review_lint`,
`integration_spec_audit`) printed BLOCKING while none of them flipped D1's
verdict. Two acceptance rounds and one lane brief named them as the halt.
Bidirectional: a two-source advisory refusal must stop reading BLOCKING, and a
refusal that DOES gate the step must keep reading BLOCKING."""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

# Wired advisory in the canonical flow AND self-declared advisory in its module
# docstring; measured at v1.16.8, this is the D1 trio's shape.
ADVISORY_GATE = "integration_spec_audit"


def _record(tmp_path, gate):
    import flow_compliance_check as fcc
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    return fcc._advisory_execution_record(
        f"{gate} .", len(fcc._GATE_LEDGER), False, "some findings", proj, None)


def test_the_gate_under_test_really_is_two_source_advisory():
    """Guard the premise: if this stops being true the two tests below become
    vacuous rather than false."""
    import flow_compliance_check as fcc
    assert fcc._gate_is_two_source_advisory(ADVISORY_GATE) is True


def _printed_label(rec):
    """What the audit's GATE EVIDENCE line prints. On a tree without the fix
    the helper is absent and the line printed the raw field, so falling back to
    it keeps this a VALUE test on both trees, never an AttributeError."""
    import flow_compliance_check as fcc
    fn = getattr(fcc, "_clause_enforcement_label", None)
    return str(fn(rec)) if fn else str(rec.get("enforcement"))


def test_advisory_refusal_does_not_read_as_blocking(tmp_path):
    """The load-bearing red."""
    rec = _record(tmp_path, ADVISORY_GATE)
    assert rec["verdict"] == "FAIL", rec
    assert "BLOCKING" not in _printed_label(rec), _printed_label(rec)
    assert "ADVISORY_REFUSAL" in _printed_label(rec), _printed_label(rec)


def test_a_refusal_that_does_gate_still_reads_blocking(tmp_path):
    """Over-reach control, and it must pass on BOTH trees. A gate wired
    advisory that still declares ITSELF blocking is a real disagreement: it
    denies the step its tier, and the label must keep saying so."""
    import flow_compliance_check as fcc
    blocking = next(
        g for g in ("spec_conformance_check", "flow_compliance_check",
                    "l4_regmap_emitter_contract_check")
        if not fcc._gate_is_two_source_advisory(g))
    rec = _record(tmp_path, blocking)
    assert _printed_label(rec) == "BLOCKING", rec


def test_the_rc_derived_field_is_still_published(tmp_path):
    """The consumer that stands the refusal down reads `enforcement`, and
    landed tests pin this record's exact dict shape. The label is DERIVED, not
    stored. Passes on both trees by design."""
    rec = _record(tmp_path, ADVISORY_GATE)
    assert rec["enforcement"] == "BLOCKING", rec
    assert "clause_enforcement" not in rec, rec
    assert "gates_step" not in rec, rec
