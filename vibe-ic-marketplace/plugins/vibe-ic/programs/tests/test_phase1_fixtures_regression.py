"""tests/test_phase1_fixtures_regression.py — v1.6.62

Regression fixture suite for the 11-project picker benchmark cited
across the issue-#5 verifier follow-ups.

The verifier's recommendation in the v1.6.61 follow-up was:

    > Suggest committing the 11-project benchmark inputs as fixtures
    > so any future picker change must keep all eleven outputs stable.

This test reads each fixture under `tests/phase1_fixtures/<project>/`
and asserts the picker returns the expected IC name. Future picker
changes must keep ALL eleven outputs stable; a regression here means
the picker thrashed on a real-input case the verifier signed off on.

**Provenance:** the verbatim README text for chacha, taxi,
liteiclink and litescope was lifted from the verifier's
v1.6.60-follow-up issue comment. The other seven fixtures
(aes, sha1, sha256, litedram, litesata, litesdcard, benchmark_a) carry
representative READMEs that mirror the corresponding open-source
project's first-paragraph form and the verifier's expected outputs;
they are intentionally minimal so any future picker behaviour change
that breaks them will surface immediately.

If the upstream README format changes for any of these projects,
update the fixture file (NOT the assertion) — the picker's expected
output is what this test pins.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from programs.phase1_one_shot_runner import _ic_name_from_docs


_FIXTURE_DIR = Path(__file__).parent / "phase1_fixtures"


# Expected pick per fixture project. These are the names the verifier
# agent confirmed as correct in the issue-#5 v1.6.61 follow-up
# scorecard ("10 of 11 returned the IP-name a human reviewer would
# have picked"). The taxi case is now also fixed by v1.6.62's tier
# reorder (Tier 3 H1 above Tier 3.5 subject), so all 11 are pinned.
_EXPECTED: dict[str, str] = {
    "aes":         "AES",
    "chacha":      "ChaCha",
    "sha1":        "SHA-1",
    "sha256":      "SHA-256",
    "litedram":    "LiteDRAM",
    "litesata":    "LiteSATA",
    "litesdcard":  "LiteSDCard",
    "liteiclink":  "LiteICLink",
    "litescope":   "LiteScope",
    "taxi":        "Taxi Transport Library",
    "benchmark_a":      "EXAMPLE_CHIP",
}


def _load_fixture(project: str) -> dict[str, str]:
    """Read every file under `tests/phase1_fixtures/<project>/` into
    a `{filename: text}` dict, matching what the real
    `phase1_one_shot_runner` extractor passes to
    `_ic_name_from_docs`."""
    pdir = _FIXTURE_DIR / project
    if not pdir.is_dir():
        raise FileNotFoundError(f"missing fixture dir: {pdir}")
    out: dict[str, str] = {}
    for fp in sorted(pdir.iterdir()):
        if fp.is_file():
            out[fp.name] = fp.read_text(encoding="utf-8")
    if not out:
        raise FileNotFoundError(f"empty fixture dir: {pdir}")
    return out


@pytest.mark.parametrize("project,expected", sorted(_EXPECTED.items()))
def test_phase1_picker_matches_verifier_benchmark(
        project: str, expected: str) -> None:
    """Per-project regression: picker output on the committed fixture
    must equal the verifier-blessed expected name."""
    extracted = _load_fixture(project)
    actual = _ic_name_from_docs(extracted)
    assert actual == expected, (
        f"phase1 picker regression on fixture {project!r}: "
        f"expected {expected!r}, got {actual!r}. "
        f"If upstream README changed, update the fixture; otherwise "
        f"investigate the picker change that flipped this result."
    )


def test_phase1_picker_returns_distinct_names_for_11_projects() -> None:
    """Aggregate guard: the 11 fixtures must not all collapse to the
    same value. This catches a degenerate picker that returns
    `UNKNOWN_IC` for everything."""
    results = {p: _ic_name_from_docs(_load_fixture(p))
               for p in _EXPECTED}
    distinct = set(results.values())
    assert len(distinct) >= 10, (
        f"phase1 picker collapsed: only {len(distinct)} distinct "
        f"results across 11 fixtures: {results}"
    )
    # No fixture should silently return UNKNOWN_IC.
    unknowns = [p for p, n in results.items() if n == "UNKNOWN_IC"]
    assert not unknowns, (
        f"phase1 picker returned UNKNOWN_IC for: {unknowns}. "
        f"Every fixture should have a deterministic non-junk pick."
    )


def test_phase1_picker_no_fpga_board_in_results() -> None:
    """Aggregate guard: NO fixture should return an FPGA / silicon
    part-number SKU. Catches regressions of the v1.6.58 VCU1525 and
    v1.6.60 XCVU095 cases."""
    from programs.phase1_one_shot_runner import _is_fpga_board_name
    bad: dict[str, str] = {}
    for p in _EXPECTED:
        actual = _ic_name_from_docs(_load_fixture(p))
        # Single-token check (multi-word names won't board-match).
        first = actual.split()[0] if actual else ""
        if _is_fpga_board_name(first):
            bad[p] = actual
    assert not bad, (
        f"phase1 picker returned FPGA board name(s): {bad}. "
        f"This is the v1.6.58/v1.6.60 regression class; "
        f"check `_FPGA_BOARD_RE` coverage."
    )
