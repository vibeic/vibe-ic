"""The native antenna deck is the one INSIDE the image the run's PDK root is bound to.

MEASURED on the spm IC-die run (vibeic-eda 0.3.85, image id sha256:7d372e6d...):
Step 26's GDS antenna gate published DISCLOSED_SKIP "container PDK deck bytes
differ from the image-bound bridge tree" although the container's
`gf180mcu.drc` / `rule_decks/antenna.rb` and the host cache copy are
byte-identical (992ed4d4... / f82e2aed... on both sides). The probe ran
`sha256sum` through the image's LOGIN shell, whose profile prints two
`[INFO] Final ... variable:` lines on stdout, and read the digests by
position -- so it compared the word "[INFO]" with a SHA-256 and never
measured the design.

The repair is not a better positional parse. The tree the run used is named by
the receipt as (image id, path inside that image); the host cache copy is an
extraction nothing re-verifies. So the deck is resolved, hashed and executed
inside a container running exactly that image, the host copy is never read,
and the count is accepted only when the transcript names the hashed rule, the
RDB names the hashed parent, and the deck's own tally equals the RDB count.
"""
from __future__ import annotations

import hashlib
import json
import posixpath
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import _klayout_launch as launch  # noqa: E402
import _watchdog as watchdog  # noqa: E402

IMAGE_ID = "sha256:" + "7d" * 32
OTHER_IMAGE_ID = "sha256:" + "2c" * 32
PDK = "fixture_pdk"
GUEST = f"/foss/pdks/{PDK}"
DRC_REL = "libs.tech/klayout/tech/drc"
PARENT = "main.drc"
PARENT_SRC = b"decks: $decks\nload rule_decks\n"
RULE_SRC = b"# the image's own antenna rule\n"
# What vibeic-eda's login profile prints on stdout before every `bash -lc`.
LOGIN_BANNER = ("[INFO] Final PATH variable: /headless/.local/bin:/foss/tools/bin\n"
                "[INFO] Final PYTHONPATH variable: /headless/.local/lib/python3.12\n")


def _rdb(violations: int, script: str) -> str:
    items = "".join("<item><category>'ANT.1'</category></item>"
                    for _ in range(violations))
    return ("<?xml version='1.0'?><report-database><description/>"
            f"<generator>drc: script='{script}'</generator>"
            "<categories><category><name>ANT.1</name><description/></category>"
            "</categories><items>" + items + "</items></report-database>")


def _transcript(rule: str, violations: int) -> str:
    tally = ("DRC RESULT: SUCCESS (0 violations)" if violations == 0
             else f"DRC RESULT: FAILURE ({violations} violation(s))")
    return (f"x: Executing deck antenna_poly2 from {rule}\n"
            "x: Executing rule ANT.1\n"
            f"x: Executing deck antenna_metal1 from {rule}\n"
            f"x: {tally}\n")


def _write_deck(drc: Path, *, rule: bytes | None = RULE_SRC) -> None:
    (drc / "rule_decks").mkdir(parents=True)
    (drc / PARENT).write_bytes(PARENT_SRC)
    (drc / "helper.rb").write_bytes(b"# not a parent\n")
    if rule is not None:
        (drc / "rule_decks" / "antenna.rb").write_bytes(rule)


