#!/usr/bin/env python3
"""Regression: getToolVersion()'s cache must invalidate on a container image swap
(v2.6.5).

`_versionCache` is process-lived. It was never invalidated, so after the
`vibeic-eda` container was recreated on a NEW image (what a version bump does —
`docker rm/run` under the same name), eda_doctor kept reporting the PRE-swap tool
versions. Since eda_doctor's entire purpose is a fresh preflight, a stale report
can mask a wrong/old/foreign toolchain. The fix keys the cache on the container's
current image id and drops it when that id moves.

Static checks against src/index.js — no live docker daemon required.
"""
from pathlib import Path

INDEX_JS = Path(__file__).resolve().parent.parent / "src" / "index.js"
assert INDEX_JS.exists()
SRC = INDEX_JS.read_text()


def test_freshness_guard_defined():
    assert "function _ensureVersionCacheFresh(" in SRC, \
        "missing the version-cache freshness guard"


def test_guard_keys_on_container_image_id():
    seg = SRC[SRC.index("function _ensureVersionCacheFresh("):]
    seg = seg[:seg.index("function getToolVersion(")]
    # must inspect the container's image and clear the cache when it changes
    assert '"inspect"' in seg and "{{.Image}}" in seg, \
        "guard must read the container's current image id via docker inspect"
    assert "_versionCache.clear()" in seg, \
        "guard must drop the cache when the image id changed"
    assert "CONTAINER" in seg, "guard must inspect the configured EDA container"


def test_get_tool_version_calls_guard_before_cache_hit():
    body = SRC[SRC.index("function getToolVersion(name) {"):]
    body = body[:body.index("_versionCache.set(name")]
    call = body.index("_ensureVersionCacheFresh()")
    hit = body.index("_versionCache.has(name)")
    assert call < hit, "getToolVersion must refresh the cache BEFORE serving a cached hit"


def test_inspect_is_throttled():
    """A 14-tool doctor burst must not fire 14 docker inspects."""
    seg = SRC[SRC.index("function _ensureVersionCacheFresh("):]
    seg = seg[:seg.index("function getToolVersion(")]
    assert "_versionCacheCheckedAt" in seg and "Date.now()" in seg, \
        "guard must throttle the docker inspect with a timestamp"
