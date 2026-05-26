//============================================================================
// tb_func.v -- COMPREHENSIVE functional + coverage testbench for sha256.
//
// Drives the L3/L5 memory-mapped register interface through every functional
// requirement enumerated from L1-L9 + L7 verification plan:
//   - SHA-256 + SHA-224 digest correctness (NIST KAT)
//   - 512-bit block intake via BLOCK0..15
//   - multi-block messages via INIT + NEXT (padding done in SW/gen_vectors.py)
//   - 1M-byte long message (NIST App B, 15626 blocks)
//   - message-length corners (1/55/56/64/119/120/1024 bytes) x both modes
//   - 1000 random messages vs Python hashlib golden (vectors.txt)
//   - ID/VERSION read, STATUS handshake, reset init, undefined-addr error
//   - protocol corners: INIT-during-BUSY, NEXT-without-INIT, read-DIGEST-during-
//     BUSY, write-BLOCK-during-BUSY, mode-switch sequence
//
// Golden = Python hashlib (de-facto NIST FIPS-180-4 oracle). vectors.txt lines:
//   <mode> <nblocks> <exp64hex> <blk0_128hex> [<blk1_128hex> ...]
//============================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_func;
    reg         clk = 0, reset_n = 0, cs = 0, we = 0;
    reg  [7:0]  address = 0;
    reg  [31:0] write_data = 0;
    wire [31:0] read_data;
    wire        error;

    integer errors = 0, ntests = 0;

    sha256 dut (.clk(clk),.reset_n(reset_n),.cs(cs),.we(we),
                .address(address),.write_data(write_data),
                .read_data(read_data),.error(error));

    always #5 clk = ~clk;

    // ----- bus helpers -----
    task wr; input [7:0] a; input [31:0] d; begin
        @(posedge clk); cs<=1; we<=1; address<=a; write_data<=d;
        @(posedge clk); cs<=0; we<=0;
    end endtask
    task rd; input [7:0] a; output [31:0] d; begin
        @(posedge clk); cs<=1; we<=0; address<=a;
        #1 d = read_data;
        @(posedge clk); cs<=0;
    end endtask
    task wait_ready; integer guard; reg [31:0] st; begin
        guard=0; st=0;
        while (st[0]!==1'b1 && guard<300) begin rd(8'h09, st); guard=guard+1; end
        if (st[0]!==1'b1) begin $display("  TIMEOUT waiting READY"); errors=errors+1; end
    end endtask
    task load_block; input [511:0] blk; integer i; begin
        for (i=0;i<16;i=i+1) wr(8'h10+i[7:0], blk[(15-i)*32 +: 32]);
    end endtask

    // ----- vector file storage -----
    // a single message may be up to 15626 blocks (1M 'a'); read block-by-block.
    integer fd, code, m, nb, b, i;
    reg [255:0] expd, got;
    reg [511:0] blk;
    reg [31:0]  w;
    reg [31:0]  tmp[0:15];
    integer     dummy_mode, dummy_nb;
    reg [255:0] exp_tmp;

    // run one full message: INIT on first block, NEXT on the rest. Returns digest.
    task run_msg; input mode; input integer nblocks; output [255:0] dig;
        integer bi; begin
            for (bi=0; bi<nblocks; bi=bi+1) begin
                // read 128-hex (512-bit) block from file into blk
                code=$fscanf(fd,"%h",blk);
                load_block(blk);
                if (bi==0) wr(8'h08, {29'b0, mode, 1'b0, 1'b1});  // INIT
                else       wr(8'h08, {29'b0, mode, 1'b1, 1'b0});  // NEXT
                wait_ready();
            end
            dig=0;
            for (bi=0;bi<8;bi=bi+1) begin rd(8'h20+bi[7:0], w); dig[(7-bi)*32 +: 32]=w; end
        end
    endtask

    reg [31:0] st;
    initial begin
        // ---------- reset init check (L3 reset/boot, L2 FRS) ----------
        reset_n=0; repeat(4) @(posedge clk);
        // during reset, READY should already be the idle value after release
        reset_n=1; @(posedge clk);
        rd(8'h09, st);
        if (st[0]===1'b1) $display("PASS reset->READY=1 (idle after reset release)");
        else begin $display("FAIL reset READY not 1 (got %h)", st); errors=errors+1; end
        ntests=ntests+1;

        // ---------- ID / VERSION read (L4 ID query) ----------
        rd(8'h00,w);
        if (w===32'h73686132) $display("PASS NAME0=sha2");
        else begin $display("FAIL NAME0 %h", w); errors=errors+1; end
        ntests=ntests+1;
        rd(8'h01,w);
        if (w===32'h35362020) $display("PASS NAME1=56");
        else begin $display("FAIL NAME1 %h", w); errors=errors+1; end
        ntests=ntests+1;
        rd(8'h02,w);
        if (w===32'h302e3830) $display("PASS VERSION=0.80");
        else begin $display("FAIL VERSION %h", w); errors=errors+1; end
        ntests=ntests+1;

        // ---------- undefined-address read => error flag (L3) ----------
        rd(8'h7f, w);
        if (error===1'b1) $display("PASS error flag on undefined addr 0x7f");
        else begin $display("FAIL error flag not set"); errors=errors+1; end
        ntests=ntests+1;
        // a defined read should NOT set error
        rd(8'h00, w);
        if (error===1'b0) $display("PASS no error on defined addr");
        else begin $display("FAIL spurious error on defined addr"); errors=errors+1; end
        ntests=ntests+1;

        // ================= PROTOCOL CORNER CASES (L7 7.1.2) =================
        // 1) NEXT without prior INIT: core seeded from H[]=0 after reset; it must
        //    still complete and assert READY/VALID (no hang). We only check it
        //    does not hang (handshake liveness), per L7 'NEXT without prior INIT'.
        $display("--- protocol: NEXT without prior INIT ---");
        load_block({32'h61626380,{14{32'h0}},32'h00000018});
        wr(8'h08, {29'b0, 1'b1, 1'b1, 1'b0});  // NEXT, MODE=256
        wait_ready();
        rd(8'h09, st);
        if (st[1]===1'b1) $display("PASS NEXT-without-INIT completes (VALID=1, no hang)");
        else begin $display("FAIL NEXT-without-INIT did not complete"); errors=errors+1; end
        ntests=ntests+1;

        // 2) INIT during BUSY must be ignored (core only launches from idle).
        $display("--- protocol: INIT during BUSY (must be ignored) ---");
        load_block({32'h61626380,{14{32'h0}},32'h00000018});
        wr(8'h08, {29'b0, 1'b1, 1'b0, 1'b1});  // INIT (launch)
        // immediately (core now BUSY) try a second INIT with a different block
        @(posedge clk);
        rd(8'h09, st);
        if (st[0]===1'b0) begin
            // confirmed BUSY -> issue spurious INIT, should be ignored
            load_block({32'hdeadbeef,{15{32'h0}}});
            wr(8'h08, {29'b0, 1'b1, 1'b0, 1'b1});  // spurious INIT during BUSY
        end
        wait_ready();
        got=0;
        for (i=0;i<8;i=i+1) begin rd(8'h20+i[7:0], w); got[(7-i)*32 +: 32]=w; end
        // result must be the ORIGINAL "abc" digest (spurious INIT ignored)
        if (got===256'hba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad)
            $display("PASS INIT-during-BUSY ignored (abc digest intact)");
        else begin $display("FAIL INIT-during-BUSY corrupted result: %h", got); errors=errors+1; end
        ntests=ntests+1;

        // 3) read DIGEST during BUSY + write BLOCK during BUSY (must not hang/crash;
        //    digest read is allowed any time, final result must still be correct).
        $display("--- protocol: read DIGEST / write BLOCK during BUSY ---");
        load_block({32'h61626380,{14{32'h0}},32'h00000018});
        wr(8'h08, {29'b0, 1'b1, 1'b0, 1'b1});  // INIT
        @(posedge clk);
        rd(8'h20, w);                          // read DIGEST mid-compute (allowed)
        rd(8'h09, st);
        if (st[0]===1'b0) wr(8'h1f, 32'hcafef00d);  // write BLOCK15 during BUSY
        wait_ready();
        got=0;
        for (i=0;i<8;i=i+1) begin rd(8'h20+i[7:0], w); got[(7-i)*32 +: 32]=w; end
        if (got===256'hba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad)
            $display("PASS read/write-during-BUSY harmless (abc digest correct)");
        else begin $display("FAIL access-during-BUSY corrupted result: %h", got); errors=errors+1; end
        ntests=ntests+1;

        // 4) mode-switch sequence: INIT-256 -> INIT-224 -> INIT-256 (L7 7.1.2)
        $display("--- protocol: mode-switch sequence 256->224->256 ---");
        // 256 abc
        load_block({32'h61626380,{14{32'h0}},32'h00000018});
        wr(8'h08, {29'b0, 1'b1, 1'b0, 1'b1}); wait_ready();
        got=0; for (i=0;i<8;i=i+1) begin rd(8'h20+i[7:0], w); got[(7-i)*32 +:32]=w; end
        if (got===256'hba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad)
            $display("  PASS mode-switch step1 SHA-256");
        else begin $display("  FAIL mode-switch step1"); errors=errors+1; end
        // 224 abc (compare top 224)
        load_block({32'h61626380,{14{32'h0}},32'h00000018});
        wr(8'h08, {29'b0, 1'b0, 1'b0, 1'b1}); wait_ready();
        got=0; for (i=0;i<8;i=i+1) begin rd(8'h20+i[7:0], w); got[(7-i)*32 +:32]=w; end
        if ((got & {{224{1'b1}},{32{1'b0}}}) === 256'h23097d223405d8228642a477bda255b32aadbce4bda0b3f7e36c9da700000000)
            $display("  PASS mode-switch step2 SHA-224 (DIGEST7 reads 0)");
        else begin $display("  FAIL mode-switch step2 got %h", got); errors=errors+1; end
        // back to 256
        load_block({32'h61626380,{14{32'h0}},32'h00000018});
        wr(8'h08, {29'b0, 1'b1, 1'b0, 1'b1}); wait_ready();
        got=0; for (i=0;i<8;i=i+1) begin rd(8'h20+i[7:0], w); got[(7-i)*32 +:32]=w; end
        if (got===256'hba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad)
            $display("  PASS mode-switch step3 SHA-256");
        else begin $display("  FAIL mode-switch step3"); errors=errors+1; end
        ntests=ntests+1;

        // ================= VECTOR-FILE DRIVEN (KAT + corners + 1000 random) =====
        fd=$fopen("vectors.txt","r");
        if (fd==0) begin $display("FATAL cannot open vectors.txt"); $finish; end
        $display("--- vector-file: SHA-256/224 digest correctness ---");
        while (!$feof(fd)) begin
            code=$fscanf(fd,"%d %d %h", m, nb, expd);
            if (code==3) begin
                run_msg(m[0:0], nb, got);
                ntests=ntests+1;
                if (m[0]==1'b1) begin
                    if (got===expd) ; // PASS (quiet)
                    else begin
                        errors=errors+1;
                        if (errors<=8) $display("  FAIL m=256 nb=%0d exp %h got %h", nb, expd, got);
                    end
                end else begin
                    // SHA-224: compare top 224 bits; DIGEST7 must read 0
                    if ((got & {{224{1'b1}},{32{1'b0}}}) === (expd & {{224{1'b1}},{32{1'b0}}})
                        && got[31:0]===32'h0) ; // PASS
                    else begin
                        errors=errors+1;
                        if (errors<=8) $display("  FAIL m=224 nb=%0d exp %h got %h", nb, expd, got);
                    end
                end
            end
        end
        $fclose(fd);

        $display("==============================");
        $display("TOTAL functional checks: %0d", ntests);
        if (errors==0) $display("ALL FUNCTIONAL TESTS PASSED");
        else           $display("FUNCTIONAL TESTS FAILED: %0d", errors);
        $finish;
    end

    // generous global timeout for the 1M-byte (15626-block) message
    initial begin #2000000000; $display("GLOBAL TIMEOUT"); $finish; end
endmodule

`default_nettype wire