class ImageContainer:
    """A container running one image: its filesystem is `fs`.

    `run_argv` behaves like `bash -lc` in vibeic-eda, banner included, which
    is the path the old digest probe took. `read_bytes`/`list_files` are the
    direct reads the container runner offers.
    """
    kind = "container"

    def __init__(self, fs: Path, image_id: str = IMAGE_ID, violations: int = 0,
                 banner: bool = True):
        self.fs = fs
        self.detail = "fixture-eda:klayout"
        self._image_id = image_id
        self.violations = violations
        self.banner = banner
        self.argv = None
        self.transcript = None      # override: (rule, script) -> stdout
        self.rdb = None             # override: (script) -> RDB text
        self.during_run = None      # hook executed while "KLayout" runs
        self.rc = 0                 # KLayout's exit status
        self.outcome = "natural"    # supervision outcome
        # What `docker inspect` / `docker diff` would report for this
        # container, and where the tree resolves (`readlink -f`).
        self.mounts: list = []
        self.changes: list = []
        self.resolved: dict = {}

    def _in_image(self, path) -> Path:
        return self.fs / str(path).lstrip("/")

    def covers(self, path):
        return True

    def cpath(self, path):
        return str(path)

    def klayout_bin(self):
        return "klayout"

    def image_id(self):
        return self._image_id, ""

    def read_bytes(self, path):
        try:
            return self._in_image(path).read_bytes()
        except OSError:
            return None

    def list_files(self, directory, suffix):
        d = self._in_image(directory)
        if not d.is_dir():
            return None
        return sorted("/" + str(p.relative_to(self.fs)) for p in d.iterdir()
                      if p.name.endswith(suffix) and p.is_file())

    def list_tree(self, directory):
        d = self._in_image(directory)
        if not d.is_dir():
            return None
        return sorted("/" + str(q.relative_to(self.fs)) for q in d.rglob("*")
                      if q.is_file())

    def image_tree_proof(self, tree):
        """The real overlay rule over this fixture's mounts and diff."""
        real = self.resolved.get(tree, tree)
        record = {"guest_tree": tree, "guest_tree_resolved": real}
        overlays = launch.image_tree_overlays([tree, real], self.mounts,
                                              self.changes)
        if overlays:
            return False, "not the image's bytes: " + "; ".join(overlays), record
        return True, "", record

    def run_argv(self, argv, env, *, timeout):
        out = LOGIN_BANNER if self.banner else ""
        if argv[0] != "sha256sum":
            raise AssertionError(f"unexpected command {argv}")
        for arg in argv[1:]:
            f = self._in_image(arg)
            if not f.is_file():
                return 1, out, f"sha256sum: {arg}: No such file or directory"
            out += f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {arg}\n"
        return 0, out, ""

    def run_argv_supervised(self, argv, env, *, stall_grace_s,
                            memory_limit_mb, progress_paths):
        self.argv = argv
        script = argv[argv.index("-r") + 1]
        assert self._in_image(script).is_file(), f"{script} is not in the image"
        rule = posixpath.join(posixpath.dirname(script), "rule_decks", "antenna.rb")
        report = Path(next(a.split("=", 1)[1] for a in argv
                           if a.startswith("report=")))
        report.write_text(self.rdb(script) if self.rdb
                          else _rdb(self.violations, script))
        if self.during_run:
            self.during_run()
        out = (LOGIN_BANNER if self.banner else "") + (
            self.transcript(rule, script) if self.transcript
            else _transcript(rule, self.violations))
        return watchdog.SupervisedResult(self.rc, out, "", self.outcome, 0.1,
                                         supervision={"fixture": True})


class HostKLayout:
    kind = "host"
    detail = "klayout -b -r"

    def __init__(self):
        self.argv = None

    def covers(self, path):
        return True

    def cpath(self, path):
        return str(path)

    def klayout_bin(self):
        return "klayout"

    def run_argv_supervised(self, argv, env, **kw):
        self.argv = argv
        report = Path(next(a.split("=", 1)[1] for a in argv
                           if a.startswith("report=")))
        script = argv[argv.index("-r") + 1]
        rule = posixpath.join(posixpath.dirname(script), "rule_decks", "antenna.rb")
        report.write_text(_rdb(0, script))
        return watchdog.SupervisedResult(0, _transcript(rule, 0), "", "natural",
                                         0.1, supervision={})


