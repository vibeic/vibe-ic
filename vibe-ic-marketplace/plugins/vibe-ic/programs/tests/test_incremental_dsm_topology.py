"""Synthetic idsm-model controls, not design-oracle or native ADC acceptance."""
import copy
import hashlib
import json
import math
from pathlib import Path

import pytest

import analog_adc_enob_corner_check as enob
import analog_incremental_capture as capture
import analog_incremental_decimator as dec
import analog_incremental_resolution as resolution
import analog_resolution_stimulus as stimulus
from _hostpaths import repo_path


GOLDEN = json.loads(repo_path("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
    "tests", "fixtures", "incremental_dsm_golden.json").read_text())
RECORDS = GOLDEN["records"]


def _declared(record):
    # Explicit A3 deck declaration, with no bitstream available to the reader.
    line = dec.stamp("incremental", record["updates"], len(record["a"]),
                     record["a"][0], record["delay"])
    declaration, detail = dec.read_stamp(line + " loop_topology=" + record["kind"])
    assert declaration is not None, detail
    options = {"order": declaration["order"], "coeff": declaration["coeff"],
               "feedback_delay": declaration["feedback_delay_clocks"]}
    if "loop_topology" in declaration:
        options["topology"] = declaration["loop_topology"]
    return options


@pytest.mark.parametrize("record", RECORDS, ids=lambda r: f'{r["kind"]}-D{r["delay"]}-N{r["updates"]}')
def test_model_stream_decode_and_quantization_bound(record):
    bits = [1. if bit == "1" else -1. for stream in record["bits"] for bit in stream]
    actual, detail = dec.decimate(bits, record["updates"], **_declared(record))
    assert actual is not None, detail
    assert actual == pytest.approx(record["decoded"], abs=2e-12)
    # Held-DC identity: error = -x_L[N] / sum(input impulse response).
    normalizer = math.prod(record["a"]) * math.comb(record["updates"], len(record["a"]))
    bound = max(record["peaks"][-1]) / normalizer
    assert max(abs(x - u) for x, u in zip(actual, record["inputs"])) <= bound + 2e-12


@pytest.mark.parametrize("delay", [0, 1])
def test_coi3_weights_are_independent_of_gains_and_shift_only_the_decisions(delay):
    record = next(r for r in RECORDS if r["kind"] == "ciff" and r["delay"] == delay)
    options = _declared(record)
    n = 512
    expected = [math.comb(n - 1 - k - delay, 2) if n - 1 - k - delay >= 2 else 0
                for k in range(n)]
    for coefficient in (.03, .2, 1., 2.):
        options["coeff"] = coefficient
        assert dec.matched_weights(n, **options) == pytest.approx(expected)


def test_a2_declaration_carries_ciff_and_unequal_gains_to_the_stamp():
    record = RECORDS[0]
    ir = {"constants": {"loop_topology": "ciff", "window_clocks": 512,
                        "feedback_delay_clocks": record["delay"]},
          "stage_expansion": {"stages": 3, "count_from": "order", "coefficients": record["a"]}}
    declaration = stimulus.incremental_decode({"converter_type": "incremental"}, ir)
    assert declaration["declared"], declaration
    assert dec.read_stamp(declaration["stamp"])[0]["loop_topology"] == "ciff"
    bad = copy.deepcopy(ir)
    bad["topology"] = "CIFB"
    assert not stimulus.incremental_decode({"converter_type": "incremental"}, bad)["declared"]


@pytest.mark.parametrize("kind", ["unknown", "CIFF_extra"])
def test_unknown_declared_topology_is_refused(kind):
    line = dec.stamp("incremental", 512, 3, .2, 0)
    declaration, detail = dec.read_stamp(line + " loop_topology=" + kind)
    assert declaration is None, detail


def test_capture_passes_declared_topology_to_the_decimator(tmp_path):
    from test_analog_incremental_capture import _dump, _declaration
    declaration = _declaration(delay=0)
    declaration.update(order=3, loop_topology="ciff")
    conversion, = capture.decode_capture(_dump(tmp_path / "wave.dat"), (1, 1, 1.2),
                                         declaration, {})["conversions"]
    # Three actual updates: CoI3 is [1,0,0]. The first bit alone contributes.
    assert conversion["decoded"] == 1.


