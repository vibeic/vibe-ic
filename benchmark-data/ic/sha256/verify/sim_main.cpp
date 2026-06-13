// sim_main.cpp -- Verilator C++ harness driving the sha256 register interface
// for CODE-COVERAGE (line + toggle). Reuses the same functional sequences as
// tb_func.v: ID/version, reset, error, KAT, SHA-224 (incl DIGEST7=0),
// multi-block, protocol corners (INIT-during-BUSY, NEXT-without-INIT,
// read/write-during-BUSY, mode-switch), plus a batch of random vectors from
// vectors.txt to exercise the datapath broadly.
#include "Vsha256.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

static Vsha256* dut;
static vluint64_t main_time = 0;

static void tick() {
    dut->clk = 0; dut->eval(); main_time++;
    dut->clk = 1; dut->eval(); main_time++;
}

// bus write: one transaction (cs/we high for one cycle), matching tb wr task
static void bus_wr(uint8_t a, uint32_t d) {
    dut->cs = 1; dut->we = 1; dut->address = a; dut->write_data = d;
    tick();
    dut->cs = 0; dut->we = 0;
    tick();
}
static uint32_t bus_rd(uint8_t a) {
    dut->cs = 1; dut->we = 0; dut->address = a;
    dut->clk = 0; dut->eval(); main_time++;
    dut->clk = 1; dut->eval(); main_time++;  // combinational read settles
    uint32_t v = dut->read_data;
    dut->cs = 0; tick();
    return v;
}
static void wait_ready() {
    for (int g = 0; g < 400; g++) {
        if (bus_rd(0x09) & 0x1) return;
    }
    fprintf(stderr, "TIMEOUT waiting READY\n");
}
// load one 512-bit block from 16 words (word[0] -> BLOCK0 = MSW)
static void load_block(const uint32_t w[16]) {
    for (int i = 0; i < 16; i++) bus_wr(0x10 + i, w[i]);
}

