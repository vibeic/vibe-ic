import hashlib
import json
from pathlib import Path

import pytest

import _pad_ring as pads
import test_pad_ring as ring


FIXTURE = Path(__file__).parent / "fixtures/pad_corner_gap_site_snap"


@pytest.mark.parametrize("count,between,start,end", [
    (4, 121_000, 123_000, 123_000),
    (7, 46_000, 47_000, 46_000),
    (5, 88_000, 89_000, 88_000),
    (8, 32_000, 33_000, 32_000),
])
def test_whole_sites_keep_pitch_and_put_extra_site_at_start(count, between, start, end):
    spacing = pads.side_spacing(80_000 * count, count, 929_000, 1_000)
    assert spacing == (between, start)
    assert 929_000 - 80_000 * count - between * (count - 1) - start == end


def test_an_odd_dbu_remainder_with_a_one_dbu_site_can_be_split():
    assert pads.side_spacing(3, 1, 8, 1) == (2, 3)


def test_a_remainder_off_the_site_grid_has_no_placement():
    assert pads.side_spacing(560_000, 7, 929_001, 1_000) is None


def project(tmp_path, *, die=1_300_000):
    counts = {"S": 4, "E": 7, "N": 5, "W": 8}
    signals = {side: [f"{side.lower()}signal{i}" for i in range(count)]
               for side, count in counts.items()}
    instances = {signal: f"pad_{signal}" for names in signals.values() for signal in names}
    config = ring._config(
        PAD_EDGE_SPACING=5.5,
        PAD_FILLERS=["pad_fill1"],
        SIGNAL_MAP={instance: signal for signal, instance in instances.items()},
        **{pads.SIDE_VAR[side]: [instances[n] for n in names] for side, names in signals.items()},
    )
    return ring._project(
        tmp_path, config=config,
        floorplan=ring._floorplan(pins=list(instances), instances=list(instances.values()), die=die),
        site_w=1.0, pad_w=80.0, corner_w=180.0,
    )


def test_half_site_corner_rows_close_with_one_um_fillers(tmp_path):
    root = project(tmp_path)
    assert ring._gen(root) == 0
    report = ring._report(root)
    expected = {"S": (121_000, 123_000, 123_000), "E": (46_000, 47_000, 46_000),
                "N": (88_000, 89_000, 88_000), "W": (32_000, 33_000, 32_000)}
    for side, (between, start, end) in expected.items():
        axis = "x" if side in "SN" else "y"
        placed = sorted((p for p in report["pads"] if p["side"] == side), key=lambda p: p[axis])
        assert report["spacing"][side]["between"] == between
        assert placed[0][axis] - 185_500 == start
        assert 1_114_500 - placed[-1][axis] - 80_000 == end
        assert all(b[axis] - a[axis] == 80_000 + between for a, b in zip(placed, placed[1:]))
    assert len(report["pads"]) == 24
    assert len(report["fillers"]) == 1_796
    assert all(f["master"] == "pad_fill1" for f in report["fillers"])
    assert report["abutment"]["abuts"]
    assert all(gap == 0 for gaps in report["abutment"]["gaps"].values() for gap in gaps)
    assert ring._chk(root) == 0


def test_truly_impossible_row_is_still_refused_by_name(tmp_path):
    root = project(tmp_path, die=1_300_001)
    assert ring._gen(root) == 1
    assert "PAD_CORNER_SPACING_NOT_SITE_MULTIPLE" in ring._rules(root)
    assert not ring._ring_def(root).exists()


def test_existing_centred_integer_def_bytes_are_unchanged(tmp_path):
    provenance = json.loads((FIXTURE / "PROVENANCE.json").read_text())
    expected = (FIXTURE / "centered.def").read_bytes()
    assert hashlib.sha256(expected).hexdigest() == provenance["centered_def_sha256"]
    root = ring._project(tmp_path)
    assert ring._gen(root) == 0
    assert ring._ring_def(root).read_bytes() == expected
    assert ring._chk(root) == 0
