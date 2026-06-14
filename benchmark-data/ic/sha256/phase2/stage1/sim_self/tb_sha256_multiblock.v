// Self-authored multi-block (NEXT chaining) check, L7 vector 248d6a61...
`timescale 1ns/1ps
module tb_sha256_multiblock;
    reg clk=0,reset_n=0,cs=0,we=0; reg [7:0] address=0; reg [31:0] write_data=0;
    wire [31:0] read_data; wire error; integer i,errors=0,guard;
    reg [31:0] blk0[0:15], blk1[0:15], exp[0:7], q;
    sha256 dut(.clk(clk),.reset_n(reset_n),.cs(cs),.we(we),.address(address),
               .write_data(write_data),.read_data(read_data),.error(error));
    always #5 clk=~clk;
    task wr(input [7:0] a, input [31:0] d); begin
        @(negedge clk); cs=1;we=1;address=a;write_data=d; @(negedge clk); cs=0;we=0; end endtask
    task rd(input [7:0] a, output [31:0] o); begin
        @(negedge clk); cs=1;we=0;address=a; #1 o=read_data; @(negedge clk); cs=0; end endtask
    task poll_ready; begin guard=0;q=0;
        while(q[0]!==1'b1 && guard<500) begin rd(8'h09,q); guard=guard+1; end end endtask
    initial begin
        blk0[0]=32'h61626364;blk0[1]=32'h62636465;blk0[2]=32'h63646566;blk0[3]=32'h64656667;
        blk0[4]=32'h65666768;blk0[5]=32'h66676869;blk0[6]=32'h6768696a;blk0[7]=32'h68696a6b;
        blk0[8]=32'h696a6b6c;blk0[9]=32'h6a6b6c6d;blk0[10]=32'h6b6c6d6e;blk0[11]=32'h6c6d6e6f;
        blk0[12]=32'h6d6e6f70;blk0[13]=32'h6e6f7071;blk0[14]=32'h80000000;blk0[15]=32'h00000000;
        for(i=0;i<15;i=i+1) blk1[i]=32'h0; blk1[15]=32'h000001c0;
        exp[0]=32'h248d6a61;exp[1]=32'hd20638b8;exp[2]=32'he5c02693;exp[3]=32'h0c3e6039;
        exp[4]=32'ha33ce459;exp[5]=32'h64ff2167;exp[6]=32'hf6ecedd4;exp[7]=32'h19db06c1;
        reset_n=0; repeat(4) @(negedge clk); reset_n=1; @(negedge clk);
        // block0 via INIT (MODE=SHA256)
        for(i=0;i<16;i=i+1) wr(8'h10+i,blk0[i]);
        wr(8'h08,{29'b0,1'b1,1'b0,1'b1}); poll_ready;
        // block1 via NEXT (continue)
        for(i=0;i<16;i=i+1) wr(8'h10+i,blk1[i]);
        wr(8'h08,{29'b0,1'b1,1'b1,1'b0}); poll_ready;
        for(i=0;i<8;i=i+1) begin rd(8'h20+i,q);
            if(q!==exp[i]) begin $display("MB DIGEST%0d MISMATCH got=%08x exp=%08x",i,q,exp[i]); errors=errors+1; end
            else $display("MB DIGEST%0d OK %08x",i,q); end
        if(errors==0) $display("MULTIBLOCK_RESULT: PASS"); else $display("MULTIBLOCK_RESULT: FAIL");
        $finish;
    end
    initial begin #300000 $display("GLOBAL TIMEOUT"); $finish; end
endmodule
