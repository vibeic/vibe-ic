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

import pytest

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
        if argv[:3] == ["python3", "-c", A._REMOTE_GLOB_SCRIPT]:
            import fnmatch
            parent = Path(argv[3]) / Path(argv[4]).parent
            hits = [f for f in self.files if Path(f).parent == parent
                    and fnmatch.fnmatchcase(Path(f).name, Path(argv[4]).name)]
            return 0, json.dumps(sorted(hits))
        if argv[:3] == ["python3", "-c", A._REALPATH_SCRIPT]:
            return (0, argv[3] + "\n") if argv[3] in self.files else (1, "")
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


def test_a_container_reader_finds_a_magic_provider_without_claiming_invocation():
    vol = "/foss/pdks/somepdk"
    provider = f"{vol}/libs.tech/magic/seal_ring_generator/neutral_gen_sealring.py"
    rd, _ = _reader({provider: "# positional generator\n"})
    has, path, tried = A.seal_ring_facility(Path(vol), reader=rd)
    assert has is True and path == provider
    assert A.seal_ring_invocation_supported(Path(vol), path, reader=rd) is False
    assert any("libs.tech/magic/seal_ring_generator" in item for item in tried)


def test_magic_provider_reports_supported_invocation_only_for_declared_api():
    vol = "/foss/pdks/somepdk"
    provider = f"{vol}/libs.tech/magic/seal_ring_generator/neutral_gen_sealring.py"
    api = ("# Usage: neutral_gen_sealring.py width height target_dir [-outer] [-keep]\n"
           "def generate_sealring(width, height, target_dir):\n    pass\n")
    rd, _ = _reader({provider: api})
    assert A.seal_ring_invocation_supported(Path(vol), provider, reader=rd) is True
    unknown, _ = _reader({provider: "# no known interface\n"})
    assert A.seal_ring_invocation_supported(Path(vol), provider, reader=unknown) is False


def test_unreachable_remote_glob_is_unknown_not_process_absence():
    vol = Path("/foss/pdks/somepdk")
    def run(_identity, argv):
        if argv[:2] == ["test", "-f"]:
            return 1, ""
        return 127, ""
    for reader in (A.ContainerReader("lost-container", runner=run),
                   A.ImageReader("lost-image", runner=run)):
        has, path, tried = A.seal_ring_facility(vol, reader=reader)
        state = ("UNKNOWN" if has is None else
                 "ABSENT" if has is False else "AVAILABLE")
        assert state == "UNKNOWN", (reader.name, tried)
        assert path is None
        assert any("127" in item for item in tried)


@pytest.mark.parametrize("reader_type", [A.ContainerReader, A.ImageReader])
@pytest.mark.parametrize("method", ["is_dir", "is_file", "read_text"])
@pytest.mark.parametrize("transport_rc", [2, 127])
def test_remote_reader_distinguishes_transport_failure_from_absence(
        reader_type, method, transport_rc):
    reader = reader_type("unreachable", runner=lambda *_: (transport_rc, ""))
    try:
        value = getattr(reader, method)("/foss/pdks/neutral/missing")
        state = "ABSENT" if value in (False, None) else "PRESENT"
    except OSError as exc:
        state = "UNKNOWN"
        assert str(transport_rc) in str(exc)
    assert state == "UNKNOWN"
    absent = reader_type("reachable", runner=lambda *_: (1, ""))
    assert getattr(absent, method)("/foss/pdks/neutral/missing") in (False, None)


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


def test_magic_provider_is_available_even_without_a_klayout_provider(tmp_path):
    """#3258: unsupported invocation is not technology absence."""
    volume = tmp_path / "neutral_process"
    provider = volume / "libs.tech/magic/seal_ring_generator/neutral_gen_sealring.py"
    provider.parent.mkdir(parents=True)
    provider.write_text("# Usage: neutral_gen_sealring.py width height target_dir [-force] [-outer] [-keep]\n")
    available, path, tried = A.seal_ring_facility(volume)
    assert available is True, (available, path, tried)
    assert path == str(provider)


def test_native_seal_rung_does_not_grant_absence_na_for_a_magic_provider(tmp_path):
    volume = tmp_path / "neutral_process"
    provider = volume / "libs.tech/magic/seal_ring_generator/neutral_gen_sealring.py"
    provider.parent.mkdir(parents=True)
    provider.write_text("# neutral provider exists; invocation is a separate contract\n")
    available, path, tried = A.seal_ring_facility(volume)
    step = next(s for s in G.LADDER if s.step_id == "General.SealRing")
    ev = G.StepEvidence(step.step_id, step.label, step.order, step.source,
                        G.NOT_DETERMINED, step.refuses_on)
    G._step_delegate(ev, step, tmp_path, None, PROGRAMS, 1,
                     seal_required=G._decl.NOT_DETERMINED,
                     seal_facility=available, seal_facility_path=path,
                     seal_facility_tried=tried,
                     seal_deliverable=G._decl.DELIVERABLE_DIE,
                     seal_route=G._decl.ROUTE_SELF_TAPEOUT)
    assert ev.verdict == G.NOT_DETERMINED, ev.as_dict()
    assert "no seal-ring facility" not in ev.evidence


def test_multiple_magic_providers_are_available_but_not_arbitrarily_selected(tmp_path):
    import die_finishing_gen as finishing
    volume = tmp_path / "neutral_process"
    directory = volume / "libs.tech/magic/seal_ring_generator"
    directory.mkdir(parents=True)
    for name in ("first_gen_sealring.py", "second_gen_sealring.py"):
        (directory / name).write_text("# neutral provider\n")
    available, selected, tried = A.seal_ring_facility(volume)
    assert available is True and selected is None, (available, selected, tried)
    with pytest.raises(ValueError, match="ambiguous seal-ring providers"):
        finishing.resolve_script(tmp_path, None, str(tmp_path), "neutral_process")


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
