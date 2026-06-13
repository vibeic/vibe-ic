// Prob080_timer — 10-bit countdown timer. load -> data; else dec until 0.
// tc = (count==0). Reset-less registered counter: initial block for power-up.
module TopModule (
  input clk,
  input load,
  input [9:0] data,
  output tc
);

  reg [9:0] count;

  initial count = 10'd0;

  always @(posedge clk) begin
    if (load)
      count <= data;
    else if (count != 10'd0)
      count <= count - 10'd1;
  end

  assign tc = (count == 10'd0);

endmodule
