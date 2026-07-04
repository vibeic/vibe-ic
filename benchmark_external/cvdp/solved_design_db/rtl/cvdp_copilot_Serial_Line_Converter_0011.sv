module serial_line_code_converter #(parameter CLK_DIV = 16)(
    input  logic clk,             // System clock
    input  logic reset_n,         // Active-low reset
    input  logic serial_in,       // Serial input signal
    input  logic enable,          // Enable signal; outputs disabled when low
    input  logic [2:0] mode,      // Mode selector
    output logic serial_out,      // Serial output signal
    output logic error_flag,      // Error flag (serial_in is x/z)
    output logic [15:0] diagnostic_bus // Diagnostic output bus
);

    // Internal signals
    logic [3:0] clk_counter;      // Clock divider counter
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

    logic [7:0] error_counter;    // Tracks total errors detected
    logic       serial_invalid;   // serial_in is x or z


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

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            prev_value <= 0;
            prev_serial_in <= 0;
        end else begin
            prev_value <= serial_in;
            prev_serial_in <= prev_value;
        end
    end

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            nrz_out <= 0;
        end else begin
            nrz_out <= serial_in;
        end
    end

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            rz_out <= 0;
        end else begin
            rz_out <= serial_in & clk_pulse;
        end
    end

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            diff_out <= 0;
        end else  begin
            diff_out <= serial_in ^ prev_serial_in;
        end
    end

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            inv_nrz_out <= 0;
        end else  begin
            inv_nrz_out <= ~serial_in;
        end
    end

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            alt_invert_out <= 0;
            alt_invert_state <= 0;
        end else  begin
            alt_invert_state <= ~alt_invert_state;
            alt_invert_out <= alt_invert_state ? ~serial_in : serial_in;
        end
    end

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            parity_out <= 0;
        end else  begin
            parity_out <= serial_in ^ parity_out;
        end
    end

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            scrambled_out <= 0;
        end else  begin
            scrambled_out <= serial_in ^ clk_counter[0];
        end
    end

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            edge_triggered_out <= 0;
        end else  begin
            edge_triggered_out <= (serial_in & ~prev_serial_in);
        end
    end

    // Error detection: invalid serial_in (1'bx / 1'bz) while enabled.
    always_comb begin
        serial_invalid = (serial_in === 1'bx) || (serial_in === 1'bz);
    end

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            error_counter <= 8'd0;
        end else if (enable && serial_invalid) begin
            error_counter <= error_counter + 8'd1;
        end
    end

    assign error_flag = enable && serial_invalid;

    // Encoding mux, gated by enable.
    always_comb begin
        if (!enable) begin
            serial_out = 1'b0;
        end else begin
            case (mode)
                3'b000: serial_out = nrz_out;
                3'b001: serial_out = rz_out;
                3'b010: serial_out = diff_out;
                3'b011: serial_out = inv_nrz_out;
                3'b100: serial_out = alt_invert_out;
                3'b101: serial_out = parity_out;
                3'b110: serial_out = scrambled_out;
                3'b111: serial_out = edge_triggered_out;
                default: serial_out = 0;
            endcase
        end
    end

    // Diagnostic bus packing.
    assign diagnostic_bus = {mode,            // [15:13] encoding mode
                             error_flag,      // [12]    error flag
                             error_counter,   // [11:4]  error counter
                             clk_pulse,        // [3]     clock pulse
                             serial_out,       // [2]     encoded output
                             alt_invert_out,   // [1]     alternating-invert output
                             parity_out};      // [0]     parity bit

endmodule
