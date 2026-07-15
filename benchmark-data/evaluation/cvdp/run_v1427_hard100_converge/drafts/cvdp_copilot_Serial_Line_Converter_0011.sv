module serial_line_code_converter #(parameter CLK_DIV = 16)(
    input  logic clk,                    // System clock
    input  logic reset_n,                // Active-low asynchronous reset
    input  logic serial_in,              // Serial input signal
    input  logic enable,                 // Module enable control
    input  logic [2:0] mode,             // Mode selector
    output logic serial_out,             // Serial output signal
    output logic error_flag,             // Error flag (invalid serial_in detected)
    output logic [15:0] diagnostic_bus   // Real-time diagnostic/status bus
);

    // Internal signals
    logic [$clog2(CLK_DIV)-1:0] clk_counter; // Clock divider counter
    logic clk_pulse;              // Clock pulse for sampling
    logic prev_serial_in;         // Previous serial input for edge detection
    logic prev_value;             // Holds the previous value of serial_in
    logic nrz_out;                // NRZ encoding output
    logic rz_out;                 // Return-to-Zero encoding output
    logic diff_out;               // Differential encoding output
    logic inv_nrz_out;            // Inverted NRZ output
    logic alt_invert_out;         // NRZ with alternating bit inversion output
    logic alt_invert_state;       // State for alternating inversion
    logic parity_out;             // Parity Bit Output
    logic scrambled_out;          // Scrambled NRZ output
    logic edge_triggered_out;     // Edge-Triggered NRZ output

    logic serial_in_invalid;      // serial_in is 1'bx or 1'bz
    logic error_flag_reg;         // Registered error flag
    logic [7:0] error_counter;    // Total number of detected errors
    logic encoded_out;            // Combinationally selected encoder output

    // 4-state detection of invalid serial input: must use case equality (===),
    // since == against x/z yields x and would never flag an error.
    assign serial_in_invalid = (serial_in === 1'bx) || (serial_in === 1'bz);

    // Clock pulse generation: counter counts 0..CLK_DIV-1, one-cycle pulse on wrap
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            clk_counter <= 0;
            clk_pulse <= 0;
        end else if (clk_counter == CLK_DIV - 1) begin
            clk_counter <= 0;
            clk_pulse <= 1;
        end else begin
            clk_counter <= clk_counter + 1;
            clk_pulse <= 0;
        end
    end

    // Previous serial input tracking
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            prev_value <= 0;
            prev_serial_in <= 0;
        end else begin
            prev_value <= serial_in;
            prev_serial_in <= prev_value;
        end
    end

    // NRZ (Non-Return-to-Zero)
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            nrz_out <= 0;
        end else begin
            nrz_out <= serial_in;
        end
    end

    // RZ (Return-to-Zero)
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            rz_out <= 0;
        end else begin
            rz_out <= serial_in & clk_pulse;
        end
    end

    // Differential encoding
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            diff_out <= 0;
        end else begin
            diff_out <= serial_in ^ prev_serial_in;
        end
    end

    // Inverted NRZ
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            inv_nrz_out <= 0;
        end else begin
            inv_nrz_out <= ~serial_in;
        end
    end

    // NRZ with alternating bit inversion (state keeps advancing every cycle,
    // regardless of the currently selected mode or enable)
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            alt_invert_out <= 0;
            alt_invert_state <= 0;
        end else begin
            alt_invert_state <= ~alt_invert_state;
            alt_invert_out <= alt_invert_state ? ~serial_in : serial_in;
        end
    end

    // Odd parity bit output (running parity keeps advancing every cycle)
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            parity_out <= 0;
        end else begin
            parity_out <= serial_in ^ parity_out;
        end
    end

    // Scrambled NRZ
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            scrambled_out <= 0;
        end else begin
            scrambled_out <= serial_in ^ clk_counter[0];
        end
    end

    // Edge-Triggered NRZ
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            edge_triggered_out <= 0;
        end else begin
            edge_triggered_out <= (serial_in & ~prev_serial_in);
        end
    end

    // Error detection: active while the module is enabled. Sets error_flag and
    // increments error_counter on each cycle serial_in is invalid (x/z);
    // error_flag clears when a valid sample is seen again.
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            error_flag_reg <= 1'b0;
            error_counter  <= 8'd0;
        end else if (enable) begin
            if (serial_in_invalid) begin
                error_flag_reg <= 1'b1;
                error_counter  <= error_counter + 8'd1;
            end else begin
                error_flag_reg <= 1'b0;
            end
        end
    end

    // Purely combinational mode mux over the independently-registered encoder
    // outputs (encoder state is never gated by mode or enable).
    always_comb begin
        case (mode)
            3'b000: encoded_out = nrz_out;
            3'b001: encoded_out = rz_out;
            3'b010: encoded_out = diff_out;
            3'b011: encoded_out = inv_nrz_out;
            3'b100: encoded_out = alt_invert_out;
            3'b101: encoded_out = parity_out;
            3'b110: encoded_out = scrambled_out;
            3'b111: encoded_out = edge_triggered_out;
            default: encoded_out = 1'b0;
        endcase
    end

    // Enable gating at the outputs: when disabled, all outputs are forced to 0.
    assign serial_out = enable ? encoded_out : 1'b0;
    assign error_flag = enable ? error_flag_reg : 1'b0;

    // Diagnostic bus (real-time / combinational):
    // [15:13] mode | [12] error flag | [11:4] error counter |
    // [3] clock pulse | [2] encoded output | [1] alt-invert output | [0] parity bit
    assign diagnostic_bus = enable
        ? {mode, error_flag_reg, error_counter, clk_pulse, encoded_out, alt_invert_out, parity_out}
        : 16'h0000;

endmodule
