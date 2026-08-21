#!/usr/bin/env python3
"""Tests for the container-visibility pre-flight (v0.1.11).

Files staged onto the host bind mount via a restricted/sandboxed shell do
not always propagate into the `vibeic-eda` container; the raw EDA tool then
emits an opaque "cannot find file" and the caller cannot distinguish a
staging miss from a real RTL error. `missingInContainer()` checks existence
INSIDE the container and tool wrappers return an actionable `stagingHint()`.

Tests are STATIC checks against src/index.js so they don't require a live
docker daemon. Wiring (helper defined + called by eda_lint / eda_synth
before dockerExec, with a hint that names the mount and the sandbox caveat)
is what we lock here.
"""
from pathlib import Path

INDEX_JS = Path(__file__).resolve().parent.parent / "src" / "index.js"
assert INDEX_JS.exists()


def test_helpers_defined():
    src = INDEX_JS.read_text()
    assert "function missingInContainer(" in src, \
        "missingInContainer pre-flight helper missing"
    assert "function stagingHint(" in src, \
        "stagingHint helper missing"


def test_preflight_checks_existence_in_container():
    """The helper must test existence INSIDE the container (docker exec
    test/-e), not just on the host — that's what makes it mount-agnostic."""
    src = INDEX_JS.read_text()
    seg = src[src.index("function missingInContainer("):]
    seg = seg[:seg.index("function stagingHint(")]
    assert "docker" in seg and "exec" in seg, \
        "missingInContainer must probe inside the container via docker exec"
    assert "[ -e " in seg, \
        "missingInContainer must test path existence with `[ -e ... ]`"


def test_preflight_does_not_block_when_docker_unreachable():
    """When docker is unreachable the helper must return [] (dockerExec
    reports that case); otherwise every call would be blocked spuriously."""
    src = INDEX_JS.read_text()
    seg = src[src.index("function missingInContainer("):]
    seg = seg[:seg.index("function stagingHint(")]
    assert "_probeDocker()" in seg and "return [];" in seg, \
        "missingInContainer must short-circuit to [] on unreachable docker"


def test_hint_names_mount_and_sandbox_caveat():
    """The hint is the actionable payload — it must name the mount mapping
    and warn about the sandboxed-copy non-propagation that caused the miss."""
    src = INDEX_JS.read_text()
    seg = src[src.index("function stagingHint("):]
    seg = seg[:seg.index("\n}\n")]
    assert "/foss/designs" in seg, "hint must name the container mount target"
    assert "sandbox" in seg.lower(), \
        "hint must warn that a sandboxed host copy may not propagate"


def test_eda_lint_calls_preflight_before_dockerexec():
    src = INDEX_JS.read_text()
    lint = src[src.index('"eda_lint"'):]
    lint = lint[:lint.index('"eda_simulate"')]
    assert "missingInContainer(verilog_files)" in lint, \
        "eda_lint must pre-flight its inputs"
    assert lint.index("missingInContainer(verilog_files)") < lint.index("dockerExec("), \
        "eda_lint pre-flight must run BEFORE dockerExec"


def test_eda_synth_calls_preflight_before_dockerexec():
    src = INDEX_JS.read_text()
    synth = src[src.index('"eda_synth"'):]
    synth = synth[:synth.index('"eda_lint"')] if '"eda_lint"' in synth[1:] else synth
    assert "missingInContainer(verilog_files)" in synth, \
        "eda_synth must pre-flight its inputs"
    assert synth.index("missingInContainer(verilog_files)") < synth.index("dockerExec("), \
        "eda_synth pre-flight must run BEFORE dockerExec"
