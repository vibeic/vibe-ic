module dot_product (
    input               clk_in,                     // Clock signal
    input               reset_in,                   // Asynchronous Reset signal, Active HIGH
    input               start_in,                   // Start computation signal, Active HIGH for one clock cycle
    input       [7:0]   dot_length_in,              // Length of the dot product vectors (up to 256 elements)
    input       [31:0]  vector_a_in,                // Input vector A: {Imaginary[31:16], Real[15:0]}
    input               vector_a_valid_in,          // Valid signal for vector A, active HIGH
    input       [31:0]  vector_b_in,                // Input vector B: {Imaginary[31:16], Real[15:0]}
    input               vector_b_valid_in,          // Valid signal for vector B, active HIGH
    input               a_complex_in,               // 1 = vector A is complex, 0 = real
    input               b_complex_in,               // 1 = vector B is complex, 0 = real
    output reg  [31:0]  dot_product_out,            // Output dot product result (32-bit)
    output reg          dot_product_valid_out,      // Valid signal for dot product output
    output reg          dot_product_error_out       // Error signal: valid dropped mid-computation
);

    typedef enum logic [1:0] {
        IDLE    = 2'b00,
        COMPUTE = 2'b01,
        OUTPUT  = 2'b10,
        ERROR   = 2'b11
    } state_t;

    state_t state;

    // -----------------------------------------------------------------
    // Registered input stage (all inputs are registered for
    // synchronization / metastability avoidance)
    // -----------------------------------------------------------------
    reg [31:0] vector_a_reg;
    reg [31:0] vector_b_reg;
    reg        vector_a_valid_reg;
    reg        vector_b_valid_reg;

    // Configuration snapshot (captured while in IDLE, like the original
    // dot_length capture; frozen for the duration of a computation)
    reg [7:0]  dot_length_reg;
    reg        a_complex_reg;
    reg        b_complex_reg;

    // Zero-length request: result is defined to be 0 (skip COMPUTE).
    wire       dot_length_is_zero = (dot_length_in == 8'd0);

    // -----------------------------------------------------------------
    // Accumulators
    //  - acc         : real-only mode, unsigned MAC of the 16-bit real
    //                  fields (zero-extended), 32-bit result
    //  - acc_re/acc_im : complex / mixed modes, signed accumulation of
    //                  16-bit signed field products
    // -----------------------------------------------------------------
    reg        [31:0] acc;
    reg signed [31:0] acc_re;
    reg signed [31:0] acc_im;
    reg        [7:0]  cnt;

    // Field extraction from the registered inputs
    wire signed [15:0] a_re = vector_a_reg[15:0];
    wire signed [15:0] a_im = vector_a_reg[31:16];
    wire signed [15:0] b_re = vector_b_reg[15:0];
    wire signed [15:0] b_im = vector_b_reg[31:16];

    // Real-only mode operands are unsigned (full 0..0xFFFF range):
    // zero-extend and multiply unsigned.
    wire        [15:0] a_re_u = vector_a_reg[15:0];
    wire        [15:0] b_re_u = vector_b_reg[15:0];

    wire complex_mode   = a_complex_reg | b_complex_reg;
    wire beat_valid     = vector_a_valid_reg & vector_b_valid_reg;
    // Mismatched valid pair at any time, or any in-flight cycle lacking
    // the full handshake once data has begun streaming, is an error.
    wire valid_mismatch = vector_a_valid_reg ^ vector_b_valid_reg;

    // -----------------------------------------------------------------
    // Input registration
    // -----------------------------------------------------------------
    always @(posedge clk_in or posedge reset_in) begin
        if (reset_in) begin
            vector_a_reg       <= 32'd0;
            vector_b_reg       <= 32'd0;
            vector_a_valid_reg <= 1'b0;
            vector_b_valid_reg <= 1'b0;
        end else begin
            vector_a_reg       <= vector_a_in;
            vector_b_reg       <= vector_b_in;
            vector_a_valid_reg <= vector_a_valid_in;
            vector_b_valid_reg <= vector_b_valid_in;
        end
    end

    // -----------------------------------------------------------------
    // Main FSM
    // -----------------------------------------------------------------
    always @(posedge clk_in or posedge reset_in) begin
        if (reset_in) begin
            state                 <= IDLE;
            acc                   <= 32'd0;
            acc_re                <= 32'sd0;
            acc_im                <= 32'sd0;
            cnt                   <= 8'd0;
            dot_product_out       <= 32'd0;
            dot_product_valid_out <= 1'b0;
            dot_product_error_out <= 1'b0;
            dot_length_reg        <= 8'd0;
            a_complex_reg         <= 1'b0;
            b_complex_reg         <= 1'b0;
        end else begin
            case (state)
                IDLE: begin
                    dot_product_valid_out <= 1'b0;
                    dot_length_reg        <= dot_length_in;
                    a_complex_reg         <= a_complex_in;
                    b_complex_reg         <= b_complex_in;
                    if (start_in) begin
                        acc                   <= 32'd0;
                        acc_re                <= 32'sd0;
                        acc_im                <= 32'sd0;
                        cnt                   <= 8'd0;
                        dot_product_error_out <= 1'b0;
                        if (dot_length_is_zero)
                            state <= OUTPUT;   // zero-length: result is 0
                        else
                            state <= COMPUTE;
                    end
                end
                COMPUTE: begin
                    if (beat_valid) begin
                        case ({a_complex_reg, b_complex_reg})
                            2'b00: begin
                                // Real-only mode: unsigned 16x16 MAC
                                acc <= acc + (a_re_u * b_re_u);
                            end
                            2'b11: begin
                                // Complex-only mode
                                acc_re <= acc_re + (a_re * b_re) - (a_im * b_im);
                                acc_im <= acc_im + (a_re * b_im) + (a_im * b_re);
                            end
                            2'b10: begin
                                // Mixed: A complex, B real scalar (B[15:0])
                                acc_re <= acc_re + (a_re * b_re);
                                acc_im <= acc_im + (a_im * b_re);
                            end
                            default: begin
                                // Mixed: A real scalar (A[15:0]), B complex
                                acc_re <= acc_re + (a_re * b_re);
                                acc_im <= acc_im + (a_re * b_im);
                            end
                        endcase
                        cnt <= cnt + 8'd1;
                        if (cnt == dot_length_reg - 8'd1) begin
                            state <= OUTPUT;
                        end
                    end else if (valid_mismatch || (cnt != 8'd0)) begin
                        // Dropped / mismatched valid mid-computation:
                        // latch the error immediately and zero the outputs.
                        state                 <= ERROR;
                        dot_product_error_out <= 1'b1;
                        dot_product_out       <= 32'd0;
                        dot_product_valid_out <= 1'b0;
                    end
                    // else: both valids low before any data arrived - wait.
                end
                OUTPUT: begin
                    if (complex_mode) begin
                        dot_product_out <= {acc_im[15:0], acc_re[15:0]};
                    end else begin
                        dot_product_out <= acc;
                    end
                    dot_product_valid_out <= 1'b1;
                    state                 <= IDLE;
                end
                ERROR: begin
                    // Recoverable: computation is reset; the sticky error
                    // flag clears on the next start_in.
                    dot_product_error_out <= 1'b1;
                    dot_product_valid_out <= 1'b0;
                    state                 <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end

endmodule
