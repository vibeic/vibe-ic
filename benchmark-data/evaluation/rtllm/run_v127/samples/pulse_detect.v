// pulse_detect: detect a 0->1->0 pulse over 3 cycles on data_in; data_out is
// asserted at the END cycle of the pulse (the closing 0). The spec's worked
// example data_in=01010 -> data_out=00101 shows SAME-CYCLE assertion, so the
// output is a COMBINATIONAL (Mealy) function of (state, data_in) — a registered
// Moore output would lag one cycle and mismatch the example.
// Async active-low reset, posedge clk; only the state is registered.
module pulse_detect (
    input  wire clk,
    input  wire rst_n,
    input  wire data_in,
    output wire data_out
);

    localparam S_LAST0 = 2'd0;  // previous bit was 0 (or reset)
    localparam S_RISE  = 2'd1;  // saw 0 then 1 (candidate pulse: prev=1, pre-prev=0)
    localparam S_HIGH  = 2'd2;  // previous bit was 1 but NOT cleanly preceded by 0

    reg [1:0] state;

    // Combinational Mealy output: pulse ends when a clean 0->1 is followed by 0
    assign data_out = (state == S_RISE) && (data_in == 1'b0);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_LAST0;
        end else begin
            case (state)
                S_LAST0: state <= data_in ? S_RISE  : S_LAST0;
                S_RISE:  state <= data_in ? S_HIGH  : S_LAST0;
                S_HIGH:  state <= data_in ? S_HIGH  : S_LAST0;
                default: state <= S_LAST0;
            endcase
        end
    end

endmodule
