"""Unit tests for `hold_buffer_cell_picker.py`."""
import importlib

mod = importlib.import_module("hold_buffer_cell_picker")


class TestClassifyRole:
    def test_delay_gate(self):
        assert mod.classify_role("sky130_fd_sc_hd__dlygate4sd1_1") == mod.ROLE_DELAY

    def test_plain_buffer(self):
        assert mod.classify_role("sky130_fd_sc_hd__buf_4") == mod.ROLE_BUFFER

    def test_clock_buffer_excluded(self):
        assert mod.classify_role("sky130_fd_sc_hd__clkbuf_1") == mod.ROLE_CLOCK

    def test_inverter_excluded(self):
        assert mod.classify_role("sky130_fd_sc_hd__inv_2") == mod.ROLE_INVERTER

    def test_logic_other(self):
        assert mod.classify_role("sky130_fd_sc_hd__nand2_1") == mod.ROLE_OTHER


class TestParseDrive:
    def test_underscore_suffix(self):
        assert mod.parse_drive("sky130_fd_sc_hd__buf_4") == 4

    def test_x_suffix(self):
        assert mod.parse_drive("bufx16") == 16

    def test_no_drive(self):
        assert mod.parse_drive("buffer") is None


class TestEvaluatePass:
    def test_picks_min_drive_delay_over_buffer(self):
        # delay gate beats buffer regardless of drive; among same role, min drive
        cells = ["buf_1", "buf_4", "dlygate_2", "dlygate_8", "clkbuf_1", "inv_1"]
        verdict, rc, report = mod.evaluate(cells)
        assert verdict == "PASS"
        assert rc == 0
        # best is the delay gate with smallest drive
        assert report["recommended"]["role"] == mod.ROLE_DELAY
        assert report["recommended"]["drive"] == 2

    def test_min_drive_buffer_when_no_delay(self):
        cells = ["buf_4", "buf_1", "buf_2"]
        verdict, rc, report = mod.evaluate(cells)
        assert verdict == "PASS"
        assert report["recommended"]["name"] == "buf_1"
        assert report["recommended"]["drive"] == 1

    def test_clock_and_inverter_excluded(self):
        cells = ["buf_1", "clkbuf_2", "inv_1"]
        _, _, report = mod.evaluate(cells)
        excluded_names = {c["name"] for c in report["excluded"]}
        assert "clkbuf_2" in excluded_names
        assert "inv_1" in excluded_names


class TestEvaluateFailHonest:
    def test_empty_list_fails(self):
        verdict, rc, report = mod.evaluate([])
        assert verdict == "FAIL"
        assert rc == 1
        assert report["reason"] == "EMPTY_CELL_LIST"
        assert report["recommended"] is None

    def test_only_clock_and_logic_fails(self):
        # no usable buffer/delay cell at all -> honest FAIL, not vacuous PASS
        verdict, rc, report = mod.evaluate(["clkbuf_1", "inv_2", "nand2_1"])
        assert verdict == "FAIL"
        assert rc == 1
        assert report["reason"] == "NO_USABLE_HOLD_CELL"

    def test_whitespace_only_garbage_fails(self):
        verdict, rc, report = mod.evaluate(["   ", "\t", ""])
        assert verdict == "FAIL"
        assert rc == 1


class TestParseCellsText:
    def test_json_array(self):
        assert mod._parse_cells_text('["a", "b"]') == ["a", "b"]

    def test_comma_and_newline(self):
        assert mod._parse_cells_text("a,b\nc") == ["a", "b", "c"]

    def test_empty(self):
        assert mod._parse_cells_text("   ") == []


class TestCli:
    def test_cli_pass(self, tmp_path):
        out = tmp_path / "r.json"
        rc = mod.main(["--cells", "buf_1,dlygate_2,clkbuf_1",
                       "--json", str(out)])
        assert rc == 0
        import json
        rep = json.loads(out.read_text())
        assert rep["verdict"] == "PASS"
        assert rep["recommended"]["name"] == "dlygate_2"

    def test_cli_missing_file_fails(self, tmp_path):
        out = tmp_path / "r.json"
        rc = mod.main([str(tmp_path / "nope.txt"), "--json", str(out)])
        assert rc == 1
        import json
        rep = json.loads(out.read_text())
        assert rep["verdict"] == "FAIL"
