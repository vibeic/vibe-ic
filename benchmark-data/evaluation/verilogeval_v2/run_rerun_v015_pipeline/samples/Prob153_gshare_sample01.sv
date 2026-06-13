module TopModule (
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
    reg [6:0] ghr;            // global history register
    reg [1:0] pht [0:127];    // 128 two-bit saturating counters

    integer i;

    // Prediction (combinational) reads PHT state BEFORE any training write.
    wire [6:0] pidx = predict_pc ^ ghr;
    assign predict_history = ghr;
    assign predict_taken   = pht[pidx][1]; // MSB of saturating counter

    wire [6:0] tidx = train_pc ^ train_history;

    // 2-bit saturating counter update (inline, no function)
    wire [1:0] tcur = pht[tidx];
    wire [1:0] tnext = train_taken ? ((tcur == 2'b11) ? 2'b11 : tcur + 2'b01)
                                   : ((tcur == 2'b00) ? 2'b00 : tcur - 2'b01);

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            ghr <= 7'b0;
            for (i = 0; i < 128; i = i + 1)
                pht[i] <= 2'b01; // weakly not-taken
        end else begin
            // PHT training (writes take effect next edge)
            if (train_valid)
                pht[tidx] <= tnext;

            // GHR update: training misprediction recovery takes precedence
            if (train_valid && train_mispredicted)
                ghr <= {train_history[5:0], train_taken};
            else if (predict_valid)
                ghr <= {ghr[5:0], predict_taken};
        end
    end
endmodule
