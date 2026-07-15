`timescale 1ns/1ps
module tb_selfverify;
  reg clk=0; reg reset_n=0; reg cs=0; reg we=0;
  reg [7:0] address=0; reg [31:0] write_data=0;
  wire [31:0] read_data; wire error;
  integer errors=0;
  sha256 dut(.clk(clk),.reset_n(reset_n),.cs(cs),.we(we),
      .address(address),.write_data(write_data),.read_data(read_data),.error(error));
  always #5 clk=~clk;
  task wr; input [7:0] a; input [31:0] d; begin
    @(posedge clk); cs<=1; we<=1; address<=a; write_data<=d;
    @(posedge clk); cs<=0; we<=0; end endtask
  task rd_chk; input [7:0] a; input [31:0] exp; input [127:0] nm; begin
    @(posedge clk); cs<=1; we<=0; address<=a;
    @(posedge clk); cs<=0; @(posedge clk);
    if (read_data!==exp) begin errors=errors+1;
      $display("MISMATCH %0s addr=%02x got=%08x exp=%08x",nm,a,read_data,exp); end
    else $display("OK       %0s addr=%02x val=%08x",nm,a,read_data); end endtask
  task wait_ready; integer k; begin k=0;
    @(posedge clk); cs<=1; we<=0; address<=8'h09;
    forever begin @(posedge clk);
      if (read_data[0]==1'b1 && k>2) begin cs<=0; disable wait_ready; end
      k=k+1; if (k>200) begin $display("TIMEOUT waiting ready"); errors=errors+1; cs<=0; disable wait_ready; end
    end end endtask
  integer i;
  initial begin
    reset_n=0; repeat(4) @(posedge clk); reset_n=1; @(posedge clk);
    // ---- abc_256 : 1 block(s) ----
    wr(8'h10, 32'h61626380);
    wr(8'h11, 32'h00000000);
    wr(8'h12, 32'h00000000);
    wr(8'h13, 32'h00000000);
    wr(8'h14, 32'h00000000);
    wr(8'h15, 32'h00000000);
    wr(8'h16, 32'h00000000);
    wr(8'h17, 32'h00000000);
    wr(8'h18, 32'h00000000);
    wr(8'h19, 32'h00000000);
    wr(8'h1a, 32'h00000000);
    wr(8'h1b, 32'h00000000);
    wr(8'h1c, 32'h00000000);
    wr(8'h1d, 32'h00000000);
    wr(8'h1e, 32'h00000000);
    wr(8'h1f, 32'h00000018);
    wr(8'h08, 32'h00000005);
    wait_ready;
    rd_chk(8'h20, 32'hba7816bf, "abc_256");
    rd_chk(8'h21, 32'h8f01cfea, "abc_256");
    rd_chk(8'h22, 32'h414140de, "abc_256");
    rd_chk(8'h23, 32'h5dae2223, "abc_256");
    rd_chk(8'h24, 32'hb00361a3, "abc_256");
    rd_chk(8'h25, 32'h96177a9c, "abc_256");
    rd_chk(8'h26, 32'hb410ff61, "abc_256");
    rd_chk(8'h27, 32'hf20015ad, "abc_256");
    // ---- twoblk_256 : 2 block(s) ----
    wr(8'h10, 32'h61626364);
    wr(8'h11, 32'h62636465);
    wr(8'h12, 32'h63646566);
    wr(8'h13, 32'h64656667);
    wr(8'h14, 32'h65666768);
    wr(8'h15, 32'h66676869);
    wr(8'h16, 32'h6768696a);
    wr(8'h17, 32'h68696a6b);
    wr(8'h18, 32'h696a6b6c);
    wr(8'h19, 32'h6a6b6c6d);
    wr(8'h1a, 32'h6b6c6d6e);
    wr(8'h1b, 32'h6c6d6e6f);
    wr(8'h1c, 32'h6d6e6f70);
    wr(8'h1d, 32'h6e6f7071);
    wr(8'h1e, 32'h80000000);
    wr(8'h1f, 32'h00000000);
    wr(8'h08, 32'h00000005);
    wait_ready;
    wr(8'h10, 32'h00000000);
    wr(8'h11, 32'h00000000);
    wr(8'h12, 32'h00000000);
    wr(8'h13, 32'h00000000);
    wr(8'h14, 32'h00000000);
    wr(8'h15, 32'h00000000);
    wr(8'h16, 32'h00000000);
    wr(8'h17, 32'h00000000);
    wr(8'h18, 32'h00000000);
    wr(8'h19, 32'h00000000);
    wr(8'h1a, 32'h00000000);
    wr(8'h1b, 32'h00000000);
    wr(8'h1c, 32'h00000000);
    wr(8'h1d, 32'h00000000);
    wr(8'h1e, 32'h00000000);
    wr(8'h1f, 32'h000001c0);
    wr(8'h08, 32'h00000006);
    wait_ready;
    rd_chk(8'h20, 32'h248d6a61, "twoblk_256");
    rd_chk(8'h21, 32'hd20638b8, "twoblk_256");
    rd_chk(8'h22, 32'he5c02693, "twoblk_256");
    rd_chk(8'h23, 32'h0c3e6039, "twoblk_256");
    rd_chk(8'h24, 32'ha33ce459, "twoblk_256");
    rd_chk(8'h25, 32'h64ff2167, "twoblk_256");
    rd_chk(8'h26, 32'hf6ecedd4, "twoblk_256");
    rd_chk(8'h27, 32'h19db06c1, "twoblk_256");
    // ---- abc_224 : 1 block(s) ----
    wr(8'h10, 32'h61626380);
    wr(8'h11, 32'h00000000);
    wr(8'h12, 32'h00000000);
    wr(8'h13, 32'h00000000);
    wr(8'h14, 32'h00000000);
    wr(8'h15, 32'h00000000);
    wr(8'h16, 32'h00000000);
    wr(8'h17, 32'h00000000);
    wr(8'h18, 32'h00000000);
    wr(8'h19, 32'h00000000);
    wr(8'h1a, 32'h00000000);
    wr(8'h1b, 32'h00000000);
    wr(8'h1c, 32'h00000000);
    wr(8'h1d, 32'h00000000);
    wr(8'h1e, 32'h00000000);
    wr(8'h1f, 32'h00000018);
    wr(8'h08, 32'h00000001);
    wait_ready;
    rd_chk(8'h20, 32'h23097d22, "abc_224");
    rd_chk(8'h21, 32'h3405d822, "abc_224");
    rd_chk(8'h22, 32'h8642a477, "abc_224");
    rd_chk(8'h23, 32'hbda255b3, "abc_224");
    rd_chk(8'h24, 32'h2aadbce4, "abc_224");
    rd_chk(8'h25, 32'hbda0b3f7, "abc_224");
    rd_chk(8'h26, 32'he36c9da7, "abc_224");
    // ---- empty_256 : 1 block(s) ----
    wr(8'h10, 32'h80000000);
    wr(8'h11, 32'h00000000);
    wr(8'h12, 32'h00000000);
    wr(8'h13, 32'h00000000);
    wr(8'h14, 32'h00000000);
    wr(8'h15, 32'h00000000);
    wr(8'h16, 32'h00000000);
    wr(8'h17, 32'h00000000);
    wr(8'h18, 32'h00000000);
    wr(8'h19, 32'h00000000);
    wr(8'h1a, 32'h00000000);
    wr(8'h1b, 32'h00000000);
    wr(8'h1c, 32'h00000000);
    wr(8'h1d, 32'h00000000);
    wr(8'h1e, 32'h00000000);
    wr(8'h1f, 32'h00000000);
    wr(8'h08, 32'h00000005);
    wait_ready;
    rd_chk(8'h20, 32'he3b0c442, "empty_256");
    rd_chk(8'h21, 32'h98fc1c14, "empty_256");
    rd_chk(8'h22, 32'h9afbf4c8, "empty_256");
    rd_chk(8'h23, 32'h996fb924, "empty_256");
    rd_chk(8'h24, 32'h27ae41e4, "empty_256");
    rd_chk(8'h25, 32'h649b934c, "empty_256");
    rd_chk(8'h26, 32'ha495991b, "empty_256");
    rd_chk(8'h27, 32'h7852b855, "empty_256");
    if (errors==0) $display("SELFVERIFY_PASS all vectors match");
    else $display("SELFVERIFY_FAIL errors=%0d",errors);
    $finish; end
  initial begin #500000 $display("GLOBAL TIMEOUT"); $finish; end
endmodule
