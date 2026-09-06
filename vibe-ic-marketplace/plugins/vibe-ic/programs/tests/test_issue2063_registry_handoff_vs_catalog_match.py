"""RB2-01 (#2063) — a surviving catalog match overrode the IC class registry's
own declared `fallback_skill`.

`design_one_shot_runner.step_rtl_gen` read
`skill = config.get("fallback_skill") or "spec-to-rtl"` and then, one line
later, `if catalog_matches_summary: skill = "catalog-glue-author"` — so ANY
match at confidence >= 0.4 replaced the registry's declaration. MEASURED on the
subservient cell (lane rbsub2, 8HD-8, 2026-09-06): class `processor_cpu`
declares `spec-to-rtl`, one entry matched, and the WAIVE told the agent to run
`catalog-glue-author`.

The rule: the registry's hand-off stands unless the input docs THEMSELVES name
the matched IP as this design's reuse. Both directions are asserted here, on
one project whose only difference between the arms is that sentence.
"""
import json
import sys
import tempfile
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))


def _project(td: Path, notes: str) -> Path:
    docs = td / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps(
        {"part_name": "widgetcpu"}))
    (docs / "L2_FRS.json").write_text(json.dumps(
        {"cpu_isa": "rv32i", "cpu_arch": "bit-serial", "notes": notes}))
    return td


def _run(notes: str):
    from design_one_shot_runner import step_rtl_gen
    with tempfile.TemporaryDirectory() as td:
        p = _project(Path(td), notes)
        return step_rtl_gen(p, "processor_cpu")


def test_registry_handoff_survives_an_undeclared_catalog_match():
    res = _run("A minimal bit-serial rv32i core, authored for this tapeout.")
    assert res.status == "WAIVED"
    assert res.extras.get("fallback_skill") == "spec-to-rtl"
    assert res.extras.get("ip_catalog_declared_reuse") == []
    assert "`spec-to-rtl`" in str(res.detail)


def test_a_match_the_docs_declare_as_reuse_does_redirect_the_handoff():
    """The other direction, so the rule is a rule and not a disablement: when
    the input docs name the IP, the glue path IS the right hand-off."""
    res = _run("A minimal bit-serial rv32i core. The serv core is reused "
               "as the CPU; this design only integrates it.")
    assert res.status == "WAIVED"
    if not res.extras.get("ip_catalog_matches"):
        # No catalog on this checkout -> nothing to redirect; the assertion
        # above (registry stands) is the whole contract then. Say so rather
        # than pass silently on an empty population.
        import pytest
        pytest.skip("ip-catalog returned no matches on this checkout")
    assert "serv" in res.extras.get("ip_catalog_declared_reuse", [])
    assert res.extras.get("fallback_skill") == "catalog-glue-author"
