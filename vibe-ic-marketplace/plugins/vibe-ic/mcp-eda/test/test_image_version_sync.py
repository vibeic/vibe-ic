#!/usr/bin/env python3
"""Fool-proof gate: the `vibeic-eda:X.Y.Z` tag in the install docs must equal the
VERSION source of truth (`tools/vibeic-eda/VERSION`). Drift means users pull a
stale / nonexistent image, so a mismatch FAILS the plugin test suite.

The check is delegated to the repo tool `tools/vibeic-eda/sync_image_version.py`,
which also carries the repo-wide `ghcr.io/...` drift net. All tests SKIP cleanly
when that tool is absent (installed plugin ships no repo-root tools/) so CI in the
packaged plugin stays green.
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _find_tool():
    for up in Path(__file__).resolve().parents:
        c = up / "tools" / "vibeic-eda" / "sync_image_version.py"
        if c.is_file():
            return c
    return None


TOOL = _find_tool()
_skip = pytest.mark.skipif(TOOL is None, reason="tools/vibeic-eda/sync_image_version.py not present")


def _load():
    spec = importlib.util.spec_from_file_location("siv", TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@_skip
def test_install_docs_in_sync_with_version_file():
    r = subprocess.run([sys.executable, str(TOOL), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, f"vibeic-eda image-version drift:\n{r.stdout}\n{r.stderr}"


@_skip
def test_bump_dry_run_is_nondestructive():
    before = (TOOL.parent / "VERSION").read_text()
    r = subprocess.run([sys.executable, str(TOOL), "--bump", "patch", "--dry-run"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "would write VERSION" in r.stdout
    assert (TOOL.parent / "VERSION").read_text() == before, "dry-run must not mutate VERSION"


@_skip
def test_next_version_rollover():
    spec = importlib.util.spec_from_file_location("siv", TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.next_version("0.2.12", "patch") == "0.2.13"
    assert m.next_version("0.2.99", "patch") == "0.3.0"      # patch 0..99 rollover
    assert m.next_version("0.9.99", "patch") == "0.10.0"
    assert m.next_version("0.2.12", "minor") == "0.3.0"
    assert m.next_version("0.2.12", "major") == "1.0.0"


@_skip
def test_history_globs_exclude_changelog_and_roadmap():
    """The classifier must treat status/roadmap docs as history (never bumped),
    else it would rewrite 'shipped in vibeic-eda:0.2.5' prose."""
    m = _load()
    assert m.is_history("tools/vibeic-eda/FIX_STATUS.md")
    assert m.is_history("benchmark-data/ic/OSS_EDA_FORK_ROADMAP.md")
    assert not m.is_history("README.md")
    assert not m.is_history("docs/INSTALL.md")


# ---- issue #215: anchor-vs-reality — consistency is not correctness -----------
# The old check only compared pointers to the VERSION file. If VERSION was itself
# stale, the tree could be internally consistent yet consistently WRONG, and the
# check went GREEN — it even demanded a correct pointer be rolled back to the
# stale anchor. These lock in that VERSION is now checked against the newest
# PUBLISHED image tag (pinnable via env for offline / deterministic CI).


@_skip
def test_newest_published_tag_honors_override(monkeypatch):
    """The published-tag source must be pinnable (offline / CI / tests): a valid
    X.Y.Z override is used verbatim; empty / non-semver overrides degrade to
    (None, reason) rather than crash or silently claim a tag."""
    m = _load()
    monkeypatch.setenv(m.PUBLISHED_TAG_ENV, "9.9.9")
    tag, src = m.newest_published_tag()
    assert tag == "9.9.9" and "override" in src
    monkeypatch.setenv(m.PUBLISHED_TAG_ENV, "not-a-version")
    tag, src = m.newest_published_tag()
    assert tag is None and "X.Y.Z" in src
    monkeypatch.setenv(m.PUBLISHED_TAG_ENV, "")
    tag, src = m.newest_published_tag()
    assert tag is None and "empty" in src


@_skip
def test_stale_anchor_flagged_loudly(monkeypatch, capsys):
    """RED/GREEN control: a VERSION older than the newest published tag must FAIL
    and name BOTH values — internal pointer consistency cannot mask it."""
    m = _load()
    monkeypatch.setenv(m.PUBLISHED_TAG_ENV, "0.2.26")
    rc = m.check_anchor_vs_reality("0.2.23")
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "STALE ANCHOR" in out
    assert "0.2.23" in out and "0.2.26" in out


@_skip
def test_anchor_ok_when_equal_and_FAILS_when_ahead(monkeypatch):
    """Equal is clean. AHEAD is a FAIL, and this test used to assert the
    opposite.

    It read "VERSION ahead of the newest published tag is a legitimate
    unreleased bump, not a failure" — the behaviour #354 deliberately
    REVERSED, because that is exactly how 0.2.29, a tag that never existed on
    ghcr, stayed pinned in 13 places for six versions while every clean-room
    install failed. `check_anchor_vs_reality`'s own docstring has said so
    since: "A pin the registry cannot resolve is a FAIL, not a future." The
    code moved and the test stayed, so it had been failing on main — a test
    asserting a superseded doctrine is worse than no test, because it argues
    for the defect.
    """
    m = _load()
    monkeypatch.setenv(m.PUBLISHED_TAG_ENV, "0.2.26")
    assert m.check_anchor_vs_reality("0.2.26") == 0     # equal to published
    assert m.check_anchor_vs_reality("0.3.0") == 1      # unresolvable pin


@_skip
def test_report_end_to_end_flags_stale_anchor():
    """The stale anchor #215 describes must still be FOUND and NAMED.

    It moved from `--check` to `--report-upstream` (vibe-ic#927): the value it
    compares against is one another org mutates, so it is an observation, not a
    landing verdict. The finding itself is unchanged and this asserts it, plus
    the exit code that makes it non-blocking — if that ever became non-zero
    again the treadmill is back. 99.99.99 is used so the injected pin is
    unambiguously newer than any real VERSION.
    """
    env = dict(os.environ, VIBEIC_EDA_PUBLISHED_TAG="99.99.99")
    r = subprocess.run([sys.executable, str(TOOL), "--report-upstream"],
                       capture_output=True, text=True, env=env)
    assert "STALE ANCHOR" in r.stdout and "99.99.99" in r.stdout, r.stdout
    assert r.returncode == 0, r.stdout


@_skip
def test_check_end_to_end_is_clean_and_ignores_the_injected_published_tag():
    """GREEN, and the invariance in one assertion.

    A check that cannot return clean is an alarm, not a check (#215). And the
    blocking half must return the SAME clean result whether the injected
    registry claims our exact version or one far newer — that difference is
    upstream's business, not this tree's (#927).
    """
    v = (TOOL.parent / "VERSION").read_text().strip()
    outs = []
    for claim in (v, "99.99.99"):
        env = dict(os.environ, VIBEIC_EDA_PUBLISHED_TAG=claim)
        r = subprocess.run([sys.executable, str(TOOL), "--check"],
                           capture_output=True, text=True, env=env)
        assert r.returncode == 0, (claim, r.stdout)
        assert "all live pointers" in r.stdout
        outs.append(r.stdout)
    assert outs[0] == outs[1], (
        "the blocking half's output depends on what the registry claims", outs)


# ── vibe-ic#423 — `:latest` must resolve to the anchor ──────────────────────

def test_latest_pointing_elsewhere_is_a_FAIL(monkeypatch, capsys):
    """THE DEFECT. `:latest` sat on the 0.2.28 manifest for four days while
    0.2.30 was current, and every existing check passed — they compared our
    POINTERS against the anchor, and the anchor was right. Nobody compared the
    tag an outside reader actually pulls."""
    m = _load()
    monkeypatch.delenv(m.PUBLISHED_TAG_ENV, raising=False)
    monkeypatch.setattr(m, "_query_ghcr_digest",
                        lambda repo, tag, timeout=6.0:
                        "sha256:aaa" if tag == "latest" else "sha256:bbb")
    assert m.check_latest_points_at_anchor("0.2.30") == 1
    out = capsys.readouterr().out
    assert "does NOT point at the anchor" in out
    assert "imagetools create" in out, "the fix must be in the message"


def test_latest_on_the_anchor_manifest_passes(monkeypatch, capsys):
    """The paired half — and the state of the registry after the #423 fix."""
    m = _load()
    monkeypatch.delenv(m.PUBLISHED_TAG_ENV, raising=False)
    monkeypatch.setattr(m, "_query_ghcr_digest",
                        lambda repo, tag, timeout=6.0: "sha256:same")
    assert m.check_latest_points_at_anchor("0.2.30") == 0
    assert "latest-vs-anchor         : OK" in capsys.readouterr().out


def test_an_unreachable_registry_does_not_silently_pass(monkeypatch, capsys):
    """With --require-remote it must not shrug: "I could not look" is not "it
    is correct".

    rc 2 (NOT CHECKED), not rc 1. This assertion read `== 1` and had been
    FAILING on main since the rc-2 vocabulary was introduced by
    test_image_version_unreachable_is_not_a_failed_pin.py — the code moved and
    this test stayed. A test asserting a superseded contract is worse than no
    test, because it argues for the thing that was fixed.
    """
    m = _load()
    monkeypatch.delenv(m.PUBLISHED_TAG_ENV, raising=False)

    def _boom(repo, tag, timeout=6.0):
        raise OSError("network down")

    monkeypatch.setattr(m, "_query_ghcr_digest", _boom)
    assert m.check_latest_points_at_anchor("0.2.30", require_remote=True) == 2
    assert m.check_latest_points_at_anchor("0.2.30") == 0      # advisory mode
    out = capsys.readouterr().out
    assert "NOT CHECKED" in out
    assert "UNVERIFIED" in out


def test_the_offline_override_skips_rather_than_guesses(monkeypatch, capsys):
    """The override exists for deterministic / offline CI. There is no
    registry to ask, so the honest result is SKIPPED — not a fabricated PASS
    and not a failure that would make offline CI red."""
    m = _load()
    monkeypatch.setenv(m.PUBLISHED_TAG_ENV, "0.2.30")
    assert m.check_latest_points_at_anchor("0.2.30", require_remote=True) == 0
    assert "SKIPPED" in capsys.readouterr().out
