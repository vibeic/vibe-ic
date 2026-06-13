module TopModule (
  input         clk,
  input         areset,
  input         predict_valid,
  input         predict_taken,
  input         train_mispredicted,
  input         train_taken,
  input  [31:0] train_history,
  output [31:0] predict_history
);
  reg [31:0] hist;
  always @(posedge clk or posedge areset) begin
    if (areset)
      hist <= 32'b0;
    else if (train_mispredicted)
      hist <= {train_history[30:0], train_taken};
    else if (predict_valid)
      hist <= {hist[30:0], predict_taken};
  end
  assign predict_history = hist;
endmodule
