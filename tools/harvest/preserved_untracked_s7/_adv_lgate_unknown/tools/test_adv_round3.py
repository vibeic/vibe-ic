"""ROUND 3 — base reports that PARSE but say nothing, and an A1 that lies rc=0."""
from __future__ import annotations
import pytest
from test_adv_unknown_buys_leniency import _junit, _run, synthetic  # noqa: F401

WRONG_SHAPE = '<?xml version="1.0"?><testsuites></testsuites>'
NOT_JUNIT = '<?xml version="1.0"?><report><ok/></report>'
HTML = '<html><body>500 Internal Server Error</body></html>'


@pytest.mark.parametrize("text", [WRONG_SHAPE, NOT_JUNIT, HTML],
                         ids=["empty-testsuites", "not-junit", "html"])
def test_a_base_report_that_parses_but_says_nothing_is_refused(synthetic, text):
    """Valid-enough bytes that carry NO verdict are the classic 'unknown reads
    as clean' vector: they dodge the ParseError branch entirely."""
    root, base = synthetic
    cp, stamp = _run(root, base, base_junit=text, cand_junit=_junit("skipped"))
    assert cp.returncode != 0, cp.stdout
    assert not stamp.exists()


def test_base_junit_identical_to_the_candidate_is_not_how_the_default_path_works(
        synthetic):
    """Control: base == candidate red means INHERITED, which is the point."""
    root, base = synthetic
    cp, stamp = _run(root, base, base_junit=_junit("failed"),
                     cand_junit=_junit("failed"))
    assert cp.returncode == 0, cp.stdout
    assert "INHERITED  test" in cp.stdout
