"""15.5ic reads the PDK in the IMAGE the run recorded, not on the audit's host.

W5/15.5ic layer 3. The flow's own clause for this step carries no PDK argument,
and `_pdk_layer_authority._environment_query` asks a container only when the
ENVIRONMENT names one. Re-run by the completion audit nothing does, so the IO
inventory the run recorded -- absolute paths under a PDK root that resolves
inside the run's image -- was judged against the audit host's filesystem, where
those paths do not exist, and `PADRING_MASTERS_UNCORROBORATED` stood over a ring
the run had built and routed.

The run's container is gone by audit time, so the durable identity is the image
digest the run wrote into `reports/container_image.json` with `image_match` true.
That receipt, and only that, decides where this gate looks. Both directions are
pinned: the recorded image is read, and every way of not having a trustworthy
receipt keeps today's behaviour instead of borrowing an answer.
"""
import json
import pytest
import _pad_ring as PR
import _pdk_layer_authority as authority

DIGEST = "ghcr.io/vibeic/vibeic-eda@sha256:" + "b" * 64
#: A PDK root that exists only inside an image -- never on the host running this.
PDK_LEF_DIR = "/pdk-inside-the-image/libs.ref/fixture_io/lef"
LEFS = [f"{PDK_LEF_DIR}/io.lef"]
#: Every master, library and file name here is invented (chip-agnostic).
MASTERS = ("fixture_io__in_c", "fixture_io__cor", "fixture_io__fill10")
#: The tech view lives beside the reference view: <tree>/libs.tech/<flow>/<lib>.
CONFIG = "/pdk-inside-the-image/libs.tech/a_flow/fixture_io/config.tcl"
#: `PAD_FAKE_SITES` is upstream's own variable and the one form the
#: distributions write, so the fixture declares the site the way a PDK does.
SITE_DECL = ('set ::env(PAD_FAKE_SITES) [dict create]\n'
             'dict set ::env(PAD_FAKE_SITES) "IO_Site" "0.5, 300"\n')


def lef_text(masters, size=(10.0, 20.0)) -> str:
    out = ["VERSION 5.8 ;", 'BUSBITCHARS "[]" ;']
    for m in masters:
        out += [f"MACRO {m}", "  CLASS PAD ;",
                f"  SIZE {size[0]} BY {size[1]} ;", f"END {m}"]
    out.append("END LIBRARY")
    return "\n".join(out) + "\n"


def def_text() -> str:
    comps = [("u_pad_a", MASTERS[0], 100000, 52000),
             ("cor_SW", MASTERS[1], 52000, 52000),
             ("fill_S_0", MASTERS[2], 300000, 52000)]
    return ('VERSION 5.8 ;\nDIVIDERCHAR "/" ;\nBUSBITCHARS "[]" ;\n'
            "DESIGN chip_top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
            "DIEAREA ( 0 0 ) ( 1000000 1000000 ) ;\n"
            f"COMPONENTS {len(comps)} ;\n"
            + "\n".join(f"- {i} {m} + PLACED ( {x} {y} ) N ;"
                         for i, m, x, y in comps)
            + "\nEND COMPONENTS\nEND DESIGN\n")


class FakeImage:
    """A stand-in for one image's filesystem: a dict of path -> contents.

    It answers the reader protocol exactly as `ImageReader` does -- False and
    None for what is not there, and `glob` returning a directory's DIRECT
    children, files and subdirectories alike, because that is what `ls -1d
    <root>/*` returns and what `_pad_ring._subdirs` walks. A `glob` that
    returned only files would make every tree look childless and the test would
    pass for the wrong reason.
    """

    def __init__(self, files):
        self.files = dict(files)
        self.asked = []

    def _dirs(self):
        out = set()
        for f in self.files:
            parts = f.strip("/").split("/")
            for i in range(1, len(parts)):
                out.add("/" + "/".join(parts[:i]))
        out.add("/")
        return out

    def is_dir(self, path):
        self.asked.append(("is_dir", path))
        return (path.rstrip("/") or "/") in self._dirs()

    def is_file(self, path):
        self.asked.append(("is_file", path))
        return path in self.files

    def glob(self, root, pattern):
        self.asked.append(("glob", root))
        base = root.rstrip("/")
        suffix = pattern.lstrip("*")
        out = set()
        for entry in list(self.files) + sorted(self._dirs()):
            if not entry.startswith(base + "/"):
                continue
            child = base + "/" + entry[len(base) + 1:].split("/")[0]
            if child.endswith(suffix):
                out.add(child)
        return sorted(out)

    def read_text(self, path):
        self.asked.append(("read", path))
        return self.files.get(path)


