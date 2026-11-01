"""Incremental CIFF synthesis and SC topology specialization for A2/A3.

Uses the Butterworth high-pass pole family (SciPy butter), with its cutoff
solved for the requested peak NTF gain. In-band zero optimization uses the
Legendre roots, as in Schreier's synthesizeNTF opt=1 for orders 1--3.
Realization matches 1/NTF-1 in a controllable integrator basis, the same
linear loop-filter matching used by realizeNTF. No converter-specific sizing.
Imports NumPy/SciPy only when CIFF is requested; CIFB needs neither dependency.
"""
from copy import deepcopy
import math
import re


def spec_label(name):
    """Canonical A1 names for the numeric CIFF contract (no fuzzy matching)."""
    token = re.sub(r"[^a-z0-9]", "", str(name).lower())
    names = ["ciff", "ntf_hinf", "feedback_delay", "ntf_optimize_zeros",
             "c0", "k0", "ciff_summer_cap_ff", "ciff_dac_ratio",
             "designed_coefficients", "quantizer_levels", "startup_reset",
             "startup_reset_tau_ns", "startup_reset_cap_ff"]
    names += [f"{stem}{i}" for stem in ("a", "b", "c") for i in range(1, 4)]
    names += [f"ntf_{stem}{i}_{part}" for stem in ("zero", "pole")
              for i in range(1, 4) for part in ("real", "imag")]
    return next((n for n in names if n.replace("_", "") == token), None)


def _integer(values, key, default=None):
    value = values.get(key, default)
    if isinstance(value, bool) or value is None or not math.isfinite(value) or value != int(value):
        raise ValueError(f"CIFF {key} must be an integer")
    return int(value)


def _roots(values, stem, order):
    keys = [f"{stem}{i}_real" for i in range(1, order + 1)]
    if not any(k.startswith(stem) and k.endswith(("_real", "_imag")) for k in values):
        return None
    if not all(k in values for k in keys):
        raise ValueError(f"CIFF {stem} requires all {order} real/imaginary pairs")
    return [complex(values[k], values.get(k.replace("_real", "_imag"), 0.0)) for k in keys]


def _real_poly(roots):
    import numpy as np
    p = np.poly(roots)
    if not np.isfinite(p).all() or np.max(np.abs(p.imag)) > 1e-9:
        raise ValueError("CIFF roots must be finite and conjugate paired")
    return p.real


def _peak(num, poles):
    import numpy as np
    from scipy.optimize import minimize_scalar
    # Refine every sampled local maximum, including the band edges.
    w = np.linspace(0, np.pi, 2049)
    def gain(f):
        z = np.exp(1j * f)
        return abs(np.polyval(num, z) / np.prod(z - poles))
    zgrid = np.exp(1j*w)
    h = np.abs(np.polyval(num, zgrid) / np.prod(zgrid[:, None] - poles, axis=1))
    peaks = [h[0], h[-1]]
    for i in np.flatnonzero((h[1:-1] >= h[:-2]) & (h[1:-1] >= h[2:])) + 1:
        peaks.append(-minimize_scalar(lambda f: -gain(f), bounds=(w[i-1], w[i+1]),
                                     method="bounded").fun)
    return float(max(peaks))


