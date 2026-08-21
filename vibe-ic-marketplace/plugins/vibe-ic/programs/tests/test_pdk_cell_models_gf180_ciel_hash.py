"""gf180's ciel-staged cell model/liberty paths carry a CONTENT-ADDRESSED
version hash (`ciel/gf180mcu/versions/<hash>/...`) that moves every time
vibeic-eda's gf180mcu pin advances — unlike sky130A / ihp-sg13g2, whose
container paths are stable. `PDK_CELL_MODELS["gf180"]`, `fault_atpg_run.
PDK_CONFIG["gf180"]["cell_model"]` and `fault_scan_chain_insert.SCAN_LIBERTY
["gf180"]` each carry a single hash as a point-in-time fallback.

MEASURED 2026-08-07 (spm x gf180mcuD, images 0.2.70 and 0.2.74): the fallback
hash baked into all three was `8f2d1529c86235d726979eb9ecb7e9628108590b`; the
image actually shipped `b344c97eacc2aaf8e14ae7e43e2e9dc0871de2c0`. Step 11
(`fault cut`/`fault atpg`, and separately `fault chain`) failed with
`cp: cannot stat '<stale-hash-path>': No such file or directory`, read
downstream as an OSS-tool capability gap ("Fault is not turnkey on gf180 UDP
DFF forms") when the real defect was a stale literal path — re-running the
SAME step against the SAME image with the hash corrected succeeded outright
(DT1/DT2/DT3 all real PASS).

These tests exercise `resolve_gf180_ciel_hash` / `materialize_gf180_paths`
against a FAKE docker runner (no container needed) — the property under test
is the substring-substitution logic and its honest failure mode, not any
particular hash value.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

import pdk_cell_models as pcm  # noqa: E402

_LIVE_HASH = "b344c97eacc2aaf8e14ae7e43e2e9dc0871de2c0"


def _runner_reports(hashes):
    def _run(argv, timeout):
        assert argv[:2] == ["ls", "-1"], argv
        return 0, "\n".join(hashes), ""
    return _run


def _runner_fails():
    def _run(argv, timeout):
        return 1, "", "ls: cannot access: No such file or directory"
    return _run


def test_resolve_returns_the_single_hash_present():
    got = pcm.resolve_gf180_ciel_hash(_runner_reports([_LIVE_HASH]))
    assert got == _LIVE_HASH


def test_resolve_refuses_to_guess_among_several():
    # More than one version dir means something this function does not
    # understand is going on — it must not pick one.
    got = pcm.resolve_gf180_ciel_hash(
        _runner_reports([_LIVE_HASH, pcm.GF180_CIEL_HASH_FALLBACK]))
    assert got is None


def test_resolve_returns_none_on_empty_listing():
    got = pcm.resolve_gf180_ciel_hash(_runner_reports([]))
    assert got is None


def test_resolve_returns_none_when_docker_access_fails():
    assert pcm.resolve_gf180_ciel_hash(_runner_fails()) is None


def test_resolve_never_raises_when_the_runner_itself_raises():
    def _boom(argv, timeout):
        raise RuntimeError("docker binary not found")
    assert pcm.resolve_gf180_ciel_hash(_boom) is None


def test_materialize_swaps_the_stale_hash_for_the_live_one():
    stale_paths = pcm.container_model_paths("gf180")
    assert pcm.GF180_CIEL_HASH_FALLBACK in stale_paths[0]

    fixed = pcm.materialize_gf180_paths(
        stale_paths, _runner_reports([_LIVE_HASH]))

    assert pcm.GF180_CIEL_HASH_FALLBACK not in fixed[0]
    assert _LIVE_HASH in fixed[0]
    # only the hash changed — the rest of the path is untouched
    assert fixed[0] == stale_paths[0].replace(
        pcm.GF180_CIEL_HASH_FALLBACK, _LIVE_HASH)


def test_materialize_is_a_noop_when_discovery_fails():
    """NEGATIVE CONTROL for the fix itself: this is exactly what the code
    did BEFORE this change (always used the literal fallback), so a
    discovery failure must degrade to that — not raise, not blank the
    path, not fabricate a hash nobody observed."""
    stale_paths = pcm.container_model_paths("gf180")
    unchanged = pcm.materialize_gf180_paths(stale_paths, _runner_fails())
    assert unchanged == stale_paths


def test_materialize_is_a_noop_when_the_image_already_matches_the_fallback():
    stale_paths = pcm.container_model_paths("gf180")
    same = pcm.materialize_gf180_paths(
        stale_paths, _runner_reports([pcm.GF180_CIEL_HASH_FALLBACK]))
    assert same == stale_paths


def test_fault_atpg_run_pdk_config_and_fault_scan_chain_insert_agree_with_pcm():
    """The three tables this module's docstring names must still carry the
    SAME fallback hash — this fix only adds live resolution on top; it must
    not fork the literal three ways again."""
    import fault_atpg_run as far  # noqa: E402
    import fault_scan_chain_insert as fsci  # noqa: E402

    assert pcm.GF180_CIEL_HASH_FALLBACK in far.PDK_CONFIG["gf180"]["cell_model"]
    assert pcm.GF180_CIEL_HASH_FALLBACK in fsci.SCAN_LIBERTY["gf180"]
