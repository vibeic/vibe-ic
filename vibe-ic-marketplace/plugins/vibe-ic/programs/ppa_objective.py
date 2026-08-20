#!/usr/bin/env python3
"""The PPA objective a configuration SEARCH optimises — ORFS `PPAImprov`,
ported, with the weights turned from a hard-coded constant into a DECLARED
input. vibe-ic ppa.html section 03 (PHASE 3, the search layer).

WHY THIS EXISTS AT ALL
======================
A configuration search is only as honest as the number it maximises. Give a
tuner a score it can improve by producing violations, or by crashing out of the
expensive stage, and it will — that is not a hypothetical, it is what a search
DOES. So the objective is not a detail of the search; it is the part that has to
be right before a single run is worth spending.

OpenROAD-flow-scripts already solved the shape of it. Fetched 2026-08-21 from
`tools/AutoTuner/src/autotuner/distributed.py` (`PPAImprov`, lines 212-256) and
`tools/AutoTuner/src/autotuner/utils.py` (`read_metrics`, lines 399-455):

    coeff_perform, coeff_power, coeff_area = 10000, 100, 100
    eff_clk_period     = clk_period     - min(0, worst_slack)
    eff_clk_period_ref = ref.clk_period - min(0, ref.worst_slack)
    percent(a, b)      = (a - b) / a * 100
    performance = percent(eff_clk_period_ref, eff_clk_period)
    power       = percent(ref.total_power,      total_power)
    area        = percent(100 - ref.final_util, 100 - final_util)
    ppa_upper_bound = (cP + cW + cA) * 100
    ppa   = ppa_upper_bound - (performance*cP + power*cW + area*cA)  # LOWER better
    gamma = ppa / 10
    score = ppa * (step/100)**-1 + gamma*num_drc

THE TWO ANTI-CHEATING TERMS ARE KEPT VERBATIM
=============================================
They are the reason the score cannot be gamed, and neither is re-derived here:

  * ``gamma * num_drc`` — DRC count is a PENALTY. A configuration that buys its
    area or its timing with violations does not win. `gamma = ppa/10` scales the
    penalty to the score, so it stays meaningful whatever the weights are.

  * ``(step/100) ** -1`` — a run is scored on HOW FAR IT GOT. Crashing out of an
    expensive stage produces a partial, flattering metric set; multiplying by
    ``100/step`` makes stopping early cost more than it saves. Without it the
    cheapest way to a good `ppa` is to not finish.

  ONE DELIBERATE REBINDING, STATED SO NOBODY MISTAKES IT FOR ORFS'S OWN.
  In ORFS, `self.step_` is the RAY TUNING-ITERATION counter (`distributed.py:137`
  `self.step_ = 0`; `:164` `self.step_ += 1` once per `step()`), so in a
  single-shot trial it is always 1 and the term is a constant x100 no-op; it only
  bites under PopulationBasedTraining. ORFS punishes a crashed run separately,
  via `ERROR_METRIC = 9e99` on any `"ERR"`/`"N/A"` metric.
  Here every configuration is run ONCE, so a tuning-iteration counter would be
  dead weight — and unlike an ORFS trial, OUR runs really do stop half-way
  (placed but not routed, routed but not signed off). So `step` is bound to
  FLOW PROGRESS: how many of the declared stages the run completed. The algebra
  is untouched; only the quantity fed to it is ours. Every record this module
  produces carries `step_semantics` saying exactly that, because an inherited
  formula whose variable means something else is the kind of difference that
  disappears the moment it is not written down.

THE ONE CHANGE THAT IS OURS: THE WEIGHTS ARE DECLARED
=====================================================
ORFS hard-codes 10000/100/100. A 100:1 preference for speed over power is a
value judgement about a MARKET — it belongs to the design, not to the tool. So:

    ppa_weights:
      performance: <from L19>
      power:       <from L19>
      area:        <from L19>

and there is NO default. A design that declares nothing INHERITS ORFS's ratio,
and the inheritance is recorded in words:

    weights.source     = "inherited"
    weights.provenance = "inherited, not chosen"

MEASURED on this host 2026-08-21 over the 533 readable `L19_CONSTRAINTS_PDK.json`
documents present: 0 declare `ppa_weights`, 3 declare `power_budget_uw`, 28
declare `die_area_budget_um`. The inheritance path is not an edge case, it is
the normal case — which is exactly why it must not print as a choice. An
inherited weight shown as if the design picked it is a lie about who made the
value judgement, and it is the only lie this module has room for.

UNMEASURED IS NOT CLEAN
=======================
`read_metrics` never returns a number it did not find. A metric the run did not
produce comes back as `NOT_MEASURED` WITH A REASON, and the three reasons are
kept apart on purpose:

    ABSENT      the artefact that would carry it does not exist
    UNREADABLE  the artefact exists and could not be parsed  <- NOT the same
    KEY_ABSENT  the artefact parsed and does not carry the key

"I could not read it" and "I read it and it was empty" must never produce the
same verdict. `score()` REFUSES (rc=2) on any NOT_MEASURED input rather than
substituting a zero, a default or a neighbouring number.

AND IT NEVER PARSES A LOG. Every metric is read from an artefact that the step
which COMPUTED the number wrote — `reports/metrics/*.json` (the #1080 declared
channel) first, then the named per-step report JSONs. A log regex is a proxy for
a measurement, not a measurement. Where the declared channel does not yet carry
a metric, this module says which one and stops; it does not go looking in a log.

chip-AGNOSTIC / PDK-AGNOSTIC / vendor-AGNOSTIC: no design, PDK, process, node,
vendor or part literal appears in the logic or can affect it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

RC_OK = 0
RC_REFUSED = 1
RC_NOT_MEASURED = 2

#: The sentinel a metric carries when the run did not produce it. It is a STRING
#: on purpose: any arithmetic that reaches it raises instead of silently
#: coercing, which is the whole point of not using 0 / None / NaN.
NOT_MEASURED = "NOT_MEASURED"

#: Why a metric is NOT_MEASURED. Kept apart because collapsing them is header
#: rule 9 — "I could not read it" and "I read it and it was empty" must not
#: produce the same artefact.
REASON_ABSENT = "ABSENT"
REASON_UNREADABLE = "UNREADABLE"
REASON_KEY_ABSENT = "KEY_ABSENT"

#: The three axes the objective weighs. Order is the declaration order and is
#: also the order the report prints them in.
AXES: Tuple[str, str, str] = ("performance", "power", "area")

#: ORFS `PPAImprov` line 222, verbatim. NOT a default — a design that declares
#: nothing INHERITS this, and the inheritance is stated in the record.
ORFS_WEIGHTS: Dict[str, float] = {
    "performance": 10000.0,
    "power": 100.0,
    "area": 100.0,
}

#: The exact words that must appear in a record whose weights were not chosen by
#: the design. A reader has to be able to see whose call it was.
INHERITED_PHRASE = "inherited, not chosen"

ORFS_SOURCE = ("OpenROAD-flow-scripts tools/AutoTuner/src/autotuner/"
               "distributed.py PPAImprov.get_ppa (coeff_perform, coeff_power, "
               "coeff_area = 10000, 100, 100)")

#: What `step` means HERE, printed into every record. See the module docstring.
STEP_SEMANTICS = (
    "step = number of declared PnR stages this run COMPLETED (flow progress). "
    "ORFS binds the same symbol to its Ray tuning-iteration counter; the "
    "algebra (step/100)**-1 is unchanged, the quantity is ours."
)

#: The metrics the objective consumes, and where a DECLARED value for each is
#: read from. Each entry is an ordered list of (relative artefact path, JSON key
#: path) candidates: the first candidate that parses AND carries its key wins.
#: `reports/metrics/*.json` — the #1080 declared channel, emitted by the step
#: that computed the number — is searched first for every metric, by key prefix
#: match, before any of these.
#:
#: NOTHING in this table is a log. If a metric is in no declared artefact it
#: comes back NOT_MEASURED and the caller is told which one; it is never
#: recovered by regexing a tool transcript.
METRIC_SOURCES: Dict[str, List[Tuple[str, Tuple[str, ...]]]] = {
    # The SDC clock period the run was constrained to, as the step that read
    # the SDC declared it.
    "clk_period": [
        ("reports/phase3/achievable_fmax.json", ("spec_period_ns",)),
    ],
    # Worst SETUP slack. `achievable_fmax` is the step that already reduced the
    # sign-off STA to one governing number and wrote it structured; the
    # multi-corner OCV stance is the fallback for a run that did not reach it.
    "worst_slack": [
        ("reports/phase3/achievable_fmax.json", ("worst_setup_slack_ns",)),
        ("reports/phase3/mcorner_ocv_stance.json", ("setup_worst_slack_ns",)),
    ],
    # Total power in WATTS, declared by the step that drove `report_power`.
    "total_power": [
        ("reports/phase3/power.json", ("total_power_w",)),
    ],
    # Utilisation as a PERCENT (0..100), the quantity ORFS's `area` term uses.
    "final_util": [
        ("reports/density.json", ("core_utilization_pct",)),
    ],
    # Sign-off DRC count. `real_violation_total` is the audited figure — the one
    # that survives the tool-corroboration cross-check — not the raw grep count.
    "num_drc": [
        ("reports/phase3/drc_signoff.json", ("summary", "real_violation_total")),
        ("reports/phase3/drc_router.json", ("summary", "real_violation_total")),
    ],
}

#: `die_area` is REPORTED, never scored (ORFS returns it alongside the score and
#: does not weigh it). It is declared as `"<W>x<H>"` in microns by the PnR step
#: that sized the die, so it needs a shape-specific reader rather than a key
#: lookup; `None` when the run did not get that far.
DIE_AREA_SOURCE: Tuple[str, Tuple[str, ...]] = (
    "phase3/stage3/pnr/pnr_args.json", ("effective_die_um",))

#: The #1080 declared-channel key SUFFIXES for each metric. `step_metrics` keys
#: are `<step>__<domain>__<name>`, so the objective asks for the measurement by
#: name and does not care which step emitted it — that is the schema's own
#: promise ("emitted by whoever computed the number").
METRIC_DECLARED_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "clk_period": ("constraints__clock_period", "timing__clock_period"),
    "worst_slack": ("timing__setup__ws",),
    "total_power": ("power__total",),
    "final_util": ("design__instance__utilization",),
    "die_area": ("design__die__area",),
    "num_drc": ("route__drc_errors", "drc__violations"),
}

#: Every metric the objective needs. Kept separate from the source tables so a
#: metric with NO declared source at all is still reported as NOT_MEASURED/ABSENT
#: rather than vanishing from the record.
REQUIRED_METRICS: Tuple[str, ...] = (
    "clk_period", "worst_slack", "total_power", "final_util", "num_drc",
)


class Refusal(Exception):
    """The objective cannot be computed from what it was given."""

    def __init__(self, code: str, message: str, rc: int = RC_REFUSED):
        super().__init__(message)
        self.code = code
        self.message = message
        self.rc = rc


# ---------------------------------------------------------------------------
# Weights — the one thing that is ours rather than ORFS's
# ---------------------------------------------------------------------------
def resolve_weights(l19: Optional[Dict[str, Any]],
                    l19_path: Optional[str] = None) -> Dict[str, Any]:
    """Resolve `ppa_weights` from an L19 document, or record the inheritance.

    Returns::

        {"weights":    {"performance": float, "power": float, "area": float},
         "source":     "declared" | "inherited",
         "provenance": str,        # carries INHERITED_PHRASE when inherited
         "declared_by": str|None}  # the L19 path, when the design declared

    A PARTIAL declaration is REFUSED, not completed from ORFS. Half a value
    judgement silently finished by the tool is the same lie as a whole one: the
    record would show three weights and only some of them would be the design's.
    """
    fields = ((l19 or {}).get("fields") or {}) if isinstance(l19, dict) else {}
    declared = fields.get("ppa_weights")
    if declared is None and isinstance(l19, dict):
        declared = l19.get("ppa_weights")

    if declared is None:
        return {
            "weights": dict(ORFS_WEIGHTS),
            "source": "inherited",
            "provenance": (
                f"{INHERITED_PHRASE} — this design declares no `ppa_weights`, "
                f"so the ratio is inherited verbatim from {ORFS_SOURCE}. The "
                "relative value of speed against power and area is a judgement "
                "about a market; nobody on this run made it."),
            "declared_by": None,
        }

    if not isinstance(declared, dict):
        raise Refusal(
            "WEIGHTS_MALFORMED",
            f"`ppa_weights` is {type(declared).__name__}, not an object with "
            f"the three axes {list(AXES)}")

    missing = [a for a in AXES if a not in declared]
    if missing:
        raise Refusal(
            "WEIGHTS_PARTIAL",
            f"`ppa_weights` declares {sorted(set(declared) & set(AXES))} and "
            f"not {missing}. A partial preference is REFUSED rather than "
            "completed from the inherited ratio: a record showing three "
            "weights of which only some are the design's cannot be read.")

    weights: Dict[str, float] = {}
    for axis in AXES:
        raw = declared[axis]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise Refusal(
                "WEIGHTS_MALFORMED",
                f"`ppa_weights.{axis}` is {raw!r}, not a number")
        if raw < 0:
            raise Refusal(
                "WEIGHTS_NEGATIVE",
                f"`ppa_weights.{axis}` = {raw!r}. A negative weight inverts "
                "the axis — it asks the search to make that axis WORSE, which "
                "no declared preference means and every reader would misread.")
        weights[axis] = float(raw)

    if sum(weights.values()) <= 0:
        raise Refusal(
            "WEIGHTS_ALL_ZERO",
            "`ppa_weights` are all zero, so every configuration scores "
            "identically and the search has nothing to optimise.")

    return {
        "weights": weights,
        "source": "declared",
        "provenance": (
            f"declared by the design at {l19_path or 'L19'} — "
            f"performance:power:area = "
            + ":".join(f"{weights[a]:g}" for a in AXES)),
        "declared_by": l19_path,
    }


def load_l19(project: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str],
                                     Optional[str]]:
    """``(document, relative path, unreadable-reason)`` for the project's L19.

    An L19 that is ABSENT and an L19 that is UNREADABLE are different answers
    (header rule 9): absent means the design declared nothing and inherits;
    unreadable means we could not tell, and the caller must refuse rather than
    inherit on its behalf.
    """
    rel = "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    path = project / rel
    if not path.exists():
        return None, None, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), rel, None
    except (OSError, json.JSONDecodeError) as exc:
        return None, rel, f"{rel}: {exc}"


# ---------------------------------------------------------------------------
# Metrics — declared only, and never a log
# ---------------------------------------------------------------------------
def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _dig(doc: Any, keys: Tuple[str, ...]) -> Any:
    cur = doc
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _declared_channel(project: Path) -> Tuple[Dict[str, Any], List[str]]:
    """Merge `reports/metrics/*.json` — the #1080 declared channel. Returns the
    merged mapping and the list of files that could NOT be parsed, which the
    caller reports rather than swallows."""
    merged: Dict[str, Any] = {}
    unreadable: List[str] = []
    root = project / "reports" / "metrics"
    if not root.is_dir():
        return merged, unreadable
    for f in sorted(root.glob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            unreadable.append(str(f.relative_to(project)))
            continue
        if isinstance(doc, dict):
            merged.update(doc)
    return merged, unreadable


def read_metrics(project: Path) -> Dict[str, Any]:
    """Read every objective metric from DECLARED artefacts only.

    Returns::

        {"metrics":    {name: float | NOT_MEASURED},
         "sources":    {name: {"path":…, "key":…, "sha256":…}},
         "unmeasured": {name: {"reason": ABSENT|UNREADABLE|KEY_ABSENT,
                               "detail": …}},
         "unreadable_declared_channel": [path, …]}

    Every returned number carries the artefact it came from AND that artefact's
    sha256 — one run tree per report, and a figure quoted across a boundary
    carries something that pins WHICH tree produced it.
    """
    declared, chan_unreadable = _declared_channel(project)
    metrics: Dict[str, Any] = {}
    sources: Dict[str, Dict[str, Any]] = {}
    unmeasured: Dict[str, Dict[str, Any]] = {}

    for name in REQUIRED_METRICS:
        value: Any = None
        src: Optional[Dict[str, Any]] = None
        tried: List[str] = []

        # 1. the #1080 declared channel, by key suffix.
        for suffix in METRIC_DECLARED_SUFFIXES.get(name, ()):
            hits = [k for k in declared if k.endswith(suffix)]
            tried.append(f"reports/metrics/*.json ~ *{suffix}")
            if hits:
                key = sorted(hits)[0]
                value = declared[key]
                src = {"path": "reports/metrics/*.json", "key": key,
                       "sha256": None, "channel": "step_metrics(#1080)"}
                break

        # 2. the named per-step report the producing step wrote.
        if value is None:
            for rel, keys in METRIC_SOURCES.get(name, []):
                tried.append(f"{rel}:{'.'.join(keys)}")
                path = project / rel
                if not path.exists():
                    continue
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    unmeasured[name] = {"reason": REASON_UNREADABLE,
                                        "detail": f"{rel}: {exc}"}
                    value = None
                    break
                got = _dig(doc, keys)
                if got is not None:
                    value = got
                    src = {"path": rel, "key": ".".join(keys),
                           "sha256": _sha256(path), "channel": "step report"}
                    break

        if name in unmeasured:
            metrics[name] = NOT_MEASURED
            continue

        if value is None:
            metrics[name] = NOT_MEASURED
            unmeasured[name] = {
                "reason": REASON_ABSENT if not tried else REASON_KEY_ABSENT,
                "detail": ("no declared artefact carries this metric; looked "
                           "in " + ", ".join(tried) if tried else
                           "this metric has no declared source configured"),
            }
            continue

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            metrics[name] = NOT_MEASURED
            unmeasured[name] = {
                "reason": REASON_UNREADABLE,
                "detail": f"declared value is {value!r}, not a number"}
            continue

        metrics[name] = float(value)
        if src is not None:
            sources[name] = src

    # `die_area` — reported, never scored, so its absence does not block.
    rel, keys = DIE_AREA_SOURCE
    dpath = project / rel
    metrics["die_area"] = NOT_MEASURED
    if not dpath.exists():
        unmeasured_die = {"reason": REASON_ABSENT, "detail": f"{rel} absent"}
    else:
        try:
            ddoc = json.loads(dpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            unmeasured_die = {"reason": REASON_UNREADABLE,
                              "detail": f"{rel}: {exc}"}
        else:
            raw = _dig(ddoc, keys)
            area = _die_area_um2(raw)
            if area is None:
                unmeasured_die = {
                    "reason": (REASON_KEY_ABSENT if raw is None
                               else REASON_UNREADABLE),
                    "detail": (f"{rel}:{'.'.join(keys)} = {raw!r}; expected "
                               "'<W>x<H>' in microns")}
            else:
                metrics["die_area"] = area
                sources["die_area"] = {
                    "path": rel, "key": ".".join(keys) + " -> W*H",
                    "sha256": _sha256(dpath), "channel": "step report",
                    "declared_as": raw}
                unmeasured_die = None
    if unmeasured_die is not None:
        unmeasured_die["non_blocking"] = True
        unmeasured_die["why_non_blocking"] = (
            "die_area is REPORTED and never weighed — ORFS returns it beside "
            "the score and does not score it. It is still NOT_MEASURED rather "
            "than 0, so a reader can see it was not read.")
        unmeasured["die_area"] = unmeasured_die

    return {"metrics": metrics, "sources": sources, "unmeasured": unmeasured,
            "unreadable_declared_channel": chan_unreadable}


def _die_area_um2(raw: Any) -> Optional[float]:
    """``W*H`` in um^2 from a declared ``"<W>x<H>"`` micron string, or None.
    Accepts a plain number too (an already-computed area). Never guesses."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    if not isinstance(raw, str):
        return None
    parts = raw.lower().split("x")
    if len(parts) != 2:
        return None
    try:
        w, h = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    return w * h if w > 0 and h > 0 else None


