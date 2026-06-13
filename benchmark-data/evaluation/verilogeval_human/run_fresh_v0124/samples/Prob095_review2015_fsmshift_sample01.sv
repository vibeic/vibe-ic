module TopModule (
  input clk,
  input reset,
  output shift_ena
);

  // count 0..3 = shifting (4 cycles), then saturate at 4 = done.
  reg [2:0] count;

  always @(posedge clk) begin
    if (reset)
      count <= 3'd0;
    else if (count != 3'd4)
      count <= count + 3'd1;
  end

  assign shift_ena = (count != 3'd4);

endmodule
