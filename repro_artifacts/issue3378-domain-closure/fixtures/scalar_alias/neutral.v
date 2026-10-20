module producer(input [2:0] data, input [1:0] phase, output flag);
 wire [2:0] gray = data ^ (data >> 1);
 wire sample; assign sample = gray[phase]; assign flag = sample;
endmodule
module consumer(input clk, rst, flag, input [1:0] phase, output reg [2:0] value);
 always @(posedge clk) begin
  if(rst) value <= 3'b000;
  else if(flag) value[phase] <= 1'b1;
  else value[phase] <= 1'b0;
 end
endmodule
module neutral(input clk,rst,input [2:0] data,input [1:0] phase,output [2:0] value);
 wire link;
 producer p(.data(data),.phase(phase),.flag(link));
 consumer c(.clk(clk),.rst(rst),.flag(link),.phase(phase),.value(value));
endmodule
