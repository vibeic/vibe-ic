"""The area unit was unestablished because the resolver looked on the wrong disk.

`_area_unit.resolve_from_registry` recovers the search root from the Liberty it
is handed, and then looked for the cell LEF on the LOCAL filesystem. For a PDK
that ships INSIDE the EDA image that root does not exist here at all, and the
refusal was published as though the REGISTRY were wrong.

MEASURED on spm x gf180mcuD (run spm_manual_1.14.30, plugin v1.14.30). The
Liberty recorded by the synthesis step is
`/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/..._tt_025C_5v00.lib`
— a CONTAINER path, because yosys ran in the container and that is the path it
knew. On the host `ls -d /foss` is "No such file or directory", and
`docker inspect vibeic-eda` shows the only mounts are the designs directory.
Inside the container the declared glob resolves to exactly one file
(`libs.ref/gf180mcu_fd_sc_mcu7t5v0/lef/gf180mcu_fd_sc_mcu7t5v0.lef`, 671072
bytes). So `stats.json` published

    "reason": "the registry entry whose layout matches this Liberty declares
               cell_lef_glob='libs.ref/.../lef/*.lef', which matches no file
               under /foss/pdks/gf180mcuD"

which is FALSE — one file matches it — and `area_total_vs_budget_check` then
named the unestablished unit as a missing authority on every gf180mcuD run.

THE LOAD-BEARING NEGATIVE CONTROL is
`test_a_root_that_is_here_and_matches_nothing_keeps_the_original_refusal`. The
fix separates "the root is not on this filesystem" from "the root is here and
the glob matched nothing". Collapsing them back — answering both with the
container, or both with the same sentence — is how a genuinely wrong registry
entry would stop being reported.
"""
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _area_unit as A          # noqa: E402

_REGISTRY_ENTRY = {
    "pdks": [{
        "name": "x",
        "liberty_glob": "libs.ref/scl/lib/*.lib",
        "cell_lef_glob": "libs.ref/scl/lef/*.lef",
    }]
}

# A Liberty and a LEF that AGREE. `_area_unit.MIN_CELLS` is 8 — agreement over
# a handful of cells is a coincidence, not a unit — so the fixture carries ten.
_CELLS = [(f"C{i}", 2.0, 3.0 + i) for i in range(10)]
_LIB = "library (scl) {\n" + "".join(
    f"  cell ({n}) {{\n    area : {w * h} ;\n  }}\n" for n, w, h in _CELLS
) + "}\n"
_LEF = "".join(
    f"MACRO {n}\n  SIZE {w} BY {h} ;\nEND {n}\n" for n, w, h in _CELLS)


def _stage(root: Path) -> Path:
    import json
    (root / "libs.ref/scl/lib").mkdir(parents=True)
    (root / "libs.ref/scl/lef").mkdir(parents=True)
    (root / "libs.ref/scl/lib/tt.lib").write_text(_LIB)
    (root / "libs.ref/scl/lef/scl.lef").write_text(_LEF)
    reg = root / "pdk_registry.json"
    reg.write_text(json.dumps(_REGISTRY_ENTRY))
    return reg


class _FakeContainer:
    """A reader for a PDK this process cannot see, standing in for the image.

    It answers ONLY for paths under `mount`, mapping them to `real` — exactly
    the relationship a container path has to the bytes on some other
    filesystem. Nothing here talks to docker: the property under test is that
    the resolver ASKS the reader instead of assuming the local disk.
    """

    def __init__(self, mount: str, real: Path):
        self.name = f"container fake({mount})"
        self.mount, self.real = mount.rstrip("/"), real

    def _map(self, path: str):
        if not str(path).startswith(self.mount):
            return None
        return self.real / str(path)[len(self.mount):].lstrip("/")

    def exists(self, path):
        p = self._map(path)
        return bool(p and p.exists())

    def glob(self, root, pattern):
        p = self._map(root)
        if p is None:
            return []
        base = str(root).rstrip("/")
        return sorted(f"{base}/{q.relative_to(p).as_posix()}"
                      for q in p.glob(pattern) if q.is_file())

    def read(self, path):
        p = self._map(path)
        try:
            return p.read_text() if p else None
        except OSError:
            return None


def test_a_root_absent_here_is_reported_as_absent_not_as_an_empty_glob(tmp_path):
    """The published sentence must not blame a registry entry for a directory
    this process simply cannot see."""
    reg = _stage(tmp_path)
    lef, why = A.resolve_from_registry(
        Path("/foss/pdks/nowhere/libs.ref/scl/lib/tt.lib"), reg, reader=A.HOST)
    assert lef is None
    assert "does not exist on this filesystem" in why, why
    assert "matches no file" not in why, (
        "the old sentence blames the registry for a root that is not here")


def test_a_root_that_is_here_and_matches_nothing_keeps_the_original_refusal(tmp_path):
    """NEGATIVE CONTROL. A genuinely wrong registry entry must still be named
    as one — the two refusals are different findings and must stay different."""
    import json
    reg = _stage(tmp_path)
    reg.write_text(json.dumps({"pdks": [{
        "name": "x",
        "liberty_glob": "libs.ref/scl/lib/*.lib",
        "cell_lef_glob": "libs.ref/scl/nowhere/*.lef"}]}))
    lef, why = A.resolve_from_registry(
        tmp_path / "libs.ref/scl/lib/tt.lib", reg, reader=A.HOST)
    assert lef is None
    assert "matches no file under" in why, why


