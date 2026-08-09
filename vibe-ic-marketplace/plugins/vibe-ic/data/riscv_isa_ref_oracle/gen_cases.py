#!/usr/bin/env python3
"""Build every firmware L10 case, derive its golden from spike, generate a
self-checking TB, run it, and record the result.

For each case <c>:
  <c>.S                 firmware (contains no expected value)
  <c>.elf               linked at 0x00000000  -> the DUT (reset_pc = 0)
  <c>_spike.elf         linked at 0x80000000  -> spike
  <c>.hex               256-word image the TB preloads into the SRAM model
  golden_<c>_sram.txt   final SRAM image, replayed from spike's commit log
  golden_<c>_gpio.txt   ordered GPIO write data, from spike's commit log
  <c>.v                 self-checking TB (module name == the L10 case id)
  <c>.simlog            the transcript

A case is PASS only if vvp exits 0 after comparing against the spike golden.
"""
import os, re, struct, subprocess, sys, json

HERE = os.path.dirname(os.path.abspath(__file__))
RTL = os.environ.get("RTL", "/home/reyerchu/_c_sub_gf180_v11029_run/phase2/stage1/rtl")
GCC = "riscv64-unknown-elf-gcc"
FLAGS = ["-march=rv32i_zifencei", "-mabi=ilp32", "-mno-relax", "-Wl,--no-relax",
         "-nostdlib", "-nostartfiles", "-Wl,--no-warn-rwx-segments",
         "-I", HERE]
BASE_SPIKE = 0x80000000
SIZE = 0x400
GPIO_ADDR = 0x40000000
STORE = re.compile(r'mem 0x([0-9a-f]+) 0x([0-9a-f]+)\s*$')

CASES = sys.argv[1:] or ["rv32i_40", "zifencei", "blinky_hex", "hello_hex"]


def sh(cmd, **kw):
    return subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, **kw)


def build(case):
    for ld, out in (("link.ld", case + ".elf"), ("link_spike.ld", case + "_spike.elf")):
        r = sh([GCC] + FLAGS + ["-Wl,-T," + ld, "-o", out, case + ".S"])
        if r.returncode:
            raise SystemExit("[%s] build failed:\n%s" % (case, r.stderr))
    # prove both links are the same program
    for e, b in ((case + ".elf", "_t0.bin"), (case + "_spike.elf", "_t8.bin")):
        sh(["riscv64-unknown-elf-objcopy", "-O", "binary", "--only-section=.text", e, b])
    a = open(os.path.join(HERE, "_t0.bin"), "rb").read()
    b = open(os.path.join(HERE, "_t8.bin"), "rb").read()
    if len(a) != len(b):
        raise SystemExit("[%s] the two links differ in .text size" % case)
    nonlui = 0
    ndiff = 0
    for i in range(0, len(a), 4):
        wa = struct.unpack_from("<I", a, i)[0]
        wb = struct.unpack_from("<I", b, i)[0]
        if wa != wb:
            ndiff += 1
            if (wa & 0x7F) != 0x37:
                nonlui += 1
    if nonlui:
        raise SystemExit("[%s] links differ in %d NON-LUI word(s)" % (case, nonlui))
    sh(["riscv64-unknown-elf-objcopy", "-O", "binary", "--gap-fill", "0",
        "--pad-to", "0x400", case + ".elf", case + ".bin"])
    img = open(os.path.join(HERE, case + ".bin"), "rb").read()
    assert len(img) == SIZE
    with open(os.path.join(HERE, case + ".hex"), "w") as f:
        for i in range(0, SIZE, 4):
            f.write("%08x\n" % struct.unpack_from("<I", img, i)[0])
    return ndiff


def golden(case):
    log = os.path.join(HERE, case + ".spikelog")
    with open(log, "w") as fh:
        r = subprocess.run(
            ["timeout", "300", "spike", "--isa=rv32i_zifencei",
             "-m0x40000000:0x1000,0x80000000:0x1000", "-l", "--log-commits",
             case + "_spike.elf"], cwd=HERE, stderr=fh, stdout=subprocess.DEVNULL)
    if r.returncode != 0:
        raise SystemExit("[%s] spike exited %d (HTIF tohost never reached?)" % (case, r.returncode))
    mem = bytearray(open(os.path.join(HERE, case + ".bin"), "rb").read())
    gpio = []
    for line in open(log, errors="replace"):
        m = STORE.search(line.rstrip())
        if not m:
            continue
        addr = int(m.group(1), 16)
        vh = m.group(2)
        val = int(vh, 16)
        n = (len(vh) + 1) // 2
        if addr == GPIO_ADDR:
            gpio.append(val)
        elif BASE_SPIKE <= addr < BASE_SPIKE + SIZE:
            off = addr - BASE_SPIKE
            for k in range(n):
                if off + k < SIZE:
                    mem[off + k] = (val >> (8 * k)) & 0xFF
    with open(os.path.join(HERE, "golden_%s_sram.txt" % case), "w") as f:
        for i in range(0, SIZE, 4):
            f.write("%08x\n" % int.from_bytes(mem[i:i + 4], "little"))
    with open(os.path.join(HERE, "golden_%s_gpio.txt" % case), "w") as f:
        for v in gpio:
            f.write("%08x\n" % v)
    return gpio


def make_tb(case, ngpio):
    tpl = open(os.path.join(HERE, "tb_case.v.in")).read()
    txt = tpl.replace("@CASE@", case).replace("@NGPIO@", str(ngpio))
    open(os.path.join(HERE, case + ".v"), "w").write(txt)


def run_tb(case):
    rtl = sorted(f for f in os.listdir(RTL) if f.endswith(".v"))
    r = sh(["iverilog", "-g2012", "-DSERV_CLEAR_RAM", "-o", case + ".vvp",
            case + ".v"] + [os.path.join(RTL, f) for f in rtl])
    if r.returncode:
        raise SystemExit("[%s] iverilog failed:\n%s" % (case, r.stderr[:2000]))
    r = sh(["timeout", "1800", "vvp", case + ".vvp"])
    open(os.path.join(HERE, case + ".simlog"), "w").write(r.stdout + r.stderr)
    return r.returncode, r.stdout.strip().splitlines()


summary = []
results = {}
for c in CASES:
    ndiff = build(c)
    g = golden(c)
    make_tb(c, len(g))
    rc, out = run_tb(c)
    verdict = "PASS" if rc == 0 else "FAIL"
    results[c] = {"verdict": verdict, "gpio_writes": len(g),
                  "link_word_diffs_all_lui": ndiff, "vvp_rc": rc}
    tail = out[-1] if out else ""
    print("%-14s %s  gpio=%-3d  %s" % (c, verdict, len(g), tail))
    summary.append("%s : %s : %s" % (c, verdict, tail))

open(os.path.join(HERE, "summary.txt"), "w").write("\n".join(summary) + "\n")
json.dump(results, open(os.path.join(HERE, "cases_result.json"), "w"), indent=2)
sys.exit(0 if all(v["verdict"] == "PASS" for v in results.values()) else 1)
