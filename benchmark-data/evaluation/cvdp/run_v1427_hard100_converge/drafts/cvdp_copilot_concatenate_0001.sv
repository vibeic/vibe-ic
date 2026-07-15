//------------------------------------------------------------------------------
// enhanced_fsm_signal_processor
//
// FSM-managed signal processor:
//   IDLE(00) -> PROCESS(01) -> READY(10) -> IDLE, with FAULT(11) override.
//
// PROCESS concatenates the six 5-bit input vectors (i_vector_1 = MSBs) into a
// 30-bit bus, appends two 1'b1 bits at the LSB to form a 32-bit bus, and splits
// it into four 8-bit output vectors (o_vector_1 = MSB byte ... o_vector_4 = LSB
// byte).
//
// Precedence: i_rst_n (async, active-low) > i_fault > normal flow.
// i_fault takes precedence over every input except i_clk / i_rst_n.
// All outputs are registered (synchronous to i_clk):
//   - o_ready  is high exactly while o_fsm_status == READY
//   - o_error  is high exactly while o_fsm_status == FAULT
//   - o_vector_* hold the last computed split, cleared by reset / FAULT.
//------------------------------------------------------------------------------

module enhanced_fsm_signal_processor (
    input  wire       i_clk,
    input  wire       i_rst_n,
    input  wire       i_enable,
    input  wire       i_clear,
    input  wire       i_ack,
    input  wire       i_fault,
    input  wire [4:0] i_vector_1,
    input  wire [4:0] i_vector_2,
    input  wire [4:0] i_vector_3,
    input  wire [4:0] i_vector_4,
    input  wire [4:0] i_vector_5,
    input  wire [4:0] i_vector_6,
    output reg        o_ready,
    output reg        o_error,
    output reg  [1:0] o_fsm_status,
    output reg  [7:0] o_vector_1,
    output reg  [7:0] o_vector_2,
    output reg  [7:0] o_vector_3,
    output reg  [7:0] o_vector_4
);

    // FSM state encoding (fixed by the spec's o_fsm_status encoding).
    localparam [1:0] IDLE    = 2'b00;
    localparam [1:0] PROCESS = 2'b01;
    localparam [1:0] READY   = 2'b10;
    localparam [1:0] FAULT   = 2'b11;

    // 30-bit concatenation of the six 5-bit inputs, 2'b11 appended at the LSB
    // -> {v1, v2, v3, v4, v5, v6, 2'b11} (MSB .. LSB).
    wire [31:0] concat_bus = {i_vector_1, i_vector_2, i_vector_3,
                              i_vector_4, i_vector_5, i_vector_6, 2'b11};

    // o_fsm_status doubles as the state register (it *is* the current state).
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n) begin
            // Reset: FSM -> IDLE, clear all outputs, reset fault.
            o_fsm_status <= IDLE;
            o_ready      <= 1'b0;
            o_error      <= 1'b0;
            o_vector_1   <= 8'd0;
            o_vector_2   <= 8'd0;
            o_vector_3   <= 8'd0;
            o_vector_4   <= 8'd0;
        end
        else if (i_fault) begin
            // Fault handling takes precedence over every other input.
            // Enter/stay in FAULT, assert error, force outputs to default.
            o_fsm_status <= FAULT;
            o_error      <= 1'b1;
            o_ready      <= 1'b0;
            o_vector_1   <= 8'd0;
            o_vector_2   <= 8'd0;
            o_vector_3   <= 8'd0;
            o_vector_4   <= 8'd0;
        end
        else begin
            case (o_fsm_status)
                IDLE: begin
                    // Default state: wait for enable; data outputs hold.
                    o_ready <= 1'b0;
                    o_error <= 1'b0;
                    if (i_enable)
                        o_fsm_status <= PROCESS;
                    else
                        o_fsm_status <= IDLE;
                end

                PROCESS: begin
                    // Concatenate + split. Register the four bytes so they are
                    // valid on the same edge READY is entered, along with
                    // o_ready.
                    o_vector_1   <= concat_bus[31:24];
                    o_vector_2   <= concat_bus[23:16];
                    o_vector_3   <= concat_bus[15:8];
                    o_vector_4   <= concat_bus[7:0];
                    o_ready      <= 1'b1;
                    o_error      <= 1'b0;
                    o_fsm_status <= READY;
                end

                READY: begin
                    // Outputs valid; wait for the 1-cycle i_ack pulse.
                    o_ready <= 1'b1;
                    o_error <= 1'b0;
                    if (i_ack) begin
                        o_ready      <= 1'b0;
                        o_fsm_status <= IDLE;
                    end
                    else begin
                        o_fsm_status <= READY;
                    end
                end

                FAULT: begin
                    // i_fault is deasserted on this branch (outer test handles
                    // the asserted case). Keep error high and outputs at
                    // default; leave FAULT only when i_clear is asserted.
                    o_error    <= 1'b1;
                    o_ready    <= 1'b0;
                    o_vector_1 <= 8'd0;
                    o_vector_2 <= 8'd0;
                    o_vector_3 <= 8'd0;
                    o_vector_4 <= 8'd0;
                    if (i_clear) begin
                        o_error      <= 1'b0;
                        o_fsm_status <= IDLE;
                    end
                    else begin
                        o_fsm_status <= FAULT;
                    end
                end

                default: begin
                    o_fsm_status <= IDLE;
                    o_ready      <= 1'b0;
                    o_error      <= 1'b0;
                end
            endcase
        end
    end

endmodule
