module producer(input seed, output flag); assign flag = seed; endmodule
module consumer(input clk, rst, flag, input [1:0] phase, output reg [2:0] value);
 always @(posedge clk) begin
  if(rst) value <= 3'b000;
  else if(flag) value[phase] <= 1'b1;
  else value[phase] <= 1'b0;
 end
endmodule
module neutral(input clk,rst,input [2:0] data,input [1:0] phase,output [2:0] value);
 wire link; wire [2:0] gray = data ^ (data >> 1); wire sample = gray[phase];
 producer p(.seed(sample),.flag(link));
 consumer c(.clk(clk),.rst(rst),.flag(link),.phase(phase),.value(value));
endmodule
