// ---------------------------------------------------------------------------
// smoke_tb.v — functional smoke test for edge_llm_matmul_accel
//
// Single fixed tile, M=K=N=16.  Golden vectors are computed IN the testbench
// (an independent reference matmul + requant), then compared bit-exact against
// the DUT result read back over Wishbone.  Exercises the full path:
//   host load weights -> load activations -> config -> START ->
//   poll STATUS.DONE / irq -> read OUT tile.
//
// This is the Phase-2 smoke (elaborate + run end-to-end); a rigorous
// independent golden is a separate later stage.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
`default_nettype none

module smoke_tb;
    // Window bases (match the DUT address decode: adr[17:16] = window).
    localparam [31:0] REG_BASE = 32'h0000_0000;
    localparam [31:0] WGT_BASE = 32'h0001_0000;
    localparam [31:0] ACT_BASE = 32'h0002_0000;
    localparam [31:0] OUT_BASE = 32'h0003_0000;

    // Register offsets.
    localparam [31:0] R_CTRL = 32'h00, R_STATUS = 32'h04, R_M = 32'h08,
                      R_K = 32'h0C, R_N = 32'h10, R_SCALE = 32'h14,
                      R_SHIFT = 32'h18, R_IRQEN = 32'h1C, R_IRQST = 32'h20;

    localparam integer SCALE = 32768;   // Q1.15 = 1.0
    localparam integer SHIFT = 18;      // out = round(acc / 8)

    reg         clk = 1'b0, rst_n = 1'b0, wb_rst = 1'b1;
    reg         stb = 0, cyc = 0, we = 0;
    reg  [3:0]  sel = 4'hF;
    reg  [31:0] adr = 0, dat_i = 0;
    wire        ack;
    wire [31:0] dat_o;
    wire        irq, ready, done;

    always #10 clk = ~clk;   // 50 MHz

    edge_llm_matmul_accel dut (
        .clk(clk), .rst_n(rst_n), .wb_clk_i(clk), .wb_rst_i(wb_rst),
        .wbs_stb_i(stb), .wbs_cyc_i(cyc), .wbs_we_i(we), .wbs_sel_i(sel),
        .wbs_dat_i(dat_i), .wbs_adr_i(adr),
        .wbs_ack_o(ack), .wbs_dat_o(dat_o),
        .irq_o(irq), .status_ready_o(ready), .status_done_o(done)
    );

    // Operand + golden storage.
    integer A [0:15][0:15];      // A[m][k]
    integer W [0:15][0:15];      // W[k][n]
    integer Cref [0:15][0:15];   // expected INT8 output
    reg [31:0] wmem [0:31];      // packed weight words
    reg [31:0] amem [0:31];      // packed activation words

    integer m, k, n, p, L, wi;
    integer acc;
    reg signed [63:0] full;
    reg signed [63:0] shifted;
    integer got, exp_v, errors, byteidx, wordidx, bytepos;
    reg [31:0] rd;

    // -- Wishbone tasks ------------------------------------------------------
    task wb_write(input [31:0] a, input [31:0] d);
    begin
        @(negedge clk); stb=1; cyc=1; we=1; sel=4'hF; adr=a; dat_i=d;
        @(posedge clk);
        while (!ack) @(posedge clk);
        @(negedge clk); stb=0; cyc=0; we=0;
    end
    endtask

    task wb_read(input [31:0] a, output [31:0] d);
    begin
        @(negedge clk); stb=1; cyc=1; we=0; sel=4'hF; adr=a;
        @(posedge clk);
        while (!ack) @(posedge clk);
        d = dat_o;
        @(negedge clk); stb=0; cyc=0;
    end
    endtask

    // -- sign helpers --------------------------------------------------------
    function integer sext4(input [3:0] v);
        sext4 = v[3] ? (v - 16) : v;
    endfunction

    initial begin
        // ---- build operands ------------------------------------------------
        for (m = 0; m < 16; m = m + 1)
            for (k = 0; k < 16; k = k + 1)
                A[m][k] = ((m + k) % 15) - 7;       // [-7,7]
        for (k = 0; k < 16; k = k + 1)
            for (n = 0; n < 16; n = n + 1)
                W[k][n] = ((k*3 + n) % 15) - 7;      // [-7,7]

        // ---- independent reference: C = A*W, then requant ------------------
        for (m = 0; m < 16; m = m + 1)
            for (n = 0; n < 16; n = n + 1) begin
                acc = 0;
                for (k = 0; k < 16; k = k + 1)
                    acc = acc + A[m][k]*W[k][n];
                full    = acc * SCALE + (64'sd1 <<< (SHIFT-1));
                shifted = full >>> SHIFT;
                if (shifted > 127)       Cref[m][n] = 127;
                else if (shifted < -128) Cref[m][n] = -128;
                else                     Cref[m][n] = shifted;
            end

        // ---- pack weight words: W[k][n] at nibble k*16+n -------------------
        for (wi = 0; wi < 32; wi = wi + 1) begin
            wmem[wi] = 32'h0;
            for (p = 0; p < 8; p = p + 1) begin
                L = wi*8 + p; k = L / 16; n = L % 16;
                wmem[wi][p*4 +: 4] = W[k][n][3:0];
            end
        end
        // ---- pack act words: A[m][k] at nibble k*16+m (column-major) -------
        for (wi = 0; wi < 32; wi = wi + 1) begin
            amem[wi] = 32'h0;
            for (p = 0; p < 8; p = p + 1) begin
                L = wi*8 + p; k = L / 16; m = L % 16;
                amem[wi][p*4 +: 4] = A[m][k][3:0];
            end
        end

        // ---- reset ---------------------------------------------------------
        rst_n = 0; wb_rst = 1;
        repeat (4) @(posedge clk);
        @(negedge clk); rst_n = 1; wb_rst = 0;
        repeat (2) @(posedge clk);

        if (ready !== 1'b1) $display("WARN: status_ready not high after reset");

        // ---- load weight + activation tiles --------------------------------
        for (wi = 0; wi < 32; wi = wi + 1) wb_write(WGT_BASE + wi*4, wmem[wi]);
        for (wi = 0; wi < 32; wi = wi + 1) wb_write(ACT_BASE + wi*4, amem[wi]);

        // ---- config --------------------------------------------------------
        wb_write(R_M,     32'd16);
        wb_write(R_K,     32'd16);
        wb_write(R_N,     32'd16);
        wb_write(R_SCALE, SCALE);
        wb_write(R_SHIFT, SHIFT);
        wb_write(R_IRQEN, 32'd1);

        // ---- START ---------------------------------------------------------
        wb_write(R_CTRL, 32'd1);

        // ---- poll STATUS.DONE ----------------------------------------------
        rd = 0;
        for (p = 0; p < 2000 && rd[1] == 1'b0; p = p + 1)
            wb_read(R_STATUS, rd);
        if (rd[1] !== 1'b1) begin
            $display("FAIL: DONE never asserted (STATUS=0x%08x)", rd);
            $finish;
        end
        $display("INFO: compute DONE after %0d status polls; irq_o=%b done_pin=%b",
                 p, irq, done);

        // ---- read back OUT tile + compare ----------------------------------
        errors = 0;
        for (m = 0; m < 16; m = m + 1)
            for (n = 0; n < 16; n = n + 1) begin
                byteidx = m*16 + n;
                wordidx = byteidx / 4;
                bytepos = byteidx % 4;
                wb_read(OUT_BASE + wordidx*4, rd);
                got   = $signed(rd[bytepos*8 +: 8]);   // signed INT8 byte
                exp_v = Cref[m][n];
                if (got !== exp_v) begin
                    errors = errors + 1;
                    if (errors <= 8)
                        $display("  MISMATCH C[%0d][%0d]: got=%0d exp=%0d",
                                 m, n, got, exp_v);
                end
            end

        // ---- spot-print a few reference results ----------------------------
        $display("INFO: reference C[0][0]=%0d  C[1][2]=%0d  C[15][15]=%0d",
                 Cref[0][0], Cref[1][2], Cref[15][15]);

        if (errors == 0)
            $display("SMOKE PASS: all 256 outputs match reference (start->done->read OK)");
        else
            $display("SMOKE FAIL: %0d / 256 outputs mismatched", errors);
        $finish;
    end

    // watchdog
    initial begin
        #2_000_000;
        $display("FAIL: global timeout");
        $finish;
    end
endmodule

`default_nettype wire
