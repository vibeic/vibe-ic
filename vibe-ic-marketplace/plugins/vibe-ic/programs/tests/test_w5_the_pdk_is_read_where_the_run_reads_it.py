"""W5/15.5ic -- the pad-ring audit asks the container the run's tools use.

THE DEFECT. `phase3_one_shot_runner` passes `--pdk-root` naming a path that
resolves INSIDE the EDA container. Every PDK question in `_pad_ring` was asked of
the HOST, so on a host without that PDK the tree list came back empty,
`IoLibrary.resolved` was False, and `pad_ring_check` refused

    PADRING_MASTERS_UNCORROBORATED -- "no PDK IO cell library resolved, so no
    declared master could be shown to be a PDK cell rather than a drawn shape"

about a run whose own in-container command had returned rc 0. The claim the step
exists to make was reported unverifiable because the audit looked in the wrong
filesystem.

THE SEAM is `_pdk_layer_authority._query`, this tree's one answer to "ask the PDK
where the run's tools are": `reader=None` selects `EDA_CONTAINER` when phase 3
published one and falls back to the local filesystem when it did not, and an
unreachable SELECTED container raises OSError instead of answering "absent".
That last property is the point -- absent is exactly what the old code reported
about a library that was simply somewhere else.
"""
import os
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _pad_ring as PR                                  # noqa: E402

_ROOT = "/pdks-that-exist-only-in-the-image"
_TREE = "gf180mcuD"                                     # an OPEN PDK
_LIB = f"{_ROOT}/{_TREE}/libs.ref/gf180mcu_fd_io"


class _ImageReader:
    """A filesystem that exists only inside the container, as a dict of paths."""

    def __init__(self, files):
        self.files = dict(files)
        self.dirs = set()
        for f in self.files:
            parts = Path(f).parts
            for i in range(1, len(parts)):
                self.dirs.add(str(Path(*parts[:i])))
        self.asked = []

    def is_dir(self, path):
        self.asked.append(("is_dir", str(path)))
        return str(path) in self.dirs

    def is_file(self, path):
        self.asked.append(("is_file", str(path)))
        return str(path) in self.files

    def glob(self, root, pattern):
        self.asked.append(("glob", f"{root}/{pattern}"))
        import fnmatch
        names = set(self.files) | self.dirs
        return sorted(n for n in names
                      if str(Path(n).parent) == str(root)
                      and fnmatch.fnmatch(Path(n).name, pattern))

    def read_text(self, path):
        self.asked.append(("read", str(path)))
        return self.files.get(str(path))


def _image():
    # a MACRO carrying a SIZE, which is what `parse_lef_macros` reads
    return _ImageReader({f"{_LIB}/lef/io.lef":
                         "MACRO PADX\n  CLASS PAD ;\n  SIZE 75.0 BY 260.0 ;\n"
                         "END PADX\n"})


# -- DIRECTION 1: the host does not have it, and says so honestly -------------
def test_a_host_without_the_pdk_resolves_nothing(monkeypatch, tmp_path):
    """Unchanged behaviour, and it must stay unchanged: with no container
    published and no PDK on disk, NOT RESOLVED is the honest answer."""
    monkeypatch.delenv("EDA_CONTAINER", raising=False)
    monkeypatch.delenv("VIBEIC_EDA_CONTAINER", raising=False)
    assert PR._pdk_trees(_ROOT, _TREE) == []
    assert PR.discover_io_lefs(_ROOT, _TREE) == []
    assert PR.IoLibrary(PR.discover_io_lefs(_ROOT, _TREE)).resolved is False


def test_a_host_that_does_have_the_pdk_still_reads_it(monkeypatch, tmp_path):
    """The local path is not broken by routing through the seam."""
    monkeypatch.delenv("EDA_CONTAINER", raising=False)
    monkeypatch.delenv("VIBEIC_EDA_CONTAINER", raising=False)
    lef = tmp_path / _TREE / "libs.ref" / "gf180mcu_fd_io" / "lef"
    lef.mkdir(parents=True)
    (lef / "io.lef").write_text(
        "MACRO PADX\n  CLASS PAD ;\n  SIZE 75.0 BY 260.0 ;\nEND PADX\n")
    assert [p.name for p in PR._pdk_trees(str(tmp_path), _TREE)] == [_TREE]
    assert [p.name for p in PR.discover_io_lefs(str(tmp_path), _TREE)] == ["io.lef"]


# -- DIRECTION 2: the container has it, and the audit finds it there ----------
def test_the_container_pdk_is_found_through_the_reader():
    """THE RED. These exact paths are absent from this host -- the previous test
    proves it -- and the library resolves anyway, because the question is asked
    where the run's tools would ask it."""
    reader = _image()
    assert [str(p) for p in PR._pdk_trees(_ROOT, _TREE, reader=reader)] == [
        f"{_ROOT}/{_TREE}"]
    lefs = PR.discover_io_lefs(_ROOT, _TREE, reader=reader)
    assert [str(p) for p in lefs] == [f"{_LIB}/lef/io.lef"]
    assert PR.IoLibrary(lefs, reader=reader).resolved is True, (
        "the central claim of step 15.5ic is corroborable once the library is "
        "read where it lives")
    assert any(op == "glob" for op, _ in reader.asked), reader.asked


def test_the_masters_come_back_from_the_container_copy():
    """Not merely resolved -- the master table is the container's own bytes."""
    reader = _image()
    lefs = PR.discover_io_lefs(_ROOT, _TREE, reader=reader)
    lib = PR.IoLibrary(lefs, reader=reader)
    assert "PADX" in lib.masters, sorted(lib.masters)
    assert lib.unread_lefs == [], lib.unread_lefs


def test_a_found_but_unreadable_lef_is_recorded_not_swallowed():
    """The other half of the same defect: `except OSError: continue` made a LEF
    that was FOUND and not READ indistinguishable from a PDK that ships none.
    The path is kept, so `resolved` False can be told from `resolved` False."""
    class _Unreadable(_ImageReader):
        def read_text(self, path):
            raise OSError("the container went away mid-audit")
    reader = _Unreadable(_image().files)
    lefs = PR.discover_io_lefs(_ROOT, _TREE, reader=reader)
    assert lefs, "the LEF must still be FOUND"
    lib = PR.IoLibrary(lefs, reader=reader)
    assert lib.resolved is False
    assert [str(q) for q in lib.unread_lefs] == [str(lefs[0])], (
        "a found-but-unread LEF must be named, not counted as absent")


# -- DIRECTION 3: selected-but-unreachable is an UNKNOWN, never an absence ----
def test_an_unreachable_selected_container_raises_rather_than_reporting_absence(
        monkeypatch):
    """The property the whole change turns on. If this returned [], the audit
    would once again refuse PADRING_MASTERS_UNCORROBORATED -- a statement about
    the PDK -- on the strength of a docker failure."""
    monkeypatch.setenv("EDA_CONTAINER", "no-such-container-w5-15-5ic")
    with pytest.raises(OSError) as exc:
        PR._pdk_trees(_ROOT, _TREE)
    assert "no-such-container-w5-15-5ic" in str(exc.value)
