"""Routing fix — design_one_shot_runner.step_rtl_gen surfaces the captured-lesson
digest to the spec-to-rtl / catalog-glue author.

A runner-driven (Shape-B) spec-to-rtl author previously got NO lessons (only the
Shape-C benchmark setup rendered lessons.md), so the author re-invented a
genre-DETERMINED topology (e.g. the odd/fractional clock-divider dual-edge-OR
LEVEL form) from the prompt's loose wording and mismatched the golden — even
though the GENERAL recovery was already captured in agents/ic-expert-agent.md.

This pins:
  POSITIVE  — when step_rtl_gen WAIVES to spec-to-rtl (a registered rtl_gen=null
    class), it deterministically writes <project>/phase2/stage1/lessons.md, the
    WAIVE detail tells the author to read it, and extras carries the path+count.
    The digest surfaces the divider topology lesson AND multiple other genres
    (it is the full general corpus, not a divider special-case).
  §4.05 NO-LEAK — the surfaced digest is blindness-clean: it carries NO benchmark
    design identifier (ProbNNN / circuitN / freq_div* / verified_*), so it never
    leaks a design-name->solution association to a blind author. And the scrubber
    does NOT over-scrub general prose (a bare "circuit", "divider", "Problem").
  NO OVER-FIRE — a pure-analog WAIVE (no RTL track) surfaces NO digest.
  BACK-COMPAT — benchmark_dispatch._render_lesson_digest still renders.
"""
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import _lesson_digest  # noqa: E402
import design_one_shot_runner as r  # noqa: E402

# a registered class with rtl_gen=null + fallback_skill=spec-to-rtl
_NULL_RTL_CLASS = "digital_arithmetic_primitive"


def _waive(tmp):
    proj = Path(tmp)
    res = r.step_rtl_gen(proj, _NULL_RTL_CLASS)
    return proj, res


# ── POSITIVE: the WAIVE surfaces the digest ───────────────────────────────────

def test_waive_writes_lessons_digest_and_points_author_at_it(tmp_path):
    proj, res = _waive(tmp_path)
    assert res.status == "WAIVED"
    ex = res.extras or {}
    assert ex.get("fallback_skill") == "spec-to-rtl"
    ld = ex.get("lessons_digest")
    assert ld and Path(ld).is_file(), "digest file not written on WAIVE"
    assert ld.endswith("phase2/stage1/lessons.md")
    assert ex.get("lessons_count", 0) >= 1
    # the WAIVE message MUST direct the author to read+apply the digest
    low = res.detail.lower()
    assert "lessons.md" in low
    assert "mandatory before authoring" in low
    assert "when to apply" in low


def test_digest_surfaces_divider_topology_and_multiple_genres(tmp_path):
    _, res = _waive(tmp_path)
    txt = Path((res.extras or {})["lessons_digest"]).read_text()
    # the divider topology lesson (the routing target) is present...
    assert "clock divider conventions" in txt
    assert "LEVEL form" in txt and "dual-edge" in txt
    # ...alongside OTHER genres -> it is the full GENERAL corpus, not a
    # divider-special-case (so no genre-detection mis-route is possible).
    for marker in ("barrel shifter", "async FIFO", "restoring division"):
        assert marker in txt, f"missing general-corpus genre: {marker!r}"


# ── §4.05 NO-LEAK: blindness-clean (no design-name->solution) ─────────────────

def test_surfaced_digest_has_no_benchmark_design_identifiers(tmp_path):
    _, res = _waive(tmp_path)
    txt = Path((res.extras or {})["lessons_digest"]).read_text()
    import re
    leaks = re.findall(r"\bProb\d+|\bcircuit\d+|\bfreq_div[a-z]+|\bverified_\w+|\bkmap\d+", txt)
    assert leaks == [], f"design-identifier leak in surfaced digest: {set(leaks)}"


def test_scrubber_masks_dataset_ids_but_not_general_prose():
    scrub = _lesson_digest._scrub_design_identifiers
    # masks the leaking identifiers
    for tok in ("freq_divbyodd", "freq_divbyfrac", "Prob098_circuit7",
                "Prob062", "circuit7", "verified_freq_divbyodd", "kmap4"):
        assert tok not in scrub(f"... {tok} ..."), f"not scrubbed: {tok}"
    # §4.05 boundary — does NOT over-scrub legitimate general prose
    for keep in ("a combinational circuit", "the divider remainder",
                 "Problem statement", "frequency divider", "circuit implementation",
                 "freq", "the FIFO"):
        assert keep in scrub(f"x {keep} y"), f"over-scrubbed general prose: {keep}"


def test_scrubber_case_insensitive_and_cvdp_and_breaks_oracle_binding():
    # NON-CIRCULAR adversarial guard (Step-2.7 re-review): the scrubber must not
    # be fooled by case variants or the CVDP cid form, and must BREAK a design→
    # oracle-value association (a value is only a cheat when bound to a NAMED
    # design — strip the name and the value is unusable).
    scrub = _lesson_digest._scrub_design_identifiers
    ph = "a benchmark design"
    # case variants of the structured ids (NOT the literal lower-case patterns)
    for tok in ("PROB099", "Circuit7", "FREQ_DIVBYODD", "Prob042", "KMAP4",
                "Verified_freq_divbyodd"):
        assert tok not in scrub(f"see {tok} here"), f"case-variant not scrubbed: {tok}"
    # CVDP cid
    assert "cvdp_copilot_fifo_0007" not in scrub("cvdp_copilot_fifo_0007 splits")
    # a design→oracle-value sentence: the NAME is removed (binding broken),
    # the standalone value alone is harmless without it
    out = scrub("Prob099 expects output 0xF2 at reset")
    assert "Prob099" not in out and ph in out
    # general words that merely CONTAIN a pattern substring stay intact
    for keep in ("the problem domain", "CVDP harness", "circuit topology",
                 "verified results", "this is a frequency-divider genre"):
        assert keep in scrub(f"z {keep} z"), f"over-scrubbed: {keep}"


# ── NO OVER-FIRE: pure-analog WAIVE (no RTL track) surfaces no digest ─────────

def test_pure_analog_waive_surfaces_no_digest(tmp_path):
    proj = Path(tmp_path)
    res = r.step_rtl_gen(proj, "pure_analog")
    assert res.status == "WAIVED"
    ex = res.extras or {}
    # analog has no digital RTL author -> no lesson digest, no stray file
    assert ex.get("lessons_digest") is None
    assert not (proj / "phase2/stage1/lessons.md").exists()


# ── BACK-COMPAT: the Shape-C alias still renders ─────────────────────────────

def test_benchmark_dispatch_alias_still_renders():
    import benchmark_dispatch as bd
    n = bd._render_lesson_digest(Path(tempfile.mkdtemp()))
    assert n >= 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
