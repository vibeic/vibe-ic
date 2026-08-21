# Keysight Oscilloscope (mcp-eda device)

JSON-IO driver for Keysight InfiniiVision-class oscilloscopes. Auto-registered
by `src/devices/_registry.js` at server start; exposes two MCP tools:

| Tool | Purpose |
|------|---------|
| `device_scope_capture` | Arm + capture a window, return raw `(time_us, voltage)` samples as CSV inside the JSON response. |
| `device_scope_periodic_pulse_check` | Capture + find LOW pulses + check whether ≥ 2 of them have a periodic inter-pulse gap. PASS/FAIL verdict. Built to catch the v0.64 wake_ctrl tITO timer-freeze bug, but the periodicity test is general. |

Both tools share `driver.py` and dispatch via `--mode {capture, pulse_check}`.

## Supported models

| Model | Status |
|-------|--------|
| **DSO-X 3014T** (VID 0x2a8d / PID 0x1768) | **Verified** on v0.65 bring-up |
| InfiniiVision 3000T family | Likely-compatible (same SCPI subset) |
| InfiniiVision 4000X family | Likely-compatible (same SCPI subset) |

Override `vid` / `pid` in the tool call to talk to a different model that
speaks the same SCPI dialect.

## Hardware setup

1. USB-B cable from the scope's rear `USB Device` port to the host PC.
2. Connect a 10× passive probe to the channel you want to monitor (default
   channel 4 — `device_scope_capture` and `device_scope_periodic_pulse_check`
   both default to CH4).
3. Probe tip → signal under test, ground clip → DUT GND.

The driver assumes a 10× probe, DC coupling, 1 V/div, 1.5 V offset, and the
25 MHz BW limit on. These are appropriate for 3.3 V CMOS digital signals.
Pass `no_configure: true` to keep your existing scope state.

## udev rule

The scope appears as `/dev/usbtmc*`. By default that node is root-only.
Install the bundled rule once:

```bash
sudo cp src/devices/keysight-scope/udev/99-keysight-scope.rules /etc/udev/rules.d/
sudo udevadm control --reload
sudo udevadm trigger
```

Then add yourself to `plugdev` if you're not already in it:

```bash
sudo usermod -aG plugdev $USER
# log out + back in for it to take effect
```

Test:

```bash
ls -l /dev/usbtmc*
# should show: crw-rw---- 1 root plugdev ... /dev/usbtmc0
python3 -c "import usbtmc; print(usbtmc.list_devices())"
```

## Python deps

```bash
pip install --user --break-system-packages python-usbtmc pyusb
```

`pyusb` needs `libusb-1.0-0` available system-wide
(`sudo apt install libusb-1.0-0`).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `cannot open scope: no device matching VID:PID` | scope not enumerated | check `lsusb \| grep 2a8d`; cycle USB-B cable |
| `Permission denied: '/dev/usbtmc0'` | udev rule not installed or user not in `plugdev` | install rule + add user, see above |
| `no trigger within timeout` | signal not arriving on the probed channel | scope it manually first, confirm trigger level |
| `unexpected preamble` | another SCPI client is racing the driver | close BenchVue / other tools first |
| `python-usbtmc not installed` | venv mismatch | install with `--break-system-packages` |

## License

MIT (matches mcp-eda). The Keysight name is used here for hardware
identification only; this driver is not affiliated with or endorsed by
Keysight Technologies.
