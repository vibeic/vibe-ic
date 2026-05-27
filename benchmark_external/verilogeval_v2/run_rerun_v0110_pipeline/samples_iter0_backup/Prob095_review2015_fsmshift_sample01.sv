module TopModule (
  input      clk,
  input      reset,
  output reg shift_ena
);
  // 0..3 -> shift_ena high (4 cycles), 4 -> done (low forever)
  reg [2:0] count;

  always @(posedge clk) begin
    if (reset) begin
      count     <= 3'd0;
      shift_ena <= 1'b1;
    end else begin
      if (count == 3'd3) begin
        count     <= 3'd4;
        shift_ena <= 1'b0;
      end else if (count < 3'd3) begin
        count     <= count + 3'd1;
        shift_ena <= 1'b1;
      end else begin
        shift_ena <= 1'b0;
      end
    end
  end
endmodule
