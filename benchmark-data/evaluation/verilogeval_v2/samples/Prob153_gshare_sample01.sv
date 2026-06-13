module TopModule (
  input  clk,
  input  areset,

  input  predict_valid,
  input  [6:0] predict_pc,
  output predict_taken,
  output [6:0] predict_history,

  input  train_valid,
  input  train_taken,
  input  train_mispredicted,
  input  [6:0] train_history,
  input  [6:0] train_pc
);

  reg [6:0] ghr;
  reg [1:0] pht [0:127];
  integer i;

  wire [6:0] p_index = predict_pc ^ ghr;
  wire [6:0] t_index = train_pc ^ train_history;

  // Prediction outputs (combinational, sees pre-training PHT state)
  assign predict_history = ghr;
  assign predict_taken   = pht[p_index][1];

  always @(posedge clk or posedge areset) begin
    if (areset) begin
      ghr <= 7'b0;
      for (i = 0; i < 128; i = i + 1)
        pht[i] <= 2'b01;   // weakly not-taken
    end else begin
      // Train PHT (2-bit saturating counter)
      if (train_valid) begin
        if (train_taken) begin
          if (pht[t_index] != 2'b11) pht[t_index] <= pht[t_index] + 2'b01;
        end else begin
          if (pht[t_index] != 2'b00) pht[t_index] <= pht[t_index] - 2'b01;
        end
      end

      // Branch history register update: training-misprediction takes precedence
      if (train_valid && train_mispredicted)
        ghr <= {train_history[5:0], train_taken};
      else if (predict_valid)
        ghr <= {ghr[5:0], predict_taken};
    end
  end

endmodule
