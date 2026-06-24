module TopModule (
  input clk,
  input areset,
  input predict_valid,
  input predict_taken,
  input train_mispredicted,
  input train_taken,
  input [31:0] train_history,
  output reg [31:0] predict_history
);

  always @(posedge clk, posedge areset) begin
    if (areset)
      predict_history <= 0;
    else if (train_mispredicted)
      predict_history <= {train_history[30:0], train_taken};
    else if (predict_valid)
      predict_history <= {predict_history[30:0], predict_taken};
  end

endmodule
