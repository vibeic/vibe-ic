"""Answering `seal_ring_script` correctly was worse than leaving it blank.

MEASURED, gf180mcuD chip path 2026-08-22. Same project, same tape-out
declaration, same layout, same invocation — only the PROGRAM VERSION differing:

    4-step resolver (no declaration step)   -> rc 0, seal PASS, 288542.0 um^2
    5-step resolver, field ANSWERED         -> rc 2, DISCLOSED_SKIP
    5-step resolver, field UNANSWERED       -> rc 0, seal PASS, 288542.0 um^2

A new step 3 -- "the design's own tape-out declaration (`seal_ring_script`)" --
was inserted ABOVE the `$PDK_ROOT/$PDK` probe, and it returned the declared
value VERBATIM. A declared script path is normally RELATIVE to the PDK root,
because that is how it appears in the PDK tree and it is the only form that is a
fact about the DIE rather than about one machine's filesystem:

    seal_ring_script: libs.tech/klayout/tech/scripts/sealring.py

so the correct declaration became the one form that could never resolve, and
because step 3 outranks the probe, answering the field truthfully turned a
passing seal ring into a DISCLOSED_SKIP on a design that declares
`seal_ring_required: true`.

Now: taken AS GIVEN when absolute (an operator who wrote an absolute path meant
it), and otherwise ALSO tried joined to `$PDK_ROOT/$PDK`, with `source`
recording which form hit.

THE NO-LEAK DIRECTION: existence is still decided by the runner, not here. A
declared script that resolves in NEITHER form is returned unchanged and still
reaches DISCLOSED_SKIP. This widens which SPELLINGS can be found, never what
counts as found.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import die_finishing_gen as G  # noqa: E402

_REL = "libs.tech/klayout/tech/scripts/sealring.py"


def _pdk(tmp_path):
    """A PDK tree with the script where a real distribution puts it."""
    s = tmp_path / "pdk" / "somepdk" / _REL
    s.parent.mkdir(parents=True, exist_ok=True)
    s.write_text("# seal ring generator\n")
    return str(tmp_path / "pdk"), "somepdk", s


def test_a_PDK_RELATIVE_declared_script_resolves(tmp_path):
    """THE DEFECT: the correct design-fact form was the unresolvable one."""
    root, name, real = _pdk(tmp_path)
    script, source, _ = G.resolve_script(
        tmp_path, None, root, name, {"seal_ring_script": _REL})
    assert script == str(real), (script, source)
    assert "joined to $PDK_ROOT/$PDK" in source, source


def test_an_ABSOLUTE_declared_script_is_taken_as_given(tmp_path):
    """An operator who wrote an absolute path meant it; do not rewrite it."""
    root, name, _ = _pdk(tmp_path)
    script, source, _ = G.resolve_script(
        tmp_path, None, root, name, {"seal_ring_script": "/opt/x/sealring.py"})
    assert script == "/opt/x/sealring.py", script
    assert "joined" not in source, source


def test_NEGATIVE_a_declared_script_in_NEITHER_form_is_returned_UNRESOLVED(tmp_path):
    """THE NO-LEAK. Widening which spellings are TRIED must not widen what
    counts as FOUND: a path that exists neither as given nor joined comes back
    unchanged, so the runner still refuses it and the step DISCLOSED_SKIPs."""
    root, name, _ = _pdk(tmp_path)
    script, source, _ = G.resolve_script(
        tmp_path, None, root, name, {"seal_ring_script": "no/such/script.py"})
    assert script == "no/such/script.py", script
    assert "joined" not in source, source


def test_NEGATIVE_the_join_never_invents_a_root(tmp_path):
    """With no PDK root and no PDK name there is nothing to join against, and
    the declared value must survive untouched rather than becoming a path
    rooted at '/'."""
    script, source, _ = G.resolve_script(
        tmp_path, None, None, None, {"seal_ring_script": _REL})
    assert script == _REL, script


def test_a_declared_script_is_never_joined_to_the_CONTAINERS_pdk(tmp_path, monkeypatch):
    """The design declares the script; the container declares nothing about it.

    THE ARM ABOVE IS NOT ENOUGH ON ITS OWN, and that is why this one exists.
    `test_NEGATIVE_the_join_never_invents_a_root` passes on any host where
    `PDK_ROOT`/`PDK` happen to be unset — which is most of them — so it could
    only ever catch this defect by accident of where it ran. Here the
    environment is set ON PURPOSE, to a PDK that is NOT the one the design
    declared, and the assertion is about what the resolver does with it.

    MEASURED in the pinned runner image
    (ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…): it exports
    `PDK_ROOT=/foss/pdks` and `PDK=ihp-sg13g2`, and
    `/foss/pdks/ihp-sg13g2/libs.tech/klayout/tech/scripts/sealring.py` exists.
    Before the fix a gf180 design's declared relative script resolved to that
    IHP file, sourced "(joined to $PDK_ROOT/$PDK)".

    The PDK planted here is synthesised and named for nothing real: what is
    under test is that a root the DESIGN did not supply is not consulted, not
    any particular foundry."""
    foreign = tmp_path / "container_pdks"
    name = "some_other_process"
    real = foreign / name / _REL
    real.parent.mkdir(parents=True)
    real.write_text("# the container's sealring, not this design's\n")
    monkeypatch.setenv("PDK_ROOT", str(foreign))
    monkeypatch.setenv("PDK", name)
    script, source, _ = G.resolve_script(
        tmp_path, None, None, None, {"seal_ring_script": _REL})
    assert script == _REL, (script, source)
    assert str(foreign) not in script, (script, source)
    assert "joined" not in source, source


def test_CONTROL_the_probe_path_still_reads_the_environment(tmp_path, monkeypatch):
    """The half that must NOT change. When the design declares nothing, the
    environment is the only thing that has spoken, and the probe still listens
    to it — removing that would break the arm that passed before the
    declaration step existed."""
    root, name, real = _pdk(tmp_path)
    monkeypatch.setenv("PDK_ROOT", str(root))
    monkeypatch.setenv("PDK", name)
    script, source, _ = G.resolve_script(tmp_path, None, None, None, {})
    assert script == str(real), (script, source)


def test_CONTROL_an_unanswered_field_still_falls_through_to_the_pdk_probe(tmp_path):
    """The behaviour that WORKED must be unchanged — this is the arm that was
    passing before the declaration step existed."""
    root, name, real = _pdk(tmp_path)
    script, source, _ = G.resolve_script(tmp_path, None, root, name, {})
    assert script == str(real), (script, source)
    assert source.startswith("$PDK_ROOT/$PDK/"), source


def test_CONTROL_explicit_script_still_outranks_everything(tmp_path):
    root, name, _ = _pdk(tmp_path)
    script, source, _ = G.resolve_script(
        tmp_path, "/explicit/one.py", root, name, {"seal_ring_script": _REL})
    assert script == "/explicit/one.py"
    assert source == "--script"


def test_CONTROL_every_location_tried_is_still_named(tmp_path):
    """An absence must stay a STATEMENT about specific locations."""
    root, name, _ = _pdk(tmp_path)
    _, _, tried = G.resolve_script(tmp_path, None, root, name, {})
    assert any("seal_ring_script" in x for x in tried), tried
    assert any("$PDK_ROOT/$PDK/" in x or "/pdk/" in x for x in tried), tried
