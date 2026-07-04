module spi_fsm (
    input  wire         i_clk,       // System clock
    input  wire         i_rst_b,     // Active-low async reset
    input  wire [15:0]  i_data_in,   // Parallel 16-bit data to transmit
    input  wire         i_enable,    // Enable block
    input  wire         i_fault,     // Fault indicator
    input  wire         i_clear,     // Forces FSM to clear/idle

    output reg          o_spi_cs_b,  // SPI chip select (active-low)
    output reg          o_spi_clk,   // SPI clock
    output reg          o_spi_data,  // Serialized SPI data out
    output reg [4:0]    o_bits_left, // Bits left to transmit
    output reg          o_done,      // Single-cycle pulse when done or error
    output reg [1:0]    o_fsm_state  // FSM state for external monitoring
);

    localparam IDLE     = 2'b00;
    localparam TRANSMIT = 2'b01;
    localparam TOGGLE   = 2'b10;
    localparam ERROR    = 2'b11;

    reg [15:0] shift_reg;

    always @(posedge i_clk or negedge i_rst_b) begin
        if (!i_rst_b) begin
            o_spi_cs_b  <= 1'b1;
            o_spi_clk   <= 1'b0;
            o_spi_data  <= 1'b0;
            o_bits_left <= 5'h10;   // 0x10 = all 16 bits remaining
            o_done      <= 1'b0;
            o_fsm_state <= IDLE;
            shift_reg   <= 16'h0000;
        end else begin
            o_done <= 1'b0;         // default: done is a single-cycle pulse

            if (i_clear) begin
                // Clear has top priority: immediately back to Idle regardless of
                // the current state (including Error), resetting counters/outputs.
                o_spi_cs_b  <= 1'b1;
                o_spi_clk   <= 1'b0;
                o_spi_data  <= 1'b0;
                o_bits_left <= 5'h10;
                o_fsm_state <= IDLE;
            end else if (i_fault) begin
                // Fault: enter Error with safe defaults.
                o_spi_cs_b  <= 1'b1;
                o_spi_clk   <= 1'b0;
                o_spi_data  <= 1'b0;
                o_bits_left <= 5'd10;
                o_done      <= (o_fsm_state != ERROR); // pulse on entry to Error
                o_fsm_state <= ERROR;
            end else begin
                case (o_fsm_state)
                    IDLE: begin
                        o_spi_cs_b  <= 1'b1;
                        o_spi_clk   <= 1'b0;
                        o_spi_data  <= 1'b0;
                        o_bits_left <= 5'h10;
                        if (i_enable) begin
                            shift_reg   <= i_data_in;
                            o_spi_cs_b  <= 1'b0;
                            o_bits_left <= 5'h10;
                            o_fsm_state <= TRANSMIT;
                        end
                    end

                    // TRANSMIT drives the next bit out (MSB first) and consumes
                    // it from the counter so that, by the time the SPI clock is
                    // toggled in the following cycle, o_spi_data and o_bits_left
                    // already hold this bit's values.
                    TRANSMIT: begin
                        if (!i_enable) begin
                            o_spi_cs_b  <= 1'b1;
                            o_spi_clk   <= 1'b0;
                            o_fsm_state <= IDLE;
                        end else begin
                            o_spi_cs_b  <= 1'b0;
                            o_spi_clk   <= 1'b0;          // bit driven while clock low
                            o_spi_data  <= shift_reg[15];
                            shift_reg   <= {shift_reg[14:0], 1'b0};
                            if (o_bits_left == 5'd1) begin
                                // Last bit: complete the transaction.
                                o_bits_left <= 5'd0;
                                o_done      <= 1'b1;
                                o_spi_cs_b  <= 1'b1;
                                o_fsm_state <= IDLE;
                            end else begin
                                o_bits_left <= o_bits_left - 5'd1;
                                o_fsm_state <= TOGGLE;
                            end
                        end
                    end

                    // TOGGLE raises the SPI clock to latch the bit externally.
                    TOGGLE: begin
                        if (!i_enable) begin
                            o_spi_cs_b  <= 1'b1;
                            o_spi_clk   <= 1'b0;
                            o_fsm_state <= IDLE;
                        end else begin
                            o_spi_clk   <= 1'b1;          // rising edge latches data
                            o_fsm_state <= TRANSMIT;
                        end
                    end

                    ERROR: begin
                        // Hold safe values until cleared or reset
                        // (i_clear / i_fault handled above).
                        o_spi_cs_b  <= 1'b1;
                        o_spi_clk   <= 1'b0;
                        o_spi_data  <= 1'b0;
                        o_bits_left <= 5'd10;
                        o_fsm_state <= ERROR;
                    end

                    default: o_fsm_state <= IDLE;
                endcase
            end
        end
    end

endmodule
