module dot_product (
    input               clk_in,                     // Clock signal
    input               reset_in,                   // Asynchronous Reset signal, Active HIGH
    input               start_in,                   // Start computation signal
    input       [7:0]   dot_length_in,              // Length of the dot product vectors (up to 256)
    input       [31:0]  vector_a_in,                // Input vector A {Imag[31:16], Real[15:0]}
    input               vector_a_valid_in,          // Valid signal for vector A
    input       [31:0]  vector_b_in,                // Input vector B {Imag[31:16], Real[15:0]}
    input               vector_b_valid_in,          // Valid signal for vector B
    input               a_complex_in,               // Vector A is complex (1) or real (0)
    input               b_complex_in,               // Vector B is complex (1) or real (0)
    output reg  [31:0]  dot_product_out,            // Output dot product result (32-bit)
    output reg          dot_product_valid_out,      // Valid signal for dot product output
    output reg          dot_product_error_out       // Error signal (valid dropped mid-computation)
);

    typedef enum logic [1:0] {
        IDLE    = 2'b00,
        COMPUTE = 2'b01,
        OUTPUT  = 2'b10,
        ERROR   = 2'b11
    } state_t;

    state_t state;

    // -----------------------------------------------------------------
    // Registered inputs (all inputs registered for synchronization)
    // -----------------------------------------------------------------
    reg  [7:0]  dot_length_r;
    reg  [31:0] vector_a_r, vector_b_r;
    reg         vector_a_valid_r, vector_b_valid_r;
    reg         a_complex_r, b_complex_r;
    reg         start_r;

    always @(posedge clk_in or posedge reset_in) begin
        if (reset_in) begin
            dot_length_r     <= 8'b0;
            vector_a_r       <= 32'b0;
            vector_b_r       <= 32'b0;
            vector_a_valid_r <= 1'b0;
            vector_b_valid_r <= 1'b0;
            a_complex_r      <= 1'b0;
            b_complex_r      <= 1'b0;
            start_r          <= 1'b0;
        end else begin
            dot_length_r     <= dot_length_in;
            vector_a_r       <= vector_a_in;
            vector_b_r       <= vector_b_in;
            vector_a_valid_r <= vector_a_valid_in;
            vector_b_valid_r <= vector_b_valid_in;
            a_complex_r      <= a_complex_in;
            b_complex_r      <= b_complex_in;
            start_r          <= start_in;
        end
    end

    // Real/Imaginary field extraction (signed, for complex/mixed modes)
    wire signed [15:0] a_re = vector_a_r[15:0];
    wire signed [15:0] a_im = vector_a_r[31:16];
    wire signed [15:0] b_re = vector_b_r[15:0];
    wire signed [15:0] b_im = vector_b_r[31:16];

    // Unsigned operands for real-only mode (real operands span the full
    // unsigned range, e.g. up to 0xFFFF, so the product must be unsigned).
    wire [15:0] a_re_u = vector_a_r[15:0];
    wire [15:0] b_re_u = vector_b_r[15:0];

    reg signed [31:0] acc_re, acc_im;
    reg [7:0]         cnt;
    reg [7:0]         length_reg;
    reg               a_cx, b_cx;

    always @(posedge clk_in or posedge reset_in) begin
        if (reset_in) begin
            state                 <= IDLE;
            acc_re                <= 32'sb0;
            acc_im                <= 32'sb0;
            cnt                   <= 8'b0;
            dot_product_out       <= 32'b0;
            dot_product_valid_out <= 1'b0;
            dot_product_error_out <= 1'b0;
            length_reg            <= 8'b0;
            a_cx                  <= 1'b0;
            b_cx                  <= 1'b0;
        end else begin
            case (state)
                IDLE: begin
                    length_reg <= dot_length_r;
                    a_cx       <= a_complex_r;
                    b_cx       <= b_complex_r;
                    if (start_r) begin
                        // A new computation clears any held valid/error result.
                        dot_product_valid_out <= 1'b0;
                        dot_product_error_out <= 1'b0;
                        state  <= COMPUTE;
                        acc_re <= 32'sb0;
                        acc_im <= 32'sb0;
                        cnt    <= 8'b0;
                    end
                end

                COMPUTE: begin
                    if (!(vector_a_valid_r && vector_b_valid_r)) begin
                        // A valid signal dropped (or the two are mismatched)
                        // mid-computation -> error.
                        state                 <= ERROR;
                        dot_product_error_out <= 1'b1;
                        dot_product_out       <= 32'b0;
                        dot_product_valid_out <= 1'b0;
                    end else begin
                        if (a_cx && b_cx) begin
                            // Complex * complex
                            acc_re <= acc_re + (a_re * b_re - a_im * b_im);
                            acc_im <= acc_im + (a_re * b_im + a_im * b_re);
                        end else if (a_cx && !b_cx) begin
                            // A complex, B real
                            acc_re <= acc_re + (a_re * b_re);
                            acc_im <= acc_im + (a_im * b_re);
                        end else if (!a_cx && b_cx) begin
                            // A real, B complex
                            acc_re <= acc_re + (a_re * b_re);
                            acc_im <= acc_im + (a_re * b_im);
                        end else begin
                            // Real * real (unsigned)
                            acc_re <= acc_re + $signed({16'b0, a_re_u} * {16'b0, b_re_u});
                        end

                        cnt <= cnt + 8'b1;
                        if (cnt == length_reg - 8'b1)
                            state <= OUTPUT;
                    end
                end

                OUTPUT: begin
                    if (a_cx || b_cx)
                        dot_product_out <= {acc_im[15:0], acc_re[15:0]};
                    else
                        dot_product_out <= acc_re;
                    dot_product_valid_out <= 1'b1;
                    state                 <= IDLE;
                end

                ERROR: begin
                    // Hold the error result until the next start / reset.
                    dot_product_error_out <= 1'b1;
                    dot_product_out       <= 32'b0;
                    dot_product_valid_out <= 1'b0;
                    state                 <= IDLE;
                end

                default: state <= IDLE;
            endcase
        end
    end

endmodule