# ---------------------------------------------------------------------------
# The objective — ORFS PPAImprov, algebra untouched
# ---------------------------------------------------------------------------
def _percent(x_1: float, x_2: float) -> float:
    """ORFS `PPAImprov.get_ppa.percent`, verbatim (distributed.py:232-233)."""
    return (x_1 - x_2) / x_1 * 100


def get_ppa(metrics: Dict[str, Any], reference: Dict[str, Any],
            weights: Dict[str, float]) -> Dict[str, Any]:
    """ORFS `PPAImprov.get_ppa` (distributed.py:217-244) with the three
    coefficients supplied instead of hard-coded. LOWER is better."""
    for label, src in (("run", metrics), ("reference", reference)):
        bad = [k for k in ("clk_period", "worst_slack", "total_power",
                           "final_util")
               if src.get(k) is NOT_MEASURED or src.get(k) == NOT_MEASURED
               or not isinstance(src.get(k), (int, float))
               or isinstance(src.get(k), bool)]
        if bad:
            raise Refusal(
                "METRIC_NOT_MEASURED",
                f"{label} does not carry a measured value for {bad}. An "
                "unmeasured metric BLOCKS: substituting a zero or a default "
                "would make 'we did not look' and 'we looked and it was fine' "
                "produce the same score.", RC_NOT_MEASURED)

    eff_clk_period = float(metrics["clk_period"])
    if metrics["worst_slack"] < 0:
        eff_clk_period -= float(metrics["worst_slack"])
    eff_clk_period_ref = float(reference["clk_period"])
    if reference["worst_slack"] < 0:
        eff_clk_period_ref -= float(reference["worst_slack"])

    if eff_clk_period_ref == 0:
        raise Refusal(
            "REFERENCE_DEGENERATE",
            "the reference effective clock period is 0, so the performance "
            "term divides by zero — the reference run cannot anchor a search.")
    if reference["total_power"] == 0:
        raise Refusal(
            "REFERENCE_DEGENERATE",
            "the reference total power is 0, so the power term divides by "
            "zero. A zero-power reference is a measurement that did not "
            "happen, not a design that consumes nothing.")
    if float(reference["final_util"]) == 100.0:
        raise Refusal(
            "REFERENCE_DEGENERATE",
            "the reference utilisation is 100%, so the area term divides by "
            "zero (ORFS's area term is percent(100 - ref_util, 100 - util)).")

    performance = _percent(eff_clk_period_ref, eff_clk_period)
    power = _percent(float(reference["total_power"]),
                     float(metrics["total_power"]))
    area = _percent(100 - float(reference["final_util"]),
                    100 - float(metrics["final_util"]))

    c_p, c_w, c_a = weights["performance"], weights["power"], weights["area"]
    ppa_upper_bound = (c_p + c_w + c_a) * 100
    ppa = performance * c_p
    ppa += power * c_w
    ppa += area * c_a
    return {
        "ppa": ppa_upper_bound - ppa,
        "terms": {"performance": performance, "power": power, "area": area},
        "weighted": {"performance": performance * c_p, "power": power * c_w,
                     "area": area * c_a},
        "ppa_upper_bound": ppa_upper_bound,
        "effective_clk_period": eff_clk_period,
        "effective_clk_period_reference": eff_clk_period_ref,
    }


