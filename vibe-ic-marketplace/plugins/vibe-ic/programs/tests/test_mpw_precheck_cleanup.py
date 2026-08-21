"""Unit tests for `mpw_precheck_cleanup.py`."""
import importlib

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("mpw_precheck_cleanup")


class TestFixReadme:
    def test_replaces_stock_template(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("# Caravel User Project\nStock template content\n")
        out = mod.fix_default_readme(tmp_path, "myproj")
        assert out.files_changed
        new = readme.read_text()
        assert "myproj" in new
        assert "Stock template content" not in new

    def test_skips_already_customised(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("# MyChip\nProject-specific content\n")
        out = mod.fix_default_readme(tmp_path, "myproj")
        # No change — already customised
        assert out.files_changed == []

    def test_creates_when_missing(self, tmp_path):
        out = mod.fix_default_readme(tmp_path, "myproj")
        assert (tmp_path / "README.md").exists()
        assert out.files_changed


class TestFixSpdx:
    def test_adds_header_to_verilog(self, tmp_path):
        v = tmp_path / "verilog" / "rtl"
        v.mkdir(parents=True)
        f = v / "dut.v"
        f.write_text("module dut; endmodule\n")
        out = mod.fix_spdx_headers(tmp_path, "myproj")
        new = f.read_text()
        assert "SPDX-License-Identifier" in new
        assert "myproj" in new
        assert "module dut" in new

    def test_skips_file_with_existing_spdx(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text(
            "# SPDX-License-Identifier: Apache-2.0\n"
            "# SPDX-FileCopyrightText: 2026 someone\n"
            "print('hi')\n")
        out = mod.fix_spdx_headers(tmp_path, "myproj")
        # Should NOT have re-added the header
        assert str(f.relative_to(tmp_path)) not in out.files_changed

    def test_adds_to_c_file_with_c_style_comment(self, tmp_path):
        f = tmp_path / "main.c"
        f.write_text("int main(void) { return 0; }\n")
        mod.fix_spdx_headers(tmp_path, "myproj")
        new = f.read_text()
        # C-style /* */ block
        assert "/*" in new
        assert "SPDX-License-Identifier" in new

    def test_skips_dependencies_subtree(self, tmp_path):
        # Files under dependencies/ should NOT be touched
        deps = tmp_path / "dependencies" / "mpw_precheck"
        deps.mkdir(parents=True)
        f = deps / "x.py"
        f.write_text("print('x')\n")
        mod.fix_spdx_headers(tmp_path, "myproj")
        # Unchanged
        assert "SPDX" not in f.read_text()


class TestFixGpioDefines:
    def test_skips_when_no_pin_map(self, tmp_path):
        out = mod.fix_gpio_defines(tmp_path, pin_map_path=None)
        assert "skipped" in out.notes.lower()

    def test_emits_when_pin_map_supplied(self, tmp_path):
        import json
        pm = tmp_path / "pinmap.json"
        pm.write_text(json.dumps({
            "project_name": "spm",
            "core_module": "spm",
            "power_domains": ["vccd1", "vssd1"],
            "pin_assignments": [
                {"core_port": "clk", "caravel_pin": "wb_clk_i",
                 "port_dir": "input"},
                {"core_port": "p", "caravel_pin": "io_out[35]",
                 "port_dir": "output"},
            ],
        }))
        out = mod.fix_gpio_defines(tmp_path, pin_map_path=pm)
        ud = (tmp_path / "verilog" / "rtl" / "user_defines.v").read_text()
        assert "USER_CONFIG_GPIO_35_INIT" in ud
        assert "OUTPUT" in ud


class TestFixDocumentationBannedWords:
    def test_patches_blacklist_to_denylist(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("Use the blacklist to filter.\n")
        out = mod.fix_documentation_banned_words(tmp_path)
        new = f.read_text()
        assert "denylist" in new
        assert "blacklist" not in new

    def test_patches_whitelist(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("The whitelist mode.\n")
        mod.fix_documentation_banned_words(tmp_path)
        assert "allowlist" in f.read_text()

    def test_patches_slave_to_secondary(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("master/slave model.\n")
        mod.fix_documentation_banned_words(tmp_path)
        new = f.read_text()
        assert "primary" in new
        assert "secondary" in new

    def test_preserves_legitimate_content(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("Project description with no banned terms.\n")
        out = mod.fix_documentation_banned_words(tmp_path)
        # No file should be in the changed list
        assert f.name not in [Path(s).name for s in out.files_changed
                                for Path in [type(f)]]


class TestFixJunkFiles:
    def test_removes_bak_file(self, tmp_path):
        (tmp_path / "x.bak").write_text("backup")
        out = mod.fix_junk_files(tmp_path)
        assert not (tmp_path / "x.bak").exists()

    def test_removes_orig_file(self, tmp_path):
        (tmp_path / "x.orig").write_text("orig")
        out = mod.fix_junk_files(tmp_path)
        assert not (tmp_path / "x.orig").exists()

    def test_keeps_normal_files(self, tmp_path):
        (tmp_path / "x.v").write_text("module x; endmodule\n")
        out = mod.fix_junk_files(tmp_path)
        assert (tmp_path / "x.v").exists()


class TestCleanupDriver:
    def _setup(self, tmp_path):
        (tmp_path / "README.md").write_text("# Caravel User Project\n")
        v = tmp_path / "verilog" / "rtl"
        v.mkdir(parents=True)
        (v / "spm.v").write_text("module spm; endmodule\n")
        (tmp_path / "x.bak").write_text("junk")
        # Banned word in markdown
        (tmp_path / "doc.md").write_text("Some blacklist content.\n")
        return tmp_path

    def test_apply_all(self, tmp_path):
        proj = self._setup(tmp_path)
        rep = mod.cleanup_project(proj, "myproj")
        assert rep.verdict == "CLEAN_FIXED"
        # All 5 fixes ran
        names = [f.fix_name for f in rep.fixes_applied]
        assert "default_readme" in names
        assert "spdx_headers" in names
        assert "documentation_banned_words" in names
        assert "junk_files" in names
        # x.bak gone
        assert not (proj / "x.bak").exists()

    def test_idempotent_on_clean_project(self, tmp_path):
        # No README, no banned, no junk
        proj = tmp_path
        rep = mod.cleanup_project(proj, "myproj")
        # README will be created (1 file changed), but the others all no-op
        # → verdict = CLEAN_FIXED (because of README)
        # Pivot the test: re-run; the 2nd run should be IDEMPOTENT
        rep2 = mod.cleanup_project(proj, "myproj")
        assert rep2.verdict == "IDEMPOTENT"

    def test_attribution(self, tmp_path):
        rep = mod.cleanup_project(tmp_path, "x")
        d = rep.as_dict()
        assert d["emitted_by"] == \
            f"mpw_precheck_cleanup v{shipped_plugin_version()}"
