module TopModule (
  input clk,
  input areset,
  input train_valid,
  input train_taken,
  output logic [1:0] state
);
  always @(posedge clk or posedge areset) begin
    if (areset) begin
      state <= 2'd1;
    end else if (train_valid) begin
      if (train_taken && state < 2'd3)
        state <= state + 2'd1;
      else if (!train_taken && state > 2'd0)
        state <= state - 2'd1;
    end
  end
endmodule
