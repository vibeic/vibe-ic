module TopModule (
  input clk,
  input areset,

  input predict_valid,
  input [6:0] predict_pc,
  output predict_taken,
  output [6:0] predict_history,

  input train_valid,
  input train_taken,
  input train_mispredicted,
  input [6:0] train_history,
  input [6:0] train_pc
);
    reg [6:0] ghr;
    reg [1:0] pht [0:127];

    wire [6:0] predict_index = predict_pc ^ ghr;
    wire [6:0] train_index   = train_pc ^ train_history;

    // Prediction (combinational), reads PHT before any same-cycle training write
    assign predict_history = ghr;
    assign predict_taken   = pht[predict_index][1];

    // Saturating update of the trained entry
    wire [1:0] cur = pht[train_index];
    wire [1:0] nxt = train_taken ? ((cur == 2'b11) ? 2'b11 : cur + 2'b01)
                                 : ((cur == 2'b00) ? 2'b00 : cur - 2'b01);

    integer i;
    always @(posedge clk or posedge areset) begin
        if (areset) begin
            ghr <= 7'b0;
            for (i = 0; i < 128; i = i + 1)
                pht[i] <= 2'b01;
        end else begin
            // PHT training write
            if (train_valid)
                pht[train_index] <= nxt;

            // GHR update: training mispredict recovery takes precedence
            if (train_valid && train_mispredicted)
                ghr <= {train_history[5:0], train_taken};
            else if (predict_valid)
                ghr <= {ghr[5:0], predict_taken};
        end
    end
endmodule
