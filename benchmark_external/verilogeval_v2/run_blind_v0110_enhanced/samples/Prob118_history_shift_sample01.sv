module TopModule (
    input  wire        clk,
    input  wire        areset,
    input  wire        predict_valid,
    input  wire        predict_taken,
    input  wire        train_mispredicted,
    input  wire        train_taken,
    input  wire [31:0] train_history,
    output reg  [31:0] predict_history
);
    always @(posedge clk or posedge areset) begin
        if (areset)
            predict_history <= 32'b0;
        else if (train_mispredicted)
            predict_history <= {train_history[30:0], train_taken};
        else if (predict_valid)
            predict_history <= {predict_history[30:0], predict_taken};
    end
endmodule
