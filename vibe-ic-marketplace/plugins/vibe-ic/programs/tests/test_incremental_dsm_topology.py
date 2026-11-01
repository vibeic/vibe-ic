"""Synthetic idsm-model controls, not design-oracle or native ADC acceptance."""
import copy
import json
import math

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
