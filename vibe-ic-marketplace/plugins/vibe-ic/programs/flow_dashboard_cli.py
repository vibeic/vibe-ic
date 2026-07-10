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
except Exception:  # pragma: no cover
    _collect = None


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
    "done": ("✔", ("green",)),        # ✔
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


# Order + display metadata for the summary counts line.
_SUMMARY_ORDER = [
    ("done", "done", ("green",)),
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
    fver = _g(data, "flow_version", "") or ""
    now = time.strftime("%H:%M:%S")

    title = f"Vibe-IC Flow Dashboard  —  {name}"
    meta_bits = []
    if mode:
        meta_bits.append(f"mode={mode}")
    if fver:
        meta_bits.append(f"flow={fver}")
    meta_bits.append(now)
    meta = "   ".join(meta_bits)

    header_plain = title
    header_col = _c(title, "bold", "white", color=color)
    add(header_plain, header_col)
    add(_clip_line(meta, width), _c(_clip_line(meta, width), "dim", color=color))

    # ---- OVERALL progress + summary counts -------------------------------
    summary = _g(data, "summary", {}) or {}
    total = int(_g(summary, "total", 0) or 0)
    done = int(_g(summary, "done", 0) or 0)

    bar_inner = max(10, min(30, width - 30))
    bar = progress_bar(done, total, bar_inner)
    overall_plain = f"{bar} {done}/{total}"
    overall_col = _c(bar, "green", color=color) + f" {_c(f'{done}/{total}', 'bold', color=color)}"
    add(overall_plain, overall_col)

    # counts line, e.g. "done 40  running 1  pending 12  skipped 3 ..."
    count_parts_plain = []
    count_parts_col = []
    for key, label, codes in _SUMMARY_ORDER:
        val = int(_g(summary, key, 0) or 0)
        seg = f"{label} {val}"
        count_parts_plain.append(seg)
        count_parts_col.append(_c(seg, *codes, color=color))
    counts_plain = "  ".join(count_parts_plain)
    counts_col = "  ".join(count_parts_col)
    add(counts_plain, counts_col)
    add("")

    # ---- PHASES ----------------------------------------------------------
    id_w = 4
    # name column width scales with terminal but capped near ~44.
    name_w = max(20, min(44, width - 34))

    for ph in _ordered_phases(_g(data, "phases", []) or []):
        icon = _g(ph, "icon", "") or ""
        label = _g(ph, "label", _g(ph, "key", "phase")) or "phase"
        p_done = int(_g(ph, "done", 0) or 0)
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
        ("✔", "done"),
        ("⏭", "skip"),
        ("⚑", "waive"),
        ("✗", "fail"),
        ("∅", "missing"),
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
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    args = parser.parse_args(argv)

    if _collect is None:
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
        data = _collect(args.project, args.full)
        width = _term_width()
        ago = 0.0 if last_collect_ts is None else max(0.0, now - last_collect_ts)
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
