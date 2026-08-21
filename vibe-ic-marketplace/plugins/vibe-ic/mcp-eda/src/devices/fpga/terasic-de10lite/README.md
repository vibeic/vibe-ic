# Terasic DE10-Lite FPGA (mcp-eda device)

JSON-IO driver for the Terasic DE10-Lite (Intel/Altera MAX10
10M50DAF484C7G with on-board USB-Blaster). Auto-registered by
`src/devices/_registry.js` at server start; exposes two MCP tools:

| Tool | Purpose |
|------|---------|
| `device_fpga_de10lite_program` | Burn a `.sof` to the board via `quartus_pgm`. |
| `device_fpga_de10lite_detect` | List USB-Blaster cables + chained devices. |

Both tools share `driver.py` and dispatch via `--mode {program, detect}`.

## Supported boards

| Board | Status |
|-------|--------|
| **DE10-Lite (MAX10 10M50DAF484C7G)** | **Verified** on v0.65 bring-up |
| DE0-CV / DE0-Nano / DE2-115 / other USB-Blaster boards | Likely-compatible (same `quartus_pgm -m JTAG` path); add a board-specific tool if you need detection guards |

This driver does **not** bundle Quartus binaries; it shells out to a
user-installed `quartus_pgm`.

## Hardware setup

1. USB-B cable from the DE10-Lite's USB-Blaster port to the host PC.
2. Power the board (USB power is fine for programming-only).
3. JTAG mode is always available over USB regardless of the on-board
   boot-mode slide switch — no jumper changes needed.

Quick sanity check from a shell:

```bash
lsusb | grep 09fb       # should show 09fb:6010 USB-Blaster II
```

## Quartus install

Tested with **Quartus Prime Lite Edition 17.1+** (free download from Intel).
Newer Lite releases (20.x, 21.x) also work for MAX10. Set
`QUARTUS_ROOTDIR` so the driver finds `quartus_pgm`:

```bash
# in ~/.bashrc
export QUARTUS_ROOTDIR=/opt/intelFPGA_lite/20.1/quartus
export PATH="$QUARTUS_ROOTDIR/bin:$PATH"
```

The driver searches in this order: `$QUARTUS_ROOTDIR/bin`, `$PATH`,
`/opt/intelFPGA*/quartus/bin`, `~/intelFPGA*/quartus/bin`,
`~/altera*/quartus/bin`. If none hit, mode `detect` returns:

```json
{"success": false, "error": "quartus_pgm not in PATH or QUARTUS_ROOTDIR"}
```

## udev rule

Install the bundled rule so `quartus_pgm` can talk to the USB-Blaster
without sudo:

```bash
sudo cp src/devices/terasic-de10lite/udev/51-usbblaster.rules /etc/udev/rules.d/
sudo udevadm control --reload
sudo udevadm trigger
```

Then add yourself to `plugdev`:

```bash
sudo usermod -aG plugdev $USER
# log out + back in
```

The rule covers USB-Blaster I (PID `0x6001`/`0x6002`/`0x6003`) and II
(`0x6010`/`0x6810`).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `quartus_pgm not in PATH or QUARTUS_ROOTDIR` | Quartus not installed or env not exported | install Lite + `export QUARTUS_ROOTDIR=...` |
| `No JTAG hardware available` | jtagd is in a bad state | `sudo killall jtagd` then re-run a `--auto`; jtagd respawns |
| `Permission denied` opening USB | udev rule missing or user not in plugdev | install the rule + add to plugdev |
| Programming hangs | competing tool (Signal Tap, another `quartus_pgm`) holds the cable | close other JTAG tools |
| `Operations done` not present in output but exit 0 | Quartus version mismatch | check Quartus output manually; driver greps for two markers, file an issue if your release uses different wording |

## License

MIT (matches mcp-eda). The Terasic and Intel/Altera names are used
here for hardware identification only; this driver is not affiliated with
or endorsed by Terasic Technologies or Intel Corporation.
