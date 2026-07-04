// Bus Arbiter FSM — two requesters, req2 prioritized, async active-high reset.
module cvdp_copilot_bus_arbiter (
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

    // Sequential logic for state transition
    always @(posedge clk or posedge reset) begin
        if (reset) begin
            state <= IDLE;
        end else begin
            state <= next_state;
        end
    end

    // Combinational logic for next state
    always @(*) begin
        // Default assignments
        next_state = state;

        case (state)
            IDLE: begin
                if (req2)
                    next_state = GRANT_2;      // req2 has priority
                else if (req1)
                    next_state = GRANT_1;
                else
                    next_state = IDLE;
            end
            GRANT_1: begin
                if (req2)
                    next_state = GRANT_2;      // preempt for higher-priority req2
                else if (req1)
                    next_state = GRANT_1;      // hold grant for req1
                else
                    next_state = CLEAR;        // request gone -> clear grants
            end
            GRANT_2: begin
                if (req2)
                    next_state = GRANT_2;      // hold grant for req2
                else if (req1)
                    next_state = GRANT_1;      // req2 gone, serve pending req1
                else
                    next_state = CLEAR;        // request gone -> clear grants
            end
            CLEAR: begin
                next_state = IDLE;             // intermediate clear, then re-evaluate
            end
            default: next_state = IDLE;
        endcase
    end

    // Output logic — grants follow the next state
    always @(posedge clk or posedge reset) begin
        if (reset) begin
            grant1 <= 1'b0;
            grant2 <= 1'b0;
        end else begin
            grant1 <= (next_state == GRANT_1);
            grant2 <= (next_state == GRANT_2);
        end
    end

endmodule