def synthesize(values):
    """Return a real state-space CIFF and its NTF, using A1 numeric rows.

    x[n+1] = A*x[n] + b*(u[n]-v[n-D]);
    y[n] = c0*u[n] + c*x[n] - k0*v[n-1].
    For non-DC zeros, extra SC state-feedback branches realize the numerator
    in the first integrator. DAC feedback still enters stage 1 only.
    """
    import numpy as np
    from scipy.optimize import brentq
    from scipy.signal import butter
    order = _integer(values, "order")
    delay = _integer(values, "feedback_delay", 0)
    opt = _integer(values, "ntf_optimize_zeros", 0)
    if order not in (1, 2, 3) or delay not in (0, 1) or opt not in (0, 1):
        raise ValueError("CIFF supports order 1--3, feedback_delay 0/1, ntf_optimize_zeros 0/1")
    hinf = float(values["ntf_hinf"])
    if not math.isfinite(hinf) or not 1 < hinf < 2**order:
        raise ValueError("CIFF ntf_hinf must lie strictly between 1 and 2**order")
    zeros = _roots(values, "ntf_zero", order)
    if zeros is None:
        if opt:
            osr = float(values["osr"])
            if not math.isfinite(osr) or osr <= 1:
                raise ValueError("CIFF optimized zeros require osr > 1")
            zeros = np.exp(1j * np.pi / osr * np.polynomial.legendre.leggauss(order)[0])
        else:
            zeros = np.ones(order, dtype=complex)
    num = _real_poly(zeros)
    poles = _roots(values, "ntf_pole", order)
    if poles is None:
        def at(cutoff):
            return butter(order, cutoff, "high", output="zpk")[1]
        # For low-pass NTFs the out-of-band maximum is at z=-1. Do not
        # bracket on the *global* peak at cutoff->0: shifted zeros then leave
        # a DC spike, giving the bracket two positive ends. Check the global
        # peak after solving, so arbitrary user roots cannot evade H_inf.
        cutoff = brentq(lambda f: abs(np.polyval(num, -1) / np.prod(-1-at(f))) - hinf,
                        1e-7, 0.999999)
        poles = at(cutoff)
    poles = np.asarray(poles, dtype=complex)
    den = _real_poly(poles)
    peak = _peak(num, poles)
    if np.any(np.abs(poles) >= 1) or peak > hinf * (1 + 1e-7):
        raise ValueError("CIFF NTF poles must be stable and meet ntf_hinf")
    a = np.asarray([values.get(f"a{i}", 1.0) for i in range(1, order+1)])
    if not np.isfinite(a).all() or np.any(a <= 0):
        raise ValueError("CIFF integrator gains a_i must be finite and positive")
    # Translate numerator P(z) into powers of t=z-1. Companion corrections
    # vanish exactly for DC zeros, leaving the ordinary CIFF integrator chain.
    t = np.polynomial.Polynomial([1., 1.])
    beta = np.polynomial.Polynomial([0.])
    for coefficient in num:
        beta = beta * t + coefficient
    A = np.eye(order) + np.diag(np.ones(order-1), -1)
    A[0, :] -= beta.coef[:order][::-1]
    scale = np.cumprod(a)
    A = scale[:, None] * A / scale[None, :]
    b = np.zeros(order)
    b[0] = a[0]
    # Match the loop filter on a circle outside its zeros. D=1 introduces a
    # constant term k0 and one cancelled closed-loop pole at z=0.
    z = 1.2 * np.exp(2j*np.pi*(np.arange(4*order+4)+0.3)/(4*order+4))
    basis = np.asarray([np.linalg.solve(zi*np.eye(order)-A, b) for zi in z])
    target = (np.polyval(den, z)/np.polyval(num, z)-1) * z**delay
    if delay:
        basis = np.column_stack((basis, np.ones(len(z))))
    fit = np.linalg.lstsq(np.vstack((basis.real, basis.imag)),
                          np.r_[target.real, target.imag], rcond=None)[0]
    if np.max(np.abs(basis @ fit - target)) > 1e-8:
        raise ValueError("CIFF NTF is not realizable by this loop")
    c, k0 = fit[:order], float(fit[-1]) if delay else 0.0
    supplied = [f"c{i}" in values for i in range(1, order+1)]
    if any(supplied):
        manual = np.asarray([values.get(f"c{i}", math.nan) for i in range(1, order+1)])
        if not all(supplied) or not np.allclose(manual, c, rtol=1e-7, atol=1e-9):
            raise ValueError("CIFF explicit c_i must match the requested NTF and a_i")
        c = manual
    if "k0" in values and not math.isclose(values["k0"], k0, rel_tol=1e-7, abs_tol=1e-9):
        raise ValueError("CIFF explicit k0 does not match feedback_delay and NTF")
    c0 = float(values.get("c0", 1.0))
    if not math.isfinite(c0):
        raise ValueError("CIFF c0 must be finite")
    osr = float(values["osr"])
    if not math.isfinite(osr) or osr < order+1 or osr > 2**20:
        raise ValueError("CIFF osr must lie between order+1 and 2**20")
    window = 2**math.ceil(math.log2(osr))
    # Input impulse weights at the last state, over window-1 updates. Unlike
    # CIFB there is no distributed DAC term in the matched incremental decode.
    state = b.copy()
    weights = []
    for _ in range(window-1):
        weights.append(state[-1])
        state = A @ state
    weights = np.asarray(weights)
    neff = float(weights.sum()**2 / (weights @ weights))
    return {"family": "CIFF", "order": order, "D": delay, "a": a.tolist(),
            "c": c.tolist(), "k": (c*scale).tolist(), "c0": c0, "k0": k0,
            "A": A.tolist(), "b": b.tolist(), "ntf_num": num.tolist(),
            "ntf_den": den.tolist(), "ntf_hinf": peak, "n_eff": neff,
            "zeros": [[complex(x).real, complex(x).imag] for x in zeros],
            "poles": [[x.real, x.imag] for x in poles],
            "method": "Butterworth peak-gain solve; Legendre opt=1; loop-filter matching",
            "verification": "linear realization only; native settling, swing and timing unverified"}


