// tb_bist.v -- pre-silicon sim of the on-FPGA BIST harness sha256_bist_top.
// Confirms the BIST FSM drives the register interface, reads back the digest,
// and asserts LEDR[0]=PASS before we spend a real Quartus compile.
`timescale 1ns/1ps
`default_nettype none
module tb_bist;
    reg CLOCK_50=0; reg [1:0] KEY=2'b00;
    wire [9:0] LEDR;
    sha256_bist_top uut(.CLOCK_50(CLOCK_50),.KEY(KEY),.LEDR(LEDR));
    always #10 CLOCK_50=~CLOCK_50;   // 50 MHz
    initial begin
        KEY[0]=0; repeat(5) @(posedge CLOCK_50); KEY[0]=1;  // release active-LOW reset
        // wait for TEST_DONE
        wait(LEDR[1]===1'b1);
        @(posedge CLOCK_50);
        if (LEDR[0]===1'b1) $display("BIST RESULT: PASS (LEDR[0]=1, digest==golden)");
        else                $display("BIST RESULT: FAIL (LEDR[0]=0)");
        repeat(4) @(posedge CLOCK_50);
        $finish;
    end
    initial begin #500000; $display("BIST TIMEOUT (DONE never asserted)"); $finish; end
endmodule
`default_nettype wire