@pytest.mark.parametrize("delay", [0, 1])
def test_enob_consumer_uses_the_ciff_deck_declaration(delay):
    from test_r0915_71_the_enob_gate_decodes_incrementally import _dump
    record = next(r for r in RECORDS if r["kind"] == "ciff" and
                  r["delay"] == delay and r["updates"] == 512)
    bits = [1. if bit == "1" else -1. for stream in record["bits"] for bit in stream]
    n = record["updates"]
    f = 9e6 / ((len(record["inputs"]) - 1) * n)
    deck = "\n".join([dec.stamp("incremental", n, 3, record["a"][0], delay) + " loop_topology=ciff",
        "v_clk clk 0 pulse(0 1.2 1u 1n 1n 499n 1000n)",
        f"v_in vin 0 sin(0.6 0.36 {f:.12g})", f".tran 5n {len(bits)/1e6}",
        "wrdata out.data v(bit_out)", ".end"])
    measured, detail = enob.sndr_db_incremental(deck, _dump(bits))
    assert measured is not None, detail
    # Same spectral instrument, with independently generated decoded values.
    power = enob._in_band_power(record["decoded"][1:], 31)
    signal = sum(power[b - 1] for b in (8, 9, 10))
    expected = 10 * math.log10(signal / (sum(power) - signal))
    assert measured == pytest.approx(expected, abs=.1), detail
    assert measured > 110, detail


def test_long_reference_preserves_bounded_third_order_and_detects_overload(monkeypatch):
    golden = GOLDEN["stability"]
    observed = []
    def model_peaks(window, b1, a, c, delay, source, **kwargs):
        observed.append(window)
        index = round(source(0) * 100) + 110
        peaks = golden["peaks_by_window"][str(window)][index]
        return {"peak_per_stage": peaks, "saturated": False, "unbounded": False}
    monkeypatch.setattr(resolution, "run_loop", model_peaks)
    limit = resolution.stable_input_limit(1., [1., 0., 0.], [0., 1., 1.], 0,
                                         512, 64, top=1.1)
    assert golden["short_limit"] < golden["long_limit"]
    assert limit == pytest.approx(golden["long_limit"])
    assert limit < 1.0  # actual overload is still refused
    assert 2048 in observed and 64 not in observed


def _model_args(record):
    a = record["a"]
    return {"b1": a[0], "a": [a[0], 0., 0.], "c": [0., *a[1:]],
            "feedback_delay": record["delay"], "feedforward": record["c"],
            "input_feedforward": record["c0"], "feedback_compensation": record["k0"]}


@pytest.mark.parametrize("delay", [0, 1])
def test_ciff_stability_recurrence_matches_the_golden_model(delay):
    record = next(r for r in RECORDS if r["kind"] == "ciff" and r["delay"] == delay)
    actual = resolution.run_loop(record["updates"], stimulus=lambda n: record["inputs"][0],
                                 **_model_args(record))
    assert "".join(map(str, actual["bits"])) == record["bits"][0]
    assert actual["peak_per_stage"] == pytest.approx([p[0] for p in record["peaks"]])


@pytest.mark.parametrize("limits", [(), (.01, .01, .01)])
def test_unbounded_or_saturating_loop_is_still_flagged(limits):
    golden = GOLDEN["stability"]
    kwargs = {"b1": 1., "a": [1., 0., 0.], "c": [0., 1., 1.],
              "feedback_delay": 0, "feedforward": golden["c"], "input_feedforward": 1.,
              "state_limits": limits}
    limit = resolution.stable_input_limit(window=512, top=1.1, **kwargs)
    assert limit < 1.0
    if limits:
        assert limit == 0.
    else:
        assert limit == pytest.approx(golden["long_limit"])


def test_nonfinite_states_cannot_pass_the_stability_check():
    limit = resolution.stable_input_limit(math.inf, [1.], [0.], 0, 8)
    assert limit == 0.


@pytest.mark.parametrize("record", GOLDEN["general_records"],
    ids=lambda r: f'{r["loop"]["kind"]}-levels{r["loop"]["levels"]}-D{r["loop"]["D"]}')
