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
    reg [6:0] ghr;                 // global history register
    reg [1:0] pht [0:127];         // 128-entry 2-bit saturating counters
    integer i;

    wire [6:0] pred_idx  = predict_pc   ^ ghr;
    wire [6:0] train_idx = train_pc     ^ train_history;

    // ---- combinational prediction outputs (PHT read sees pre-train state) ----
    assign predict_history = ghr;
    assign predict_taken   = pht[pred_idx][1];

    // ---- saturating update helper value ----
    reg [1:0] new_ctr;
    always @(*) begin
        if (train_taken)
            new_ctr = (pht[train_idx] == 2'b11) ? 2'b11 : pht[train_idx] + 2'b01;
        else
            new_ctr = (pht[train_idx] == 2'b00) ? 2'b00 : pht[train_idx] - 2'b01;
    end

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            ghr <= 7'b0;
            for (i = 0; i < 128; i = i + 1)
                pht[i] <= 2'b01;   // weakly not-taken
        end else begin
            // PHT training update
            if (train_valid)
                pht[train_idx] <= new_ctr;

            // GHR: training (misprediction recovery) takes precedence over prediction
            if (train_valid && train_mispredicted)
                ghr <= {train_history[5:0], train_taken};
            else if (predict_valid)
                ghr <= {ghr[5:0], predict_taken};
        end
    end
endmodule
