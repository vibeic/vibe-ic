module arithmetic_progression_generator #(
    parameter DATA_WIDTH = 16,       // Width of the input data
    parameter SEQUENCE_LENGTH = 10   // Number of terms in the progression
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
    // WIDTH_OUT_VAL is sized so the largest possible term never overflows.
    // The maximum term is start_val + (SEQUENCE_LENGTH-1)*step_size, which is
    // bounded by (2^DATA_WIDTH - 1) * SEQUENCE_LENGTH < 2^(DATA_WIDTH+$clog2(SEQUENCE_LENGTH)).
    localparam WIDTH_OUT_VAL = DATA_WIDTH + $clog2(SEQUENCE_LENGTH);

  // ----------------------------------------
  // - Interface Definitions
  // ----------------------------------------
    input  logic clk;                          // Clock signal
    input  logic resetn;                       // Active-low reset
    input  logic enable;                       // Enable signal for the generator
    input  logic [DATA_WIDTH-1:0]    start_val; // Start value of the sequence
    input  logic [DATA_WIDTH-1:0]    step_size; // Step size of the sequence
    output logic [WIDTH_OUT_VAL-1:0] out_val;   // Current value of the sequence
    output logic done;                          // High when sequence generation is complete

  // ----------------------------------------
  // - Internal signals
  // ----------------------------------------
    logic [WIDTH_OUT_VAL-1:0]           current_val; // Register to hold the current value
    logic [$clog2(SEQUENCE_LENGTH)-1:0] counter;     // Counter to track sequence length

  // ----------------------------------------
  // - Procedural block
  // ----------------------------------------
    always_ff @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            current_val <= 0;
            counter     <= 0;
            done        <= 1'b0;
        end else if (enable) begin
            if (!done) begin
                // Generate one term per clock. The first term (counter == 0)
                // is start_val; every subsequent term adds step_size. The
                // output therefore appears one clock after enable is asserted.
                if (counter == 0)
                    current_val <= start_val;
                else
                    current_val <= current_val + step_size;

                // Assert done in the very cycle the final (SEQUENCE_LENGTH-th)
                // term is produced, so out_val holds that final value while
                // done is high. Stop advancing the counter so it never exceeds
                // its declared $clog2(SEQUENCE_LENGTH) width.
                if (counter == SEQUENCE_LENGTH - 1)
                    done <= 1'b1;
                else
                    counter <= counter + 1'b1;
            end
            // else: sequence complete -- done stays asserted and out_val holds
            //       the final value until resetn is applied.
        end
        // enable low: pause -- all state (current_val, counter, done) holds.
    end

  // ----------------------------------------
  // - Combinational Assignments
  // ----------------------------------------
    assign out_val = current_val;

endmodule