def test_state_equation_weights_match_unequal_and_multilevel_model(record):
    loop = record["loop"]
    order = len(loop["a"])
    # The study explicitly defines delaying integrators and their injection
    # vectors. This reference is independent of the topology-name shortcut.
    transition = [[float(i == j) + (loop["a"][i] if i == j + 1 else 0.)
                   for j in range(order)] for i in range(order)]
    feedback = [-loop["a"][0]] + ([-b for b in loop["b"][1:]] if loop["kind"] == "cifb"
                                      else [0.] * (order - 1))
    wu, wv = dec.state_weights(record["updates"], transition,
        [loop["a"][0]] + [0.] * (order - 1), feedback, loop["D"])
    mapping = {"-": -1., "0": 0., "+": 1.}
    decoded = [sum(w * mapping[code] for w, code in zip(wv, stream)) / sum(wu)
               for stream in record["decisions"]]
    assert decoded == pytest.approx(record["decoded"], abs=2e-12)
    assert max(abs(x-u) for x,u in zip(decoded, record["inputs"])) <= (
        max(record["peaks"][-1]) / sum(wu) + 2e-12)
    if loop["levels"] == 3:
        assert {code for stream in record["decisions"] for code in stream} == {"-", "0", "+"}


@pytest.mark.parametrize("voltages, expected", [([0., 1.2], -1.), ([0., 0.], 0.), ([1.2, 0.], 1.)])
def test_declared_comparator_codebook_preserves_three_decision_levels(voltages, expected):
    value, margin = dec.decision_value(voltages, [.6, .6],
                                      [([0, 1], -1.), ([0, 0], 0.), ([1, 0], 1.)])
    assert value == expected and margin == .6


@pytest.mark.parametrize("voltages", [[1.2, 1.2], [.6, 0.], [math.nan, 0.]])
def test_undeclared_or_ambiguous_decision_code_is_refused(voltages):
    with pytest.raises(ValueError, match="incremental_invalid_decision_code"):
        dec.decision_value(voltages, [.6, .6], [([0, 1], -1.), ([0, 0], 0.), ([1, 0], 1.)])


PRODUCER = json.loads(repo_path("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
    "tests", "fixtures", "producer_loop_declarations.json").read_text())


def _loop_ir(record):
    loop = record["loop"]
    declared = copy.deepcopy(next(item["declaration"] for item in PRODUCER["records"]
                                 if item["kind"] == loop["kind"] and item["D"] == loop["D"]))
    if loop["levels"] == 3:
        # A synthetic extension for decoder coverage. The aligned producer
        # itself emits two levels; this does not claim a ternary A2 circuit.
        declared["quantizer_levels"] = 3
        declared["normalization"]["dac_output_levels"] = [-1., 0., 1.]
    return {"constants": {"window_clocks": record["updates"]}, "loop_declaration": declared}


def _model_codec(record):
    if record["loop"]["levels"] == 2:
        return None
    return {"output_nodes": ["decision_hi", "decision_lo"],
            "codes": [[[0, 1], -1.], [[0, 0], 0.], [[1, 0], 1.]]}


@pytest.mark.parametrize("record", GOLDEN["general_records"],
    ids=lambda r: f'{r["loop"]["kind"]}-D{r["loop"]["D"]}')
def test_ir_equations_stamp_and_decoder_match_model(record):
    ir = _loop_ir(record)
    declaration = stimulus.incremental_decode({"converter_type": "incremental"}, ir, decision_encoding=_model_codec(record))
    assert declaration["declared"], declaration
    model = declaration["loop_model"]
    import analog_ciff
    assert PRODUCER["producer_source_sha256"] == hashlib.sha256(
        Path(analog_ciff.__file__).read_bytes()).hexdigest()
    assert model["normalization"]["full_scale_over_reference"] == 1.3
    assert dec.read_stamp(declaration["stamp"])[0]["loop_model"] == model
    bits = [{"-": -1., "0": 0., "+": 1.}[code] for stream in record["decisions"] for code in stream]
    actual, detail = dec.decimate(bits, record["updates"], loop_model=model)
    assert actual == pytest.approx(record["decoded"], abs=2e-12), detail


@pytest.mark.parametrize("ratio", [1., 1.4])
def test_landed_shared_dac_declaration_drives_matched_decode(tmp_path, ratio):
    from test_analog_ciff import _emit
    _, ir = _emit(tmp_path, shared_input_dac=1, ciff_dac_ratio=ratio)
    declared = stimulus.incremental_decode({"converter_type": "incremental"}, ir)
    assert declared["declared"], declared
    raw, model = ir["loop_declaration"], declared["loop_model"]
    assert model["feedback_vector"] == raw["feedback_vector"]
    assert [p for p in model["state_paths"] if p["kind"] == "dac_shared"]
    assert dec.read_stamp(declared["stamp"])[0]["loop_model"] == model
    broken = copy.deepcopy(ir)
    broken["loop_declaration"]["paths"] = [p for p in raw["paths"] if p["kind"] != "dac_shared"]
    refused = stimulus.incremental_decode({"converter_type": "incremental"}, broken)
    assert not refused["declared"] and refused["reason"] == dec.BAD_STATE_EQUATIONS


