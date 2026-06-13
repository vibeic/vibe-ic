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

    // 7-bit global branch history register
    reg [6:0] ghr;

    // 128-entry table of 2-bit saturating counters
    reg [1:0] pht [0:127];

    integer i;

    // Prediction index and read (combinational, sees current PHT state)
    wire [6:0] predict_index = predict_pc ^ ghr;
    assign predict_taken   = pht[predict_index][1];
    assign predict_history = ghr;

    // Training index
    wire [6:0] train_index = train_pc ^ train_history;

    // Saturating counter update for training
    wire [1:0] train_old = pht[train_index];
    wire [1:0] train_new = train_taken ?
                             (train_old == 2'b11 ? 2'b11 : train_old + 2'b01) :
                             (train_old == 2'b00 ? 2'b00 : train_old - 2'b01);

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            ghr <= 7'b0;
            for (i = 0; i < 128; i = i + 1)
                pht[i] <= 2'b01;   // weakly not-taken
        end else begin
            // PHT update from training
            if (train_valid)
                pht[train_index] <= train_new;

            // Global history register update.
            // Training (misprediction recovery) takes precedence over prediction.
            if (train_valid && train_mispredicted)
                ghr <= {train_history[5:0], train_taken};
            else if (predict_valid)
                ghr <= {ghr[5:0], predict_taken};
        end
    end

endmodule
