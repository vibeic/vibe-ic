"""U23: the per-layer density FILL measures on the stream that ships must be
where the tape-out precheck's density delegate reads it.

Measured on a subservient DIE tree (FILL proof lane, 8hd-3, 2026-09-29):
`phase3/librelane/37-proof-final-density-ratios/density_ratios.json` held a
MEASURED per-rule density of the finished stream, while general_precheck's
Checker.KLayoutDensity ran `metal_layer_density_check reports/phase3` and came
back NOT_DETERMINED: "no density report at .../reports/phase3". The measured
rows are carried verbatim in `data/u23_density_path/density_ratios.json`.

One canonical place (`reports/phase3/metal_density.json`, where the direct
path's emitter and every reader already put it): the producer moves, the reader
is not taught a second path.
"""
import hashlib
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import librelane_fill_dfm as fill  # noqa: E402
from test_die_density_finish import _put



def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()








STALE = {"gds": "phase3/stage3/pnr/chip_top.gds", "gds_sha256": "f" * 64,
         "layers": {f"metal{i}": 0.5 for i in range(1, 6)}}








def test_two_values_for_one_layer_publish_nothing(tmp_path):
    gds = tmp_path / "chip.gds"
    gds.write_bytes(b"x")
    _put(tmp_path / fill.METAL_DENSITY_REL, STALE)
    ratios = {"subject_sha256": _sha(gds), "layers": {
        "M1.4": {"status": "MEASURED", "identifier": "metal1", "ratio": 0.4},
        "M1.9": {"status": "MEASURED", "identifier": "metal1", "ratio": 0.5}}}
    assert fill.publish_metal_density(tmp_path, ratios, gds, "p") is None
    assert not (tmp_path / fill.METAL_DENSITY_REL).exists()
