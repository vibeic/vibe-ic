"""#566 — the landing gate was keyed to a value another repository mutates.

`sync_image_version.py --check` runs in the FULL tier of `gatekeeper-land.sh`
and FAILed whenever this repo's anchor was older than the newest tag published
to ghcr AT THE MOMENT THE CHECK RAN. The full tier takes ~35 minutes;
`vibeic-eda` publishes on its own schedule from a different session.

Measured on the 2026-07-31 landing — 0.2.47 -> .48 -> .49 -> .50 -> .51 at
60-140 minute intervals:

    gate run #1   anchor 0.2.47, published 0.2.48   FAIL      ~35 min discarded
    gate run #2   anchor 0.2.48, published 0.2.49   aborted   ~12 min discarded
    gate run #3   anchor 0.2.49, published 0.2.50   aborted   ~18 min discarded
    gate run #4   anchor 0.2.50, published 0.2.51   aborted   ~25 min discarded

for a batch of eight commits that touch no image pin. Fixing the anchor
rewrites the tip commit, which voids the gate stamp, which restarts the 35
minutes — against a target that moves every ~2 hours. No fixed point exists,
and while it ran NOBODY could land.

The split this file pins:

    older AND absent from the registry   FAIL   (#354 — 0.2.29 pinned in 13
                                                 places for six versions while
                                                 every clean-room install failed)
    older BUT resolvable                 WARN   (#566 — currency, not breakage)
    below this repo's committed anchor   FAIL   (#215 reached from the other
                                                 side, guarded by no-regress)

The middle row is the change; the outer two are what stop it from being a hole.
"""
from __future__ import annotations

import importlib.util
import io
import contextlib
import pathlib
import subprocess
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve()
_REPO = _HERE.parents[5]
PROG = _REPO / "tools" / "vibeic-eda" / "sync_image_version.py"


def _load(name="sync_image_version_probe"):
    spec = importlib.util.spec_from_file_location(name, PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pytestmark = pytest.mark.skipif(
    not PROG.is_file(), reason=f"{PROG} not present in this checkout")


def _anchor(mod, version, tags):
    """Run the anchor check against a STUBBED registry, capturing its output.

    The registry is stubbed rather than queried: the whole defect is a check
    whose verdict depends on a live external value, and a test that queried it
    would inherit exactly that flakiness.
    """
    mod.published_tags = lambda repo=None: (set(tags), "stub")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.check_anchor_vs_reality(version)
    return rc, buf.getvalue()


# ── the change ───────────────────────────────────────────────────────────────
def test_behind_but_resolvable_does_not_block():
    """The row this issue changes: one release behind, image still pullable."""
    rc, out = _anchor(_load(), "0.2.50", {"0.2.50", "0.2.51"})
    assert rc == 0, out
    assert "BEHIND" in out, out


def test_behind_still_says_a_newer_image_exists():
    """Downgrading to a WARNING must not downgrade to SILENCE.

    Without this, the relaxation could be implemented by deleting the
    comparison, and nobody would learn the anchor had fallen behind at all.
    """
    _, out = _anchor(_load(), "0.2.50", {"0.2.50", "0.2.51"})
    assert "0.2.51" in out, out
    assert "WARNING" in out, out
    assert "--set 0.2.51" in out, out


# ── what must still fail (#354) ──────────────────────────────────────────────
def test_an_anchor_absent_from_the_registry_still_fails():
    """0.2.29 was pinned in 13 places for six versions and pulled nowhere.

    This is the accept case for the relaxation: if it also went green, the
    change would have traded a real gate for a comment.
    """
    rc, out = _anchor(_load(), "0.2.29", {"0.2.50", "0.2.51"})
    assert rc == 1, out


def test_an_anchor_ahead_of_the_registry_still_fails():
    """A version this repo invented and never published is unresolvable too —
    the direction #354 was actually opened for."""
    rc, out = _anchor(_load(), "0.2.99", {"0.2.50", "0.2.51"})
    assert rc == 1, out
    assert "UNRESOLVABLE" in out, out


def test_current_anchor_is_still_reported_as_ok():
    rc, out = _anchor(_load(), "0.2.51", {"0.2.50", "0.2.51"})
    assert rc == 0, out
    assert "OK" in out, out


# ── what keeps the relaxation honest (#215 from the other side) ──────────────
def _no_regress(mod, version):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.check_anchor_no_regress(
            _REPO, _REPO / "tools" / "vibeic-eda" / "VERSION", version)
    return rc, buf.getvalue()


def _committed_anchor():
    r = subprocess.run(
        ["git", "-C", str(_REPO), "show", "HEAD:tools/vibeic-eda/VERSION"],
        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        pytest.skip("no committed VERSION baseline in this checkout")
    return r.stdout.strip()


def test_rolling_the_anchor_backwards_fails():
    """The guard that makes 'behind is only a warning' safe to say.

    Being one release behind is a currency question. Being BELOW what this repo
    already shipped puts every pointer consistently on an older image, which is
    the #215 state — and without this check the #566 relaxation would have
    opened that door from the other direction.
    """
    base = _committed_anchor()
    major, minor, patch = (int(n) for n in base.split("."))
    if patch > 0:
        older_parts = (major, minor, patch - 1)
    elif minor > 0:
        older_parts = (major, minor - 1, 999_999)
    elif major > 0:
        older_parts = (major - 1, 999_999, 999_999)
    else:
        pytest.skip("0.0.0 has no older non-negative semantic version")
    assert older_parts < (major, minor, patch)
    older = ".".join(str(n) for n in older_parts)
    rc, out = _no_regress(_load(), older)
    assert rc == 1, out
    assert "REGRESSED" in out, out


def test_advancing_or_holding_the_anchor_passes():
    base = _committed_anchor()
    major, minor, patch = (int(n) for n in base.split("."))
    mod = _load()
    for candidate in (base, f"{major}.{minor}.{patch + 1}"):
        rc, out = _no_regress(mod, candidate)
        assert rc == 0, (candidate, out)


def test_no_regress_compares_against_git_not_the_registry():
    """The baseline must be something the OTHER repo cannot move.

    If this guard read the registry, it would flap for the same reason the
    check it protects did, and the fix would be circular.
    """
    src = PROG.read_text(encoding="utf-8")
    body = src.split("def check_anchor_no_regress", 1)[1]
    body = body.split("\ndef ", 1)[0]
    assert '"git"' in body, "no-regress does not consult git"
    assert "published_tags" not in body, (
        "no-regress reads the registry — it would inherit the flakiness it exists "
        "to bound")


def test_an_unreadable_baseline_is_not_checked_rather_than_passed():
    """rc 2, not rc 0. An unavailable baseline has told us nothing, and this
    repo's own doctrine is that 'could not check' must never aggregate as a
    pass."""
    mod = _load()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.check_anchor_no_regress(_REPO, None, "0.2.51")
    assert rc == 2, buf.getvalue()
