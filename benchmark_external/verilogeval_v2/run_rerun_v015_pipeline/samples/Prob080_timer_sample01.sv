module TopModule (
  input  clk,
  input  load,
  input  [9:0] data,
  output tc
);
  reg [9:0] count = 10'd0;

  always @(posedge clk) begin
    if (load)
      count <= data;                 // load count value
    else if (count != 10'd0)
      count <= count - 10'd1;        // decrement; hold at 0 once reached
  end

  assign tc = (count == 10'd0);      // terminal count reached
endmodule
