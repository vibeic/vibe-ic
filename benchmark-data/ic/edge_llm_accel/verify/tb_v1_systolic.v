// tb_v1_systolic.v — V1 unit-level bit-true golden check of int4_systolic (8x8, ACCW=20).
// RE-VERIFICATION ROUND 2 — against the FIXED full-rate load chain.
//
// Golden model: an independent cycle-accurate software re-implementation (in this TB)
// of the DOCUMENTED PE dataflow (post-fix):
//     on posedge:  if (load_w) { w <= w_in; w_out <= w_in; }   // full-rate load chain
//                  a_out  <= a_in;
//                  ps_out <= ps_in + w*a_in;   (OLD w, OLD ps_in, OLD a_in; 20-bit wrap)
// The golden state is advanced from TB-driven inputs only — it never reads DUT internals.
// DUT ps_bot is compared against the golden bottom row EVERY cycle (=== , catches X).
//
// Also documents the row<->beat orientation empirically:
//   after P=8 load pulses of beats B0..B7: row r holds B[7-r] for ALL r=0..7
//   (full population, complete overwrite of any previous tile).
`timescale 1ns/1ps
module tb_v1_systolic;
    localparam ROWS = 8;
    localparam COLS = 8;
    localparam ACCW = 20;
    localparam K    = 32;          // activation vectors streamed per test
    localparam NTEST = 108;        // >= 100 random + directed extremes

    reg clk = 1'b0;
    reg rst_n;
    reg load_w;
    reg [4*COLS-1:0] w_top;
    reg [4*ROWS-1:0] a_left;
    wire [ACCW*COLS-1:0] ps_bot;

    int4_systolic #(.ROWS(ROWS), .COLS(COLS), .ACCW(ACCW)) dut (
        .clk(clk), .rst_n(rst_n), .load_w(load_w),
        .w_top(w_top), .a_left(a_left), .ps_bot(ps_bot)
    );

    always #5 clk = ~clk;

    // ---------------- golden model state (independent re-implementation) ----------------
    reg signed [3:0]      gw   [0:ROWS-1][0:COLS-1];  // stationary weight regs
    reg signed [3:0]      gwo  [0:ROWS-1][0:COLS-1];  // w_out regs
    reg signed [3:0]      gah  [0:ROWS-1][1:COLS];    // a_out regs (a_h[r][c], c>=1)
    reg signed [ACCW-1:0] gps  [0:ROWS-1][0:COLS-1];  // ps_out regs
    // next-state temporaries
    reg signed [3:0]      ngw  [0:ROWS-1][0:COLS-1];
    reg signed [3:0]      ngwo [0:ROWS-1][0:COLS-1];
    reg signed [3:0]      ngah [0:ROWS-1][1:COLS];
    reg signed [ACCW-1:0] ngps [0:ROWS-1][0:COLS-1];

    integer r, c;
    reg signed [3:0] a_in_v;
    reg signed [ACCW-1:0] ps_in_v;

    reg model_en = 1'b0;

    // advance golden model on every posedge, from TB-driven inputs only
    always @(posedge clk) begin
        if (model_en) begin
            for (r = 0; r < ROWS; r = r + 1) begin
                for (c = 0; c < COLS; c = c + 1) begin
                    // a_in of PE(r,c): left edge for c==0, else registered a_h
                    if (c == 0) a_in_v = a_left[4*r +: 4];
                    else        a_in_v = gah[r][c];
                    // ps_in of PE(r,c): 0 at top edge, else ps_out of row above
                    if (r == 0) ps_in_v = {ACCW{1'b0}};
                    else        ps_in_v = gps[r-1][c];
                    // registers
                    ngps[r][c]   = ps_in_v + gw[r][c] * a_in_v;   // 20-bit wrap
                    ngah[r][c+1] = a_in_v;
                    if (load_w) begin
                        if (r == 0) ngw[r][c] = w_top[4*c +: 4];
                        else        ngw[r][c] = gwo[r-1][c];
                        ngwo[r][c] = ngw[r][c];   // post-fix: w_out <= w_in (full-rate chain)
                    end else begin
                        ngw[r][c]  = gw[r][c];
                        ngwo[r][c] = gwo[r][c];
                    end
                end
            end
            // commit
            for (r = 0; r < ROWS; r = r + 1)
                for (c = 0; c < COLS; c = c + 1) begin
                    gw[r][c]  = ngw[r][c];
                    gwo[r][c] = ngwo[r][c];
                    gps[r][c] = ngps[r][c];
                    gah[r][c+1] = ngah[r][c+1];
                end
        end
    end

    // ---------------- checker: compare DUT ps_bot vs golden every negedge ----------------
    integer n_cmp = 0;
    integer n_bad = 0;
    always @(negedge clk) begin
        if (model_en) begin
            for (c = 0; c < COLS; c = c + 1) begin
                n_cmp = n_cmp + 1;
                if (ps_bot[ACCW*c +: ACCW] !== gps[ROWS-1][c][ACCW-1:0]) begin
                    n_bad = n_bad + 1;
                    if (n_bad <= 20)
                        $display("MISMATCH t=%0t col=%0d dut=%h gold=%h",
                                 $time, c, ps_bot[ACCW*c +: ACCW], gps[ROWS-1][c]);
                end
            end
        end
    end

    // ---------------- stimulus ----------------
    reg [31:0] beatv [0:ROWS-1];   // 8 beats x 32b (8 nibbles) for current tile
    reg [31:0] prevb [0:ROWS-1];
    integer t, p, k, i;
    integer seed = 32'hC0FFEE01;
    integer map_bad;
    reg signed [3:0] expn;

    task load_tile(input integer spaced);  // 8 load pulses; spaced=1 -> 8-cycle cadence like top level
        integer pp, gap;
        begin
            for (pp = 0; pp < ROWS; pp = pp + 1) begin
                if (spaced) begin
                    for (gap = 0; gap < 7; gap = gap + 1) begin
                        @(negedge clk); load_w = 1'b0; w_top = $random(seed);  // w_top don't-care when !load_w
                    end
                end
                @(negedge clk); load_w = 1'b1; w_top = beatv[pp];
            end
            @(negedge clk); load_w = 1'b0;
        end
    endtask

    initial begin
        rst_n = 1'b0; load_w = 1'b0; w_top = 0; a_left = 0;
        // init golden state to reset values
        for (r = 0; r < ROWS; r = r + 1)
            for (c = 0; c < COLS; c = c + 1) begin
                gw[r][c] = 0; gwo[r][c] = 0; gps[r][c] = 0; gah[r][c+1] = 0;
            end
        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        @(negedge clk);
        model_en = 1'b1;

        for (t = 0; t < NTEST; t = t + 1) begin
            // remember previous tile
            for (p = 0; p < ROWS; p = p + 1) prevb[p] = beatv[p];
            // choose tile
            for (p = 0; p < ROWS; p = p + 1) begin
                case (t)
                    0: beatv[p] = {8{p[3:0] + 4'd1}};            // doc tile 1: nibble = beat idx+1
                    1: beatv[p] = {8{p[3:0] + 4'd9}};            // doc tile 2
                    2: beatv[p] = 32'h77777777;                  // all +7
                    3: beatv[p] = 32'h88888888;                  // all -8
                    4: beatv[p] = 32'h78787878;                  // alternating extremes
                    default: beatv[p] = $random(seed);
                endcase
            end
            load_tile((t % 10) == 5);   // every 10th test uses the top-level 8-cycle cadence

            // ---- orientation documentation / analytic check (tests 0 and 1) ----
            if (t == 0 || t == 1) begin
                map_bad = 0;
                for (r = 0; r < ROWS; r = r + 1) begin
                    for (c = 0; c < COLS; c = c + 1) begin
                        expn = beatv[7-r][4*c +: 4];   // post-fix: full-rate, row r <- beat 7-r
                        if (gw[r][c] !== expn) map_bad = map_bad + 1;
                    end
                end
                $display("ORIENT t=%0d : ALL rows r <- beat[7-r] (%s) : %s (%0d bad)",
                         t, (t==0) ? "from reset" : "full overwrite of previous tile",
                         (map_bad == 0) ? "CONFIRMED" : "VIOLATED", map_bad);
                for (r = 0; r < ROWS; r = r + 1)
                    $display("ORIENT t=%0d row%0d w = %h%h%h%h%h%h%h%h", t, r,
                        gw[r][7] & 4'hF, gw[r][6] & 4'hF, gw[r][5] & 4'hF, gw[r][4] & 4'hF,
                        gw[r][3] & 4'hF, gw[r][2] & 4'hF, gw[r][1] & 4'hF, gw[r][0] & 4'hF);
                if (map_bad != 0) n_bad = n_bad + 1;
            end

            // ---- stream K activation vectors ----
            for (k = 0; k < K; k = k + 1) begin
                @(negedge clk);
                case (t)
                    2: a_left = 32'h77777777;
                    3: a_left = 32'h88888888;
                    4: a_left = (k[0]) ? 32'h87878787 : 32'h78787878;
                    default: a_left = $random(seed);
                endcase
            end
            @(negedge clk); a_left = 0;
            repeat (ROWS + COLS + 2) @(negedge clk);   // drain
        end

        $display("V1 RESULT: tests=%0d comparisons=%0d mismatches=%0d -> %s",
                 NTEST, n_cmp, n_bad, (n_bad == 0) ? "PASS" : "FAIL");
        $finish;
    end
endmodule
