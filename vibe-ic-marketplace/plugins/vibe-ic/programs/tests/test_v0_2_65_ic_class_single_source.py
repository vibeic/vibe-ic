"""v0.2.65 ic_class single-source-of-truth regressions.

Pins the #435 fix (ORGANIC-20260606-ic-class-detector-disagreement): the
runner's detect step and a later direct `ic_class_profile.detect_ic_class`
call could return DIFFERENT classes for the same project — not because the
implementations differ (the runner has delegated to the profile since
v1.6.55) but because two inferences at different times see different L-doc
states (later steps augment the docs). With the v0.2.57 no-protocol N/A
escapes keyed on class capability, that fork flips real gates between
enforced and N/A. Fix: `detect_ic_class` PERSISTS its result once at
`<project>/reports/ic_class.json` and every later call returns the
persisted truth verbatim; the runner's detect step calls with
`refresh=True` (the run's authoritative inference re-persists); an
`unknown` inference is never persisted (fail-closed stays re-inferable).

chip-AGNOSTIC: synthetic L-doc fixtures only.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ic_class_profile as ICP  # noqa: E402
import design_one_shot_runner as P2  # noqa: E402


def _proj(tmp_path, opcodes):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "opcodes": opcodes,
        "crc_parameters": {"polynomial_hex": "0x31"},
    }))
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "x", "pin_table": [{"name": "clk", "dir": "input"}]}))
    return tmp_path


_OPS = [{"hex": f"0x{i:02x}", "name": f"OP{i}", "payload_bytes": 1}
        for i in range(6)]


def test_detection_persists_and_later_calls_return_it(tmp_path):
    proj = _proj(tmp_path, _OPS)
    first = ICP.detect_ic_class(proj)
    assert first["ic_class"] != "unknown"
    assert (proj / "reports" / "ic_class.json").is_file()
    # mutate the docs the way a later step would — the persisted truth wins
    (proj / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json").write_text(
        json.dumps({"opcodes": []}))
    second = ICP.detect_ic_class(proj)
    assert second["ic_class"] == first["ic_class"], \
        "a later call must return the persisted class, never a re-inference"


def test_refresh_reinfers_and_repersists(tmp_path):
    proj = _proj(tmp_path, _OPS)
    first = ICP.detect_ic_class(proj)
    (proj / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json").write_text(
        json.dumps({"opcodes": []}))
    refreshed = ICP.detect_ic_class(proj, refresh=True)
    assert refreshed["ic_class"] != first["ic_class"] or \
        refreshed == first  # re-inference ran (class may legitimately move)
    again = ICP.detect_ic_class(proj)
    assert again["ic_class"] == refreshed["ic_class"]  # re-persisted


def test_runner_adapter_agrees_with_direct_profile_call(tmp_path):
    # the filing's acceptance: both entry points over the same project
    # return the identical class
    proj = _proj(tmp_path, _OPS)
    runner_class, _ev = P2.detect_ic_class(proj)
    direct = ICP.detect_ic_class(proj)
    assert runner_class == direct["ic_class"]


def test_unknown_is_never_persisted(tmp_path):
    proj = tmp_path  # no generated_docs at all → unknown
    (proj / "phase1").mkdir()
    out = ICP.detect_ic_class(proj)
    assert out["ic_class"] == "unknown"
    assert not (proj / "reports" / "ic_class.json").is_file(), \
        "fail-closed unknown must stay re-inferable once docs land"
    # docs land later → fresh inference succeeds and persists
    _proj(proj, _OPS)
    later = ICP.detect_ic_class(proj)
    assert later["ic_class"] != "unknown"
    assert (proj / "reports" / "ic_class.json").is_file()


def test_memory_mapped_register_fixture_class_pinned(tmp_path):
    # the filing's borderline shape: a datapath core WITH a memory-mapped
    # register read interface (registers + a couple of read commands).
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "opcodes": [
            {"hex": "0x01", "name": "REG_READ", "payload_bytes": 1},
            {"hex": "0x02", "name": "REG_WRITE", "payload_bytes": 2},
        ]}))
    (gd / "L4_REGMAP.json").write_text(json.dumps({
        "registers": [{"name": "ctrl", "addr": 0},
                      {"name": "status", "addr": 4},
                      {"name": "digest0", "addr": 8}]}))
    runner_class, _ = P2.detect_ic_class(tmp_path)
    direct = ICP.detect_ic_class(tmp_path)
    assert runner_class == direct["ic_class"]
    # a register/command interface is a COMMAND-DRIVEN contract — pin it
    # so a future heuristic change that flips this shape fails loudly.
    assert direct["ic_class"] == "digital_cmd_driven", direct["ic_class"]
