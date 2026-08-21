#!/usr/bin/env python3
"""Wave 76 — CI test: every BENCHMARK_A-referencing SKILL.md must carry
the chip-AGNOSTIC banner, and zero ACTIVE INSTRUCTION_FIXED hits
must remain.

Run via:
    python3 -m pytest plugins/vibe-ic/tests/test_wave76_skill_md_chip_agnostic.py
"""
from __future__ import annotations
import re
from pathlib import Path

import pytest

from _plugin_tree import plugin_path

# flow #486: skills/ is a SHIPPED in-plugin dir (plugin-root resolver); the
# audit tool tools/wave76_*.py is a repo-root-only tool NOT shipped in the
# flattened cache and is resolved lazily inside the test that needs it.
SKILLS = plugin_path("skills")

PATTERNS = re.compile(
    r"\b(EXAMPLE_CHIP|BigTen|A1101|A1103|A1105|MDV-?A1101|"
    r"ACC_ID|ID_IO|MD-?905|0xF2|altsyncram)\b"
)
BANNER_MARKER = "<!-- WAVE_76_CHIP_AGNOSTIC_BANNER -->"
ALLOWLIST = {"community-backlog-submit"}


def _affected_skills() -> list[Path]:
    out = []
    for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
        if PATTERNS.search(skill_md.read_text()):
            out.append(skill_md)
    return out


def test_at_least_one_affected_skill_exists():
    """Sanity: this test file is meaningful only if some SKILL.md
    references the BENCHMARK_A reference project. v0.131: 16 files."""
    assert len(_affected_skills()) >= 1, (
        "no SKILL.md references the BENCHMARK_A reference project — has the "
        "case study been moved out? Update PATTERNS or remove this test."
    )


def test_every_affected_skill_carries_banner_or_is_allowlisted():
    """Every SKILL.md that mentions EXAMPLE_CHIP / EXAMPLE_TESTER / MDV-A1101 must
    EITHER carry the chip-AGNOSTIC banner OR be in the allowlist
    (community-backlog-submit, whose mentions are the redaction
    pattern table itself)."""
    missing = []
    for p in _affected_skills():
        skill_name = p.parent.name
        if skill_name in ALLOWLIST:
            continue
        if BANNER_MARKER not in p.read_text():
            missing.append(skill_name)
    assert not missing, (
        f"Skills with BENCHMARK_A references but no chip-AGNOSTIC banner: "
        f"{missing}. Run "
        f"`python3 tools/wave76_skill_md_chip_agnostic_audit.py` to "
        f"regenerate the banner."
    )


def test_no_active_instruction_fixed_hits():
    """ACTIVE rule: rule body that says 'for EXAMPLE_CHIP do X' (instead
    of 'for ic_class=aid_class_half_duplex do X') would fail this
    contract. Wave 76 audit reports 0; if a future PR introduces
    one, this test catches it.

    Heuristic: line matches `(MUST|SHALL|REQUIRED) ... (EXAMPLE_CHIP|EXAMPLE_TESTER|
    MDV-A1101)` AND lacks generality verbs (replace/swap/redact)."""
    active = []
    for p in _affected_skills():
        skill_name = p.parent.name
        if skill_name in ALLOWLIST:
            continue
        for n, line in enumerate(p.read_text().splitlines(), 1):
            s = line.strip()
            if re.search(
                r"\b(MUST|SHALL|REQUIRED)\b.*?"
                r"\b(EXAMPLE_CHIP|MD-?905|MDV-?A1101)\b",
                s,
            ) and not re.search(
                r"\b(replace|swap|substitute|redact)\b", s, re.I
            ):
                active.append((skill_name, n, s[:160]))
    assert not active, (
        f"ACTIVE INSTRUCTION_FIXED hits: {active}. Rewrite each rule "
        f"to talk about ic_class (see "
        f"plugins/vibe-ic/programs/ic_class_profile.py) instead of "
        f"the chip SKU."
    )


def test_audit_tool_runs_clean(tmp_path):
    """Running the audit tool MUST exit 0 (== ACTIVE hits = 0).

    The audit tool lives at tools/ in the source tree but is NOT
    mirrored into opensource_repo/. When this test runs from the
    mirror tree, skip the subprocess invocation — the BANNER +
    INSTRUCTION_FIXED invariants above already cover the audit's
    pass criteria, and re-running the tool against a tree that
    doesn't ship it would always fail.

    ``--report`` is passed on purpose. Invoked bare, the tool defaults
    to ``ROOT/docs/reports/wave76_skill_md_audit.json`` (see its
    ``main()``), so this test — which is in the fixed doctrine SMOKE set
    and therefore runs on EVERY PR — rewrote a file inside the very tree
    it audits, every time. `git status` never showed it because
    `docs/reports/` is ignored (.gitignore:103), so the write was real
    and invisible at the same time; `suite_write_guard --compare` is
    what surfaces it, as `!! docs/reports/wave76_skill_md_audit.json
    (rewritten)`.

    The redirect changes WHERE the report lands and nothing else: the
    tool audits the same tree and returns the same code, because `out`
    is only the write target. The exit-status assertion below is
    unchanged and still the thing being tested.
    """
    import subprocess
    from _plugin_tree import repo_path_or_missing
    tool = repo_path_or_missing("tools", "wave76_skill_md_chip_agnostic_audit.py")
    if not tool.exists():
        pytest.skip(
            f"audit tool not present at {tool} (mirror/cache tree); "
            f"BANNER + INSTRUCTION_FIXED invariants are checked above"
        )
    report = tmp_path / "wave76_skill_md_audit.json"
    r = subprocess.run(
        ["python3", str(tool), "--report", str(report)],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, (
        f"audit tool exited {r.returncode}\nstdout:\n{r.stdout}\n"
        f"stderr:\n{r.stderr}"
    )
    # The redirect must actually be honoured. Without this, a future
    # change that ignores `--report` would send the write back into the
    # tree and nothing here would notice — the failure mode this test
    # just had.
    assert report.is_file(), (
        f"the tool exited 0 but wrote no report to {report}; `--report` "
        f"was not honoured, so the audit may have written into the "
        f"repository tree instead"
    )
