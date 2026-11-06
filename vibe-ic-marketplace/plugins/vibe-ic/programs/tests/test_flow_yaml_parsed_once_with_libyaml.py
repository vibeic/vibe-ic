"""F18: the flow yaml is parsed ONCE per process, with libyaml when present,
and the parse is IDENTICAL to `yaml.safe_load`'s.

Since e06c227f9 every gate program's exit parsed the 645 KB
`flow/phase1_phase2_phase3.yaml` with pure-Python `yaml.safe_load` (~0.4 s),
twice for some, and `flow_compliance_check` parsed it three more times per
launch. `programs/_flow_yaml.load` is the one loader now. These tests hold:

  * the in-flow callers (step_metrics, flow_compliance_check,
    stage_on_pass_review) parse the flow at most once per process, and never
    with the pure-Python scanner when libyaml is importable;
  * the result is deep-equal -- values, Python types AND key order -- to
    `yaml.safe_load(read_text(...))` on the REAL flow yaml;
  * an edit re-parses, even one that keeps mtime and size;
  * a PyYAML built without libyaml falls back to SafeLoader, same result;
  * every caller gets its own copy, as with a fresh safe_load;
  * read/decode/parse errors are the ones read_text + safe_load raised.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml
import yaml.constructor
import yaml.reader

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"


def _strict_equal(a, b, where="$"):
    """Deep equality that also demands the same Python type at every node and
    the same dict key order (`1 == True` and `{a,b} == {b,a}` do not pass)."""
    assert type(a) is type(b), f"{where}: {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        assert list(a.keys()) == list(b.keys()), f"{where}: key order/set differs"
        for k in a:
            _strict_equal(a[k], b[k], f"{where}.{k}")
    elif isinstance(a, list):
        assert len(a) == len(b), f"{where}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            _strict_equal(x, y, f"{where}[{i}]")
    else:
        assert a == b, f"{where}: {a!r} != {b!r}"


class _ParseSpy:
    """Counts every document construction (both loaders end in
    BaseConstructor.get_single_data) and every pure-Python scan (only the
    pure-Python loaders construct a yaml.reader.Reader)."""

    def __init__(self, monkeypatch):
        self.docs = []
        self.pure_python = 0
        spy = self
        orig_get = yaml.constructor.BaseConstructor.get_single_data
        orig_reader = yaml.reader.Reader.__init__

        def get_single_data(self_):
            doc = orig_get(self_)
            spy.docs.append(type(self_).__name__)
            return doc

        def reader_init(self_, stream):
            if isinstance(stream, str) and len(stream) > 100_000:
                spy.pure_python += 1
            return orig_reader(self_, stream)

        monkeypatch.setattr(yaml.constructor.BaseConstructor,
                            "get_single_data", get_single_data)
        monkeypatch.setattr(yaml.reader.Reader, "__init__", reader_init)


@pytest.fixture(autouse=True)
def _fresh_cache():
    # getattr: on a tree without the shared loader this is a no-op, so the
    # behavioural tests below still RUN there and answer wrongly (red).
    fy = sys.modules.get("_flow_yaml")
    if fy is not None:
        fy.clear_cache()
    yield
    fy = sys.modules.get("_flow_yaml")
    if fy is not None:
        fy.clear_cache()


def _libyaml() -> bool:
    return getattr(yaml, "CSafeLoader", None) is not None


# --------------------------------------------------------------------------- #
# The in-flow callers: parse once, never pure-Python when libyaml is there.
# --------------------------------------------------------------------------- #

def test_step_metrics_gate_exit_parses_the_flow_once_and_with_libyaml(monkeypatch):
    import step_metrics as SM
    spy = _ParseSpy(monkeypatch)
    sid, why = SM.step_for_invocation("sta_report_check",
                                      [".", "--json", "reports/x.json"])
    runs = [SM._step_runs_program(s, "sta_report_check") for s in ("10", "23", "1")]
    again, _ = SM.step_for_invocation("sta_report_check",
                                      [".", "--json", "reports/x.json"])
    assert (sid, why) and again == sid
    assert runs == [True, True, False]          # the answers themselves
    assert len(spy.docs) == 1, f"flow parsed {len(spy.docs)}x in one process"
    if _libyaml():
        assert spy.pure_python == 0, "flow yaml went through the pure-Python scanner"






# --------------------------------------------------------------------------- #
# The loader itself.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("kwargs, read_kwargs", [
    ({"encoding": "utf-8"}, {"encoding": "utf-8"}),
    ({"errors": "replace"}, {"errors": "replace"}),
    ({}, {}),
])
def test_the_parse_is_identical_to_safe_load_on_the_real_flow(kwargs, read_kwargs):
    import _flow_yaml
    reference = yaml.safe_load(_FLOW.read_text(**read_kwargs))   # pure Python
    got = _flow_yaml.load(_FLOW, **kwargs)
    assert isinstance(reference, dict) and reference.get("steps")
    _strict_equal(got, reference)


def test_the_c_loader_is_chosen_when_pyyaml_has_it():
    import _flow_yaml
    _flow_yaml.load(_FLOW)
    want = "CSafeLoader" if _libyaml() else "SafeLoader"
    assert _flow_yaml.loader_class().__name__ == want
    assert _flow_yaml.PARSES == {want: 1}


def test_the_flow_is_parsed_once_per_process():
    import _flow_yaml
    for _ in range(4):
        _flow_yaml.load(_FLOW)
    assert sum(_flow_yaml.PARSES.values()) == 1


def test_every_caller_gets_its_own_copy():
    import _flow_yaml
    first = _flow_yaml.load(_FLOW)
    first["steps"].clear()
    first["injected"] = True
    second = _flow_yaml.load(_FLOW)
    assert second["steps"] and "injected" not in second
    _strict_equal(second, yaml.safe_load(_FLOW.read_text()))


def test_an_edit_is_re_read_even_with_the_same_mtime_and_size(tmp_path):
    import _flow_yaml
    p = tmp_path / "flow.yaml"
    p.write_text("steps:\n- id: '1'\n  name: aaaa\n", encoding="utf-8")
    st = os.stat(p)
    assert _flow_yaml.load(p) == {"steps": [{"id": "1", "name": "aaaa"}]}
    p.write_text("steps:\n- id: '1'\n  name: bbbb\n", encoding="utf-8")
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))       # same mtime, same size
    assert os.stat(p).st_mtime_ns == st.st_mtime_ns and os.stat(p).st_size == st.st_size
    assert _flow_yaml.load(p) == {"steps": [{"id": "1", "name": "bbbb"}]}
    assert _flow_yaml.load(p) == {"steps": [{"id": "1", "name": "bbbb"}]}
    assert sum(_flow_yaml.PARSES.values()) == 2


def test_a_touched_but_unchanged_file_keeps_its_parse(tmp_path):
    import _flow_yaml
    p = tmp_path / "flow.yaml"
    p.write_text("steps: []\n", encoding="utf-8")
    _flow_yaml.load(p)
    os.utime(p, ns=(1, 1))
    assert _flow_yaml.load(p) == {"steps": []}
    # mtime is part of the key, so a touch re-parses; the content is the same.
    assert sum(_flow_yaml.PARSES.values()) == 2


def test_the_fallback_when_libyaml_is_absent_in_this_process(monkeypatch):
    import _flow_yaml
    monkeypatch.delattr(yaml, "CSafeLoader", raising=False)
    assert _flow_yaml.loader_class() is yaml.SafeLoader
    got = _flow_yaml.load(_FLOW, encoding="utf-8")
    assert _flow_yaml.PARSES == {"SafeLoader": 1}
    monkeypatch.undo()
    _strict_equal(got, yaml.safe_load(_FLOW.read_text(encoding="utf-8")))


def test_the_fallback_when_pyyaml_was_built_without_libyaml(tmp_path):
    """A real PyYAML-without-libyaml: block `yaml._yaml` before `yaml` is
    imported, so `yaml/__init__` never defines CSafeLoader. The gate-exit path
    (step_metrics) must still answer, and answer the same."""
    code = textwrap.dedent(f"""
        import json, sys
        sys.modules["yaml._yaml"] = None          # libyaml extension absent
        import yaml
        assert not hasattr(yaml, "CSafeLoader"), "simulation failed"
        sys.path.insert(0, {str(_PROGRAMS)!r})
        import step_metrics as SM, _flow_yaml
        sid = SM.step_for_invocation("sta_report_check",
                                     [".", "--json", "reports/x.json"])
        runs = SM._step_runs_program("23", "sta_report_check")
        print(json.dumps({{"sid": sid, "runs": runs,
                          "parses": _flow_yaml.PARSES,
                          "with_libyaml": yaml.__with_libyaml__}}))
    """)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, timeout=120,
                         env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    import step_metrics as SM
    want_sid = SM.step_for_invocation("sta_report_check",
                                      [".", "--json", "reports/x.json"])
    assert got["with_libyaml"] is False
    assert got["parses"] == {"SafeLoader": 1}
    assert tuple(got["sid"]) == tuple(want_sid)
    assert got["runs"] is True


def test_newlines_and_decoding_match_read_text(tmp_path):
    import _flow_yaml
    p = tmp_path / "crlf.yaml"
    p.write_bytes(b"a: |\r\n  one\r\n  two\r\nb: \xff\r\n")
    assert _flow_yaml.load(p, errors="replace") == \
        yaml.safe_load(p.read_text(errors="replace"))
    with pytest.raises(UnicodeDecodeError):
        p.read_text(encoding="utf-8")
    with pytest.raises(UnicodeDecodeError):
        _flow_yaml.load(p, encoding="utf-8")


def test_errors_are_the_ones_read_text_and_safe_load_raised(tmp_path):
    import _flow_yaml
    with pytest.raises(FileNotFoundError):
        _flow_yaml.load(tmp_path / "absent.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("steps: [\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(bad.read_text())
    with pytest.raises(yaml.YAMLError):
        _flow_yaml.load(bad)
    assert _flow_yaml.PARSES == {}                          # nothing cached
    bad.write_text("steps: []\n", encoding="utf-8")
    assert _flow_yaml.load(bad) == {"steps": []}


# --------------------------------------------------------------------------- #
# The other in-flow callers a full spm audit launches (measured: 33 of the
# 137 flow parses of one flow_compliance_check run went through these four).
# --------------------------------------------------------------------------- #



def _call_l24_signoff_requirements_extract():
    import l24_signoff_requirements_extract as M
    M._RECORD_CACHE.clear()
    return M._declared_records(_FLOW)






@pytest.mark.parametrize("call", [
    "_call_waivers_schema_check",
    "_call_l24_signoff_requirements_extract",
    "_call_closed_loop_metric_reaches_its_producer",
    "_call_phase1_planned_consumer_starved_check",
])
def test_the_other_in_flow_callers_parse_through_the_shared_loader(call, monkeypatch, tmp_path):
    fn = globals()[call]
    args = (tmp_path,) if call.endswith("starved_check") else ()
    fn(*args)                            # import-time effects happen here
    fy = sys.modules.get("_flow_yaml")
    if fy is not None:
        fy.clear_cache()
    spy = _ParseSpy(monkeypatch)
    first = fn(*args)
    second = fn(*args)
    assert first == second
    if call.endswith("starved_check"):
        assert first != 2, "OPERATIONAL refusal: the flow was not read"
    else:
        assert first not in (None, {}, frozenset(), 0), f"{call}: empty answer"
    flow_docs = len(spy.docs)
    assert flow_docs >= 1, "the call never read the flow; nothing measured"
    if _libyaml():
        assert spy.pure_python == 0, f"{call}: flow yaml went through the pure-Python scanner"


def test_decode_variants_of_the_same_text_share_one_parse():
    """A full spm audit measured 137 parses in 95 processes when the key held
    (encoding, errors): FCC reads with errors="replace" and with the locale
    default, step_metrics with utf-8. The same decoded text is one parse."""
    import _flow_yaml
    a = _flow_yaml.load(_FLOW, encoding="utf-8")
    b = _flow_yaml.load(_FLOW, errors="replace")
    c = _flow_yaml.load(_FLOW)
    d = _flow_yaml.load(_FLOW, encoding="utf-8", errors="replace")
    assert a == b == c == d
    assert sum(_flow_yaml.PARSES.values()) == 1


def test_different_decoded_texts_of_one_file_are_different_parses(tmp_path):
    import _flow_yaml
    p = tmp_path / "f.yaml"
    p.write_bytes(b"k: a\xffb\n")
    replaced = _flow_yaml.load(p, errors="replace")
    ignored = _flow_yaml.load(p, errors="ignore")
    assert replaced == yaml.safe_load(p.read_text(errors="replace")) == {"k": "a�b"}
    assert ignored == yaml.safe_load(p.read_text(errors="ignore")) == {"k": "ab"}
    assert sum(_flow_yaml.PARSES.values()) == 2




def _metadata_steps(name, result):
    return result[1] if name == 'dashboard' else result[0] if name == 'required_inputs' else result












def test_profiled_identity_reader_keeps_absolute_path_import_without_programs_on_sys_path(tmp_path):
    path = tmp_path / 'custom.yaml'
    path.write_text("steps:\n- id: 'custom'\n  name: absolute path control\n", encoding='utf-8')
    code = textwrap.dedent(f'''
        import importlib.util, json, sys
        from pathlib import Path
        programs = Path({str(_PROGRAMS)!r}).resolve()
        sys.path[:] = [p for p in sys.path if Path(p).resolve() != programs]
        assert str(programs) not in sys.path
        spec = importlib.util.spec_from_file_location('absolute_identity_control', programs / '_step_identity.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        print(json.dumps(module.load_steps(Path({str(path)!r}))))
    ''')
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path,
                            capture_output=True, text=True, timeout=120,
                            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [{'id': 'custom', 'name': 'absolute path control'}]
