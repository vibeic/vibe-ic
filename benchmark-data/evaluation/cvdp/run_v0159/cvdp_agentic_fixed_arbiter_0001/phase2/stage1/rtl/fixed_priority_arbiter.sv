// fixed_priority_arbiter
// Fixed-priority arbitration among 8 requesters (lowest index = highest priority)
// with an external priority_override that takes precedence over req.
// Synchronous active-high reset; registered outputs => 1-cycle arbitration latency.
module fixed_priority_arbiter(
    input            clk,
    input            reset,                 // active-high synchronous reset
    input      [7:0] req,
    input      [7:0] priority_override,

    output reg [7:0] grant,
    output reg       valid,
    output reg [2:0] grant_index
);

    // Combinational fixed-priority selection.
    // priority_override takes precedence over req when non-zero.
    // Lowest active bit (bit 0 first) is the highest priority.
    reg [7:0] sel;          // the vector being arbitrated this cycle
    reg [7:0] nxt_grant;
    reg [2:0] nxt_index;
    reg       nxt_valid;
    integer   i;

    always @(*) begin
        sel = (priority_override != 8'b0) ? priority_override : req;

        nxt_grant = 8'b0;
        nxt_index = 3'b0;
        nxt_valid = 1'b0;

        // scan from bit 0 (highest priority) to bit 7; first active wins
        for (i = 0; i < 8; i = i + 1) begin
            if (!nxt_valid && sel[i]) begin
                nxt_grant       = 8'b0;
                nxt_grant[i[2:0]] = 1'b1;
                nxt_index       = i[2:0];
                nxt_valid       = 1'b1;
            end
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            grant       <= 8'b0;
            valid       <= 1'b0;
            grant_index <= 3'b0;
        end else begin
            grant       <= nxt_grant;
            valid       <= nxt_valid;
            grant_index <= nxt_index;
        end
    end

endmodule
