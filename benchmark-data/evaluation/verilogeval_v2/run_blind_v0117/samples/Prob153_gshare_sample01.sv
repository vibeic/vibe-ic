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
    reg [6:0] history;          // global branch history register
    reg [1:0] pht [0:127];      // 128-entry 2-bit saturating counters

    integer i;

    wire [6:0] pidx = predict_pc ^ history;        // prediction index
    wire [6:0] tidx = train_pc   ^ train_history;  // training index

    // Prediction outputs (combinational, see PHT before same-cycle training)
    assign predict_taken   = pht[pidx][1];
    assign predict_history = history;

    // saturating update toward 'taken'
    function [1:0] sat_update;
        input [1:0] cur;
        input       taken;
        begin
            if (taken)
                sat_update = (cur == 2'b11) ? 2'b11 : cur + 2'b01;
            else
                sat_update = (cur == 2'b00) ? 2'b00 : cur - 2'b01;
        end
    endfunction

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            history <= 7'b0;
            for (i = 0; i < 128; i = i + 1)
                pht[i] <= 2'b01;   // weakly not-taken
        end else begin
            // PHT training update (takes effect next edge)
            if (train_valid)
                pht[tidx] <= sat_update(pht[tidx], train_taken);

            // History register update: training (recovery) takes precedence
            if (train_valid && train_mispredicted)
                history <= {train_history[5:0], train_taken};
            else if (predict_valid)
                history <= {history[5:0], predict_taken};
        end
    end
endmodule