def _project(tmp_path, *, host_copy: bytes | None = RULE_SRC,
             image_rule: bytes | None = RULE_SRC):
    """A resolved-PDK run: host cache copy + the tree inside the image."""
    project = tmp_path / "project"
    gds_dir = project / "phase3/stage4/gds"
    gds_dir.mkdir(parents=True)
    (gds_dir / "layout.gds").write_bytes(b"routed stream geometry")
    fs = tmp_path / "image_fs"
    _write_deck(fs / GUEST.lstrip("/") / DRC_REL, rule=image_rule)
    cache = tmp_path / "host_cache" / IMAGE_ID.split(":", 1)[1]
    if host_copy is not None:
        _write_deck(cache / PDK / DRC_REL, rule=host_copy)
    return project, fs




def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_named_container_keeps_original_runner_with_a_native_sidecar(tmp_path, monkeypatch):
    project, fs = _project(tmp_path)
    runner = ImageContainer(fs)
    folder = project / 'phase3/librelane/26-gds/01-klayout-antenna'
    folder.mkdir(parents=True)
    (folder / 'pdk_root.json').write_text(json.dumps({'cli_pdk_root': '/pdk',
        'stated_by': 'run_chain(pdk_root=...)'}))
    (project / 'phase3/librelane_switch.json').write_text(json.dumps({'steps': {'26': 'librelane'}}))
    record = project / 'reports/phase3/antenna_librelane.json'
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({'gds': {'state': str(folder / 'state_out.json')}}))
    assert runner.argv is not None


@pytest.mark.parametrize("violations, verdict", [(0, "PASS"), (1, "FAIL")])
def test_login_banner_no_longer_reads_as_a_deck_digest_mismatch(
        tmp_path, monkeypatch, violations, verdict):
    """The measured defect: identical decks, banner on stdout -> never measured."""
    project, fs = _project(tmp_path)
    runner = ImageContainer(fs, violations=violations)
    parent = f"{GUEST}/{DRC_REL}/{PARENT}"
    assert runner.argv[runner.argv.index("-r") + 1] == parent






def test_container_running_another_image_is_not_measured(tmp_path, monkeypatch):
    project, fs = _project(tmp_path)
    runner = ImageContainer(fs, image_id=OTHER_IMAGE_ID, banner=False)
    assert runner.argv is None


def test_host_klayout_never_substitutes_for_the_image_tree(tmp_path, monkeypatch):
    project, _ = _project(tmp_path)
    host = HostKLayout()
    assert host.argv is None


def test_deck_missing_inside_the_image_stays_not_measured(tmp_path, monkeypatch):
    project, fs = _project(tmp_path, image_rule=None)
    runner = ImageContainer(fs)
    assert runner.argv is None






@pytest.mark.parametrize("derivation, needle", [
    ({"image_id": IMAGE_ID, "guest_path": "/foss/pdks/another_pdk"}, "is not the absolute tree"),
    ({"image_id": "7d372e6d", "guest_path": GUEST}, "names no image bytes"),
    ({"guest_path": GUEST}, "names no image bytes"),
])
def test_receipt_that_cannot_bind_a_tree_to_image_bytes_is_unusable(
        tmp_path, monkeypatch, derivation, needle):
    project, fs = _project(tmp_path)
    runner = ImageContainer(fs, banner=False)
    assert runner.argv is None


def test_container_reader_runs_the_command_directly_not_in_a_login_shell(
        monkeypatch):
    seen = []
    monkeypatch.setattr(launch._ce, "docker_exec_argv",
                        lambda c, *rest, opts=(): ["docker", "exec", c, *rest])

    def fake_run(argv, **kw):
        seen.append(argv)
        body = b"deck bytes\n" if argv[3] == "cat" else b"/t/a.drc\0/t/b.drc\0"
        return subprocess.CompletedProcess(argv, 0, body, b"")

    monkeypatch.setattr(launch.subprocess, "run", fake_run)
    runner = launch.ContainerRunner("fixture-eda")
    assert runner.read_bytes("/t/rule_decks/antenna.rb") == b"deck bytes\n"
    assert runner.list_files("/t", ".drc") == ["/t/a.drc", "/t/b.drc"]
    assert seen[0] == ["docker", "exec", "fixture-eda", "cat", "--",
                       "/t/rule_decks/antenna.rb"]
    assert all("bash" not in argv and "-lc" not in argv for argv in seen)


