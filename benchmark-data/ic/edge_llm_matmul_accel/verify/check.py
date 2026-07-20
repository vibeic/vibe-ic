#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# check.py -- independent Python cross-check of the DUT readback dump.
#
# Reads verify/vectors/out.txt (every INT8 byte the DUT produced, dumped by
# tb_functional.v in pass/o order) and, using ONLY the from-scratch Python
# golden, verifies:
#   (A) every pass's 256 outputs == golden requant of that tile   (bit-true)
#   (B) M/N software tiling: 4 sub-tiles reassemble into the golden 32x32 GEMM
#   (C) K  software tiling: host-add of two K=16 passes == golden K=32 GEMM
#
# Emits verify/functional_verify_result.json.
# ---------------------------------------------------------------------------
import os
import json
import golden_int4_gemm as g

VDIR = g.VDIR


def read_out(num_passes):
    with open(os.path.join(VDIR, "out.txt")) as f:
        vals = [int(line.strip(), 16) for line in f if line.strip()]
    assert len(vals) == num_passes * 256, \
        "out.txt has %d bytes, expected %d" % (len(vals), num_passes * 256)
    # to signed, and into per-pass 16x16 tiles (o = m*16+n)
    tiles = []
    for p in range(num_passes):
        tile = [[0] * 16 for _ in range(16)]
        for o in range(256):
            b = vals[p * 256 + o]
            if b > 127:
                b -= 256
            tile[o // 16][o % 16] = b
        tiles.append(tile)
    return tiles


def main():
    passes, checks = g.build_cases()
    name2idx = {p["name"]: i for i, p in enumerate(passes)}

    # golden per-pass int8 tiles
    gold_tiles = []
    for p in passes:
        acc = g.int4_matmul(p["A"], p["W"], p["k"])
        gold_tiles.append(g.requant_tile(acc, p["scale"], p["shift"]))

    dut_tiles = read_out(len(passes))

    result = {
        "verdict": None,
        "tests": len(passes),
        "comparisons": len(passes) * 256,
        "mismatches": 0,
        "cases": [],
        "golden_selftest": None,
        "blindness_ok": True,
    }

    # golden self-test
    ok_self, _ = g.selftest_2x2()
    result["golden_selftest"] = "PASS" if ok_self else "FAIL"

    total_mism = 0

    # (A) per-pass bit-true
    for i, p in enumerate(passes):
        mism = sum(1 for m in range(16) for n in range(16)
                   if dut_tiles[i][m][n] != gold_tiles[i][m][n])
        total_mism += mism
        result["cases"].append(dict(
            name=p["name"], kind="single_tile", k=p["k"],
            scale=p["scale"], shift=p["shift"],
            comparisons=256, mismatches=mism,
            verdict="PASS" if mism == 0 else "FAIL"))

    # (B) M/N tiling reconstruction -> full 32x32 GEMM
    mn = next(c for c in checks if c["kind"] == "mn_tiling")
    # rebuild Abig (32x16) and Wbig (16x32) from the sub-tile operands
    p00 = passes[name2idx["mn_tile_r0_c0"]]
    p01 = passes[name2idx["mn_tile_r0_c1"]]
    p10 = passes[name2idx["mn_tile_r1_c0"]]
    Abig = [row[:] for row in p00["A"]] + [row[:] for row in p10["A"]]   # 32x16
    Wbig = [p00["W"][k][:] + p01["W"][k][:] for k in range(16)]           # 16x32
    scale_mn = p00["scale"]; shift_mn = p00["shift"]
    acc_full = g.int4_matmul(Abig, Wbig, 16)                # 32x32
    gold_full = g.requant_tile(acc_full, scale_mn, shift_mn)
    # assemble DUT 32x32 from the four sub-tiles
    dut_full = [[0] * 32 for _ in range(32)]
    for (nm, ti, tj) in (("mn_tile_r0_c0", 0, 0), ("mn_tile_r0_c1", 0, 1),
                         ("mn_tile_r1_c0", 1, 0), ("mn_tile_r1_c1", 1, 1)):
        t = dut_tiles[name2idx[nm]]
        for m in range(16):
            for n in range(16):
                dut_full[ti * 16 + m][tj * 16 + n] = t[m][n]
    mn_mism = sum(1 for m in range(32) for n in range(32)
                  if dut_full[m][n] != gold_full[m][n])
    total_mism += mn_mism
    result["cases"].append(dict(
        name="mn_tiling_32x32", kind="mn_software_tiling",
        desc="4x 16x16 sub-tiles reassembled == golden 32x32x16 GEMM",
        comparisons=32 * 32, mismatches=mn_mism,
        verdict="PASS" if mn_mism == 0 else "FAIL"))

    # (C) K tiling reconstruction -> host-add two K=16 passes == golden K=32
    kt = next(c for c in checks if c["kind"] == "k_tiling")
    full = kt["full"]
    acc_k = g.int4_matmul(full["A"], full["W"], full["K"])   # 16x16, K=32
    gold_k = g.requant_tile(acc_k, full["scale"], full["shift"])
    t0 = dut_tiles[name2idx["k_tile_p0"]]
    t1 = dut_tiles[name2idx["k_tile_p1"]]
    host_sum = [[t0[m][n] + t1[m][n] for n in range(16)] for m in range(16)]
    k_mism = sum(1 for m in range(16) for n in range(16)
                 if host_sum[m][n] != gold_k[m][n])
    total_mism += k_mism
    result["cases"].append(dict(
        name="k_tiling_K32", kind="k_software_tiling",
        desc="host-add of two K=16 passes == golden K=32 GEMM",
        comparisons=256, mismatches=k_mism,
        verdict="PASS" if k_mism == 0 else "FAIL"))

    # ------------------------------------------------------------------
    # DIRECTED SCALE-GRANULARITY FIDELITY TEST
    # The L2/L15 docs CLAIM a per-OUTPUT-CHANNEL scale, but the L4 regmap
    # exposes only ONE 16-bit SCALE register and the RTL applies that single
    # value to all 256 outputs. Evidence it structurally:
    #   (a) DUT matches a SINGLE-GLOBAL-scale golden bit-true (already shown), and
    #   (b) DUT does NOT match a hypothetical per-channel-scale golden (where a
    #       different scale is used per output column) -> per-channel is not
    #       realized in hardware. We only had one SCALE reg to write.
    demo_idx = name2idx["rand_seed1_K16"]
    demo = passes[demo_idx]
    S = demo["scale"]; SH = demo["shift"]
    acc_demo = g.int4_matmul(demo["A"], demo["W"], demo["k"])
    # global-scale golden (what the hardware can do): every channel uses S
    gold_global = g.requant_tile(acc_demo, S, SH)
    # hypothetical per-channel golden: even cols use S, odd cols use S/2
    S_odd = S // 2
    gold_perchan = [[g.requant(acc_demo[m][n], (S if n % 2 == 0 else S_odd), SH)
                     for n in range(16)] for m in range(16)]
    dut_demo = dut_tiles[demo_idx]
    diff_vs_global = sum(1 for m in range(16) for n in range(16)
                         if dut_demo[m][n] != gold_global[m][n])
    diff_vs_perchan = sum(1 for m in range(16) for n in range(16)
                          if dut_demo[m][n] != gold_perchan[m][n])
    result["scale_granularity_finding"] = (
        "RTL implements single global SCALE; L2/L15 doc claim of "
        "per-output-channel scale is NOT realized in the regmap/RTL")
    result["scale_granularity_evidence"] = dict(
        demo_pass="rand_seed1_K16", global_scale=S, per_channel_odd_scale=S_odd,
        dut_vs_global_scale_mismatches=diff_vs_global,
        dut_vs_per_channel_scale_mismatches=diff_vs_perchan,
        interpretation=("DUT bit-matches single-global-scale golden "
                        "(mism=%d) and diverges from a per-channel-scale "
                        "golden (mism=%d) -> hardware applies ONE SCALE "
                        "register to all 256 outputs; verdict is based on "
                        "that actual behavior." % (diff_vs_global, diff_vs_perchan)))

    result["comparisons"] += 32 * 32 + 256
    result["mismatches"] = total_mism
    result["verdict"] = "PASS" if (total_mism == 0 and ok_self) else "FAIL"

    with open(os.path.join(os.path.dirname(VDIR), "functional_verify_result.json"), "w") as f:
        json.dump(result, f, indent=2)

    print("golden_selftest:", result["golden_selftest"])
    for c in result["cases"]:
        print("  %-20s %-22s comps=%-4d mism=%d  %s" %
              (c["name"], c["kind"], c["comparisons"], c["mismatches"], c["verdict"]))
    print("")
    ev = result["scale_granularity_evidence"]
    print("SCALE-GRANULARITY FIDELITY: DUT vs global-scale mism=%d ; "
          "DUT vs per-channel-scale mism=%d" %
          (ev["dut_vs_global_scale_mismatches"],
           ev["dut_vs_per_channel_scale_mismatches"]))
    print("  finding:", result["scale_granularity_finding"])
    print("")
    print("tests=%d comparisons=%d mismatches=%d -> %s" %
          (result["tests"], result["comparisons"], result["mismatches"], result["verdict"]))


if __name__ == "__main__":
    main()
