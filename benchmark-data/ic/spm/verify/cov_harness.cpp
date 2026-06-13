// Verilator coverage harness for spm.v (Pillar 3 — code coverage).
// Drives the SAME stimulus families the functional TBs use (golden vectors +
// directed/corner/reset), so the measured line+toggle coverage reflects the
// real functional verification, then writes coverage.dat for verilator_coverage.
#include "Vspm.h"
#include "verilated.h"
#include "verilated_cov.h"
#include <cstdio>
#include <cstdint>
#include <cstdlib>

static Vspm* dut;

static void tick() {
    dut->clk = 0; dut->eval();
    dut->clk = 1; dut->eval();
}

// run one N=32 multiply with a 1-cycle sync reset; return reassembled product
static uint32_t run_mul(uint32_t x, uint32_t y) {
    // sync reset
    dut->rst = 1; dut->x = x; dut->y = 0; tick();
    dut->rst = 0;
    uint32_t got = 0;
    for (int k = 0; k < 32; k++) {
        dut->y = (y >> k) & 1u;
        tick();
        got |= ((uint32_t)(dut->p & 1u)) << k;
    }
    return got;
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    dut = new Vspm;

    // --- golden vectors ---
    FILE* f = fopen("../phase2/stage1/sim/vectors.hex", "r");
    long nvec = 0, errors = 0;
    if (f) {
        unsigned int vx, vy, vp;
        while (fscanf(f, "%x %x %x", &vx, &vy, &vp) == 3) {
            uint32_t got = run_mul(vx, vy);
            if (got != (uint32_t)vp) errors++;
            nvec++;
        }
        fclose(f);
    }

    // --- directed / corner operands (exercise all-0, all-1, MSB-set toggles) ---
    uint32_t corner[] = {0x00000000u, 0xFFFFFFFFu, 0x7FFFFFFFu, 0x80000000u,
                         0x00000001u, 0xAAAAAAAAu, 0x55555555u, 0xDEADBEEFu};
    for (unsigned a = 0; a < sizeof(corner)/sizeof(corner[0]); a++)
        for (unsigned b = 0; b < sizeof(corner)/sizeof(corner[0]); b++) {
            uint32_t got = run_mul(corner[a], corner[b]);
            uint32_t exp = (uint32_t)((uint64_t)corner[a] * (uint64_t)corner[b]);
            if (got != exp) errors++;
        }

    // --- reset held high for several cycles (exercise the rst branch) ---
    dut->rst = 1; dut->x = 0xFFFFFFFFu; dut->y = 1;
    for (int i = 0; i < 4; i++) tick();
    dut->rst = 0;

    // --- mid-computation reset ---
    dut->rst = 1; dut->x = 0x12345678u; dut->y = 0; tick();
    dut->rst = 0;
    for (int k = 0; k < 8; k++) { dut->y = (0x6789ABCDu >> k) & 1u; tick(); }
    dut->rst = 1; tick();           // mid-stream reset
    dut->rst = 0;
    run_mul(0x12345678u, 0x6789ABCDu);

    dut->final();
    VerilatedCov::write("coverage.dat");
    printf("HARNESS: nvec=%ld errors=%ld\n", nvec, errors);
    delete dut;
    return errors == 0 ? 0 : 1;
}
