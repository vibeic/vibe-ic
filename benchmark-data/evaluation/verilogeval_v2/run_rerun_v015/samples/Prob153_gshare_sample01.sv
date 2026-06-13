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
    reg [6:0] ghr;                 // global history register
    reg [1:0] pht [0:127];         // pattern history table of 2-bit counters

    integer i;

    // Prediction (combinational read)
    wire [6:0] predict_index = predict_pc ^ ghr;
    assign predict_history = ghr;
    assign predict_taken   = pht[predict_index][1];

    // Training index
    wire [6:0] train_index = train_pc ^ train_history;

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            ghr <= 7'd0;
            for (i = 0; i < 128; i = i + 1)
                pht[i] <= 2'b01; // weakly not-taken
        end else begin
            // Train PHT (saturating up/down)
            if (train_valid) begin
                if (train_taken) begin
                    if (pht[train_index] != 2'b11)
                        pht[train_index] <= pht[train_index] + 2'b01;
                end else begin
                    if (pht[train_index] != 2'b00)
                        pht[train_index] <= pht[train_index] - 2'b01;
                end
            end

            // Update global history register.
            // Training (misprediction recovery) takes precedence over prediction.
            if (train_valid && train_mispredicted)
                ghr <= {train_history[5:0], train_taken};
            else if (predict_valid)
                ghr <= {ghr[5:0], predict_taken};
        end
    end
endmodule