def designed(values):
    """Accept an explicitly designed loop without substituting library gains.

    a_i are the input/cascade gains, b_i the subtracted DAC injections,
    c_i the quantizer feed-forward weights. Signed gains are permitted.
    """
    import numpy as np
    order = _integer(values, "order")
    delay = _integer(values, "feedback_delay", 0)
    family = "CIFF" if values.get("ciff", 0) == 1 else "CIFB"
    if order not in (1, 2, 3) or delay not in (0, 1):
        raise ValueError("designed loops support order 1--3 and feedback_delay 0/1")
    vectors = {}
    for stem in ("a", "b", "c"):
        vector = np.asarray([values.get(f"{stem}{i}", math.nan) for i in range(1, order+1)])
        if not np.isfinite(vector).all():
            raise ValueError(f"designed loop requires complete finite {stem}1..{stem}{order}")
        vectors[stem] = vector
    a, b, c = (vectors[k] for k in ("a", "b", "c"))
    if np.any(a == 0) or not np.any(b) or c[-1] == 0:
        raise ValueError("designed loop needs nonzero a_i, a DAC path and a final-state quantizer path")
    if family == "CIFF" and np.any(b[1:] != 0):
        raise ValueError("CIFF DAC injection is restricted to stage 1")
    c0, k0 = float(values.get("c0", 1. if family == "CIFF" else 0.)), float(values.get("k0", 0.))
    if not math.isfinite(c0) or not math.isfinite(k0):
        raise ValueError("designed loop c0/k0 must be finite")
    if delay == 0 and k0:
        raise ValueError("a nonzero k0 latch path requires feedback_delay=1")
    A = np.eye(order) + np.diag(a[1:], -1)
    num = np.poly(A)
    feedback = np.poly(A - np.outer(b, c)) - num
    den = num + feedback
    if delay or k0:
        den = np.polyadd(np.convolve(num, [1., 0.]), np.polyadd(feedback, k0*num)) if delay else np.polyadd(np.convolve(den, [1., 0.]), k0*num)
        num = np.convolve(num, [1., 0.])
    poles = np.roots(den).astype(complex)
    osr = float(values["osr"])
    if not math.isfinite(osr) or not order+1 <= osr <= 2**20:
        raise ValueError("designed loop osr must lie between order+1 and 2**20")
    state = np.r_[a[0], np.zeros(order-1)]
    weights = []
    for _ in range(2**math.ceil(math.log2(osr))-1):
        weights.append(state[-1])
        state = A @ state
    weights = np.asarray(weights)
    return {"family": family, "order": order, "D": delay, "a": a.tolist(), "b": b.tolist(),
            "c": c.tolist(), "c0": c0, "k0": k0, "k": (c*np.cumprod(a)).tolist(),
            "A": A.tolist(), "ntf_num": num.tolist(), "ntf_den": den.tolist(),
            "poles": [[p.real, p.imag] for p in poles],
            "linear_closed_loop_stable": bool(np.all(np.abs(poles) < 1)),
            "n_eff": float(weights.sum()**2/(weights@weights)),
            "method": "explicit designed a/b/c; no coefficient substitution",
            "verification": "designed coefficients; native stability, settling, swing and timing unverified"}


