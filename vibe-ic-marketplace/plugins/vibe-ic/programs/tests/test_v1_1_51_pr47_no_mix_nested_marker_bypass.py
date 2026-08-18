"""Step-2.7 §4.05 anti-gaming hardening of PR #47's NO-MIX invariant (gatekeeper
remediation). PR #47 lets the benchmark agent author plugin/MCP fixes via PR, kept
honest by NO-MIX: a single change set may carry benchmark RESULTS (benchmark-data/)
OR plugin/MCP EDITS, never BOTH (so a hand-patch can't ride the run whose number it
inflates). Step-2.7 reproduced a HIGH BYPASS: normalize_path() re-truncated an
ALREADY-repo-root-relative path at the first list-order marker with idx>0, so a
result path that NESTS a later marker (`benchmark-data/run/work/vibe-ic-marketplace/
.../SCORE.md`) lost its `benchmark-data/` zone → has_result went False → NO-MIX did
NOT fire on a genuinely mixed result+plugin PR. The same strip mis-classified a
legit `benchmark-data/.../IP/...` result (false-positive) and a plugin
`.../vibe-ic-marketplace/plugins/vibe-ic/tools/...` file (NO-MIX false-negative).
Fixed: normalize_path no longer re-truncates a path that already starts at a zone
marker, and cuts a genuinely-absolute path at the LEFTMOST marker.
"""
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import agent_checkin_scope_guard as G  # noqa: E402

_PLUGIN = "vibe-ic-marketplace/plugins/vibe-ic/programs/spec_conformance_check.py"
_MCP = "vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/server.py"
_PLUGIN_TOOLS = "vibe-ic-marketplace/plugins/vibe-ic/tools/phase1_engine/render.py"


def _no_mix(paths):
    return any(v["zone"].startswith("NO-MIX") for v in G.evaluate("benchmark-agent", paths))


def test_normalize_path_keeps_leading_zone_when_a_later_marker_nests():
    # the HIGH bug: an already-rooted result path that embeds a later marker must
    # KEEP its leading benchmark-data/ zone (was truncated to vibe-ic-marketplace/).
    assert G.normalize_path(
        "benchmark-data/v0353/work/vibe-ic-marketplace/plugins/vibe-ic/SCORE.md"
    ) == "benchmark-data/v0353/work/vibe-ic-marketplace/plugins/vibe-ic/SCORE.md"
    assert G.normalize_path("benchmark-data/run/IP/spm/x.json") == "benchmark-data/run/IP/spm/x.json"
    assert G.normalize_path(_PLUGIN_TOOLS) == _PLUGIN_TOOLS


def test_no_mix_fires_on_nested_marker_result_plus_plugin():
    # the anti-gaming bypass: a mixed result (with a nested marker) + plugin edit
    # MUST trip NO-MIX (else a hand-patch rides the run whose number it inflates).
    assert _no_mix(["benchmark-data/v0353/work/vibe-ic-marketplace/plugins/vibe-ic/SCORE.md", _PLUGIN])
    assert _no_mix(["benchmark-data/run/IP/spm/RESULT.json", _PLUGIN])
    assert _no_mix(["benchmark-data/run/scores.json", _PLUGIN_TOOLS])   # plugin tools/ subdir
    assert _no_mix(["benchmark-data/run/scores.json", _MCP])            # MCP still fires


def test_legit_benchmark_data_result_under_ip_subdir_is_in_scope():
    # false-positive guard: a real result under benchmark-data/.../IP/ (the canonical
    # ic roster has IP/ subdirs) must NOT be rejected as out-of-scope.
    assert G.evaluate("benchmark-agent", ["benchmark-data/run42/IP/spm/RESULT_SCORE.json"]) == []


def test_pure_channels_clean_and_absolute_rerooting_preserved():
    assert G.evaluate("benchmark-agent", ["benchmark-data/run/score.json", "benchmark-data/run/RESULT.md"]) == []
    assert G.evaluate("benchmark-agent", [_PLUGIN]) == []
    assert not _no_mix([_PLUGIN, _MCP])     # two plugin/MCP edits, no result → no NO-MIX
    # genuinely-absolute paths still re-root to repo-root-relative
    assert G.normalize_path("/home/u/vibe-ic-pr/gk/benchmark-data/run/x.json") == "benchmark-data/run/x.json"
    assert G.normalize_path("/abs/p/vibe-ic-marketplace/plugins/vibe-ic/p.py") == "vibe-ic-marketplace/plugins/vibe-ic/p.py"


def test_canonicalizes_redundant_separators_defense_in_depth():
    # defense-in-depth (manual --paths route): a `//` or mid-path `/./` must not
    # defeat the startswith-zone check and weaken NO-MIX.
    assert G.normalize_path("vibe-ic-marketplace//plugins/vibe-ic/x.py") == \
        "vibe-ic-marketplace/plugins/vibe-ic/x.py"
    assert G.normalize_path("vibe-ic-marketplace/./plugins/vibe-ic/x.py") == \
        "vibe-ic-marketplace/plugins/vibe-ic/x.py"
    assert _no_mix(["benchmark-data/run/s.json", "vibe-ic-marketplace/./plugins/vibe-ic/programs/x.py"])
    assert _no_mix(["benchmark-data/run/s.json", "vibe-ic-marketplace//plugins/vibe-ic/programs/x.py"])


def test_role_matrix_intact():
    # field-agent still cannot touch the plugin; repo-gatekeeper is NO-MIX-exempt.
    assert G.evaluate("field-agent", [_PLUGIN]) != []
    assert not any(v["zone"].startswith("NO-MIX")
                   for v in G.evaluate("repo-gatekeeper", ["benchmark-data/s.json", _PLUGIN]))


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
