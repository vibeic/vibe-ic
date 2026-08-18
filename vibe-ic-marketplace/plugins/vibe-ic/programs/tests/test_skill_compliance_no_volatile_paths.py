"""tests/test_skill_compliance_no_volatile_paths.py — v1.6.53

Unit tests for the `no_volatile_paths` cross-check rule added to
`_shared/skill_compliance_check.py`. Surface volatile-storage path
leaks (/tmp, /var/tmp, /dev/shm, /run) in skill output before they
reach `project_outputs_in_tree_check` at burn time."""
from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

from _shared.skill_compliance_check import (  # noqa: E402
    _cc_no_volatile_paths,
    CROSS_CHECK_RULES,
)


def _run(text: str):
    return _cc_no_volatile_paths(
        {"id": "X_no_volatile_paths",
         "description": "test forbid",
         "rule": "no_volatile_paths"},
        text)


# ---------------------------------------------------------------------------
# Positive cases — must PASS (no findings).
# ---------------------------------------------------------------------------

def test_clean_text_passes():
    assert _run("Just a normal report. No volatile paths here.") == []


def test_relative_paths_pass():
    text = ("See `phase1/extraction_patterns.json` and "
            "`reports/phase1_completeness_deep_review.md`.")
    assert _run(text) == []


def test_persistent_storage_paths_pass():
    """`/var/log/...`, `/etc/...`, `/usr/...`, `/home/...` are
    persistent and should not be flagged."""
    text = (
        "Logs in /var/log/syslog. Config in /etc/hosts. "
        "Helpers in /usr/local/bin/foo. Project root /home/user/project.")
    assert _run(text) == []


def test_word_inside_other_word_does_not_match():
    """A bare word `tmp` inside another identifier (`settmpval`,
    `mytmp.log`) must not trigger. The regex requires a leading
    word-boundary character so that `/run/x` inside `/home/x/run/x`
    is NOT flagged (it's a sub-path of persistent storage), while
    a top-level `/run/foo.lock` IS flagged."""
    # Sub-path inside persistent storage — must NOT trigger.
    text = "settmpval set; mytmp.log written; /home/x/run/y is fine."
    assert _run(text) == []
    # Top-level volatile mount — MUST trigger.
    text2 = "Lock at /run/user/foo.lock during build."
    out2 = _run(text2)
    assert len(out2) == 1
    assert "/run/user/foo.lock" in out2[0].detail


# ---------------------------------------------------------------------------
# Negative cases — must FAIL (findings emitted).
# ---------------------------------------------------------------------------

def test_tmp_path_flagged():
    text = "Local helper `/tmp/dump_full_missing.py` — diagnostic."
    out = _run(text)
    assert len(out) == 1
    assert out[0].severity == "FAIL"
    assert "/tmp/dump_full_missing.py" in out[0].detail


def test_var_tmp_path_flagged():
    text = "Output cache at /var/tmp/build_cache_2026.tar.gz"
    out = _run(text)
    assert len(out) == 1
    assert "/var/tmp/build_cache_2026.tar.gz" in out[0].detail


def test_dev_shm_path_flagged():
    text = "Mmap region /dev/shm/region.bin used during synth."
    out = _run(text)
    assert len(out) == 1
    assert "/dev/shm/region.bin" in out[0].detail


def test_run_mount_path_flagged():
    text = "Lock file at /run/user/1000/foo.lock"
    out = _run(text)
    assert len(out) == 1


def test_multiple_paths_deduped():
    """Multiple references to the same volatile path emit one finding
    listing all unique paths in the detail string."""
    text = (
        "Helper /tmp/foo.py was used. Then /tmp/foo.py was deleted. "
        "Also /tmp/bar.log got rotated. Plus /var/tmp/cache stays.")
    out = _run(text)
    assert len(out) == 1  # one finding aggregating all paths
    detail = out[0].detail
    assert "/tmp/foo.py" in detail
    assert "/tmp/bar.log" in detail
    assert "/var/tmp/cache" in detail


def test_path_inside_backticks_flagged():
    text = "See `/tmp/scratch.py` for context."
    out = _run(text)
    assert len(out) == 1
    assert "/tmp/scratch.py" in out[0].detail


def test_path_in_parens_flagged():
    text = "Refer to (/tmp/scratch.py) for the helper."
    out = _run(text)
    assert len(out) == 1


# ---------------------------------------------------------------------------
# Registration sanity.
# ---------------------------------------------------------------------------

def test_rule_registered_in_dispatcher():
    assert "no_volatile_paths" in CROSS_CHECK_RULES
    assert CROSS_CHECK_RULES["no_volatile_paths"] is _cc_no_volatile_paths
