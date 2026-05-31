// =====================================================================
// tb_sent_rx_crcerr — self-checking testbench: CRC-error conformance.
//   Drives a SENT frame with a DELIBERATELY WRONG CRC nibble and checks
//   that the receiver still completes the frame (frame_valid=1) but
//   FLAGS the error (crc_ok=0).  This is the L3/L9 error-detection rule:
//   "recompute the CRC-4 over the data nibbles and compare; flag a frame
//   error on mismatch."  Tool substitution: iverilog 12 + vvp for VCS.
// =====================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_sent_rx_crcerr;

    localparam integer NUM_DATA = 6;
    localparam integer PERIOD_W = 16;
    localparam integer TICK_CLK = 20;
    localparam integer MIN_LOW  = 5;

    reg  clk = 1'b0, rst_n = 1'b0, sent_in = 1'b1;
    wire [4*NUM_DATA-1:0] data_nibbles;
    wire [3:0]            status_nibble;
    wire                  crc_ok, frame_valid;

    sent_rx #(.NUM_DATA_NIBBLES(NUM_DATA), .PERIOD_W(PERIOD_W)) dut (
        .clk(clk), .rst_n(rst_n), .sent_in(sent_in),
        .data_nibbles(data_nibbles), .status_nibble(status_nibble),
        .crc_ok(crc_ok), .frame_valid(frame_valid)
    );

    always #5 clk = ~clk;

    function [3:0] crc4_step;
        input [3:0] c; input [3:0] d; reg [3:0] i;
        begin
            i = c ^ d;
            case (i)
                4'd0:crc4_step=4'd0;4'd1:crc4_step=4'd13;4'd2:crc4_step=4'd7;4'd3:crc4_step=4'd10;
                4'd4:crc4_step=4'd14;4'd5:crc4_step=4'd3;4'd6:crc4_step=4'd9;4'd7:crc4_step=4'd4;
                4'd8:crc4_step=4'd1;4'd9:crc4_step=4'd12;4'd10:crc4_step=4'd6;4'd11:crc4_step=4'd11;
                4'd12:crc4_step=4'd15;4'd13:crc4_step=4'd2;4'd14:crc4_step=4'd8;default:crc4_step=4'd5;
            endcase
        end
    endfunction

    task emit_pulse;
        input integer ticks; integer low_clks, high_clks, k;
        begin
            low_clks  = MIN_LOW * TICK_CLK;
            high_clks = (ticks - MIN_LOW) * TICK_CLK;
            sent_in = 1'b0;
            for (k=0;k<low_clks;k=k+1)  @(posedge clk);
            sent_in = 1'b1;
            for (k=0;k<high_clks;k=k+1) @(posedge clk);
        end
    endtask
    task emit_nibble; input [3:0] v; begin emit_pulse(12 + v); end endtask
    task emit_cal;                   begin emit_pulse(56);     end endtask

    integer n;
    reg [3:0] data_q [0:NUM_DATA-1];
    reg [3:0] crc_calc, crc_bad, status_v;

    // Concurrent capture of the 1-clk frame_valid pulse + outputs.
    reg got_frame; reg cap_crc_ok;
    initial got_frame = 1'b0;
    always @(posedge clk)
        if (frame_valid && !got_frame) begin got_frame <= 1'b1; cap_crc_ok <= crc_ok; end

    initial begin
        $dumpfile("tb_sent_rx_crcerr.vcd"); $dumpvars(0, tb_sent_rx_crcerr);

        data_q[0]=4'h1; data_q[1]=4'h2; data_q[2]=4'h3;
        data_q[3]=4'h4; data_q[4]=4'h5; data_q[5]=4'h6;
        status_v = 4'hA;

        crc_calc = 4'd5;
        for (n=0;n<NUM_DATA;n=n+1) crc_calc = crc4_step(crc_calc, data_q[n]);
        crc_bad = crc_calc ^ 4'h1;            // corrupt by one bit (guaranteed != correct)

        repeat (10) @(posedge clk); rst_n = 1'b1; repeat (5) @(posedge clk);

        emit_cal();
        emit_nibble(status_v);
        for (n=0;n<NUM_DATA;n=n+1) emit_nibble(data_q[n]);
        emit_nibble(crc_bad);                 // WRONG crc
        emit_cal();                           // close CRC period

        n = 0;
        while (got_frame !== 1'b1 && n < 200000) begin @(posedge clk); n=n+1; end
        if (got_frame !== 1'b1) begin
            $display("CRCERR TB FAIL: frame_valid never asserted"); $finish;
        end
        $display("frame_valid=1  crc_ok=%b (expect 0)  crc_calc=%h crc_bad=%h",
                 cap_crc_ok, crc_calc, crc_bad);
        if (cap_crc_ok !== 1'b0) begin
            $display("CRCERR TB FAIL: crc_ok=%b expected 0 on corrupted CRC", cap_crc_ok);
            $finish;
        end
        $display("CRCERR TB PASS  (corrupted CRC %h vs correct %h -> crc_ok=0)",
                 crc_bad, crc_calc);
        $finish;
    end

    initial begin #50_000_000 $display("CRCERR TB FAIL: global timeout"); $finish; end

endmodule

`default_nettype wire
