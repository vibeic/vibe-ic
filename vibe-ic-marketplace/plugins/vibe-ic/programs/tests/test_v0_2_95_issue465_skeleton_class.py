"""v0.2.95 #465 — L-doc skeleton emitter must NOT stamp a hardcoded ic_class.

ORGANIC-20260606 (#465, continuation of #435 / #450): the L-doc skeleton
emitter (`phase1_post_process.emit_l_doc_skeleton`) used to stamp whatever
ic_class it was handed, and the runner default could leak a concrete
constant (`digital_arithmetic_primitive`) into the emitted doc. Observed:
a pure-analog project's L19 carried `digital_arithmetic_primitive` while
`reports/ic_class.json` correctly said `pure_analog` — re-introducing the
two-sources-of-truth detector fork at the EMISSION layer.

建議修法: ANY doc emitter that records an ic_class field must read
`reports/ic_class.json['ic_class']` (honest 'unknown' when the file is
absent); hardcoded default class constants are forbidden.

CORPUS-SWEEP guard: digital projects keep their detected class; absent
ic_class.json yields 'unknown', never a fabricated class.

chip-AGNOSTIC: synthetic project dirs + synthetic class strings only.
"""
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
mod = importlib.import_module("phase1_post_process")  # noqa: E402


def _write_ic_class(project: Path, ic_class) -> None:
    """Persist a reports/ic_class.json the way detect_ic_class would."""
    rep = project / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "ic_class.json").write_text(
        json.dumps({"ic_class": ic_class}), encoding="utf-8")


# ---------------------------------------------------------------------------
# The fixed path — persisted ic_class.json is the single source of truth
# ---------------------------------------------------------------------------
class TestSkeletonReadsPersistedClass:
    def test_pure_analog_l19_not_stamped_digital(self, tmp_path):
        """The exact #465 reproduction: project is pure_analog, but a caller
        hands the emitter a stale `digital_arithmetic_primitive`. The emitted
        L19 must carry pure_analog (from reports/ic_class.json), NOT the
        stale digital class."""
        _write_ic_class(tmp_path, "pure_analog")
        sk = mod.emit_l_doc_skeleton(
            "L19", "digital_arithmetic_primitive", project_dir=tmp_path)
        assert sk["ic_class"] == "pure_analog"
        assert sk["ic_class"] != "digital_arithmetic_primitive"

    def test_persisted_class_overrides_any_caller_value(self, tmp_path):
        _write_ic_class(tmp_path, "chip_otp_centric")
        # caller passes a wholly unrelated class — persisted truth wins
        sk = mod.emit_l_doc_skeleton(
            "L21", "bus_interconnect_protocol", project_dir=tmp_path)
        assert sk["ic_class"] == "chip_otp_centric"

    def test_persisted_class_used_even_when_caller_omits_ic_class(
            self, tmp_path):
        _write_ic_class(tmp_path, "pure_analog")
        sk = mod.emit_l_doc_skeleton("L19", project_dir=tmp_path)
        assert sk["ic_class"] == "pure_analog"

    def test_canonical_ic_class_reads_persisted(self, tmp_path):
        _write_ic_class(tmp_path, "mixed_signal")
        assert mod.canonical_ic_class(tmp_path) == "mixed_signal"


# ---------------------------------------------------------------------------
# CORPUS-SWEEP guard — absent file → 'unknown', never a fabricated class
# ---------------------------------------------------------------------------
class TestAbsentClassFileYieldsUnknown:
    def test_absent_file_emits_unknown(self, tmp_path):
        # no reports/ic_class.json on disk
        sk = mod.emit_l_doc_skeleton(
            "L19", "digital_arithmetic_primitive", project_dir=tmp_path)
        assert sk["ic_class"] == "unknown"
        assert sk["ic_class"] != "digital_arithmetic_primitive"

    def test_canonical_ic_class_absent_is_unknown(self, tmp_path):
        assert mod.canonical_ic_class(tmp_path) == "unknown"

    def test_unreadable_file_is_unknown(self, tmp_path):
        rep = tmp_path / "reports"
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "ic_class.json").write_text("{not valid json", encoding="utf-8")
        assert mod.canonical_ic_class(tmp_path) == "unknown"
        sk = mod.emit_l_doc_skeleton("L19", "pure_analog", project_dir=tmp_path)
        assert sk["ic_class"] == "unknown"

    def test_file_without_class_key_is_unknown(self, tmp_path):
        rep = tmp_path / "reports"
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "ic_class.json").write_text(
            json.dumps({"protocol_class": "none"}), encoding="utf-8")
        assert mod.canonical_ic_class(tmp_path) == "unknown"


