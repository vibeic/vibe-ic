#!/usr/bin/env python3
"""flow_dashboard.py — unified entry for the Vibe-IC flow execution dashboard.

One glanceable view of EVERY step in the Vibe-IC flow as it runs — Phase 1
(spec → L1-L23 docs), Phase 2 (RTL → synth → verify), Phase 3 (PnR → sign-off),
plus the Analog A1-A9, Mixed-Signal M1-M4 and Manufacturing 40-44 tracks. Each
step shows its live status AND where its output artifact is on disk, so a
silently-skipped step is impossible to miss.

Two front-ends, one data source (`flow_dashboard_data.collect`):

  python3 flow_dashboard.py <project>                 # live CLI  (default)
  python3 flow_dashboard.py <project> --once          # one CLI snapshot, exit
  python3 flow_dashboard.py <project> --web            # localhost web page
  python3 flow_dashboard.py <project> --web --port 8787

Common flags:
  --full          authoritative gate verdicts (runs flow_compliance_check; slower)
  --interval N    CLI live poll seconds (default 2.0)
  --no-color      CLI: disable ANSI colour
  --port N        web: port (default 8787)
  --host H        web: bind interface (default 127.0.0.1)

The dashboard is READ-ONLY: it observes the project tree, it never runs or
mutates the flow. Launch it in a second terminal (or background it) while the
runner executes and watch the steps light up one by one.
"""
import sys
from pathlib import Path

# make the sibling dashboard modules importable no matter the CWD
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _strip_valued(argv, names):
    """Drop `--name VALUE` and `--name=VALUE` occurrences for the given names."""
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a in names:
            skip = True
            continue
        if any(a.startswith(n + "=") for n in names):
            continue
        out.append(a)
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    if "--web" in argv:
        argv = [a for a in argv if a != "--web"]
        # web has no CLI-only flags to strip (--interval/--once/--no-color are
        # CLI-only; drop them so the web arg-parser doesn't choke)
        argv = _strip_valued(argv, {"--interval"})
        argv = [a for a in argv if a not in ("--once", "--no-color")]
        import flow_dashboard_web as web
        return web.main(argv)

    # default: live CLI. Strip web-only flags if the user mixed them in.
    argv = _strip_valued(argv, {"--port", "--host"})
    import flow_dashboard_cli as cli
    # cli.main() reads sys.argv, so hand it the cleaned list
    sys.argv = ["flow_dashboard_cli.py"] + argv
    return cli.main()


if __name__ == "__main__":
    sys.exit(main())
