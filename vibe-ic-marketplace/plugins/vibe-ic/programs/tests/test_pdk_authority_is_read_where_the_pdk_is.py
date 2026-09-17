"""The technology's own files are read where they ARE — inside the image.

Every path `_pdk_layer_authority` looks at is a CONTAINER path: the registry's
`container_path` and `$PDK_ROOT/<name>` both name `/foss/pdks/...`.
`general_precheck` runs on the HOST, spawned by `tapeout_precheck`, and the
host has no `/foss`. MEASURED on spm x gf180mcuD (v1.22.10, run5):

    volume_resolution: "no volume for 'gf180mcuD' in the registry or under
                        $PDK_ROOT"
    volume_tried:      ["/foss/pdks/gf180mcuD", "/foss/pdks/gf180mcuD"]

so `General.ForbiddenLayers` reported NOT_DETERMINED over 37 layer/datatype
pairs and `General.SealRing` could not reach the facility question either — on
every host-side run, for every PDK. With the container named, the same three
readings are taken through it; MEASURED against the pinned image's gf180mcuD:
volume `/foss/pdks/gf180mcuD`, 118 layer/datatype pairs from
`libs.tech/klayout/tech/gf180mcu.lyp` (the figure this module's own docstring
records), seal-ring facility `libs.tech/klayout/tech/scripts/sealring.py`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _pdk_layer_authority as A  # noqa: E402
import general_precheck as G  # noqa: E402
import tapeout_precheck as T  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402

_LYP = """<layer-properties>
 <properties><source>metal1 34/0@1</source></properties>
 <properties><source>metal2 36/0@1</source></properties>
</layer-properties>
"""


class _FakeContainer:
    """A container whose filesystem is a dict: {path: text}, dirs implied."""

    def __init__(self, files):
        self.files = dict(files)
        self.calls = []

    def __call__(self, container, argv):
        self.calls.append(argv)
        if argv[:2] == ["test", "-d"]:
            p = argv[2].rstrip("/") + "/"
            return (0 if any(f.startswith(p) for f in self.files) else 1), ""
        if argv[:2] == ["test", "-f"]:
            return (0 if argv[2] in self.files else 1), ""
        if argv[0] == "cat":
            return (0, self.files[argv[2 - 1]]) if argv[1] in self.files else (1, "")
        if argv[0] == "bash":
            import fnmatch
            pat = argv[2].split("ls -1d ", 1)[1].split(" 2>")[0].strip("'")
            hits = [f for f in self.files if fnmatch.fnmatch(f, pat)]
            return (0 if hits else 1), "\n".join(sorted(hits))
        return 127, ""


def _reader(files):
    fake = _FakeContainer(files)
    rd = A.ContainerReader("some-container", runner=fake)
    return rd, fake


def test_a_container_reader_answers_the_three_readings(tmp_path):
    vol = "/foss/pdks/somepdk"
    rd, fake = _reader({
        f"{vol}/libs.tech/klayout/tech/somepdk.lyp": _LYP,
        f"{vol}/libs.tech/klayout/tech/scripts/sealring.py": "print()\n",
    })
    registry = tmp_path / "reg.json"
    registry.write_text(json.dumps({"pdks": [{"name": "somepdk",
                                              "container_path": vol}]}))
    volume, why, tried = A.resolve_volume("somepdk", registry_path=registry,
                                          reader=rd)
    assert str(volume) == vol, (why, tried)
    pairs, authority, _ = A.layer_table(volume, reader=rd)
    assert pairs == {(34, 0), (36, 0)} and authority.endswith("somepdk.lyp")
    has, path, _ = A.seal_ring_facility(volume, reader=rd)
    assert has is True and path.endswith("scripts/sealring.py")
    assert rd.name == "container:some-container"


def test_the_same_pdk_is_unreadable_from_the_host_filesystem(tmp_path):
    """The defect, stated as a test: a container path is not a host path."""
    registry = tmp_path / "reg.json"
    registry.write_text(json.dumps({"pdks": [{"name": "somepdk",
                                              "container_path": "/foss/pdks/somepdk"}]}))
    volume, why, tried = A.resolve_volume("somepdk", registry_path=registry,
                                          environ={})
    assert volume is None and "no volume for 'somepdk'" in why
    # tier 1 (registry name) and tier 2 (registry basename) both look there
    assert tried == ["/foss/pdks/somepdk", "/foss/pdks/somepdk"]
    assert A.layer_table(None)[0] is None
    assert A.seal_ring_facility(None)[0] is None


def test_an_unreadable_file_is_not_a_table_and_never_an_empty_allowed_set(tmp_path):
    vol = "/foss/pdks/somepdk"
    rd, fake = _reader({f"{vol}/libs.tech/klayout/tech/x.lyp": "<not a table/>"})
    registry = tmp_path / "reg.json"
    registry.write_text(json.dumps({"pdks": [{"name": "somepdk",
                                              "container_path": vol}]}))
    volume, _, _ = A.resolve_volume("somepdk", registry_path=registry, reader=rd)
    pairs, authority, tried = A.layer_table(volume, reader=rd)
    assert pairs is None and authority is None and tried  # named what it tried
    has, path, _ = A.seal_ring_facility(volume, reader=rd)
    assert has is False and path is None       # the volume is here; no facility


def test_no_container_is_the_previous_behaviour_exactly():
    assert isinstance(A.container_reader(None), A.LocalReader)
    assert isinstance(A.container_reader(""), A.LocalReader)
    assert isinstance(A.container_reader("c"), A.ContainerReader)


def test_the_chain_forwards_the_container_from_the_runner_to_the_ladder():
    import inspect
    runner = inspect.getsource(R.step_declared_signoff_gates)
    assert '"--pdk-container", container' in runner
    assert "_PDK_AWARE_SIGNOFF_GATES" in runner
    tp = Path(T.__file__).read_text()
    assert '"--pdk-container", pdk_container' in tp
    gp = inspect.signature(G.evaluate).parameters
    assert "pdk_container" in gp and gp["pdk_container"].default is None
    assert "--pdk-container" in Path(G.__file__).read_text()


def test_the_report_names_which_filesystem_answered(tmp_path):
    """A reading that could be local or container-side must say which it was.

    The ladder needs a layout to get as far as the technology block; an
    unreadable one is enough, and its own rung reports that honestly."""
    layout = tmp_path / "x.gds"
    layout.write_bytes(b"not a gds")
    rep = G.evaluate(project=tmp_path, pdk="somepdk", layout=layout,
                     pdk_container="some-container", timeout=1.0)
    assert rep.technology["volume_read_through"] == "container:some-container"
    rep2 = G.evaluate(project=tmp_path, pdk="somepdk", layout=layout,
                      timeout=1.0)
    assert rep2.technology["volume_read_through"] == "local"