def specialize(lib, values, expand, cap_length, sampling_cap_expr, load_expr):
    """Return a flat CIFF library entry, reusing CIFB OTA/switch/latch cells.

    A3's existing flat device renderer is the netlist-template producer.
    All new capacitors carry ff_expr and traverse the normal PDK sizing path.
    """
    startup = _integer(values, "startup_reset", 0)
    if startup not in (0, 1):
        raise ValueError("startup_reset must be 0 or 1")
    for key in ("startup_reset_tau_ns", "startup_reset_cap_ff"):
        if key in values and (not math.isfinite(values[key]) or values[key] <= 0):
            raise ValueError(f"{key} must be finite and positive")
    manual = _integer(values, "designed_coefficients", 0)
    if _integer(values, "quantizer_levels", 2) != 2:
        raise ValueError("SC loop template supports quantizer_levels=2 only")
    if values.get("ciff", 0) == 0 and manual == 0:
        return lib
    if values.get("ciff", 0) not in (0, 1) or manual not in (0, 1):
        raise ValueError("ciff must be 0 (CIFB) or 1 (CIFF)")
    if "sc_loop" in lib:
        return lib
    rec = designed(values) if manual else synthesize(values)
    dac_ratio = float(values.get("ciff_dac_ratio", 1.0))
    if not math.isfinite(dac_ratio) or dac_ratio <= 0:
        raise ValueError("ciff_dac_ratio must be finite and positive")
    rec["dac_ratio"] = dac_ratio
    lib = deepcopy(lib)
    lib.pop("coefficient_derivation", None)
    lib.pop("graded_range_choice", None)
    lib.pop("loop_probe", None)  # its distributed-feedback decoder is CIFB
    lib["requires_domain"]["order"] = [1, 2, 3]
    lib["coefficient_sets"] = {str(rec["order"]): [abs(a) for a in rec["a"]]}
    lib["topology"] = ("order-{stages} incremental "+rec["family"]+" switched-capacitor integrators / Miller OTAs, "
                       "passive SC feed-forward summer before a StrongARM comparator; "
                       "explicit per-stage DAC paths, quantiser timing and k0")
    lib["circuit_class_citation"] = (
        "Schreier & Temes, Understanding Delta-Sigma Data Converters: CIFF; "
        "Butterworth NTF pole shaping and Legendre in-band zero optimization; "
        "linear loop-filter matching as in synthesizeNTF/realizeNTF. "
        "State gains are positive diagonal scalings; native verification required.")
    lib["tradeoffs"] = ["Passive summer attenuates all terms equally; comparator loading and offset require sizing.",
                        "DAC enters only stage 1. Optimized zeros add SC state-feedback branches to the first stage.",
                        "D=0 decides during sampling; D=1 holds the summer for the transfer-phase decision and adds k0."]
    lib["boundary_notes"] = ["Internal conversion counter resets all integrators; raw 1-bit output requires a CIFF-aware external decoder."]
    lib["behaviour_record"] = {"verified": False, "claim": "CIFF native conversion not yet verified",
        "diagnosis": "NTF realization and graph are tested; transistor timing/swing remain unmeasured",
        "next": "Run native transient and PVT with a CIFF-aware decoder", "how": "linear state-space matching"}
    # Bias/settling expressions must cover this CIFF's actual worst integrator
    # load rather than the legacy CIFB coefficient formula.
    worst_load = f"((1 + miller_fraction_of_load) / {min(abs(a) for a in rec['a'])!r})"
    def replace(obj):
        if isinstance(obj, str):
            return obj.replace(load_expr, worst_load)
        if isinstance(obj, list):
            return [replace(x) for x in obj]
        if isinstance(obj, dict):
            return {k: replace(v) for k, v in obj.items()}
        return obj
    lib = replace(lib)
    # Expand with the existing coefficient/stage mechanism, then specialize
    # the graph BEFORE geometry flooring, capacitor arrays and A3 rendering.
    lib["stage"][0].pop("feedback_selectors", None)
    lib["stage"][0]["alternates"] = [""]
    devices, nets, exprs, stages = expand(lib, values)
    order = rec["order"]
    outputs = stages["chain"][1:]
    dac_names = {d["name"].format(i=i) for d in lib["stage"][0]["devices"]
                 if any(n in d["nets"] for n in ("ndacs{i}", "ncft{i}"))
                 for i in range(1, order+1) if rec["b"][i-1] == 0}
    devices = [d for d in devices if d["name"] not in dac_names | {"caz", "mn_azq", "mp_azq"}]
    exprs = [e for e in exprs if e["device"] not in dac_names | {"caz"}]
    for i, gain in enumerate(rec["a"], 1):
        for d in devices:
            if gain < 0 and d["name"] in (f"mn_smp{i}", f"mp_smp{i}"):
                d["nets"][2] = "vcm"
            if gain < 0 and d["name"] in (f"mn_cstc{i}", f"mp_cstc{i}"):
                d["nets"][2] = stages["chain"][i-1]
            if d["name"] in (f"mn_dacs{i}", f"mp_dacs{i}"):
                d["nets"][2] = "ndac" if rec["b"][i-1] > 0 else "ndacb"
    for e in exprs:
        if e["device"].startswith("cf") and e["device"][2:].isdigit():
            i = int(e["device"][2:])-1
            ratio = abs(rec["b"][i]/rec["a"][i])*dac_ratio
            e["ff_expr"] = f"{ratio!r} * ({sampling_cap_expr})"
            e["expr"] = cap_length(e["ff_expr"])
    def tg(name, left, right, phase, complement):
        for role, gate, body, width in (("nmos", phase, "vss", 2.), ("pmos", complement, "vdd", 4.)):
            devices.append({"name": ("mn_" if role == "nmos" else "mp_")+name,
                            "role": role, "function": "CIFF SC transmission gate",
                            "nets": [left, gate, right, body], "w": width, "l": .15})
    def cap(name, left, right, ff):
        devices.append({"name": name, "role": "cap", "function": "CIFF SC coefficient capacitor",
                        "nets": [left, right], "w": lib["constants"]["w_cap"], "l": 1.})
        exprs.append({"device": name, "param": "l", "expr": cap_length(ff), "ff_expr": ff,
                      "rationale": "CIFF coefficient times the declared capacitor unit"})
    unit = "ciff_summer_cap_ff" if "ciff_summer_cap_ff" in values else f"({sampling_cap_expr})"
    if "ciff_summer_cap_ff" in values and values["ciff_summer_cap_ff"] <= 0:
        raise ValueError("ciff_summer_cap_ff must be positive")
    # Summer resets in ph2, then its bottom plates step in ph1. Negative
    # weights exchange source/reference phases. Total capacitance is a common
    # positive divisor and leaves the one-bit decision unchanged.
    terms = [("0", "vin", rec["c0"])] + [(str(i), out, c) for i, (out, c) in enumerate(zip(outputs, rec["c"]), 1)]
    if rec["D"] and abs(rec["k0"]) > 1e-12:
        terms.append(("k0", "ndac", rec["k0"]*dac_ratio))  # ndac encodes -v[n-1]
    reset, resetb = "nph2", "nph2b"
    if rec["D"]:
        # Decision first, then reset the summer AND hold capacitor. Otherwise
        # the hold capacitor injects the previous sample into the next sum.
        for name, out, inp in (("sumrb", "nsumrb", "nqstb"), ("sumr", "nsumr", "nsumrb")):
            for role, body, width in (("nmos", "vss", 2.), ("pmos", "vdd", 4.)):
                devices.append({"name": ("mn_" if role == "nmos" else "mp_")+name,
                                "role": role, "function": "CIFF post-decision summer reset delay",
                                "nets": [out, inp, body, body], "w": width, "l": .5})
        reset, resetb = "nsumr", "nsumrb"
    tg("sum_reset", "nsum", "vcm", reset, resetb)
    tg("sum_hold_reset", "nqz", "vcm", reset, resetb)
    for suffix, source, weight in terms:
        if abs(weight) < 1e-12:
            continue
        bottom = "nff"+suffix
        cap("cff"+suffix, "nsum", bottom, f"{abs(weight)!r} * ({unit})")
        phase = ("nph1", "nph1b") if weight > 0 else ("nph2", "nph2b")
        reference_phase = ("nph2", "nph2b") if weight > 0 else ("nph1", "nph1b")
        tg("ff"+suffix, bottom, source, *phase)
        tg("ffr"+suffix, bottom, "vcm", *reference_phase)
    # Track during sampling, hold through the transfer-phase decision (D=1).
    tg("sum_hold", "nsum", "nqz", "nph1", "nph1b")
    cap("csum_hold", "nqz", "vcm", unit)
    tg("sum_conversion_reset", "nqz", "vcm", "nall", "nrstb")
    # Existing delayed comparator strobe chain is reused on the chosen phase.
    for d in devices:
        if d["name"] in ("mp_qdly1", "mn_qdly1"):
            d["nets"][1] = "nph1b" if rec["D"] == 0 else "nph2b"
    # General optimized numerator: signed charge injection into the first
    # integrator. No DAC term is introduced in later stages.
    for j, source in enumerate(outputs):
        ordinary = 1. if j == 0 else 0.
        gain = rec["A"][0][j] - ordinary
        if abs(gain) < 1e-12:
            continue
        suffix = f"zero{j+1}"
        bottom, top = "nb_"+suffix, "nt_"+suffix
        ff = f"{abs(gain)/rec['a'][0]!r} * ({sampling_cap_expr})"
        cap("c"+suffix, bottom, top, ff)
        tg(suffix+"bs", bottom, source if gain > 0 else "vcm", "nph1", "nph1b")
        tg(suffix+"br", bottom, "vcm", "nph2", "nph2b")
        tg(suffix+"ts", top, "vcm" if gain > 0 else source, "nph1", "nph1b")
        tg(suffix+"tt", top, "vsum1", "nph2", "nph2b")
    # Prune selector legs and net declarations that no remaining branch uses.
    for selector in ("ndac", "ndacb"):
        if not any(selector in d["nets"][1:] for d in devices):
            devices = [d for d in devices if selector not in d["nets"]]
    nets = sorted({n for d in devices for n in d["nets"]} - set(lib["ports"]))
    # The phase generator was expanded above; do not emit it a second time.
    lib.pop("clock_phase_generator", None)
    lib["startup_counter_template"] = lib["stage"][1]
    lib.pop("stage", None)
    lib["devices"], lib["internal_nets"], lib["device_param_exprs"] = devices, nets, exprs
    lib["sc_loop"] = rec
    lib["sc_loop_stages"] = stages
    lib["constants"]["n_eff"] = rec["n_eff"]
    for group in stages.get("groups", [stages]):
        if "window_clocks" in group:
            lib["constants"]["window_clocks"] = float(group["window_clocks"])
    lib["constants"]["feedback_delay_clocks"] = float(rec["D"])
    # Flat entry retains its stage count in the descriptive topology.
    lib["topology"] = lib["topology"].format(stages=order)
    return lib


