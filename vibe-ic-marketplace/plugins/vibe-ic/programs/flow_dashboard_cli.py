#!/usr/bin/env python3
"""flow_dashboard_cli.py — LIVE terminal dashboard for the Vibe-IC flow.

Renders, step-by-step and "一目瞭然", the full Vibe-IC flow as it executes:

  Phase 1 · Spec → Design Docs
  Phase 2 · Design Docs → RTL → SOF
  Phase 3 · Synth → PnR → GDS → sign-off
  Analog  · A1–A9
  Mixed   · M1–M4
  Manufacturing · 40–44

For each step it shows a status pill (DONE / SKIPPED / WAIVED / FAIL /
MISSING / RUNNING / PENDING) and WHERE that step's output lives on disk
(the first existing output, or the expected path dimmed if not produced).

STDLIB ONLY. Colors are raw ANSI escape codes (no rich/curses). Colors
auto-disable when stdout is not a TTY or when --no-color is passed.

The data it renders is produced by the sibling provider module
`flow_dashboard_data.collect(project, full)`; this file only RENDERS that
dict (fixed contract — see module docstring of flow_dashboard_data). The
renderer itself is a pure function `render_frame(data, ...)` with no I/O,
so it is unit-testable without ever calling collect().

CLI:
    python3 flow_dashboard_cli.py <project> [--interval 2.0] [--once] \\
        [--full] [--no-color]

  Default            LIVE: clear + redraw every --interval seconds.
  --once             render a single snapshot and exit 0.
  --full             pass-through to collect() (authoritative gate
                     verdicts; slower).
  --no-color         disable ANSI colors.
  Ctrl-C             exit cleanly (restore cursor, no traceback).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time

# The provider is built in parallel to the SAME contract; at runtime it is
# present. Guard the import so THIS module still parses / imports for unit
# tests (which feed render_frame a hand-built dict and never call collect).
try:  # pragma: no cover - import wiring, exercised at runtime not in tests
    from flow_dashboard_data import collect as _collect
    from flow_dashboard_data import collect_fleet as _collect_fleet
except Exception:  # pragma: no cover
    _collect = None
    _collect_fleet = None


# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------
_ESC = "\x1b["

# Named SGR codes (foreground + attributes) we use.
_SGR = {
    "reset": "0",
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "grey": "90",
    "white": "37",
}


def _c(text: str, *codes: str, color: bool = True) -> str:
    """Wrap *text* in the given named SGR *codes* when color is enabled."""
    if not color or not codes:
        return text
    seq = ";".join(_SGR.get(k, "0") for k in codes)
    return f"{_ESC}{seq}m{text}{_ESC}{_SGR['reset']}m"


# ---------------------------------------------------------------------------
# Status → (icon, color) mapping
# ---------------------------------------------------------------------------
# NOTE: icons are single display-cells (emoji-free) so column alignment holds
# in a fixed-width terminal.
_STATUS_STYLE = {
    "pass": ("✔", ("green",)),        # ✔ done · verdict PASS
    "skipped": ("⏭", ("cyan", "dim")),  # ⏭
    "waived": ("⚑", ("yellow",)),     # ⚑
    "fail": ("✗", ("red", "bold")),   # ✗
    "missing": ("∅", ("red",)),       # ∅
    "running": ("▸", ("blue",)),      # ▸
    "partial": ("◐", ("magenta",)),   # ◐ primary out present, secondary absent
    "na": ("○", ("grey",)),           # ○ lane not applicable to this design
    "external": ("⊗", ("grey", "dim")),  # ⊗ off-machine (fab / test)
    "pending": ("·", ("grey",)),      # ·
}
_UNKNOWN_STYLE = ("?", ("grey",))

# Spinner frames advanced once per refresh; shown in place of the running icon.
_SPINNER = "⠹⠸⠼⠴⠦⠧⠇⠏"  # braille dots


def status_style(status: str):
    """Return (icon, color_codes_tuple) for a status string."""
    return _STATUS_STYLE.get((status or "").lower(), _UNKNOWN_STYLE)


# ---------------------------------------------------------------------------
# Small formatting utilities
# ---------------------------------------------------------------------------
def _human_size(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    if n < 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    if i == 0:
        return f"{int(n)} {units[i]}"
    return f"{n:.0f} {units[i]}" if n >= 10 else f"{n:.1f} {units[i]}"


def _truncate(text: str, width: int, ellipsis: str = "…") -> str:
    """Truncate *text* to at most *width* display columns (naive 1-col/char)."""
    text = "" if text is None else str(text)
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return ellipsis
    return text[: width - 1] + ellipsis


def progress_bar(done, total, width: int) -> str:
    """A `[██████░░░░]` bar of the given inner *width* (excludes brackets)."""
    try:
        done = int(done)
        total = int(total)
    except (TypeError, ValueError):
        done, total = 0, 0
    width = max(0, int(width))
    if total <= 0:
        filled = 0
    else:
        frac = max(0.0, min(1.0, done / total))
        filled = int(round(frac * width))
        # Never show a full bar unless truly complete.
        if filled == width and done < total:
            filled = width - 1
        # Show at least one cell of progress once anything is done.
        if filled == 0 and done > 0:
            filled = 1
    empty = width - filled
    return "[" + ("█" * filled) + ("░" * empty) + "]"


# ---------------------------------------------------------------------------
# Frame rendering (pure)
# ---------------------------------------------------------------------------
def _g(d, key, default=None):
    """dict.get that tolerates a non-dict *d*."""
    if isinstance(d, dict):
        return d.get(key, default)
    return default


# Order + display metadata for the summary counts line (outcome breakdown).
_SUMMARY_ORDER = [
    ("pass", "pass", ("green",)),
    ("running", "running", ("blue",)),
    ("partial", "partial", ("magenta",)),
    ("pending", "pending", ("grey",)),
    ("na", "n/a", ("grey",)),
    ("external", "external", ("grey", "dim")),
    ("skipped", "skipped", ("cyan", "dim")),
    ("waived", "waived", ("yellow",)),
    ("fail", "fail", ("red", "bold")),
    ("missing", "missing", ("red",)),
]

# Canonical phase order — always these six, in this order (contract guarantee,
# but we defend against a provider that omits or reorders).
_PHASE_ORDER = ["phase1", "phase2", "phase3", "analog", "mixed", "manufacturing"]


def _ordered_phases(phases):
    if not isinstance(phases, list):
        return []
    by_key = {}
    extras = []
    for ph in phases:
        k = _g(ph, "key")
        if k in _PHASE_ORDER and k not in by_key:
            by_key[k] = ph
        else:
            extras.append(ph)
    ordered = [by_key[k] for k in _PHASE_ORDER if k in by_key]
    ordered.extend(extras)
    return ordered


def _clip_line(line: str, width: int) -> str:
    """Hard clip a *visible* line to width (no ANSI here — plain text only)."""
    if len(line) <= width:
        return line
    return _truncate(line, width)


def _primary_output(step):
    """Return (rel, size, exists, extra_count) for the output to display."""
    outputs = _g(step, "outputs", []) or []
    if not isinstance(outputs, list) or not outputs:
        return None
    total = len(outputs)
    # Prefer the first existing output; else the first (expected) one.
    chosen = None
    for o in outputs:
        if _g(o, "exists"):
            chosen = o
            break
    if chosen is None:
        chosen = outputs[0]
    rel = _g(chosen, "rel") or _g(chosen, "abs") or ""
    return {
        "rel": rel,
        "size": _g(chosen, "size"),
        "exists": bool(_g(chosen, "exists")),
        "extra": total - 1,
    }


def render_frame(
    data: dict,
    *,
    width: int = 100,
    color: bool = True,
    spinner_frame: int = 0,
    updated_ago: float | None = None,
    interval: float | None = None,
) -> str:
    """Render the full dashboard frame as a single string (no I/O).

    *data* conforms to the flow_dashboard_data.collect() contract. Missing
    keys are defaulted so this never raises on partial/empty input.
    """
    width = max(20, int(width))
    lines: list[str] = []

    def add(visible: str, colored: str | None = None):
        """Append a line, hard-clipped to width on its VISIBLE form."""
        vis = _clip_line(visible, width)
        if colored is None or not color:
            lines.append(vis)
        else:
            # colored must correspond 1:1 to `visible`; we clipped the visible
            # form, so re-clip is a no-op when they match. When color wrapping
            # is present we trust the caller kept visible == plain(colored).
            lines.append(colored if len(visible) <= width else vis)

    # ---- HEADER ----------------------------------------------------------
    name = _g(data, "project_name") or os.path.basename(str(_g(data, "project", ""))) or "(project)"
    mode = _g(data, "mode", "") or ""
    pver = _g(data, "plugin_version", "") or ""
    now = time.strftime("%H:%M:%S")

    title = f"Vibe-IC Flow Dashboard  —  {name}"
    meta_bits = []
    # The shipped vibe-ic plugin version (what the user runs) leads the meta line.
    if pver:
        meta_bits.append(f"vibe-ic v{pver}")
    if mode:
        meta_bits.append(f"mode={mode}")
    meta_bits.append(now)
    meta = "   ".join(meta_bits)

    header_plain = title
    header_col = _c(title, "bold", "white", color=color)
    add(header_plain, header_col)
    add(_clip_line(meta, width), _c(_clip_line(meta, width), "dim", color=color))

    # ---- OVERALL progress + summary counts -------------------------------
    summary = _g(data, "summary", {}) or {}
    total = int(_g(summary, "total", 0) or 0)
    # DONE = reached & judged (any verdict) = resolved. NOT just the PASS subset.
    done = int(_g(summary, "resolved", _g(summary, "done", 0)) or 0)

    bar_inner = max(10, min(30, width - 30))
    bar = progress_bar(done, total, bar_inner)
    overall_plain = f"{bar} Done {done}/{total}"
    overall_col = (_c(bar, "green", color=color)
                   + f" {_c('Done', 'dim', color=color)} "
                   + _c(f'{done}/{total}', 'bold', color=color))
    add(overall_plain, overall_col)

    # outcome breakdown, e.g. "pass 33  fail 0  skipped 8  na 13  external 5 ..."
    # A status this mode's classifier cannot emit is rendered "n/a", never as a
    # count: "fail 0" from a classifier with no fail branch asserts a verdict
    # that was never computed.
    unavailable = set(_g(data, "summary_unavailable", []) or [])
    count_parts_plain = []
    count_parts_col = []
    for key, label, codes in _SUMMARY_ORDER:
        if key in unavailable:
            seg = f"{label} n/a"
            count_parts_plain.append(seg)
            count_parts_col.append(_c(seg, "dim", color=color))
            continue
        val = int(_g(summary, key, 0) or 0)
        seg = f"{label} {val}"
        count_parts_plain.append(seg)
        count_parts_col.append(_c(seg, *codes, color=color))
    counts_plain = "  ".join(count_parts_plain)
    counts_col = "  ".join(count_parts_col)
    add(counts_plain, counts_col)
    if unavailable:
        names = ", ".join(
            lbl for k, lbl, _ in _SUMMARY_ORDER if k in unavailable
        )
        hint = (f"   ({names} not derivable in {_g(data, 'mode', '')} mode "
                f"— this map is output-file presence, not a verdict; "
                f"run --full, or read reports/orchestrator/*.json)")
        add(_clip_line(hint, width), _c(_clip_line(hint, width), "dim",
                                        color=color))

    # ---- AUTHORITATIVE failing steps, quoted verbatim --------------------
    # Deliberately a flat list, NOT painted onto step rows: the orchestrator
    # keys steps by runner-internal name and the flow keys them by id, with no
    # mapping between the two. See flow_dashboard_data._orchestrator_failures.
    ofails = _g(data, "orchestrator_failures", []) or []
    if ofails:
        head = f"✗ runner-reported failing step(s): {len(ofails)}"
        add(_clip_line(head, width),
            _c(_clip_line(head, width), "red", "bold", color=color))
        for rec in ofails:
            line = (f"   {_g(rec, 'status', '')}  {_g(rec, 'name', '')}"
                    f"   [{_g(rec, 'source', '')}]")
            add(_clip_line(line, width),
                _c(_clip_line(line, width), "red", color=color))
    add("")

    # ---- PHASES ----------------------------------------------------------
    id_w = 4
    # name column width scales with terminal but capped near ~44.
    name_w = max(20, min(44, width - 34))

    for ph in _ordered_phases(_g(data, "phases", []) or []):
        icon = _g(ph, "icon", "") or ""
        label = _g(ph, "label", _g(ph, "key", "phase")) or "phase"
        p_done = int(_g(ph, "resolved", _g(ph, "done", 0)) or 0)
        p_total = int(_g(ph, "total", 0) or 0)

        head_plain = f"{icon} {label}  ({p_done}/{p_total})"
        head_col = (
            f"{icon} "
            + _c(label, "bold", "magenta", color=color)
            + "  "
            + _c(f"({p_done}/{p_total})", "dim", color=color)
        )
        add(head_plain, head_col)

        steps = _g(ph, "steps", []) or []
        if not isinstance(steps, list) or not steps:
            add("    (no steps)", _c("    (no steps)", "dim", color=color))
            add("")
            continue

        for st in steps:
            status = (_g(st, "status", "pending") or "pending").lower()
            sid = str(_g(st, "id", "") or "")
            sname = str(_g(st, "name", "") or "")
            base_icon, codes = status_style(status)

            # Spinner replaces the static icon for a running step.
            if status == "running" and _SPINNER:
                sicon = _SPINNER[spinner_frame % len(_SPINNER)]
            else:
                sicon = base_icon

            status_label = _g(st, "status_label", status.upper()) or status.upper()
            detail = str(_g(st, "detail", "") or "").strip()

            id_txt = sid[:id_w].ljust(id_w)
            name_txt = _truncate(sname, name_w).ljust(name_w)
            pill = f"[{status_label}]"

            row_plain = f"  {sicon} {id_txt} {name_txt}  {pill}"
            # Append short detail dimmed, only if it fits.
            if detail:
                remaining = width - len(row_plain) - 3
                if remaining >= 6:
                    det = _truncate(detail, remaining)
                    row_plain = f"{row_plain}   {det}"

            # Colored form: color the icon, pill, and detail.
            row_col = (
                "  "
                + _c(sicon, *codes, color=color)
                + f" {id_txt} {name_txt}  "
                + _c(pill, *codes, color=color)
            )
            if detail and (width - len(f"  {sicon} {id_txt} {name_txt}  {pill}") - 3) >= 6:
                remaining = width - len(f"  {sicon} {id_txt} {name_txt}  {pill}") - 3
                det = _truncate(detail, remaining)
                row_col = row_col + "   " + _c(det, "dim", color=color)

            add(row_plain, row_col)

            # Output location line.
            out = _primary_output(st)
            if out is not None:
                rel = out["rel"] or "(no path)"
                size_txt = _human_size(out["size"]) if out["exists"] else ""
                extra = f"  (+{out['extra']} more)" if out["extra"] > 0 else ""
                if out["exists"]:
                    tail = f"  ({size_txt})" if size_txt else ""
                    body = f"└─ {rel}{tail}{extra}"
                    out_plain = "        " + body
                    out_col = "        " + _c(body, "green", color=color)
                else:
                    body = f"└─ {rel}{extra}  (expected)"
                    out_plain = "        " + body
                    out_col = "        " + _c(body, "dim", color=color)
                add(out_plain, out_col)

        add("")

    # ---- FOOTER ----------------------------------------------------------
    legend_pairs = [
        ("✔", "pass"),
        ("⏭", "skip"),
        ("⚑", "waive"),
        ("○", "n/a"),
        ("⊗", "extern"),
        ("◐", "partial"),
        ("✗", "fail"),
        ("▸", "run"),
        ("·", "pend"),
    ]
    legend = "  ".join(f"{i} {t}" for i, t in legend_pairs)
    add(legend, _c(legend, "dim", color=color))

    foot_bits = []
    if updated_ago is not None:
        foot_bits.append(f"updated {int(round(updated_ago))}s ago")
    if interval is not None:
        foot_bits.append(f"refreshing every {interval:g}s")
    foot_bits.append("Ctrl-C to quit")
    footer = "  ·  ".join(foot_bits)
    add(footer, _c(footer, "dim", color=color))

    return "\n".join(lines)


def render_fleet(
    data: dict,
    *,
    width: int = 100,
    color: bool = True,
    spinner_frame: int = 0,
    updated_ago: float | None = None,
    interval: float | None = None,
) -> str:
    """Render the FLEET overview — one compact block per IC (multi-IC / multi-
    subagent view) — as a single string (no I/O).

    *data* conforms to flow_dashboard_data.collect_fleet(): {kind:"fleet",
    agg:{...}, fleet:[<ic card>, ...]}. Missing keys are defaulted so this
    never raises on partial/empty input.
    """
    width = max(20, int(width))
    lines: list[str] = []

    def add(visible: str, colored: str | None = None):
        vis = _clip_line(visible, width)
        if colored is None or not color:
            lines.append(vis)
        else:
            lines.append(colored if len(visible) <= width else vis)

    agg = _g(data, "agg", {}) or {}
    fleet = _g(data, "fleet", []) or []
    if not isinstance(fleet, list):
        fleet = []
    pver = _g(data, "plugin_version", "") or ""
    now = time.strftime("%H:%M:%S")

    ic_count = int(_g(agg, "ic_count", len(fleet)) or 0)
    ic_running = int(_g(agg, "ic_running", 0) or 0)
    ic_done = int(_g(agg, "ic_done", 0) or 0)

    # ---- HEADER ----------------------------------------------------------
    title = f"Vibe-IC Fleet Dashboard  —  {ic_count} IC{'s' if ic_count != 1 else ''}"
    add(title, _c(title, "bold", "white", color=color))
    meta_bits = []
    if pver:
        meta_bits.append(f"vibe-ic v{pver}")
    meta_bits.append(f"{ic_running} running")
    meta_bits.append(f"{ic_done} done")
    meta_bits.append(now)
    meta = "   ".join(meta_bits)
    add(_clip_line(meta, width), _c(_clip_line(meta, width), "dim", color=color))

    # ---- AGGREGATE progress ---------------------------------------------
    a_total = int(_g(agg, "total", 0) or 0)
    a_done = int(_g(agg, "resolved", _g(agg, "done", 0)) or 0)
    bar_inner = max(10, min(30, width - 34))
    bar = progress_bar(a_done, a_total, bar_inner)
    overall_plain = f"{bar} Done {a_done}/{a_total} steps"
    overall_col = (_c(bar, "green", color=color)
                   + f" {_c('Done', 'dim', color=color)} "
                   + _c(f'{a_done}/{a_total}', 'bold', color=color)
                   + _c(' steps', 'dim', color=color))
    add(overall_plain, overall_col)
    add("")

    # ---- PER-IC blocks ---------------------------------------------------
    # name column so the bars line up across ICs.
    name_w = max(10, min(24, width - 46))
    ic_bar_w = max(8, min(20, width - name_w - 26))

    for card in fleet:
        pname = str(_g(card, "project_name", "") or _g(card, "project", "") or "(ic)")
        mode = str(_g(card, "mode", "") or "")
        err = _g(card, "error")
        s = _g(card, "summary", {}) or {}
        total = int(_g(s, "total", 0) or 0)
        done = int(_g(s, "resolved", _g(s, "done", 0)) or 0)
        running = int(_g(s, "running", 0) or 0)

        name_txt = _truncate(pname, name_w).ljust(name_w)

        if err:
            row_plain = f"  ✗ {name_txt}  {_truncate(str(err), max(6, width - name_w - 8))}"
            add(row_plain, "  " + _c("✗", "red", "bold", color=color)
                + f" {name_txt}  " + _c(_truncate(str(err), max(6, width - name_w - 8)), "red", color=color))
            continue

        # live marker: spinner while running, else a done/idle dot.
        if running > 0 and _SPINNER:
            mk = _SPINNER[spinner_frame % len(_SPINNER)]
            mk_codes = ("blue",)
        elif total and done >= total:
            mk, mk_codes = "✔", ("green",)
        else:
            mk, mk_codes = "•", ("grey",)

        ic_bar = progress_bar(done, total, ic_bar_w)
        count_txt = f"{done:>2}/{total:<2}"
        run_txt = f"  ▸{running}" if running > 0 else ""
        row_plain = f"  {mk} {name_txt} {ic_bar} {count_txt}{run_txt}"
        row_col = (
            "  " + _c(mk, *mk_codes, color=color)
            + f" {name_txt} "
            + _c(ic_bar, "green", color=color)
            + " " + _c(count_txt, "bold", color=color)
            + (("  " + _c(f"▸{running}", "blue", color=color)) if running > 0 else "")
        )
        add(row_plain, row_col)

        # outcome breakdown for this IC — only the non-zero, non-pass buckets
        # that carry signal, kept to one dim line.
        seg_plain = []
        seg_col = []
        for key, label, codes in _SUMMARY_ORDER:
            val = int(_g(s, key, 0) or 0)
            if not val:
                continue
            seg_plain.append(f"{label} {val}")
            seg_col.append(_c(f"{label} {val}", *codes, color=color))
        if seg_plain:
            body = "      " + "  ".join(seg_plain)
            body_col = "      " + "  ".join(seg_col)
            add(body, body_col)

        # currently-running step names (what each subagent is doing right now).
        rsteps = _g(card, "running_steps", []) or []
        if isinstance(rsteps, list) and rsteps:
            names = ", ".join(
                f"#{_g(r, 'id', '')} {_g(r, 'name', '')}".strip() for r in rsteps[:3]
            )
            more = f" +{len(rsteps) - 3}" if len(rsteps) > 3 else ""
            body = "      ▸ " + _truncate(names + more, max(6, width - 8))
            add(body, "      " + _c("▸ " + _truncate(names + more, max(6, width - 8)),
                                     "blue", color=color))
        add("")

    # ---- FOOTER ----------------------------------------------------------
    foot_bits = []
    if updated_ago is not None:
        foot_bits.append(f"updated {int(round(updated_ago))}s ago")
    if interval is not None:
        foot_bits.append(f"refreshing every {interval:g}s")
    foot_bits.append("one row per IC · ▸N = N steps running · Ctrl-C to quit")
    footer = "  ·  ".join(foot_bits)
    add(footer, _c(footer, "dim", color=color))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Live loop / CLI
# ---------------------------------------------------------------------------
_CLEAR_HOME = "\x1b[2J\x1b[H"
_HIDE_CURSOR = "\x1b[?25l"
_SHOW_CURSOR = "\x1b[?25h"


def _term_width() -> int:
    try:
        return max(40, shutil.get_terminal_size((100, 40)).columns)
    except Exception:
        return 100


def _write(s: str) -> None:
    try:
        sys.stdout.write(s)
        sys.stdout.flush()
    except BrokenPipeError:  # pragma: no cover
        pass


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="flow_dashboard_cli.py",
        description="LIVE terminal dashboard for the Vibe-IC Phase 1/2/3 "
        "(+ Analog / Mixed / Manufacturing) flow.",
    )
    parser.add_argument("project", help="Path to the Vibe-IC project directory")
    parser.add_argument(
        "--interval", type=float, default=2.0,
        help="Live refresh interval in seconds (default 2.0)",
    )
    parser.add_argument("--once", action="store_true", help="Render one snapshot and exit")
    parser.add_argument(
        "--full", action="store_true",
        help="Authoritative gate verdicts (slower); passed to collect()",
    )
    parser.add_argument(
        "--fleet", action="store_true",
        help="Treat PROJECT as a parent dir; show ALL child projects (fleet view)",
    )
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    args = parser.parse_args(argv)

    if _collect is None or (args.fleet and _collect_fleet is None):
        sys.stderr.write(
            "flow_dashboard_cli: provider module 'flow_dashboard_data' not "
            "importable; cannot collect flow state.\n"
        )
        return 2

    # Color on only when a TTY and not suppressed.
    color = (not args.no_color) and sys.stdout.isatty()
    interval = max(0.2, float(args.interval))

    def snapshot(spinner_frame: int, last_collect_ts: float | None) -> str:
        now = time.time()
        width = _term_width()
        ago = 0.0 if last_collect_ts is None else max(0.0, now - last_collect_ts)
        if args.fleet:
            data = _collect_fleet([], full=args.full, root=args.project)
            return render_fleet(
                data,
                width=width,
                color=color,
                spinner_frame=spinner_frame,
                updated_ago=ago if not args.once else None,
                interval=None if args.once else interval,
            )
        data = _collect(args.project, args.full)
        return render_frame(
            data,
            width=width,
            color=color,
            spinner_frame=spinner_frame,
            updated_ago=ago if not args.once else None,
            interval=None if args.once else interval,
        )

    if args.once:
        try:
            frame = snapshot(0, None)
        except Exception as exc:  # pragma: no cover - defensive
            sys.stderr.write(f"flow_dashboard_cli: collect failed: {exc}\n")
            return 1
        _write(frame + "\n")
        return 0

    # LIVE loop.
    spinner = 0
    last_ts = None
    if color:
        _write(_HIDE_CURSOR)
    try:
        while True:  # watchdog-exempt: interactive live-redraw UI loop (Ctrl-C / --once to exit); no tool subprocess
            try:
                frame = snapshot(spinner, last_ts)
                last_ts = time.time()
            except Exception as exc:  # pragma: no cover - defensive
                frame = f"flow_dashboard_cli: collect failed: {exc}"
            _write(_CLEAR_HOME + frame + "\n")
            spinner += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0
    finally:
        if color:
            _write(_SHOW_CURSOR)
    return 0  # pragma: no cover


def main() -> int:  # pragma: no cover - thin wrapper
    return run()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
