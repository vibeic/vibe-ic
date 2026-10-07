"""The auditor has ONE writer, and this test is what keeps it that way.

R-0915-168. Three reviews found the same defect in three places: a temp or a lock the auditor
creates is the AUDITOR'S file, carries no content a reader can identify it by, and
`design_input_digest` therefore hashed the leftover as a DESIGN INPUT -- so an interrupted pass
moved the design hash permanently on an unchanged design.

    R-0915-151  the canonical audit's temp   `<audit>.json.<pid>.tmp`
    R-0915-152  the note's lock and temp     `audit_created/<hex>.json.lock`, `....<pid>.<tid>.tmp`
    R-0915-165  the per-step record's temp   `step_outputs/<sid>.json.<pid>.tmp`

Each was patched with its own shape, after its own review. This file is the general form: the
shape is declared once in `_path_layout`, minted only by `_auditor_write`, recognised by the
digest through that declaration -- and the guard below goes RED on any file-creating call in the
auditor's own modules that bypasses the helper. A fourth mechanism is covered the day it is
written rather than the day someone notices.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _auditor_write as AW                 # noqa: E402
import _path_layout as PL                   # noqa: E402
import design_input_digest as D             # noqa: E402

#: The auditor's own modules. `_auditor_write` is the helper itself and is exempt; `_path_layout`
#: and `step_metrics` are NOT in scope and the census says why -- `emit_steps_view`'s callers are
#: the one-shot RUNNERS, and `reports/metrics/<sid>.json` is the run's row, covered by the
#: footprint.
AUDITOR_MODULES = ("flow_compliance_check.py", "_gate_authorship.py", "_audit_scope.py",
                   "design_input_digest.py")

#: Calls that CREATE a file.
CREATORS = frozenset({
    "write_text", "write_bytes", "write_json", "atomic_write_text", "atomic_write_json",
    "touch", "copy2", "copy", "copyfile", "mkstemp", "NamedTemporaryFile",
    "symlink_to", "hardlink_to",
})
OPEN_WRITE_MODES = frozenset({"w", "a", "x", "wb", "ab", "xb", "w+", "a+"})

#: THE ONLY PERMITTED BYPASSES, each with the reason it is not a project write.
#: `(module, enclosing function, call)` -> why.
# Receipt redirects now live in the project's durable runtime state. They use
# the same atomic writer as every other auditor publication; no bypass remains.
ALLOWED_BYPASSES = {}


def _is_os_replace(node: ast.Call) -> bool:
    f = node.func
    return (isinstance(f, ast.Attribute) and f.attr == "replace"
            and isinstance(f.value, ast.Name) and f.value.id == "os")


def _creating_calls(module: str):
    """(lineno, enclosing function, call name, source) for every file-creating call."""
    text = (PROGRAMS / module).read_text(errors="replace")
    lines = text.splitlines()
    tree = ast.parse(text, filename=module)
    owner = {}
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for sub in ast.walk(fn):
            owner.setdefault(id(sub), fn.name)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else (
            f.id if isinstance(f, ast.Name) else None)
        if _is_os_replace(node):
            name = "os.replace"
        elif name == "open":
            mode = ""
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value)
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = str(kw.value.value)
            if mode not in OPEN_WRITE_MODES:
                continue
            name = "open"
        elif name in CREATORS:
            # `str.replace` is not a file write; `os.replace` was caught above
            if name == "replace":
                continue
        else:
            continue
        src = "\n".join(lines[node.lineno - 1:node.end_lineno]).strip()
        out.append((node.lineno, owner.get(id(node), "<module>"), name,
                    src.replace("\n", " ")[:110]))
    return out


# ── the guard ────────────────────────────────────────────────────────────────

def test_no_auditor_module_creates_a_file_outside_the_one_writer():
    """RED on any file-creating call that bypasses `_auditor_write`.

    This is the test that makes the pattern structural. Adding a bare `write_text` to
    `flow_compliance_check` reddens it, which is the point: the next atomicity mechanism cannot
    ship with a shape the digest has never heard of.
    """
    offenders = []
    for module in AUDITOR_MODULES:
        for lineno, fn, name, src in _creating_calls(module):
            key = (module, fn, name)
            if key in ALLOWED_BYPASSES:
                continue
            offenders.append(f"{module}:{lineno} {fn}() -> {name}   {src}")

    assert offenders == [], (
        "these auditor writes bypass `_auditor_write`, so their temp/lock names are not the "
        "shape `design_input_digest` recognises:\n  " + "\n  ".join(offenders)
        + "\n\nRoute them through `_auditor_write.publish` / `copy_aside` / `holding_lock`, or "
          "add a reasoned entry to ALLOWED_BYPASSES if the write is OUTSIDE the project tree.")


def test_every_allowed_bypass_still_exists_and_is_still_outside_the_tree():
    """An allow-list that outlives what it excused is a hole.

    Each entry must still name a real call, and its reason must still say why the write is not a
    project write -- so a bypass that moves into the project cannot keep its exemption quietly.
    """
    for (module, fn, name), why in ALLOWED_BYPASSES.items():
        found = [c for c in _creating_calls(module) if c[1] == fn and c[2] == name]
        assert found, f"{module}:{fn}() no longer has a {name} call; drop the allow-list entry"
        assert "OUTSIDE the project tree" in why, (module, fn, why)
        src = (PROGRAMS / module).read_text(errors="replace")
        i = src.index(f"def {fn}(")
        assert "TemporaryDirectory" in src[i:i + 4000], (
            f"{fn}() no longer uses a TemporaryDirectory, so its write may now land in the "
            f"project; re-measure before keeping the exemption")


def test_durable_receipt_is_published_by_the_one_writer(tmp_path, monkeypatch):
    """The real redirect preserves producer bytes and the input fingerprint."""
    import flow_compliance_check as FCC
    project = tmp_path / "p"
    source = project / "reports/phase3/die_finishing.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"run": {"producer": "die_finishing_gen"}}\n')
    original = source.read_bytes()
    before = D.build_digest(D.scan_inputs(project), [])["sha256"]
    calls = []
    real = AW.copy_aside
    def copy(source, destination):
        calls.append((source, Path(destination)))
        return real(source, destination)
    monkeypatch.setattr(AW, "copy_aside", copy)
    argv = ["python3", "die_finishing_check.py", ".", "--json", str(source)]
    moved, note, keep = FCC._receipt_off_a_produced_document(argv, project)
    try:
        destination = Path(moved[-1])
        assert calls == [(source, destination)]
        assert destination.is_relative_to(project / ".vibeic-state/audit_receipts")
        assert destination.read_bytes() == source.read_bytes() == original
        assert note and keep is not None
        assert not list(destination.parent.glob("*" + PL.AUDITOR_TMP_SUFFIX))
        assert D.build_digest(D.scan_inputs(project), [])["sha256"] == before
    finally:
        FCC._RECEIPT_REDIRECTS.pop(FCC._resolved_key(source), None)


def test_the_helper_itself_is_the_one_place_that_mints_the_shape():
    """Only `_auditor_write` names a temp or a lock; the shape lives in `_path_layout`."""
    minters = []
    for module in list(AUDITOR_MODULES) + ["_auditor_write.py"]:
        text = (PROGRAMS / module).read_text(errors="replace")
        for marker in (PL.AUDITOR_TMP_SUFFIX, PL.AUDITOR_LOCK_SUFFIX):
            if marker in text:
                minters.append((module, marker))
    assert {m for m, _ in minters} <= {"_auditor_write.py", "_path_layout.py"}, minters

    # and the declaration is where the digest reads it from
    dsrc = (PROGRAMS / "design_input_digest.py").read_text()
    assert "is_auditor_inprogress_name" in dsrc, (
        "the digest no longer asks `_path_layout` what an in-progress name is")
    for retired in ("_AUDITOR_NOTE_TMP_RE", "_AUDITOR_LOCK_RE"):
        assert retired not in dsrc, f"{retired} is back: the shape is declared twice again"


# ── the shape, and what it must not swallow ──────────────────────────────────

def test_the_declared_shape_covers_every_shape_the_incidents_added(tmp_path):
    """One rule, and it still recognises all four pre-R-0915-168 leftovers.

    A tree produced before this change carries leftovers in the OLD shapes. A reader that stopped
    recognising them would let an old leftover move the design hash -- the same mistake as
    dropping a legacy report location, which cost a round on `next/icslot70`.
    """
    project = tmp_path / "proj"
    (project / "input").mkdir(parents=True)
    (project / "input" / "spec.md").write_text("# a counter\n")

    def sha() -> str:
        blk = D.build_digest(D.scan_inputs(project), [])
        assert blk["unusable_reason"] is None, blk
        return blk["sha256"]

    before = sha()
    for rel in (
            # the new, declared shape
            f"reports/audit/phase23_completion_audit.json.111.222{PL.AUDITOR_TMP_SUFFIX}",
            f"reports/audit/phase23_completion_audit.json{PL.AUDITOR_LOCK_SUFFIX}",
            f"reports/phase1/gates/stage_phase1_compliance.json.7.8{PL.AUDITOR_TMP_SUFFIX}",
            # the four the incidents added, still recognised
            "reports/audit/phase23_completion_audit.json.99.tmp",
            "reports/audit/audit_created/6be9e0442a07f03f3260.json.lock",
            "reports/audit/audit_created/6be9e0442a07f03f3260.json.1.2.tmp",
            "reports/audit/step_outputs/37_4.json.99.tmp"):
        f = project / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('{"half": ')
        assert D.is_auditor_output(project, f) is True, rel
    assert sha() == before, "an auditor in-progress file moved the design hash"


def test_a_producers_own_partial_write_is_still_a_design_input(tmp_path):
    """NOT `*.tmp` and NOT `*.lock`: the marker is what makes this safe to match anywhere."""
    project = tmp_path / "proj"
    (project / "input").mkdir(parents=True)
    (project / "input" / "spec.md").write_text("x\n")
    for rel in ("phase2/stage1/rtl/core.v.tmp",
                "phase2/stage1/rtl/core.v.1.2.tmp",
                "phase2/stage1/rtl/core.v.lock",
                "reports/phase3/drc_signoff.json.4242.tmp"):
        f = project / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("a producer's partial write\n")
        assert D.is_auditor_output(project, f) is False, rel


# ── the helper's own guarantees ──────────────────────────────────────────────

def test_publish_leaves_no_temp_and_never_masks_the_write_error(tmp_path):
    final = tmp_path / "reports" / "audit" / "phase23_completion_audit.json"
    AW.publish(final, '{"verdict": "PASS"}')
    assert json.loads(final.read_text())["verdict"] == "PASS"
    assert not [p for p in final.parent.iterdir()
                if PL.AUDITOR_TMP_SUFFIX in p.name], "a temp survived a successful publish"

    boom = OSError(28, "No space left on device")
    real = os.replace
    try:
        os.replace = lambda a, b: (_ for _ in ()).throw(boom)
        with pytest.raises(OSError) as caught:
            AW.publish(tmp_path / "reports" / "audit" / "other.json", "{}")
    finally:
        os.replace = real
    assert caught.value is boom, "the cleanup masked the original failure"
    assert not [p for p in (tmp_path / "reports" / "audit").iterdir()
                if PL.AUDITOR_TMP_SUFFIX in p.name], "the temp outlived the failed publish"


def test_copy_aside_is_atomic_too(tmp_path):
    src = tmp_path / "a.json"
    src.write_text('{"overall": "FAIL"}')
    dest = tmp_path / "reports" / "x.superseded-1.json"
    AW.copy_aside(src, dest)
    assert json.loads(dest.read_text())["overall"] == "FAIL"
    assert not [p for p in dest.parent.iterdir() if PL.AUDITOR_TMP_SUFFIX in p.name]


def test_the_temp_is_a_sibling_so_the_rename_cannot_cross_a_filesystem(tmp_path):
    final = tmp_path / "deep" / "er" / "audit.json"
    assert AW.temp_name(final).parent == final.parent
    assert AW.lock_name(final).parent == final.parent


# ── the lock cannot hang the audit ───────────────────────────────────────────

def test_a_lock_left_by_a_killed_pass_does_not_block_a_later_pass(tmp_path):
    """MEASURED, because the failure mode here is a HANG, which is worse than a wrong verdict.

    A publish that asks for a lock (`_stamp_publication`, the one read-modify-write) leaves the
    lock FILE behind when the pass is interrupted -- `flock` lives on the inode and cannot be
    unlinked on release without a race. That file must not stop the next pass: `flock` is held by the open file
    description, and the kernel releases it when the holder dies, so a leftover file is just a
    file. Driven with a real child that is killed while holding it.
    """
    import subprocess
    import time

    final = tmp_path / "reports" / "audit" / "phase23_completion_audit.json"
    holder = tmp_path / "holder.py"
    holder.write_text(
        "import sys, time\n"
        f"sys.path.insert(0, {str(PROGRAMS)!r})\n"
        "import _auditor_write as AW\n"
        "from pathlib import Path\n"
        f"with AW.holding_lock(Path({str(final)!r})):\n"
        "    print('LOCKED', flush=True)\n"
        "    time.sleep(60)\n")

    proc = subprocess.Popen([sys.executable, str(holder)],
                            stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "LOCKED"
        assert PL.auditor_lock_name(final).is_file()
    finally:
        proc.kill()
        proc.wait(timeout=30)

    assert PL.auditor_lock_name(final).is_file(), "the arm needs the leftover to still be there"
    t0 = time.time()
    AW.publish(final, '{"verdict": "PASS"}')
    assert time.time() - t0 < 10, "a leftover lock file blocked a later publish"
    assert json.loads(final.read_text())["verdict"] == "PASS"


def test_no_locking_publish_is_nested_inside_a_held_lock():
    """A SECOND flock on one file from the SAME process BLOCKS -- measured in this arm -- so a
    locking publish nested inside a held lock on that file would DEADLOCK the audit.

    The one place the auditor publishes inside a held lock is the authorship note, and it passes
    `lock=False` for exactly this reason. This pins that, structurally, so the day someone drops
    the argument the test says why it mattered instead of the audit hanging.
    """
    import fcntl
    import signal
    import tempfile

    # the premise: same-process, two descriptions, the second blocks
    probe = Path(tempfile.mkdtemp()) / "x.lock"
    a = open(probe, "a+")                                   # noqa: SIM115
    try:
        fcntl.flock(a.fileno(), fcntl.LOCK_EX)
        blocked = False

        def _bang(*_):
            raise TimeoutError

        old = signal.signal(signal.SIGALRM, _bang)
        signal.alarm(3)
        b = open(probe, "a+")                               # noqa: SIM115
        try:
            fcntl.flock(b.fileno(), fcntl.LOCK_EX)
            signal.alarm(0)
        except TimeoutError:
            blocked = True
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
            b.close()
    finally:
        a.close()
    assert blocked, (
        "a same-process second flock no longer blocks, so the reason for `lock=False` below has "
        "changed; re-measure before trusting this arm")

    # the note writer -- the only publish inside a held lock -- must not take the lock again
    src = (PROGRAMS / "flow_compliance_check.py").read_text()
    assert "_aw.publish(note, payload, lock=False)" in src, (
        "the note writer publishes inside `_note_lock` WITHOUT `lock=False`, which deadlocks on "
        "the second flock of the same file")

    # and no other publish call site sits inside a `with _note_lock` / `holding_lock` block
    import ast
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        held = any(
            isinstance(item.context_expr, ast.Call)
            and getattr(item.context_expr.func, "attr", getattr(
                item.context_expr.func, "id", "")) in ("_note_lock", "holding_lock")
            for item in node.items)
        if not held:
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call)
                    and getattr(sub.func, "attr", "") == "publish"):
                kw = {k.arg: k.value for k in sub.keywords}
                lock = kw.get("lock")
                assert (isinstance(lock, ast.Constant) and lock.value is False), (
                    f"a locking publish at line {sub.lineno} is nested inside a held lock; "
                    f"that deadlocks on the same file")
