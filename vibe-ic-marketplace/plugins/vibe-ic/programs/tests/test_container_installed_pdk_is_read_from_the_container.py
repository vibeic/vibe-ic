"""A container-installed PDK cannot be read with a host filesystem reader.

`resolve_deck_context` accepted a `reader` and its docstring said the caller
supplies "local read or container read" — but every call site left it
defaulted, and the default did a HOST `Path(path).read_text()`. Measured:
`/foss/pdks` is absent on the host and present in the container, while the
resolver reported `source: container_installed` with 32 libs. Every lib read as
unreadable, the deck context came back empty, and the emitter reported
`NEEDS_NATIVE_TEMPLATE` — "this PDK does not ship what we need" — when the PDK
ships it and nothing had looked.

Control on the real PDK, same call, only the reader changed:

    host reader       device_map {}                          NEEDS_NATIVE_TEMPLATE
    container reader  {nmos: sg13_hv_nmos, pmos: sg13_hv_pmos}  OK, section mos_tt

WHY IT HID: `resolve_deck_context` routes sky130/gf180 to
`known_family_context`, which never parses a lib. Only an UNKNOWN
container-installed family reaches the parsing path, so the two PDKs everything
is tested against could not expose it.

Chip-AGNOSTIC: reader plumbing. No design, vendor or part number involved.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))


def _mod():
    import analog_pdk_deck_context
    return analog_pdk_deck_context


def test_the_dispatcher_exposes_a_container_parameter():
    import inspect
    sig = inspect.signature(_mod().resolve_deck_context)
    assert "container" in sig.parameters, (
        "the dispatcher cannot choose a container reader without knowing the "
        "container")


def test_a_container_reader_falls_back_to_docker_exec(monkeypatch, tmp_path):
    """Host read first, `docker exec <c> cat <path>` when the host cannot see
    it. The host-first order matters: a project-staged PDK IS host-readable and
    must not pay a subprocess per file."""
    m = _mod()
    calls = []

    class _R:
        returncode = 0
        stdout = "FROM-CONTAINER"

    def _fake_run(argv, **kw):
        calls.append(argv)
        return _R()

    monkeypatch.setattr(m.subprocess, "run", _fake_run)
    read = m.container_reader("some_container")

    # host-visible file: no subprocess at all
    p = tmp_path / "on_host.lib"
    p.write_text("FROM-HOST")
    assert read(str(p)) == "FROM-HOST"
    assert calls == []

    # host-invisible file: falls back
    assert read("/foss/pdks/only/in/container.lib") == "FROM-CONTAINER"
    assert calls and calls[0][:3] == ["docker", "exec", "some_container"]
    assert calls[0][3] == "cat"


def test_no_container_means_no_fallback_and_no_crash(tmp_path):
    """An empty container name must degrade to host-only, not raise."""
    read = _mod().container_reader("")
    assert read(str(tmp_path / "absent.lib")) is None


def test_an_explicit_reader_is_the_one_that_runs():
    """The dispatcher may choose a DEFAULT reader; it must never replace one
    the caller supplied. Asserted on `custom_family_context`, the function that
    actually consumes the reader — the dispatcher's routing to it depends on
    resolver fields that are not the subject of this test."""
    m = _mod()
    used = []

    def _explicit(path):
        used.append(path)
        return None

    m.custom_family_context(
        {"source": "container_installed", "family": "unknown_fam",
         "spice_libs": ["/foss/pdks/x/only_in_container.lib"]},
        (), _explicit)
    assert used == ["/foss/pdks/x/only_in_container.lib"], used
