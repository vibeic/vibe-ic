module TopModule (
    input        clk,
    input        areset,
    input        train_valid,
    input        train_taken,
    output reg [1:0] state
);
    always @(posedge clk or posedge areset) begin
        if (areset) begin
            state <= 2'b01;     // weakly not-taken
        end else if (train_valid) begin
            if (train_taken) begin
                if (state != 2'b11) state <= state + 2'b01;  // saturate at 3
            end else begin
                if (state != 2'b00) state <= state - 2'b01;  // saturate at 0
            end
        end
    end
endmodule