def evaluate(metrics: Dict[str, Any], reference: Dict[str, Any],
             weights: Dict[str, float], step: int,
             stages_total: Optional[int] = None) -> Dict[str, Any]:
    """ORFS `PPAImprov.evaluate` (distributed.py:246-256) with `step` bound to
    flow progress. LOWER score is better.

        gamma = ppa / 10
        score = ppa * (step/100)**-1 + gamma*num_drc
    """
    if not isinstance(step, int) or isinstance(step, bool) or step <= 0:
        raise Refusal(
            "STEP_ZERO",
            f"step={step!r}. A run that completed no declared stage produced "
            "no measurement to score. It is REFUSED rather than given a large "
            "number, because a large number is still a rank and this run has "
            "no place in the ranking.", RC_NOT_MEASURED)

    num_drc = metrics.get("num_drc")
    if num_drc is NOT_MEASURED or num_drc == NOT_MEASURED \
            or not isinstance(num_drc, (int, float)) \
            or isinstance(num_drc, bool):
        raise Refusal(
            "METRIC_NOT_MEASURED",
            "num_drc was not measured. It is the anti-cheating term: without "
            "it a configuration that buys area or timing with violations is "
            "indistinguishable from one that did not.", RC_NOT_MEASURED)

    parts = get_ppa(metrics, reference, weights)
    ppa = parts["ppa"]
    gamma = ppa / 10
    progress_multiplier = (step / 100) ** (-1)
    score = ppa * progress_multiplier + (gamma * float(num_drc))
    return {
        "score": score,
        "ppa": ppa,
        "gamma": gamma,
        "num_drc": float(num_drc),
        "drc_penalty": gamma * float(num_drc),
        "step": step,
        "stages_total": stages_total,
        "progress_multiplier": progress_multiplier,
        "step_semantics": STEP_SEMANTICS,
        "lower_is_better": True,
        **{k: v for k, v in parts.items() if k != "ppa"},
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="ORFS PPAImprov objective with DECLARED weights.")
    p.add_argument("project", type=Path, nargs="?",
                   help="a run tree, to read its declared metrics and L19")
    p.add_argument("--weights-only", action="store_true",
                   help="resolve and print `ppa_weights` and stop")
    p.add_argument("--json", type=Path, default=None)
    args = p.parse_args(argv)

    out: Dict[str, Any] = {"program": "ppa_objective",
                           "step_semantics": STEP_SEMANTICS,
                           "orfs_source": ORFS_SOURCE}
    rc = RC_OK
    try:
        if args.project is None:
            out["weights"] = resolve_weights(None, None)
        else:
            l19, rel, unreadable = load_l19(args.project)
            if unreadable:
                raise Refusal(
                    "L19_UNREADABLE",
                    f"{unreadable}. The design's L19 exists and could not be "
                    "parsed, so we cannot tell whether it declares "
                    "`ppa_weights`. Inheriting here would print somebody's "
                    "value judgement as absent when it may be present.",
                    RC_NOT_MEASURED)
            out["weights"] = resolve_weights(l19, rel)
            if not args.weights_only:
                out["metrics"] = read_metrics(args.project)
                miss = sorted(k for k, v in
                              out["metrics"]["unmeasured"].items()
                              if not v.get("non_blocking"))
                if miss:
                    out["verdict"] = "NOT_MEASURED"
                    out["blocking"] = miss
                    rc = RC_NOT_MEASURED
                else:
                    out["verdict"] = "MEASURED"
    except Refusal as exc:
        out["verdict"] = "REFUSED"
        out["refusal"] = {"code": exc.code, "message": exc.message}
        rc = exc.rc

    text = json.dumps(out, indent=2, sort_keys=False)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    w = out.get("weights")
    if isinstance(w, dict):
        print(f"[ppa_objective] weights {w['source'].upper()}: "
              + ", ".join(f"{a}={w['weights'][a]:g}" for a in AXES),
              file=sys.stderr)
        if w["source"] == "inherited":
            print(f"[ppa_objective] {INHERITED_PHRASE}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