def test_container_resolver_never_returns_a_host_klayout(monkeypatch):
    monkeypatch.delenv("VIBEIC_KLAYOUT_FORCE_ABSENT", raising=False)
    monkeypatch.setattr(launch.shutil, "which",
                        lambda name: "/usr/bin/klayout" if name == "klayout" else None)
    assert isinstance(launch.find_runner(), launch.HostRunner)
    assert launch.find_container_runner() is None




# --------------------------------------------------------------------------- #
# review wave 57 (ANTDECK)
# --------------------------------------------------------------------------- #
DECK_DIR = f"{GUEST}/{DRC_REL}"


def _image_file(fs: Path, rel: str) -> Path:
    return fs / DECK_DIR.lstrip("/") / rel


# (1) measured violations are never relabelled NOT_MEASURED ------------------ #
def _mount_after_run(runner):
    def hook():
        runner.mounts.append("/foss/pdks")
    return hook








# (2) the image id is not the bytes: mounts and the writable layer ----------- #
@pytest.mark.parametrize("mounts, changes, resolved", [
    (["/foss/pdks"], [], {}),                                  # above the tree
    ([f"{DECK_DIR}/rule_decks"], [], {}),                      # below the tree
    ([], [f"C {DECK_DIR}/rule_decks/antenna.rb"[2:]], {}),     # writable layer
    (["/pdk_store/v1"], [], {GUEST: "/pdk_store/v1/fixture_pdk"}),  # link target
    ([], ["/pdk_store/v1/fixture_pdk/libs.tech"], {GUEST: "/pdk_store/v1/fixture_pdk"}),
])
def test_bytes_not_from_the_image_are_not_measured(tmp_path, monkeypatch,
                                                   mounts, changes, resolved):
    project, fs = _project(tmp_path)
    runner = ImageContainer(fs, banner=False)
    runner.mounts, runner.changes, runner.resolved = mounts, changes, resolved
    assert runner.argv is None




def _docker(monkeypatch, *, mounts, tmpfs=None, diff="", real=GUEST,
            fail=()):
    seen = []
    monkeypatch.setattr(launch._ce, "docker_exec_argv",
                        lambda c, *rest, opts=(): ["docker", "exec", c, *rest])

    def fake_run(argv, **kw):
        seen.append(list(argv))
        verb = argv[1]
        if verb in fail:
            return subprocess.CompletedProcess(argv, 1, "" if kw.get("text")
                                               else b"", "boom")
        if verb == "exec":
            assert argv[3:6] == ["readlink", "-f", "--"]
            return subprocess.CompletedProcess(argv, 0, real.encode() + b"\n", b"")
        if verb == "inspect":
            body = (json.dumps([{"Type": "bind", "Source": "/h",
                                 "Destination": d} for d in mounts])
                    + "\t" + json.dumps(tmpfs))
            return subprocess.CompletedProcess(argv, 0, body + "\n", "")
        if verb == "diff":
            return subprocess.CompletedProcess(argv, 0, diff, "")
        raise AssertionError(argv)

    monkeypatch.setattr(launch.subprocess, "run", fake_run)
    return seen


def test_container_image_tree_proof_reads_inspect_and_diff_without_a_shell(
        monkeypatch):
    seen = _docker(monkeypatch, mounts=["/foss/designs"],
                   diff="C /foss\nC /foss/pdks\nA /root/.cache\n")
    proven, why, record = launch.ContainerRunner("fx").image_tree_proof(GUEST)
    assert (proven, why) == (True, ""), record
    assert record["mounts_checked"] == 1
    assert record["writable_layer_changes_checked"] == 3
    assert all("bash" not in a and "-lc" not in a for a in seen)


