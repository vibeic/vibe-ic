`timescale 1ns/1ps
`default_nettype none
// Overrun test: transmitter word is LONGER than receiver WORD_WIDTH.
// Per L8/L3 spec, receiver keeps the MSB-aligned WORD_WIDTH bits and
// IGNORES the extra trailing LSBs. With WORD_WIDTH=8 and a 12-bit TX word
// 0xABC (1010_1011_1100), receiver should capture the first 8 bits MSB-first
// = 1010_1011 = 0xAB (extra 4 LSBs 1100 ignored).
module tb_ovr;
  localparam W=8;
  reg clk,rst_n,sck,ws,sd; integer i,errors;
  wire [W-1:0] ld,rd; wire lv,rv; reg [W-1:0] gl; reg glv;
  localparam SCK_HALF=100;
  i2s_rx #(.WORD_WIDTH(W)) dut(.clk(clk),.rst_n(rst_n),.SCK(sck),.WS(ws),.SD(sd),
    .left_data(ld),.right_data(rd),.left_valid(lv),.right_valid(rv));
  initial clk=0; always #5 clk=~clk;
  always @(posedge clk) if(lv) begin gl<=ld; glv<=1; end
  task sbit(input b); begin sd=b; #(SCK_HALF) sck=1; #(SCK_HALF) sck=0; end endtask
  reg [11:0] tx;
  initial begin
    errors=0; glv=0; gl=0; tx=12'hABC;
    sck=0; ws=1; sd=0; rst_n=0; #50 rst_n=1; #50;
    // prime opposite channel, then WS->0 edge re-arms for LEFT
    ws=1; sbit(0); sbit(0);
    ws=0; sbit(0);            // re-arm LEFT
    ws=0;
    for(i=11;i>=0;i=i-1) sbit(tx[i]);   // 12-bit TX word (overrun for 8-bit RX)
    ws=1; sbit(0);           // WS edge publishes LEFT
    #400;
    if(!glv) begin $display("FAIL: no left_valid"); errors=errors+1; end
    else if(gl!==8'hAB) begin $display("FAIL: got %h expected ab (overrun MSB-align)",gl); errors=errors+1; end
    else $display("OK  : overrun left=%h (expected ab, extra LSBs ignored)",gl);
    if(errors==0) $display("OVERRUN TB PASS"); else $display("OVERRUN TB FAIL");
    $finish;
  end
  initial begin #2000000 $display("FAIL timeout"); $finish; end
endmodule
`default_nettype wire
