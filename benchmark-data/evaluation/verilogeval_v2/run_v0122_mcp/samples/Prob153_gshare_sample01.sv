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

    wire [6:0] p_idx = predict_pc  ^ ghr;
    wire [6:0] t_idx = train_pc    ^ train_history;

    // prediction (combinational read of current PHT/GHR)
    assign predict_taken   = pht[p_idx][1];
    assign predict_history = ghr;

    // next PHT value for the trained entry (saturating toward train_taken)
    reg [1:0] t_new;
    always @(*) begin
        if (train_taken)
            t_new = (pht[t_idx] == 2'b11) ? 2'b11 : pht[t_idx] + 2'b01;
        else
            t_new = (pht[t_idx] == 2'b00) ? 2'b00 : pht[t_idx] - 2'b01;
    end

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            ghr <= 7'd0;
            for (i = 0; i < 128; i = i + 1)
                pht[i] <= 2'b01;        // weakly not-taken
        end else begin
            // PHT update on training (applies next edge -> same-cycle predict sees old)
            if (train_valid)
                pht[t_idx] <= t_new;

            // GHR update: training-misprediction recovery takes precedence
            if (train_valid && train_mispredicted)
                ghr <= {train_history[5:0], train_taken};
            else if (predict_valid)
                ghr <= {ghr[5:0], predict_taken};
        end
    end

endmodule