def declaration(loop, stages):
    """Versioned consumer contract. a/b/c never use the legacy decoder names."""
    outputs = stages["chain"][1:]
    paths = []
    def path(kind, source, destination, gain, capacitor):
        return {"kind": kind, "source": source, "destination": destination,
                "gain": gain, "capacitor": capacitor}
    for i, (out, a, b, c) in enumerate(zip(outputs, loop["a"], loop["b"], loop["c"]), 1):
        paths.append(path("input" if i == 1 else "integrator", stages["chain"][i-1], out, a, f"cs{i}"))
        if b:
            p = path("dac", "bit_out", out, -b, f"cf{i}")
            p.update(destination_stage=i, delay_clocks=loop["D"])
            paths.append(p)
        if c:
            paths.append(path("feedforward", out, "quantizer", c, f"cff{i}"))
    if loop["c0"]:
        paths.append(path("input_feedforward", stages["chain"][0], "quantizer", loop["c0"], "cff0"))
    k0 = path("k0", "bit_out", "quantizer", -loop["k0"], "cffk0") if loop["k0"] else None
    if k0:
        k0["delay_clocks"] = 1
        paths.append(k0)
    for j, gain in enumerate(loop["A"][0]):
        correction = gain - (1. if j == 0 else 0.)
        if abs(correction) > 1e-12:
            paths.append(path("zero_feedback", outputs[j], outputs[0], correction, f"czero{j+1}"))
    result = {"schema": 1, "family": loop["family"], "order": loop["order"],
              "a": loop["a"], "b": loop["b"], "c": loop["c"], "c0": loop["c0"],
              "D": loop["D"], "k0": loop["k0"], "k0_path": k0,
              "dac_stages": [i for i, b in enumerate(loop["b"], 1) if b],
              "quantizer_levels": 2, "state_nets": outputs, "paths": paths,
              "A": loop["A"], "input_vector": [loop["a"][0]]+[0.]*(loop["order"]-1),
              "feedback_vector": [-b for b in loop["b"]],
              "quantizer_input_net": "nqz", "quantizer_strobe_device": "mn_qtail",
              "normalization": {"state_and_input": "relative to vcm, divided by DAC full scale",
                                "dac_output_levels": [-1, 1],
                                "full_scale_over_reference": loop["dac_ratio"]},
              "coefficient_source": loop["method"], "verification": loop["verification"]}
    return result