static int errors = 0, ntests = 0;

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    dut = new Vsha256;

    // ---- reset (sync active-LOW) ----
    dut->reset_n = 0; dut->cs = 0; dut->we = 0;
    for (int i = 0; i < 4; i++) tick();
    dut->reset_n = 1; tick();

    // reset -> READY=1
    ntests++; if (!(bus_rd(0x09) & 0x1)) { errors++; fprintf(stderr,"FAIL reset READY\n"); }
    // ID / version
    ntests++; if (bus_rd(0x00) != 0x73686132u) errors++;
    ntests++; if (bus_rd(0x01) != 0x35362020u) errors++;
    ntests++; if (bus_rd(0x02) != 0x302e3830u) errors++;
    // undefined-addr error flag
    dut->cs = 1; dut->we = 0; dut->address = 0x7f; dut->eval();
    ntests++; if (!dut->error) { errors++; fprintf(stderr,"FAIL error flag\n"); }
    dut->cs = 0; dut->eval();
    // CTRL readback path (exercise read_data CTRL case)
    bus_wr(0x08, 0x4); // MODE=1 only, no init/next launch from idle? init/next 0 -> no launch
    (void)bus_rd(0x08);

    // ---- KAT abc SHA-256 ----
    {
        uint32_t blk[16] = {0x61626380,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0x18};
        load_block(blk);
        bus_wr(0x08, 0x5); // MODE=1 INIT
        wait_ready();
        uint32_t d0 = bus_rd(0x20);
        ntests++; if (d0 != 0xba7816bfu) { errors++; fprintf(stderr,"FAIL abc-256 d0=%08x\n",d0); }
    }
    // ---- empty SHA-256 ----
    {
        uint32_t blk[16] = {0x80000000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0};
        load_block(blk);
        bus_wr(0x08, 0x5);
        wait_ready();
        ntests++; if (bus_rd(0x20) != 0xe3b0c442u) errors++;
    }
    // ---- abc SHA-224 (MODE=0): check DIGEST7 reads 0 ----
    {
        uint32_t blk[16] = {0x61626380,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0x18};
        load_block(blk);
        bus_wr(0x08, 0x1); // MODE=0 INIT
        wait_ready();
        uint32_t d0 = bus_rd(0x20);
        uint32_t d7 = bus_rd(0x27);
        ntests++; if (d0 != 0x23097d22u || d7 != 0x0u) { errors++; fprintf(stderr,"FAIL abc-224 d0=%08x d7=%08x\n",d0,d7); }
    }
    // ---- multi-block (INIT + NEXT) SHA-256 ----
    {
        uint32_t b0[16] = {0x61626364,0x62636465,0x63646566,0x64656667,
                           0x65666768,0x66676869,0x6768696a,0x68696a6b,
                           0x696a6b6c,0x6a6b6c6d,0x6b6c6d6e,0x6c6d6e6f,
                           0x6d6e6f70,0x6e6f7071,0x80000000,0x00000000};
        uint32_t b1[16] = {0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0x1c0};
        load_block(b0); bus_wr(0x08,0x5); wait_ready();   // INIT
        load_block(b1); bus_wr(0x08,0x6); wait_ready();   // NEXT
        ntests++; if (bus_rd(0x20) != 0x248d6a61u) errors++;
    }
    // ---- protocol: NEXT without prior INIT (after a fresh reset) ----
    {
        dut->reset_n = 0; for(int i=0;i<3;i++) tick(); dut->reset_n=1; tick();
        uint32_t blk[16] = {0x61626380,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0x18};
        load_block(blk); bus_wr(0x08,0x6); wait_ready();  // NEXT, no INIT
        ntests++; if (!(bus_rd(0x09) & 0x2)) errors++;     // VALID asserted
    }
    // ---- protocol: INIT during BUSY ignored ----
    {
        uint32_t blk[16] = {0x61626380,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0x18};
        load_block(blk); bus_wr(0x08,0x5);                 // INIT launch
        tick();
        if (!(bus_rd(0x09)&0x1)) {                          // BUSY
            uint32_t junk[16]={0xdeadbeef,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0};
            load_block(junk); bus_wr(0x08,0x5);            // spurious INIT (ignored)
        }
        wait_ready();
        ntests++; if (bus_rd(0x20) != 0xba7816bfu) { errors++; fprintf(stderr,"FAIL INIT-busy\n"); }
    }
    // ---- random vectors from vectors.txt (single-block subset for toggle) ----
    {
        FILE* f = fopen("vectors.txt","r");
        if (f) {
            char line[200000];
            int driven = 0;
            while (fgets(line, sizeof(line), f) && driven < 300) {
                int mode, nb;
                char* p = line;
                if (sscanf(p, "%d %d", &mode, &nb) != 2) continue;
                if (nb != 1) continue;  // only single-block for the coverage batch
                // skip mode, nb, exp(64 hex) -> get to block hex
                // tokens: mode nb exp blk0
                // advance past 3 whitespace-separated tokens
                char m_s[32], nb_s[32], exp_s[80], blk_s[200];
                if (sscanf(line, "%31s %31s %79s %199s", m_s, nb_s, exp_s, blk_s) != 4) continue;
                // parse 128-hex block string into 16 words
                uint32_t w[16];
                for (int i = 0; i < 16; i++) {
                    char wbuf[9]; memcpy(wbuf, blk_s + i*8, 8); wbuf[8]=0;
                    w[i] = (uint32_t)strtoul(wbuf, nullptr, 16);
                }
                load_block(w);
                bus_wr(0x08, mode ? 0x5 : 0x1);
                wait_ready();
                // compare top word vs exp (first 8 hex chars of exp_s)
                char ebuf[9]; memcpy(ebuf, exp_s, 8); ebuf[8]=0;
                uint32_t e0 = (uint32_t)strtoul(ebuf, nullptr, 16);
                uint32_t d0 = bus_rd(0x20);
                ntests++;
                if (d0 != e0) { errors++; if (errors<=5) fprintf(stderr,"FAIL rand mode=%d d0=%08x e0=%08x\n",mode,d0,e0); }
                driven++;
            }
            fclose(f);
            fprintf(stderr, "drove %d random single-block vectors\n", driven);
        } else {
            fprintf(stderr, "WARN vectors.txt not found, skipping random batch\n");
        }
    }

    dut->final();
#if VM_COVERAGE
    Verilated::mkdir("logs");
    VerilatedCov::write("logs/coverage.dat");
#endif
    delete dut;
    printf("VERILATOR HARNESS: tests=%d errors=%d\n", ntests, errors);
    return errors ? 1 : 0;
}
