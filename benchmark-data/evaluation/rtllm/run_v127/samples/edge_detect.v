// edge_detect: rising/falling edge detector on a slowly-changing 1-bit input.
// Outputs are REGISTERED (asserted on the NEXT clock after the edge, per spec)
// as single-cycle pulses, then return to 0 until the next corresponding edge.
// Async active-low reset, posedge clk.
module edge_detect (
    input  wire clk,
    input  wire rst_n,
    input  wire a,
    output reg  rise,
    output reg  down
);

    reg a_prev;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_prev <= 1'b0;
            rise   <= 1'b0;
            down   <= 1'b0;
        end else begin
            a_prev <= a;
            rise   <= ( a & ~a_prev);   // 0 -> 1 transition
            down   <= (~a &  a_prev);   // 1 -> 0 transition
        end
    end

endmodule