def test_the_container_reader_resolves_what_the_host_cannot(tmp_path):
    """The whole fix, in one assertion: same Liberty path, same registry, and
    the answer depends only on WHERE the resolver was told to look."""
    real = tmp_path / "image"
    real.mkdir()
    reg = _stage(real)
    lib = "/foss/pdks/x/libs.ref/scl/lib/tt.lib"

    lef_host, why_host = A.resolve_from_registry(Path(lib), reg, reader=A.HOST)
    assert lef_host is None and "does not exist on this filesystem" in why_host

    rd = _FakeContainer("/foss/pdks/x", real)
    lef_c, why_c = A.resolve_from_registry(Path(lib), reg, reader=rd)
    assert why_c is None
    assert str(lef_c).endswith("libs.ref/scl/lef/scl.lef"), lef_c


def test_the_unit_is_ESTABLISHED_through_the_reader(tmp_path):
    """MEASURED on the real gf180mcuD library through the real container
    reader: established True, unit um^2, 229 cells compared, ratio median
    exactly 1.0, interquartile spread 2.2e-16 against a tolerance of 0.01."""
    real = tmp_path / "image"
    real.mkdir()
    reg = _stage(real)
    lib = "/foss/pdks/x/libs.ref/scl/lib/tt.lib"
    rd = _FakeContainer("/foss/pdks/x", real)
    lef, _why = A.resolve_from_registry(Path(lib), reg, reader=rd)
    rec = A.derive(Path(lib), lef, reader=rd)
    assert rec["established"] is True, rec
    assert rec["unit"] == "um^2"
    assert rec["cells_compared"] == len(_CELLS)


def test_a_liberty_in_ANOTHER_UNIT_is_not_established(tmp_path):
    """NEGATIVE CONTROL. The reader changes WHERE we look, never WHETHER the
    numbers agree. A unit difference is a COMMON FACTOR across the library —
    which is exactly what `derive` tests for — so a Liberty stated in a
    hundredth of a micron squared must stay unestablished however it was
    reached. Reaching the file is not the same as believing it."""
    import re as _re
    real = tmp_path / "image"
    real.mkdir()
    reg = _stage(real)
    scaled = _re.sub(r"area : ([\d.]+) ;",
                     lambda m: f"area : {float(m.group(1)) * 100} ;", _LIB)
    (real / "libs.ref/scl/lib/tt.lib").write_text(scaled)
    rd = _FakeContainer("/foss/pdks/x", real)
    lib = "/foss/pdks/x/libs.ref/scl/lib/tt.lib"
    lef, _why = A.resolve_from_registry(Path(lib), reg, reader=rd)
    rec = A.derive(Path(lib), lef, reader=rd)
    assert rec["established"] is False, rec
    assert rec["unit"] is None
    assert "centred on 100" in rec["reason"], rec["reason"]


def test_a_single_outlier_is_DISCLOSED_and_does_not_block(tmp_path):
    """The shipped rule is a POPULATION judgement — median centred, spread
    coherent — not "every cell agrees", and its own docstring used to claim
    otherwise. Pinned here so the two cannot drift again: one odd cell is
    reported in `cells_outside_tolerance`, and the unit still stands."""
    real = tmp_path / "image"
    real.mkdir()
    reg = _stage(real)
    (real / "libs.ref/scl/lib/tt.lib").write_text(
        _LIB.replace("area : 6.0 ;", "area : 600.0 ;"))
    rd = _FakeContainer("/foss/pdks/x", real)
    lib = "/foss/pdks/x/libs.ref/scl/lib/tt.lib"
    lef, _why = A.resolve_from_registry(Path(lib), reg, reader=rd)
    rec = A.derive(Path(lib), lef, reader=rd)
    assert rec["established"] is True, rec
    assert rec["cells_outside_tolerance"] == 1, rec
    assert rec["outliers"] and rec["outliers"][0]["cell"] == "C0"


def test_the_host_reader_is_still_the_default(tmp_path):
    """A staged, mounted PDK must behave exactly as before and cost no
    container call: omitting the reader means this filesystem."""
    reg = _stage(tmp_path)
    lef, why = A.resolve_from_registry(tmp_path / "libs.ref/scl/lib/tt.lib", reg)
    assert why is None and str(lef).endswith("scl.lef")


def test_a_reader_that_cannot_run_is_recorded_not_read_as_not_found(tmp_path):
    """The failure I shipped and the measurement caught: the first container
    reader swallowed every exception and passed a wrong keyword name, so a
    TypeError was published as 'that directory does not exist'. An unrunnable
    reader must reach the evidence as an unrunnable reader."""
    import synth_area_stats_emit as S

    class _Broken:
        name = "broken reader"

        def exists(self, path):
            raise RuntimeError("container is gone")

        def glob(self, root, pattern):
            raise RuntimeError("container is gone")

        def read(self, path):
            raise RuntimeError("container is gone")

    class _NoSuchHost:
        # The host must NOT be able to answer, whatever machine or image this
        # test runs in: the first shipping of this test hardcoded a shipped
        # /foss path and asserted the host lacks it, which is false inside the
        # EDA image — where the suite actually runs — so the host established
        # the unit and the broken reader was never consulted.
        name = "host filesystem"

        def exists(self, path):
            return False

        def glob(self, root, pattern):
            return []

        def read(self, path):
            raise FileNotFoundError(path)

    # A path the SHIPPED pdk_registry.json actually claims, so resolution
    # reaches the reader instead of refusing one step earlier.
    lib = ("/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/"
           "gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib")
    orig = A.container_reader
    orig_host = A.HOST
    try:
        A.container_reader = lambda c: _Broken() if c else None
        A.HOST = _NoSuchHost()
        _unit, ev = S._resolve_area_unit(Path(lib), container="anything")
    finally:
        A.container_reader = orig
        A.HOST = orig_host
    assert ev["established"] is False
    assert "could not run" in ev["reason"], ev
    assert "RuntimeError" in ev["reason"], ev