def legacy_declaration(stages, devices, exprs, env, delay, evaluate):
    """Describe the final CIFB capacitor ratios, after ordinary swing sizing."""
    if not stages or stages.get("role") != "cascade":
        return None
    order = stages["stages"]
    by_name = {d["name"]: d for d in devices}
    by_expr = {e["device"]: e for e in exprs if e.get("param") == "l"}
    def capacitance(name):
        d = by_name[name]
        e = by_expr.get(name)
        length = evaluate(e["expr"], env) if e else d["l"]
        return env["cap_area_ff_per_um2"]*d["w"]*length + 2*env.get("cap_perim_ff_per_um", 0)*(d["w"]+length)
    a, b = [], []
    for i in range(1, order+1):
        a.append(capacitance(f"cs{i}")/capacitance(f"ci{i}"))
        b.append(capacitance(f"cf{i}")/capacitance(f"ci{i}"))
    A = [[float(i == j)+(a[i] if i == j+1 else 0.) for j in range(order)] for i in range(order)]
    loop = {"family": "CIFB", "order": order, "D": delay, "a": a, "b": b,
            "c": [0.]*(order-1)+[1.], "c0": 0., "k0": 0., "A": A,
            "dac_ratio": 1., "method": "final emitted capacitor ratios after legacy sizing",
            "verification": "capacitor ratios; consult loop_swing for measured realization"}
    result = declaration(loop, stages)
    # Legacy CIFB quantizes the last state through its autozero capacitor;
    # it does not have the new passive summer.
    for p in result["paths"]:
        if p["kind"] == "feedforward":
            p["capacitor"] = "caz"
    return result