@pytest.mark.parametrize("ciff", [0, 1])
def test_landed_producer_equations_allow_unequal_stage_gains(tmp_path, ciff):
    from test_analog_ciff import _emit
    order = 3 if ciff else 2  # The landed legacy CIFB entry admits orders 1 and 2.
    gains = {f"a{i}": gain for i, gain in enumerate((.21, .34, .18)[:order], 1)}
    _, ir = _emit(tmp_path, order, ciff=ciff, **gains)
    declared = stimulus.incremental_decode({"converter_type": "incremental"}, ir)
    assert declared["declared"], declared
    assert declared["loop_model"]["input_vector"] == ir["loop_declaration"]["input_vector"]
    assert declared["loop_model"]["transition"] == ir["loop_declaration"]["A"]


def test_explicit_equations_own_the_weights_even_with_non_cascade_coefficients():
    record = GOLDEN["general_records"][-1]
    ir = _loop_ir(record)
    raw = ir["loop_declaration"]
    raw["A"] = [[.99, -.02], [.37, 1.]]
    model = stimulus.incremental_loop_adapter(ir)
    assert model["feedback_vector"] == [-.21, -.37]
    assert model["transition"] == [[.99, -.02], [.37, 1.]]


def test_capture_decodes_multiple_declared_outputs_and_preserves_zero(tmp_path):
    from test_analog_incremental_capture import _dump, _declaration
    declaration = _declaration(delay=0)
    # CoI1 is an average. Three active decisions are +1, 0, -1.
    model = {"transition": [[1.]], "input_vector": [1.], "feedback_vector": [-1.],
             "feedback_delay_clocks": 0, "feedforward_weights": [1.], "input_feedforward": 0.,
             "feedback_compensation": 0., "quantizer_levels": [-1., 0., 1.],
             "decision_encoding": {"output_nodes": ["decision_hi", "decision_lo"],
                 "threshold_fractions": [.5, .5], "codes": [[[0,1],-1.], [[0,0],0.], [[1,0],1.]]}}
    declaration["loop_model"] = model
    path = _dump(tmp_path / "multi.dat")
    lines = path.read_text().splitlines()
    lines[0] = "time v(decision_hi) v(decision_lo) reset input v(xdut.transfer_n) v(xdut.transfer_p)"
    for index in range(1, len(lines)):
        fields = lines[index].split()
        slot = math.floor(float(fields[0]) - 1 + 1e-9)
        pair = ('1.2', '0') if slot == 1 else ('0', '0') if slot == 2 else ('0', '1.2')
        lines[index] = " ".join([fields[0], *pair, *fields[2:]])
    path.write_text("\n".join(lines)+"\n")
    conversion, = capture.decode_capture(path, (1, 1, 1.2), declaration, {})["conversions"]
    assert conversion["decoded"] == 0.
    assert conversion["minimum_decision_margin_v"] == .6


@pytest.mark.parametrize("record", [r for r in GOLDEN["general_records"] if r["loop"]["levels"] == 3],
                         ids=lambda r: f'D{r["loop"]["D"]}')
def test_enob_reads_declared_multilevel_output_codebook(record):
    declaration = stimulus.incremental_decode({"converter_type": "incremental"}, _loop_ir(record), decision_encoding=_model_codec(record))
    n = record["updates"]
    f = 9e6 / (64*n)
    deck = "\n".join([declaration["stamp"], "v_clk clk 0 pulse(0 1.2 1u 1n 1n 499n 1000n)",
        f"v_in vin 0 sin(0.6 0.36 {f:.12g})", f".tran 5n {65*n/1e6}",
        "wrdata out.data v(decision_hi) v(decision_lo)", ".end"])
    rows = ["time v(decision_hi) v(decision_lo)"]
    bits = "".join(record["decisions"])
    for k, bit in enumerate(bits):
        hi, lo = {"+": (1.2, 0.), "-": (0., 1.2), "0": (0., 0.)}[bit]
        for phase in (0., .9):
            rows.append(f'{1e-6+(k+phase)*1e-6:.14g} {hi} {lo}')
    rows.append(f'{1e-6+len(bits)*1e-6:.14g} {hi} {lo}')
    measured, detail = enob.sndr_db_incremental(deck, "\n".join(rows))
    power = enob._in_band_power(record["decoded"][1:], 31)
    signal = sum(power[b-1] for b in (8,9,10))
    expected = 10*math.log10(signal/(sum(power)-signal))
    assert measured == pytest.approx(expected, abs=.1), detail


