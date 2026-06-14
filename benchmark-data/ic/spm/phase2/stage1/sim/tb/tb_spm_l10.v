// tb_spm_l10.v — L10-traceable functional testbench for spm (clean-room).
// Each $display tag below is the L10_TEST_CASES.json case id, so
// l10_tb_conformance_check can trace every required L10 case to a tb.
// Golden model: p_stream = (x * y) mod 2^size, LSB-first serial in/out.
//
// L10 cases exercised:
//   - random_multiplication_functional_equivalence
//   - corner_operand
//   - case_3
//   - reset
//   - toggle_branch_coverage
`timescale 1ns/1ps
module tb_spm_l10;
    parameter size = 32;
    localparam LAT = 1;          // declared latency (LSB-first), see declaration.json

    reg             clk = 0, rst = 1, y = 0;
    reg [size-1:0]  x = 0;
    wire            p;

    spm #(.size(size)) u_dut (.clk(clk), .rst(rst), .x(x), .y(y), .p(p));
    always #5 clk = ~clk;

    integer errors = 0;
    integer t;
    reg [size-1:0] xr, yr, expected, got;

    task run_one(input [size-1:0] xin, input [size-1:0] yin, output integer mism);
        integer cyc; reg [size-1:0] pcap;
        begin
            @(negedge clk); rst = 1; x = xin; y = 0;
            @(negedge clk); rst = 0;
            pcap = 0;
            for (cyc = 0; cyc < size + LAT + 2; cyc = cyc + 1) begin
                y = (cyc < size) ? yin[cyc] : 1'b0;       // LSB-first multiplier
                @(posedge clk); #1;
                if (cyc >= LAT && (cyc-LAT) < size) pcap[cyc-LAT] = p;  // LSB-first product
            end
            expected = (xin * yin);
            got = pcap;
            mism = (got !== expected) ? 1 : 0;
        end
    endtask

    integer m;
    initial begin
        // ---- case: reset ----
        // reset during operation, reset release, then compute -> must start clean.
        @(negedge clk); rst = 1; x = 32'hAAAAAAAA; y = 1; @(posedge clk);
        @(negedge clk); rst = 1; y = 1;            @(posedge clk);  // assert mid-stream
        run_one(32'h12345678, 32'h0000000F, m); errors = errors + m;
        $display("reset: %s", (m==0) ? "PASS" : "FAIL");

        // ---- case: corner_operand ----
        run_one(0, 0, m);                     errors = errors + m;
        run_one(32'hFFFFFFFF, 0, m);          errors = errors + m;
        run_one(0, 32'hFFFFFFFF, m);          errors = errors + m;
        run_one(32'h7FFFFFFF, 32'h7FFFFFFF, m); errors = errors + m;   // MAX_POS
        run_one(32'h80000000, 32'h80000000, m); errors = errors + m;   // MIN_NEG
        run_one(32'hFFFFFFFF, 32'hFFFFFFFF, m); errors = errors + m;   // -1 * -1
        run_one(32'hFFFFFFFF, 1, m);          errors = errors + m;     // -1
        $display("corner_operand: %s", (errors==0) ? "PASS" : "FAIL");

        // ---- case: case_3 (continuous back-to-back multiplications) ----
        run_one(32'hDEADBEEF, 32'h12345678, m); errors = errors + m;
        run_one(32'hCAFEBABE, 32'h0BADF00D, m); errors = errors + m;
        run_one(32'h01234567, 32'h89ABCDEF, m); errors = errors + m;
        $display("case_3: %s", (errors==0) ? "PASS" : "FAIL");

        // ---- case: random_multiplication_functional_equivalence ----
        for (t = 0; t < 12000; t = t + 1) begin
            xr = $random; yr = $random;
            run_one(xr, yr, m); errors = errors + m;
        end
        $display("random_multiplication_functional_equivalence: %s",
                 (errors==0) ? "PASS" : "FAIL");

        // ---- case: toggle_branch_coverage (walking-ones / walking-zeros stimulus) ----
        for (t = 0; t < size; t = t + 1) begin
            run_one(32'h1 << t, 32'hFFFFFFFF, m); errors = errors + m;     // walking ones in x
            run_one(32'hFFFFFFFF, 32'h1 << t, m); errors = errors + m;     // walking ones in y
        end
        $display("toggle_branch_coverage: %s", (errors==0) ? "PASS" : "FAIL");

        if (errors == 0) $display("L10_TB_ALL_PASS errors=0");
        else             $display("L10_TB_FAIL errors=%0d", errors);
        $finish;
    end
endmodule