def add_startup_reset(lib, values, stages, devices, nets, exprs, cap_length, sampling_cap_expr):
    """Optional RC + six-transistor Schmitt POR, counter clear and reset OR.

    Uses only the existing resistor/capacitor/CMOS roles. The low-clock-phase
    release latch prevents an RC threshold crossing from creating a spurious
    rising counter edge. Both counter storage nodes are preset before release.
    """
    option = lib.get("startup_reset_template")
    if not option or values.get(option["enable_spec"], 0) == 0:
        return None
    tau = float(values.get("startup_reset_tau_ns", 2000/values["fclk"]))
    ff = "startup_reset_cap_ff" if "startup_reset_cap_ff" in values else f"40 * ({sampling_cap_expr})"
    counter = lib.get("startup_counter_template") or next(g for g in lib["stage"] if g.get("role") == "conversion_window_counter")
    counter_rec = next(g for g in stages["groups"] if g.get("role") == "conversion_window_counter")
    counter_names = {d["name"].format(i=i, i1=i+1) for d in counter["devices"] for i in range(1, counter_rec["stages"]+1)}
    for d in devices:
        if d["name"] in counter_names:
            d["nets"] = ["npor_clk" if n == counter["first_in"] else n for n in d["nets"]]
        if d["name"] in option["reset_driver_devices"]:
            d["nets"][0] = "nwindow_reset"
    def mos(name, role, drain, gate, source, width=2.):
        body = "vss" if role == "nmos" else "vdd"
        devices.append({"name": name, "role": role, "function": "incremental startup reset",
                        "nets": [drain, gate, source, body], "w": width, "l": .5})
    def inv(name, out, inp, width=2.):
        mos("mn_"+name, "nmos", out, inp, "vss", width)
        mos("mp_"+name, "pmos", out, inp, "vdd", 2*width)
    def passive(name, role, terminals, expr, ff_expr=None):
        devices.append({"name": name, "role": role, "function": "startup RC delay",
                        "nets": terminals, "w": lib["constants"]["w_cap" if role == "cap" else "w_res"], "l": 1.})
        e = {"device": name, "param": "l", "expr": expr}
        if ff_expr:
            e["ff_expr"] = ff_expr
        exprs.append(e)
    passive("cpor", "cap", ["npor_rc", "vss"], cap_length(ff), ff)
    passive("rpor", "res", ["vdd", "npor_rc", "vss"],
            f"{tau!r} * 1e6 / ({ff}) * w_res / rsheet_ohm_per_sq")
    # Schmitt inverter: series pull-up/down stacks, plus state-dependent
    # source feedback. Hysteresis avoids chatter during a slow supply ramp.
    mos("mp_por1", "pmos", "npor_p", "npor_rc", "vdd", 4.)
    mos("mp_por2", "pmos", "npor", "npor_rc", "npor_p", 4.)
    mos("mn_por1", "nmos", "npor", "npor_rc", "npor_n")
    mos("mn_por2", "nmos", "npor_n", "npor_rc", "vss")
    mos("mn_porf", "nmos", "npor_n", "npor", "vdd")
    mos("mp_porf", "pmos", "npor_p", "npor", "vss", 4.)
    inv("porb", "nporb", "npor")
    # Release is sampled only while the source clock is low, then held.
    mos("mn_por_release", "nmos", "npor_run", "nclkb", "nporb")
    mos("mp_por_release", "pmos", "npor_run", "clk", "nporb", 4.)
    inv("por_runb", "npor_runb", "npor_run")
    inv("por_keeper", "npor_run", "npor_runb", .5)
    mos("mn_por_force", "nmos", "npor_run", "npor", "vss", 4.)
    # NAND + inverter gates the counter clock until the release latch opens.
    mos("mp_por_ck1", "pmos", "npor_ckb", "clk", "vdd", 4.)
    mos("mp_por_ck2", "pmos", "npor_ckb", "npor_run", "vdd", 4.)
    mos("mn_por_ck1", "nmos", "npor_ckb", "clk", "npor_cks")
    mos("mn_por_ck2", "nmos", "npor_cks", "npor_run", "vss")
    inv("por_clk", "npor_clk", "npor_ckb")
    for i in range(1, counter_rec["stages"]+1):
        for j, node in enumerate(option["counter_storage_high"]):
            mos(f"mp_por_clear{i}_{j}", "pmos", node.format(i=i), "npor_run", "vdd", 8.)
    # OR window reset with startup reset; the existing reset-complement
    # inverter and every integrator reset switch now see the combined reset.
    reset = option["reset_net"]
    mos("mp_por_or1", "pmos", "npor_ors", "nwindow_reset", "vdd", 4.)
    mos("mp_por_or2", "pmos", "npor_orb", "npor_runb", "npor_ors", 4.)
    mos("mn_por_or1", "nmos", "npor_orb", "nwindow_reset", "vss")
    mos("mn_por_or2", "nmos", "npor_orb", "npor_runb", "vss")
    inv("por_or", reset, "npor_orb")
    nets[:] = sorted({n for d in devices for n in d["nets"]} - set(lib["ports"]))
    return {"enabled": True, "kind": "RC_Schmitt", "tau_ns": tau,
            "rc_net": "npor_rc", "por_net": "npor", "reset_net": reset,
            "counter_clock_net": "npor_clk", "release_net": "npor_run",
            "counter_state_on_reset": [0]*counter_rec["stages"],
            "clears": ["window_counter", "all_integrators"],
            "verification": "structural only; native power-ramp verification required"}
