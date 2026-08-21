"""Tests for flow_dashboard.py — the thin CLI/web dispatcher (no I/O)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flow_dashboard as fd  # noqa: E402


def test_strip_valued_removes_flag_and_value():
    assert fd._strip_valued(["a", "--port", "8787", "b"], {"--port"}) == ["a", "b"]


def test_strip_valued_removes_equals_form():
    assert fd._strip_valued(["--host=0.0.0.0", "x"], {"--host"}) == ["x"]


def test_strip_valued_keeps_unrelated_flags():
    assert fd._strip_valued(["--web", "--full"], {"--port"}) == ["--web", "--full"]


def test_help_and_empty_return_zero():
    assert fd.main(["-h"]) == 0
    assert fd.main([]) == 0


def test_web_flag_routes_to_web_and_strips_cli_only(monkeypatch):
    seen = {}

    def fake_web_main(argv):
        seen["argv"] = argv
        return 0

    import flow_dashboard_web as web
    monkeypatch.setattr(web, "main", fake_web_main)
    rc = fd.main(["/proj", "--web", "--port", "9999", "--once"])
    assert rc == 0
    # --web consumed, --once (cli-only) stripped, project + --port preserved
    assert "--web" not in seen["argv"] and "--once" not in seen["argv"]
    assert "/proj" in seen["argv"] and "--port" in seen["argv"] and "9999" in seen["argv"]


def test_fleet_flag_passes_through_to_web(monkeypatch):
    seen = {}

    def fake_web_main(argv):
        seen["argv"] = argv
        return 0

    import flow_dashboard_web as web
    monkeypatch.setattr(web, "main", fake_web_main)
    rc = fd.main(["/root", "--web", "--fleet"])
    assert rc == 0
    # --fleet is a shared flag; it must survive the web dispatch untouched.
    assert "--fleet" in seen["argv"] and "/root" in seen["argv"]


def test_fleet_flag_passes_through_to_cli(monkeypatch):
    seen = {}

    def fake_cli_main():
        seen["argv"] = list(sys.argv)
        return 0

    import flow_dashboard_cli as cli
    monkeypatch.setattr(cli, "main", fake_cli_main)
    rc = fd.main(["/root", "--fleet", "--once"])
    assert rc == 0
    assert "--fleet" in seen["argv"] and "/root" in seen["argv"]


def test_default_routes_to_cli_and_strips_web_only(monkeypatch):
    seen = {}

    def fake_cli_main():
        seen["argv"] = list(sys.argv)
        return 0

    import flow_dashboard_cli as cli
    monkeypatch.setattr(cli, "main", fake_cli_main)
    rc = fd.main(["/proj", "--port", "8787", "--interval", "2"])
    assert rc == 0
    # cli.main() reads sys.argv; the web-only --port/value must be stripped,
    # the cli-only --interval preserved.
    assert "--port" not in seen["argv"] and "8787" not in seen["argv"]
    assert "/proj" in seen["argv"] and "--interval" in seen["argv"]
