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
    reg [1:0] pht [0:127];
    reg [6:0] ghr;
    integer i;

    wire [6:0] pidx = predict_pc ^ ghr;
    wire [6:0] tidx = train_pc ^ train_history;

    // Prediction (combinational read of current state)
    assign predict_history = ghr;
    assign predict_taken   = pht[pidx][1];

    // saturating counter update toward taken (+1) / not-taken (-1)
    wire [1:0] tc = pht[tidx];
    wire [1:0] tc_next = train_taken ? ((tc == 2'b11) ? 2'b11 : tc + 2'b01)
                                     : ((tc == 2'b00) ? 2'b00 : tc - 2'b01);

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            for (i = 0; i < 128; i = i + 1) pht[i] <= 2'b01;
            ghr <= 7'b0;
        end else begin
            // PHT training update (next edge) -- prediction this cycle saw old value
            if (train_valid)
                pht[tidx] <= tc_next;

            // GHR: training (misprediction recovery) takes precedence over prediction
            if (train_valid && train_mispredicted)
                ghr <= {train_history[5:0], train_taken};
            else if (predict_valid)
                ghr <= {ghr[5:0], predict_taken};
        end
    end
endmodule
