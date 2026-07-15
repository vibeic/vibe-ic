module arithmetic_progression_generator #(
    parameter DATA_WIDTH = 16,  // Width of the input data
    parameter SEQUENCE_LENGTH = 10 // Number of terms in the progression
)(
    clk,
    resetn,
    enable,
    start_val,
    step_size,
    out_val,
    done
);
  // ----------------------------------------
  // - Local parameter definition
  // ----------------------------------------

    // Guarded $clog2: avoid the math domain error when SEQUENCE_LENGTH == 0.
    // For SEQUENCE_LENGTH <= 1 the extra width contribution is 0 (matches
    // $clog2(1) == 0), so widths are unchanged for all valid lengths >= 1.
    localparam CLOG2_SEQ_LEN = (SEQUENCE_LENGTH <= 1) ? 0 : $clog2(SEQUENCE_LENGTH);
    localparam WIDTH_OUT_VAL = CLOG2_SEQ_LEN + DATA_WIDTH; // Bit width of out_val to prevent overflow
    localparam COUNTER_WIDTH = (CLOG2_SEQ_LEN == 0) ? 1 : CLOG2_SEQ_LEN; // At least 1 bit wide

  // ----------------------------------------
  // - Interface Definitions
  // ----------------------------------------
    input logic clk;                          // Clock signal
    input logic resetn;                       // Active-low reset
    input logic enable;                       // Enable signal for the generator
    input logic [DATA_WIDTH-1:0] start_val;   // Start value of the sequence
    input logic [DATA_WIDTH-1:0] step_size;   // Step size of the sequence
    output logic [WIDTH_OUT_VAL-1:0] out_val; // Current value of the sequence
    output logic done;                        // High when sequence generation is complete


  // ----------------------------------------
  // - Internal signals
  // ----------------------------------------
    logic [WIDTH_OUT_VAL-1:0] current_val;  // Register to hold the current value
    logic [COUNTER_WIDTH-1:0] counter;      // Counter to track sequence length

  // ----------------------------------------
  // - Procedural block
  // ----------------------------------------
    always_ff @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            current_val <= 0;
            counter <= 0;
            done <= 1'b0;
        end else if (enable && (SEQUENCE_LENGTH != 0)) begin
            // When SEQUENCE_LENGTH == 0 there is no sequence to generate:
            // out_val stays at its reset value (0) and done never asserts.
            if (!done) begin
                if (counter == 0) begin
                    current_val <= start_val; // Initialize with start value
                end else begin
                    current_val <= current_val + step_size; // Compute next term
                end

                if (counter < SEQUENCE_LENGTH - 1) begin
                    counter <= counter + 1; // Increment counter
                end else begin
                    done <= 1'b1; // Mark completion
                end
            end
        end
    end

  // ----------------------------------------
  // - Combinational Assignments
  // ----------------------------------------
    assign out_val = current_val;

endmodule
