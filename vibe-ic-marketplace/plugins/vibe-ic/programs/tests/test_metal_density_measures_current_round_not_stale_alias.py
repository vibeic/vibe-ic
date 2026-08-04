#!/usr/bin/env python3
"""Regression — metal density must measure the CURRENT round's GDS, not the
not-yet-refreshed canonical alias.

Defect (measured on a real re-run)
----------------------------------
`_emit_metal_density_report` resolved its GDS as, verbatim:

    gds = _pl.gds_dir(project) / f"{top}.gds"          # stage4/gds alias
    if not gds.is_file():
        gds = _pl.pnr_dir(project) / f"{top}.gds"      # streamed pnr GDS

i.e. it PREFERRED the canonical alias `phase3/stage4/gds/<top>.gds` whenever it
existed. But that alias is a byte copy of the streamed pnr GDS, refreshed by
"Step 37 GDS canonical alias" which runs LATER in the SAME
`step_canonicalize_artefacts` pass than this emit. So the emit read the alias
BEFORE Step 37 rewrote it:

  * first-ever run  — alias ABSENT -> the streamed pnr GDS is used (honest).
  * every RE-RUN    — alias present but still holding the PREVIOUS round's
                      bytes -> metal density silently reports the prior round's
                      per-layer numbers.

Measured on one run: metal_density.json was written 00:30:10 naming
phase3/stage4/gds/<top>.gds, and the runner rewrote that same file 00:30:31 —
21 s LATER. The report quoted the inherited density
0.190819/0.109204/0.08294/0.064308/0.054103 for a GDS that actually measured
0.2148/0.2403/0.2799/0.3629/0.3848. It was caught only because the density was
byte-identical to baseline while DRC had moved 5 -> 103 failures — an impossible
pair.

This is a READ/WRITE ORDERING defect WITHIN one run — distinct from the
cross-run mtime-vs-input staleness of the sign-off-emit and Step-34-metal-fill
fixes: those re-run the emitter when its output predates the routed DEF, but the
metal-density emit would STILL read the stale alias because the alias is
refreshed after the emit. The fix is to point the measurement at the fresher of
{alias, streamed source}.

Fix — `_freshest_gds(alias, source)`
------------------------------------
Return whichever of the canonical alias and the streamed pnr GDS has the larger
mtime (skipping absent files); ties prefer the alias; unprovable freshness
prefers the source. Selects the layout this round produced regardless of the
Step-37 copy ordering.

REVERSE case (the one that matters)
-----------------------------------
The over-correction is "always read the pnr source, never the alias" — which
would discard the canonical deliverable even once Step 37 HAS refreshed it.
`test_reverse_fresh_alias_is_measured` fails if that happens.

chip-AGNOSTIC: pure mtime comparison on synthetic paths; no design, vendor,
SKU, process-node or PDK literal.
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402


def _mk(tmp_path: Path, alias_age, source_age):
    """Create the alias and/or source GDS with explicit mtimes. `*_age` is
    seconds BEFORE a fixed reference instant — larger age = older. None = absent."""
    ref = 1_700_000_000.0
    stage4 = tmp_path / "stage4"
    pnr = tmp_path / "pnr"
    stage4.mkdir(parents=True, exist_ok=True)
    pnr.mkdir(parents=True, exist_ok=True)
    alias = stage4 / "top.gds"
    source = pnr / "top.gds"
    if alias_age is not None:
        alias.write_text("HEADER 5;\n")  # any bytes; only mtime matters here
        os.utime(alias, (ref - alias_age, ref - alias_age))
    if source_age is not None:
        source.write_text("HEADER 5;\n")
        os.utime(source, (ref - source_age, ref - source_age))
    return alias, source


# --------------------------------------------------------------------------
# THE DEFECT — a stale alias (older than the streamed source) must not be
# measured; the fresh source is.
# --------------------------------------------------------------------------
def test_stale_alias_is_not_measured(tmp_path):
    alias, source = _mk(tmp_path, alias_age=21.0, source_age=0.0)  # alias 21s old
    chosen = R._freshest_gds(alias, source)
    assert chosen == source, (
        "the alias was 21 s older than the streamed pnr GDS (the measured "
        "read-before-Step-37-refresh window); metal density must measure the "
        "fresh source, not the superseded alias"
    )


def test_pre_fix_prefer_alias_would_have_measured_the_stale_one(tmp_path):
    """States the BEHAVIOURAL delta using the pre-fix resolution verbatim, so
    the change is visible without the new symbol (every other test would fail
    pre-fix with AttributeError, which only proves the helper is new)."""
    alias, source = _mk(tmp_path, alias_age=21.0, source_age=0.0)

    # Pre-fix: `gds = alias; if not gds.is_file(): gds = source` -> alias wins
    # whenever it exists.
    pre_fix_choice = alias if alias.is_file() else source
    assert pre_fix_choice == alias, "pre-fix always preferred the alias"

    assert R._freshest_gds(alias, source) == source
    assert R._freshest_gds(alias, source) != pre_fix_choice


# --------------------------------------------------------------------------
# THE REVERSE CASE — once Step 37 HAS refreshed the alias (alias newer-or-equal)
# the canonical alias is measured. Fails if the fix degenerates into "always
# read the pnr source".
# --------------------------------------------------------------------------
def test_reverse_fresh_alias_is_measured(tmp_path):
    alias, source = _mk(tmp_path, alias_age=0.0, source_age=600.0)  # alias newer
    assert R._freshest_gds(alias, source) == alias


def test_equal_mtime_prefers_alias(tmp_path):
    alias, source = _mk(tmp_path, alias_age=100.0, source_age=100.0)
    assert R._freshest_gds(alias, source) == alias


# --------------------------------------------------------------------------
# Absence / freshness edges.
# --------------------------------------------------------------------------
def test_first_run_absent_alias_uses_source(tmp_path):
    alias, source = _mk(tmp_path, alias_age=None, source_age=0.0)
    assert R._freshest_gds(alias, source) == source


def test_absent_source_uses_alias(tmp_path):
    alias, source = _mk(tmp_path, alias_age=0.0, source_age=None)
    assert R._freshest_gds(alias, source) == alias


def test_both_absent_returns_none(tmp_path):
    alias, source = _mk(tmp_path, alias_age=None, source_age=None)
    assert R._freshest_gds(alias, source) is None


def test_unprovable_freshness_prefers_source(tmp_path, monkeypatch):
    """Both files exist (is_file() succeeds) but the mtime read raises — a TOCTOU
    stat failure. The conservative direction is the always-current-round source."""
    alias, source = _mk(tmp_path, alias_age=0.0, source_age=600.0)  # alias newer
    real_stat = Path.stat
    calls = {"n": 0}

    def boom(self, *a, **kw):
        calls["n"] += 1
        # Let the two is_file() probes through; fail the mtime-read stats.
        if calls["n"] > 2:
            raise OSError("stat unavailable")
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", boom)
    assert R._freshest_gds(alias, source) == source


@pytest.mark.parametrize("alias_age,source_age,expect_source", [
    (21.0, 0.0, True),     # measured stale-alias case
    (1.0, 0.0, True),      # one second stale is still stale
    (0.0, 1.0, False),     # alias fresh
    (0.0, 0.0, False),     # tie -> alias
])
def test_polarity_table(tmp_path, alias_age, source_age, expect_source):
    alias, source = _mk(tmp_path, alias_age, source_age)
    chosen = R._freshest_gds(alias, source)
    assert (chosen == source) is expect_source


# --------------------------------------------------------------------------
# Structural — the emitter must route through the freshness choice and keep its
# glob fallback (the reverse-scope guard: the fix must not over-reach).
# --------------------------------------------------------------------------
def test_emitter_uses_freshest_gds_and_keeps_glob_fallback():
    src = inspect.getsource(R._emit_metal_density_report)
    assert "_freshest_gds(" in src, (
        "the metal-density emit must resolve its GDS through _freshest_gds so a "
        "re-run measures the current round, not the not-yet-refreshed alias"
    )
    # The pre-fix unconditional 'prefer the alias' resolution must be gone.
    assert 'gds = _pl.gds_dir(project) / f"{top}.gds"\n    if not gds.is_file():' \
        not in src, "the emit still prefers the stale alias unconditionally"
    # The honest 'no GDS at all' skip must survive.
    assert "no streamed GDS found" in src