@pytest.mark.parametrize("record", GOLDEN["general_records"],
    ids=lambda r: f'{r["loop"]["kind"]}-levels{r["loop"]["levels"]}-D{r["loop"]["D"]}')
def test_stability_and_decoder_share_the_same_declared_equations(record):
    model = stimulus.incremental_loop_adapter(_loop_ir(record), decision_encoding=_model_codec(record))
    actual = resolution.run_loop(record["updates"], 0., [], [], 0,
        lambda n: record["inputs"][0], loop_model=model)
    expected = [{"-": -1., "0": 0., "+": 1.}[code] for code in record["decisions"][0]]
    assert actual["decisions"] == expected
    assert actual["peak_per_stage"] == pytest.approx([stage[0] for stage in record["peaks"]])


def test_declared_stability_model_uses_long_reference_and_rejects_clipping():
    model = {"transition": [[1.,0.,0.],[1.,1.,0.],[0.,1.,1.]],
        "input_vector": [1.,0.,0.], "feedback_vector": [-1.,0.,0.],
        "feedforward_weights": GOLDEN["stability"]["c"], "input_feedforward": 1.,
        "feedback_compensation": 0., "feedback_delay_clocks": 0, "quantizer_levels": [-1.,1.],
        "decision_encoding": None}
    assert resolution.declared_stable_input_limit(model, 512, reference_window=64, top=1.1) == pytest.approx(.84)
    assert resolution.declared_stable_input_limit(model, 512, state_limits=[.01]*3) == 0.


def test_multilevel_ir_requires_an_explicit_measurement_codebook():
    record = GOLDEN["general_records"][0]
    result = stimulus.incremental_decode({"converter_type": "incremental"}, _loop_ir(record))
    assert result["declared"] is False
    assert "decision_code" in result["reason"]


@pytest.mark.parametrize("arrays", [False, True])
def test_ciff_transfer_paths_come_from_the_published_contract_without_a_loop_probe(tmp_path, arrays):
    from test_analog_incremental_capture import _template
    _source, _spec, topology = _template(tmp_path)
    raw = copy.deepcopy(next(r["declaration"] for r in PRODUCER["records"] if r["kind"] == "cifb" and r["D"] == 0))
    chain = topology["stage_expansion"]["chain"]
    names = topology["loop_probe"]["coefficient_devices"]
    rename = {"input": chain[0], "state1": chain[1], "state2": chain[2], "bit_out": topology["ports"][-1]}
    for i in (1,2):
        rename[f"cs{i}"] = names["sampling"].format(i=i)
        rename[f"cf{i}"] = names["feedback"].format(i=i)
    def mapped(value):
        if isinstance(value,dict): return {k:v if k == "kind" else mapped(v) for k,v in value.items()}
        if isinstance(value,list): return [mapped(v) for v in value]
        return rename.get(value,value) if isinstance(value,str) else value
    raw = mapped(raw)
    raw.update(family="CIFF", b=[raw["b"][0],0.], feedback_vector=[raw["feedback_vector"][0],0.], dac_stages=[1])
    raw["paths"] = [p for p in raw["paths"] if not (p["kind"] == "dac" and p["destination_stage"] == 2)]
    second = names["feedback"].format(i=2)
    topology["devices"] = [d for d in topology["devices"] if second not in d["name"]]
    topology.pop("loop_probe")
    topology["loop_declaration"] = raw
    first = names["sampling"].format(i=1)
    if arrays:
        capacitor = next(d for d in topology["devices"] if d["name"] == first)
        topology["devices"].remove(capacitor)
        topology["devices"].extend({**capacitor,"name":f"{first}_u{i}"} for i in (0,1))
        topology["_provenance"] = {"layout_maxima": {"capacitor_arrays": [{"device": first,"units":2}]}}
    timing = capture._transfer_timing(topology,"xdut.reset_b")
    assert len(timing["groups"]) == 3 + int(arrays)
    assert second not in {g["capacitor"] for g in timing["groups"]}