def fixture(tmp_path, change=None, in_image=True):
    p = tmp_path
    (p / "reports/phase3").mkdir(parents=True)
    ring = p / "phase3/stage3/pnr/padring.def"
    ring.parent.mkdir(parents=True)
    ring.write_text(def_text())
    producer = {
        "schema": PR.SCHEMA, "program": "pad_ring_gen", "verdict": "PASS",
        "reason": "placed the ring",
        "padring_def": "phase3/stage3/pnr/padring.def",
        "config": {"PAD_CORNER": MASTERS[1], "PAD_FILLERS": ["a_family_name"]},
        "pads": [{"instance": "u_pad_a", "master": MASTERS[0], "side": "S"}],
        "corners": [{"instance": "cor_SW", "master": MASTERS[1]}],
        "fillers": [{"instance": "fill_S_0", "master": MASTERS[2]}],
    }
    (p / "reports/phase3/padring.json").write_text(json.dumps(producer))
    (p / "reports/phase3/io_pad_chip_top.json").write_text(json.dumps({
        "program": "io_pad_chip_top_gen", "verdict": "WROTE",
        "io_library_lefs": LEFS}))

    receipt = {"container": "eda-run", "image_match": True,
               "require_image": DIGEST, "verdict": "PASS", "running": True}
    if change == "image-mismatch":
        receipt["image_match"] = False
    if change == "tag-not-digest":
        receipt["require_image"] = "vibeic-eda:0.3.67"
        receipt.pop("image_ref", None)
    if change == "receipt-not-json":
        (p / "reports/container_image.json").write_text("{ not json")
        receipt = None
    if change == "no-receipt":
        receipt = None
    if receipt is not None:
        (p / "reports/container_image.json").write_text(json.dumps(receipt))

    files = {}
    if in_image:
        files[LEFS[0]] = lef_text(MASTERS)
    return p, FakeImage(files)


def producer_of(p):
    return json.loads((p / "reports/phase3/padring.json").read_text())


def install(monkeypatch, image, env=None):
    monkeypatch.setattr(authority, "ImageReader",
                        lambda digest, runner=None: image)
    # PDK_ROOT / PDK are SET inside the pinned image, and a named PDK takes an
    # earlier branch that never reaches the recorded record. Cleared so these
    # cases measure the receipt, not whichever harness the suite ran in.
    for var in ("EDA_CONTAINER", "VIBEIC_EDA_CONTAINER", "PDK_ROOT", "PDK"):
        monkeypatch.delenv(var, raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    # docker is "reachable" so the decision is the receipt's, not the host's.
    import _container_exec as cex
    monkeypatch.setattr(cex, "no_container_route", lambda: False)


def rules(rep):
    return [f["rule"] for f in rep["findings"]]


# ── the decision: which reader, and why ────────────────────────────────────


# ── the consequence: the inventory is judged where the run looked ──────────
def test_an_inventory_absent_here_but_present_there_is_not_uncorroborated(
        tmp_path, monkeypatch):
    p, image = fixture(tmp_path)
    install(monkeypatch, image)
    assert not any((p / l.lstrip("/")).exists() for l in LEFS)
    assert ("is_file", LEFS[0]) in image.asked


def test_an_explicit_pdk_argument_is_still_the_callers_word(tmp_path,
                                                            monkeypatch):
    p, image = fixture(tmp_path)
    install(monkeypatch, image)
    rep = json.loads((p / "reports/phase3/padring.json").read_text())
    assert rep["pdk_read_where"] == "the PDK argument given"
    assert image.asked == []


def test_the_tech_view_declaration_is_read_through_the_same_seam(tmp_path,
                                                                 monkeypatch):
    """The last host read in this path: `IoLibrary` used a bare `read_text()`
    for its tech-view configs while their paths came from a reader-aware
    discovery, so a declaration found in the image and read here raised and was
    swallowed -- and the gate published "PAD-class sites available: []"."""
    p, image = fixture(tmp_path)
    image.files[CONFIG] = SITE_DECL
    install(monkeypatch, image)
    assert ("read", CONFIG) in image.asked


# ── the reader itself ──────────────────────────────────────────────────────
def test_an_unreachable_image_is_unknown_never_a_default():
    reader = authority.ImageReader(DIGEST, runner=lambda _i, _a: (127, ""))
    for query in (lambda: reader.is_file("/x"),
                  lambda: reader.is_dir("/x"),
                  lambda: reader.read_text("/x"),
                  lambda: reader.glob("/x", "*")):
        with pytest.raises(OSError, match="rc=127"):
            query()
    absent = authority.ImageReader(
        DIGEST, runner=lambda _i, argv: (0, "[]") if argv[0] == "python3"
        else (1, ""))
    assert absent.is_file("/x") is False
    assert absent.is_dir("/x") is False
    assert absent.read_text("/x") is None
    assert absent.glob("/x", "*") == []


def test_a_read_only_image_is_asked_each_question_once():
    calls = []

    def runner(image, argv):
        calls.append(argv)
        return 0, "MACRO m\nEND m\n"

    reader = authority.ImageReader(DIGEST, runner=runner)
    for _ in range(3):
        reader.read_text("/pdk/a.lef")
        reader.is_file("/pdk/a.lef")
    assert len(calls) == 2, calls