# ---------------------------------------------------------------------------
# Regression guard for prior CORRECT behavior — digital projects keep class
# ---------------------------------------------------------------------------
class TestDigitalKeepsDetectedClass:
    def test_digital_project_keeps_detected_class(self, tmp_path):
        """CORPUS-SWEEP: a genuinely-digital project whose reports/ic_class.json
        says digital_arithmetic_primitive must STILL carry that class. The fix
        must not blanket-erase a correctly-detected digital class."""
        _write_ic_class(tmp_path, "digital_arithmetic_primitive")
        sk = mod.emit_l_doc_skeleton(
            "L19", "digital_arithmetic_primitive", project_dir=tmp_path)
        assert sk["ic_class"] == "digital_arithmetic_primitive"

    def test_no_project_dir_uses_caller_value_verbatim(self, tmp_path):
        """Backward-compat: when no project_dir is supplied (legacy callers),
        the caller-supplied class is used verbatim and is NOT silently
        overridden — but it is still the caller's responsibility, not a
        hardcoded default."""
        sk = mod.emit_l_doc_skeleton("L14", "bus_interconnect_protocol")
        assert sk["ic_class"] == "bus_interconnect_protocol"

    def test_no_project_dir_no_class_falls_back_to_unknown(self):
        """No project_dir AND no caller class → honest 'unknown', never a
        fabricated concrete class."""
        sk = mod.emit_l_doc_skeleton("L14")
        assert sk["ic_class"] == "unknown"


# ---------------------------------------------------------------------------
# No hardcoded class constant anywhere in the emitter source
# ---------------------------------------------------------------------------
class TestNoHardcodedClassConstant:
    def test_source_has_no_default_class_constant(self):
        """The whole file must not assign a concrete ic_class as a default /
        constant (e.g. `ic_class = "digital_arithmetic_primitive"`). Such a
        stamp is the #465 root cause."""
        src = Path(mod.__file__).read_text(encoding="utf-8")
        # forbidden: any literal that DEFAULTS a class to a concrete value
        forbidden = (
            'ic_class = "digital_arithmetic_primitive"',
            "ic_class = 'digital_arithmetic_primitive'",
            'ic_class: str = "digital_arithmetic_primitive"',
            'ic_class=str("digital_arithmetic_primitive")',
        )
        for f in forbidden:
            assert f not in src, f"hardcoded class default found: {f!r}"


# ---------------------------------------------------------------------------
# post_process honors the persisted class too (na_stub + skeleton + result)
# ---------------------------------------------------------------------------
class TestPostProcessHonorsPersistedClass:
    def _setup_docs(self, tmp_path):
        gd = tmp_path / "phase1" / "generated_docs"
        gd.mkdir(parents=True, exist_ok=True)
        (gd / "L1_DATASHEET.json").write_text(
            json.dumps({"ic_name": "synthetic_part"}), encoding="utf-8")
        return tmp_path

    def test_post_process_skeleton_uses_persisted_not_arg(self, tmp_path):
        proj = self._setup_docs(tmp_path)
        _write_ic_class(proj, "pure_analog")
        # caller passes the WRONG (stale digital) class on the CLI/arg path
        rep = mod.post_process(proj, "digital_arithmetic_primitive")
        # result reflects the persisted truth, not the stale arg
        assert rep.ic_class == "pure_analog"
        # any emitted skeleton on disk must carry pure_analog
        gd = proj / "phase1" / "generated_docs"
        stamped = []
        for p in gd.glob("*.json"):
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict) and "ic_class" in d:
                stamped.append(d["ic_class"])
        assert stamped, "expected at least one emitted doc carrying ic_class"
        assert all(c == "pure_analog" for c in stamped), stamped
        assert "digital_arithmetic_primitive" not in stamped

    def test_post_process_falls_back_to_arg_when_no_persisted(self, tmp_path):
        """When the project has not persisted a class (file absent), the
        caller-supplied class is used (the CLI contract) — but it is the
        caller's value, not a hardcoded default."""
        proj = self._setup_docs(tmp_path)
        rep = mod.post_process(proj, "chip_otp_centric")
        assert rep.ic_class == "chip_otp_centric"
