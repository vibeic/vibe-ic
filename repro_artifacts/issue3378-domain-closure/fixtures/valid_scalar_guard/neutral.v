module producer(input [2:0] data,input [1:0] phase,input seed,output reg flag);
wire [2:0] unused_gray = data ^ (data >> 1);
always @* begin if(seed) flag=1'b1; else flag=1'b0; end
endmodule
module consumer(input clk,rst,flag,output reg seen);
always @(posedge clk) if(rst) seen<=1'b0; else if(flag) seen<=1'b1; else seen<=1'b0;
endmodule
module neutral(input clk,rst,seed,input [2:0] data,input [1:0] phase,output seen);
wire link;producer p(.data(data),.phase(phase),.seed(seed),.flag(link));
consumer c(.clk(clk),.rst(rst),.flag(link),.seen(seen));
endmodule
