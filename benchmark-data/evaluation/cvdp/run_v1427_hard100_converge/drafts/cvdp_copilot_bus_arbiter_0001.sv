module bus_arbiter (
    input wire reset,
    input wire clk,
    input wire req1,
    input wire req2,
    output reg grant1,
    output reg grant2
);
    // State encoding using localparam
    localparam IDLE    = 3'b000,
               GRANT_1 = 3'b001,
               GRANT_2 = 3'b010,
               CLEAR   = 3'b011;

    // State registers
    reg [2:0] state;
    reg [2:0] next_state;

    // Sequential logic for state transition (asynchronous, active-high reset)
    always @(posedge clk or posedge reset) begin
        if (reset) begin
            state <= IDLE;
        end else begin
            state <= next_state;
        end
    end

    // Combinational logic for next state
    always @(*) begin
        // Default: hold current state
        next_state = state;

        case (state)
            IDLE: begin
                // req2 is prioritized when both requests are asserted
                if (req2)
                    next_state = GRANT_2;
                else if (req1)
                    next_state = GRANT_1;
                else
                    next_state = IDLE;
            end

            GRANT_1: begin
                // Both asserted simultaneously -> req2 preempts (req2 priority)
                if (req1 && req2)
                    next_state = GRANT_2;
                // req1 still asserted alone -> keep granting Master 1
                else if (req1)
                    next_state = GRANT_1;
                // req1 deasserted -> clear grants first, then (from CLEAR)
                // return to IDLE or serve another pending request
                else
                    next_state = CLEAR;
            end

            GRANT_2: begin
                // req2 is the highest priority: hold while it stays asserted
                if (req2)
                    next_state = GRANT_2;
                // req2 (the served request) deasserted -> clear grants first
                else
                    next_state = CLEAR;
            end

            CLEAR: begin
                // Re-arbitrate after clearing grants (req2 prioritized), or
                // return to IDLE when nothing is pending
                if (req2)
                    next_state = GRANT_2;
                else if (req1)
                    next_state = GRANT_1;
                else
                    next_state = IDLE;
            end

            default: next_state = IDLE;
        endcase
    end

    // Output logic: grant1/grant2 are driven (registered) based on the next
    // state of the FSM. Asynchronous reset deasserts both grants.
    always @(posedge clk or posedge reset) begin
        if (reset) begin
            grant1 <= 1'b0;
            grant2 <= 1'b0;
        end else begin
            case (next_state)
                GRANT_1: begin
                    grant1 <= 1'b1;
                    grant2 <= 1'b0;
                end
                GRANT_2: begin
                    grant1 <= 1'b0;
                    grant2 <= 1'b1;
                end
                default: begin // IDLE, CLEAR -> no grants asserted
                    grant1 <= 1'b0;
                    grant2 <= 1'b0;
                end
            endcase
        end
    end

endmodule
