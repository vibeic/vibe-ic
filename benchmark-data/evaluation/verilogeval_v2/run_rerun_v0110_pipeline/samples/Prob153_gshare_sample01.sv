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
    reg [1:0] pht [0:127];
    reg [6:0] ghr;
    integer i;

    wire [6:0] p_idx = predict_pc ^ ghr;
    wire [6:0] t_idx = train_pc   ^ train_history;

    // Prediction outputs (combinational, use PHT state before this cycle's training)
    assign predict_history = ghr;
    assign predict_taken   = pht[p_idx][1];

    // 2-bit saturating counter next value (inlined)
    wire [1:0] cur  = pht[t_idx];
    wire [1:0] nxt  = train_taken ? ((cur == 2'b11) ? 2'b11 : cur + 2'b01)
                                  : ((cur == 2'b00) ? 2'b00 : cur - 2'b01);

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            ghr <= 7'b0;
            for (i = 0; i < 128; i = i + 1)
                pht[i] <= 2'b01;            // weakly not-taken
        end else begin
            // PHT update on training
            if (train_valid)
                pht[t_idx] <= nxt;

            // GHR update: training (misprediction recovery) takes precedence
            if (train_valid && train_mispredicted)
                ghr <= {train_history[5:0], train_taken};
            else if (predict_valid)
                ghr <= {ghr[5:0], predict_taken};
        end
    end
endmodule
