module TopModule(
    input        clk,
    input        areset,
    input        predict_valid,
    input  [6:0] predict_pc,
    output       predict_taken,
    output [6:0] predict_history,
    input        train_valid,
    input        train_taken,
    input        train_mispredicted,
    input  [6:0] train_history,
    input  [6:0] train_pc
);
    reg [1:0] pht [0:127];     // 2-bit saturating counters
    reg [6:0] ghr;             // global history register
    integer i;

    // Prediction (combinational): index = pc xor current history
    wire [6:0] pidx = predict_pc ^ ghr;
    assign predict_taken   = pht[pidx][1];   // MSB = taken
    assign predict_history = ghr;

    // Training index
    wire [6:0] tidx = train_pc ^ train_history;

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            ghr <= 7'd0;
            for (i = 0; i < 128; i = i + 1)
                pht[i] <= 2'b01;             // weakly not-taken
        end else begin
            // PHT update (saturating) on training
            if (train_valid) begin
                if (train_taken) begin
                    if (pht[tidx] != 2'b11) pht[tidx] <= pht[tidx] + 2'b01;
                end else begin
                    if (pht[tidx] != 2'b00) pht[tidx] <= pht[tidx] - 2'b01;
                end
            end

            // Global history register update.
            // Training (misprediction recovery) takes precedence over prediction.
            if (train_valid && train_mispredicted)
                ghr <= {train_history[5:0], train_taken};
            else if (predict_valid)
                ghr <= {ghr[5:0], pht[pidx][1]};
        end
    end
endmodule
