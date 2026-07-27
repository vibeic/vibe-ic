"""tests/test_analog_a2_topology_select_check.py — v1.6.35"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "analog_a2_topology_select_check.py")


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


def _topology(project: Path, block: str, body: str) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "topology.md").write_text(body)


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True,
    )


def test_happy_path(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _topology(tmp_path, "ldo",
              "# LDO topology\n\n"
              "Topology selected: PMOS pass-transistor regulator with "
              "cascode error amplifier and current-mirror bias network. "
              "Loop bandwidth ~1MHz with phase margin > 60deg.\n"
              + "Stage detail line.\n" * 5)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"


def test_missing_per_block_waived(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 2
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["suggested_skill"] == "analog-topology-select"


def test_too_small_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _topology(tmp_path, "ldo", "TBD\n")  # < 200B
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A2_TOPOLOGY_EMPTY" in f["rule"] for f in rpt["findings"])


def test_no_primitive_fails(tmp_path: Path) -> None:
    """Long file but no transistor/circuit primitive keyword → FAIL."""
    _block_list(tmp_path, ["ldo"])
    _topology(tmp_path, "ldo",
              "# Some heading\n\n"
              + "Lorem ipsum dolor sit amet consectetur adipiscing elit "
                "sed do eiusmod tempor incididunt ut labore et dolore "
                "magna aliqua ut enim ad minim veniam quis nostrud "
                "exercitation ullamco laboris nisi ut aliquip ex ea "
                "commodo consequat. Duis aute irure dolor in.\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A2_TOPOLOGY_NO_PRIMITIVE" in f["rule"]
               for f in rpt["findings"])


def test_multiblock_one_failing(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo", "bandgap"])
    _topology(tmp_path, "ldo",
              "Topology selected: cascode amplifier with current "
              "mirror loads and bandgap reference.\n" * 5)
    _topology(tmp_path, "bandgap", "TBD\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "FAIL"
    assert any(f["block"] == "bandgap" for f in rpt["findings"])


def test_no_block_list_vacuous(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS"


# ── the substance floor must be substance, not ordinary English ───────────
# The A2 "primitive" panel used to be one flat list that mixed real circuit
# vocabulary with six words any office memo contains — 'stage', 'load',
# 'switch', 'bias', 'driver', 'feedback'. Measured: the 486-byte paragraph
# below scored SIX hits and PASSed A2 with zero analog content.

_OFFICE_MEMO = (
    "# Company Picnic Committee Notes\n\n"
    "The first stage of the event planning went well. We had a good "
    "feedback session with the volunteers, and there was a load of "
    "paperwork to get through before the catering contract was signed. "
    "The driver of the shuttle bus confirmed he can do two runs. There "
    "is some bias toward the beach location among the committee, but we "
    "may switch to the park if the weather forecast worsens. Please "
    "bring your own chairs and a reference copy of the sign-up sheet.\n"
)


def test_ordinary_english_alone_does_not_satisfy_a2(tmp_path: Path) -> None:
    """THE discriminator. A long, well-formed document that names no circuit
    element must not certify that a topology was selected — however many
    ordinary English words it shares with the panel."""
    _block_list(tmp_path, ["ldo"])
    _topology(tmp_path, "ldo", _OFFICE_MEMO)
    assert len(_OFFICE_MEMO.encode()) >= 200, "fixture must clear the size gate"
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any(f["rule"] == "A2_TOPOLOGY_GENERIC_ONLY"
               for f in rpt["findings"]), rpt["findings"]


def test_guard_real_topology_with_generic_words_still_passes(
        tmp_path: Path) -> None:
    """Direction-1 guard: real topology prose is FULL of the generic words
    ('two-stage', 'active load', 'tail bias', 'feedback compensation'). Making
    them insufficient on their own must not make them disqualifying."""
    _block_list(tmp_path, ["ldo"])
    _topology(tmp_path, "ldo",
              "# ldo — topology\n\n"
              "Two-stage architecture. First stage: PMOS differential pair "
              "with an NMOS current mirror as the active load. Tail bias is "
              "a Widlar reference. Second stage: common-source output "
              "driver with Miller feedback compensation; the dominant pole "
              "sits at the output node and the zero is nulled with a "
              "series resistor.\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_guard_runner_deterministic_stub_topology_still_passes(
        tmp_path: Path) -> None:
    """Direction-1 guard: `analog_one_shot_runner._emit_deterministic_stub`
    writes this text for A2 so a stub dry-run is self-consistent. The gate
    must keep accepting it — the runner's own artefact failing the runner's
    own gate is the exact regression this fixture exists to catch."""
    bname = "ldo"
    _block_list(tmp_path, [bname])
    _topology(tmp_path, bname,
              f"<!-- deterministic_stub "
              f"extraction_strategy=deterministic_stub low_confidence=true\n"
              f"# {bname} — topology (stub)\n\n"
              f"Topology family: generic class-A amplifier (placeholder)\n\n"
              f"Primitive skeleton (deterministic stub — replace with the "
              f"`analog-topology-select` skill output):\n"
              f"- differential pair: NMOS input transistors\n"
              f"- active load: PMOS current mirror\n"
              f"- tail bias: NMOS current source (bias)\n"
              f"- output stage: common-source PMOS with feedback "
              f"compensation\n\n"
              f"Replace with output of `analog-topology-select` skill.\n"
              "-->\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_guard_document_with_no_vocabulary_keeps_no_primitive_rule(
        tmp_path: Path) -> None:
    """Direction-1 guard: a file that hits NEITHER panel keeps reporting
    A2_TOPOLOGY_NO_PRIMITIVE, not the new generic-only rule."""
    _block_list(tmp_path, ["ldo"])
    _topology(tmp_path, "ldo",
              "# Heading\n\n" + "Nulla pariatur excepteur sint occaecat "
              "cupidatat non proident sunt in culpa qui officia deserunt "
              "mollit anim id est laborum ut perspiciatis unde omnis iste "
              "natus error sit voluptatem accusantium doloremque.\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any(f["rule"] == "A2_TOPOLOGY_NO_PRIMITIVE"
               for f in rpt["findings"]), rpt["findings"]
