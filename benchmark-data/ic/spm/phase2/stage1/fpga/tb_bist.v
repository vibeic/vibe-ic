`timescale 1ns/1ps
`default_nettype none
// BFM for the FPGA BIST harness: drives CLOCK_50 + KEY, watches LEDR.
module tb_bist;
    reg        CLOCK_50 = 0;
    reg  [1:0] KEY;
    wire [9:0] LEDR;

    spm_fpga_bist #(.N(32), .NPAT(64)) uut (.CLOCK_50(CLOCK_50), .KEY(KEY), .LEDR(LEDR));

    always #10 CLOCK_50 = ~CLOCK_50;   // 50 MHz

    integer cyc;
    initial begin
        KEY = 2'b10;          // KEY[0]=0 -> rst_btn active (restart)
        repeat (4) @(posedge CLOCK_50);
        KEY = 2'b11;          // release; BIST runs
        // each pattern ~ (N+4) cycles; 64 patterns -> ~2400 cycles, give margin
        for (cyc = 0; cyc < 5000; cyc = cyc + 1) begin
            @(posedge CLOCK_50);
            if (LEDR[0]) begin   // done
                if (LEDR[1] && !LEDR[2])
                    $display("BIST RESULT: PASS  (done=1 pass=1 fail=0 after %0d cycles, idx=%0d)", cyc, LEDR[8:3]);
                else
                    $display("BIST RESULT: FAIL  (done=%b pass=%b fail=%b)", LEDR[0], LEDR[1], LEDR[2]);
                $finish;
            end
        end
        $display("BIST RESULT: TIMEOUT (done never asserted; done=%b fail=%b)", LEDR[0], LEDR[2]);
        $finish;
    end
endmodule
`default_nettype wire
