"""Every ghcr tag under benchmark-data/ is a RECORD, and was listed one at a time.

`.image-version-ignore` protects a file from having its image tag advanced to the
current anchor. Two entries already stated the rule in prose, one file each:

    benchmark-data/ic/spm/.../DYNAMIC_IR_REGENERATED.md
        "benchmark-data is read-only to the flow for exactly this reason — the
         tag names the toolchain that produced the numbers beside it"
    benchmark-data/ic/caravel_user_project/.../SOURCE_MANIFEST.md

A per-file list behaves exactly one way: it is always one evidence cell behind.
The caravel landing surfaced SEVEN more in a single cell — scan_chain.json,
container_image.json (x3), vibe_ic_one_shot.json (x3) — and each would have been
rewritten to claim a run happened under an image that did not exist when it ran.

The rule is now stated once, as a path glob. 37 pointers across 13 cells fall
under it; every one is a RESULT.md, a run record, or a roadmap line saying which
image a landed fork change first shipped in.
"""
from __future__ import annotations

import fnmatch
import pathlib

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_IGNORE = _REPO / ".image-version-ignore"


def _globs():
    return [l.strip() for l in _IGNORE.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def _ignored(rel: str) -> bool:
    """The matcher `sync_image_version._matches` uses: basename OR full path."""
    base = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(base, g) or fnmatch.fnmatch(rel, g)
               for g in _globs())


def test_the_rule_is_stated_once_as_a_path():
    assert "benchmark-data/*" in _globs()


def test_a_record_in_any_cell_is_covered_including_ones_that_do_not_exist_yet():
    """The point of the glob: a cell landed next month is protected without
    anyone remembering to come here."""
    for rel in ("benchmark-data/ic/x/reports/container_image.json",
                "benchmark-data/ic/x/v9.9.9_pdk/RESULT.md",
                "benchmark-data/evaluation/run_future/pass_at_1.json",
                "benchmark-data/ic/brand_new_design/reports/phase2/dft/scan_chain.json"):
        assert _ignored(rel), rel


def test_the_seven_the_caravel_landing_surfaced_are_covered():
    cell = "benchmark-data/ic/caravel_user_project/v1.9.43_sky130A"
    for rel in (f"{cell}/reports/phase2/dft/scan_chain.json",
                f"{cell}/reports/container_image.json",
                f"{cell}/reports/orchestrator/vibe_ic_one_shot.json",
                f"{cell}/RESULT.md"):
        assert _ignored(rel), rel


def test_install_pointers_are_NOT_covered():
    """LOAD-BEARING, and the only thing that makes the glob safe: a rule that
    also silenced the install docs would let every pointer a real user follows
    rot, which is the defect the whole mechanism exists to prevent. `_matches`
    tries the BASENAME too, so a careless glob reaches much further than its
    directory."""
    for rel in ("README.md",
                "docs/INSTALL.md",
                "tools/vibeic-eda/README.md",
                "vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/INSTALL_GUIDE.md",
                "vibe-ic-marketplace/plugins/vibe-ic/README.md"):
        assert not _ignored(rel), rel


def test_a_file_merely_NAMED_like_a_record_outside_benchmark_data_is_not_covered():
    """The basename half of the matcher is the trap. `RESULT.md` under
    benchmark-data is history; a `RESULT.md` somewhere else is not, and must not
    inherit the exemption by name alone."""
    assert not _ignored("docs/RESULT.md")
    assert not _ignored("RESULT.md")


def test_the_reason_travels_with_the_rule():
    """A bare glob is a waiver; a glob with its reason is a record. The next
    person to widen or narrow this needs to know it is about measurement
    honesty, not about noise."""
    text = _IGNORE.read_text(encoding="utf-8")
    # the LAST occurrence: `benchmark-data/*/RESULT.md` appears earlier, under
    # its own (also-reasoned) preamble, and matching that one would let this
    # test pass while the rule it is about carried no reason at all.
    i = text.rindex("\nbenchmark-data/*\n")
    preamble = text[max(0, i - 1400):i]
    assert "PRODUCED" in preamble or "produced" in preamble
    assert "never ran" in preamble or "never rewritten" in preamble
