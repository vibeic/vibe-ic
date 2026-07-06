// PHT counter reset = weakly-not-taken 2'b01 (house default; spec silent)
// history register reset = 0 (house default; spec silent)
// program-SOLVED gshare branch predictor datapath; deterministic, no AI.
module TopModule(
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
    reg [1:0] pht [0:127];
    reg [6:0] history_r;
    wire [6:0] predict_index = history_r ^ predict_pc[6:0];
    wire [6:0] train_index   = train_history ^ train_pc[6:0];
    integer i;
    always @(posedge clk, posedge areset) begin
        if (areset) begin
            for (i = 0; i < 128; i = i + 1)
                pht[i] <= 2'd1;
            history_r <= 7'd0;
        end else begin
            if (predict_valid)
                history_r <= {history_r[5:0], predict_taken};
            if (train_valid) begin
                if (pht[train_index] < 2'd3 && train_taken)
                    pht[train_index] <= pht[train_index] + 2'd1;
                else if (pht[train_index] > 2'd0 && !train_taken)
                    pht[train_index] <= pht[train_index] - 2'd1;
                if (train_mispredicted)
                    history_r <= {train_history[5:0], train_taken};
            end
        end
    end
    assign predict_taken   = predict_valid ? pht[predict_index][1] : 1'bx;
    assign predict_history = predict_valid ? history_r : {7{1'bx}};
endmodule