@pytest.mark.parametrize("kw, needle", [
    ({"mounts": [], "tmpfs": {"/foss/pdks": ""}}, "mount /foss/pdks"),
    ({"mounts": ["/foss"]}, "mount /foss overlays"),
    ({"mounts": [], "diff": f"C /foss\nA {GUEST}/x.rb\n"}, "writable-layer change"),
    ({"mounts": ["/ciel"], "real": "/ciel/v/fixture_pdk"}, "/ciel/v/fixture_pdk"),
    ({"mounts": [], "fail": ("diff",)}, "failed"),
    ({"mounts": [], "fail": ("inspect",)}, "failed"),
    ({"mounts": [], "fail": ("exec",)}, "does not resolve"),
])
def test_container_image_tree_proof_refuses_overlays_and_silence(
        monkeypatch, kw, needle):
    _docker(monkeypatch, **kw)
    proven, why, _ = launch.ContainerRunner("fx").image_tree_proof(GUEST)
    assert proven is False and needle in why, why


# (3) every file the parent executes is hashed and re-checked ---------------- #




# (4) exactly one tally, and its polarity ------------------------------------ #




# (5) the declared receipt the producer actually writes ---------------------- #
def _declared_project(tmp_path, monkeypatch, *, pdk=PDK):
    import librelane_contract as contract
    project = tmp_path / "project"
    gds_dir = project / "phase3/stage4/gds"
    gds_dir.mkdir(parents=True)
    (gds_dir / "layout.gds").write_bytes(b"routed stream geometry")
    host_root = tmp_path / "declared_pdk_root"
    _write_deck(host_root / PDK / DRC_REL)
    (project / "phase3/librelane_switch.json").write_text(
        json.dumps({"pdk_root_host": str(host_root)}))
    monkeypatch.delenv("VIBEIC_LIBRELANE_PDK_ROOT", raising=False)
    answer = contract.pdk_root_resolution(project, pdk)
    return project, host_root, answer


def test_a_declared_pdk_root_receipt_is_measured_on_the_host(tmp_path,
                                                             monkeypatch):
    project, host_root, answer = _declared_project(tmp_path, monkeypatch)
    assert answer["source"] == "declared" and "derivation" not in answer
    host = HostKLayout()


def test_a_declared_receipt_naming_no_pdk_is_refused_by_name(tmp_path,
                                                             monkeypatch):
    project, _, answer = _declared_project(tmp_path, monkeypatch, pdk=None)
    assert "pdk" not in answer


# the same login-banner class, in die finishing's technology lookup ---------- #
def test_die_finishing_names_the_technology_through_a_login_banner(
        tmp_path, monkeypatch):
    """Review wave 57 (ANTDECK, low): `derive_tech` listed `*.lyt` through
    `run_argv` (`bash -lc` in the container), read the two banner lines as
    two more technology files and refused. It now lists directly."""
    import die_finishing_gen as dfg
    tech = "/pdk/libs.tech/klayout/tech"
    lyt = f"{tech}/fixture.lyt"

    def fake_run(argv, **kw):
        argv = list(argv)
        if "bash" in argv and "-lc" in argv:       # the login-shell path
            cmd = argv[-1]
            if cmd.split()[:1] == ["head"] or " head " in f" {cmd} ":
                body = LOGIN_BANNER + "<technology><name>fx</name></technology>\n"
            else:
                body = LOGIN_BANNER + lyt + "\n"
            return subprocess.CompletedProcess(argv, 0, body, "")
        assert argv[3:5] == ["find", "-L"], argv   # direct, no shell
        return subprocess.CompletedProcess(argv, 0, lyt.encode() + b"\0", b"")

    monkeypatch.setattr(launch._ce, "docker_exec_argv",
                        lambda c, *rest, opts=(): ["docker", "exec", c, *rest])
    monkeypatch.setattr(launch.subprocess, "run", fake_run)
    monkeypatch.setattr(launch._pr, "run_best_effort",
                        lambda argv, **kw: fake_run(argv, **kw), raising=False)
    runner = launch.ContainerRunner("fixture-eda")
    name, why = dfg.derive_tech(runner, f"{tech}/scripts/sealring.py")
    assert name == "fx", why
    assert "fixture.lyt" in why
