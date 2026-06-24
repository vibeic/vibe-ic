// counter_12 — 4-bit counter, counts 0..11 (4'd11), wraps to 0, gated by valid_count.
// Active-low reset rst_n. Per RTLLM design_description.
module counter_12 (
    input  wire       rst_n,        // active-low reset
    input  wire       clk,          // clock
    input  wire       valid_count,  // enable counting
    output reg  [3:0] out           // current count value
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out <= 4'b0000;
        end else if (valid_count) begin
            if (out == 4'd11)
                out <= 4'b0000;
            else
                out <= out + 4'b0001;
        end
        // valid_count == 0: hold (out unchanged)
    end
endmodule
