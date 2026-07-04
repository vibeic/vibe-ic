module enhanced_fsm_signal_processor (
    input  wire        i_clk,        // Clock
    input  wire        i_rst_n,      // Active-low reset
    input  wire        i_enable,     // Start processing
    input  wire        i_clear,      // Clear outputs / fault
    input  wire        i_ack,        // 1-cycle pulse: READY -> IDLE
    input  wire        i_fault,      // Fault condition
    input  wire [4:0]  i_vector_1,
    input  wire [4:0]  i_vector_2,
    input  wire [4:0]  i_vector_3,
    input  wire [4:0]  i_vector_4,
    input  wire [4:0]  i_vector_5,
    input  wire [4:0]  i_vector_6,
    output reg         o_ready,      // Outputs valid / processing complete
    output reg         o_error,      // Fault detected
    output reg  [1:0]  o_fsm_status, // Current FSM state
    output reg  [7:0]  o_vector_1,
    output reg  [7:0]  o_vector_2,
    output reg  [7:0]  o_vector_3,
    output reg  [7:0]  o_vector_4
);

    // FSM state encoding (matches o_fsm_status mapping)
    localparam [1:0] IDLE    = 2'b00,
                     PROCESS = 2'b01,
                     READY   = 2'b10,
                     FAULT   = 2'b11;

    reg [1:0] state, next_state;

    // ---------------------------------------------------------------------
    // All inputs are synchronous to i_clk -> register them before use. This
    // adds the single sampling cycle the FSM timeline relies on.
    // ---------------------------------------------------------------------
    reg        en_r, clr_r, ack_r, flt_r;
    reg [4:0]  v1_r, v2_r, v3_r, v4_r, v5_r, v6_r;

    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n) begin
            en_r  <= 1'b0; clr_r <= 1'b0; ack_r <= 1'b0; flt_r <= 1'b0;
            v1_r  <= 5'd0; v2_r <= 5'd0; v3_r <= 5'd0;
            v4_r  <= 5'd0; v5_r <= 5'd0; v6_r <= 5'd0;
        end else begin
            en_r  <= i_enable;
            clr_r <= i_clear;
            ack_r <= i_ack;
            flt_r <= i_fault;
            v1_r  <= i_vector_1; v2_r <= i_vector_2; v3_r <= i_vector_3;
            v4_r  <= i_vector_4; v5_r <= i_vector_5; v6_r <= i_vector_6;
        end
    end

    // Concatenate the six 5-bit vectors (MSB..LSB) into 30 bits, then append
    // two '1' bits at the LSB to form a 32-bit bus.
    wire [31:0] concat_bus = {v1_r, v2_r, v3_r, v4_r, v5_r, v6_r, 2'b11};

    // ---------------------------------------------------------------------
    // Next-state logic uses the registered inputs. i_fault takes precedence
    // over every other input (except clock / reset).
    // ---------------------------------------------------------------------
    always @(*) begin
        next_state = state;
        if (flt_r) begin
            next_state = FAULT;
        end else begin
            case (state)
                IDLE:    next_state = en_r ? PROCESS : IDLE;
                PROCESS: next_state = READY;
                READY:   next_state = ack_r ? IDLE : READY;
                FAULT:   next_state = (clr_r && !flt_r) ? IDLE : FAULT;
                default: next_state = IDLE;
            endcase
        end
    end

    // ---------------------------------------------------------------------
    // Registered state + outputs (all outputs synchronous to i_clk).
    // ---------------------------------------------------------------------
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n) begin
            state        <= IDLE;
            o_ready      <= 1'b0;
            o_error      <= 1'b0;
            o_fsm_status <= IDLE;
            o_vector_1   <= 8'd0;
            o_vector_2   <= 8'd0;
            o_vector_3   <= 8'd0;
            o_vector_4   <= 8'd0;
        end else begin
            state        <= next_state;
            o_fsm_status <= next_state;
            o_ready      <= (next_state == READY);
            o_error      <= (next_state == FAULT);

            // Vector handling: concatenation result is captured while in
            // PROCESS so it becomes valid as the FSM enters READY; outputs are
            // forced to default in IDLE/FAULT.
            if ((state == PROCESS) && !flt_r) begin
                o_vector_1 <= concat_bus[31:24];
                o_vector_2 <= concat_bus[23:16];
                o_vector_3 <= concat_bus[15:8];
                o_vector_4 <= concat_bus[7:0];
            end else if ((next_state == IDLE) || (next_state == FAULT)) begin
                o_vector_1 <= 8'd0;
                o_vector_2 <= 8'd0;
                o_vector_3 <= 8'd0;
                o_vector_4 <= 8'd0;
            end
        end
    end

endmodule
