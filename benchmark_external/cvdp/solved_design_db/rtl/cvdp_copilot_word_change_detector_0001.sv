module Word_Change_Pulse#(
    parameter DATA_WIDTH = 8 // Default word width
) (
    input  wire                  clk,               // Clock signal for synchronizing operations
    input  wire                  reset,             // Reset signal to initialize the module
    input  wire [DATA_WIDTH-1:0] data_in,           // Input data, width defined by parameter DATA_WIDTH
    input  wire [DATA_WIDTH-1:0] mask,              // Mask signal to enable/disable change detection for each bit
    input  wire [DATA_WIDTH-1:0] match_pattern,     // Pattern to match for generating the pulse
    input  wire                  enable,            // Enable signal to allow module operation
    input  wire                  latch_pattern,     // Signal to latch the match pattern
    output reg                   word_change_pulse, // Output signal indicating a change in any bit of data_in
    output reg                   pattern_match_pulse, // Output signal indicating a match with the pattern
    output reg [DATA_WIDTH-1:0]  latched_pattern    // Latched pattern for comparison
);

    wire [DATA_WIDTH-1:0] change_pulses;

    reg [DATA_WIDTH-1:0] masked_data_in;
    reg [DATA_WIDTH-1:0] masked_change_pulses;
    reg                  match_detected;

    genvar i;

    // Instantiate one Bit_Change_Detector per input bit.
    generate
        for (i = 0; i < DATA_WIDTH; i = i + 1) begin : gen_bit_change
            Bit_Change_Detector u_bcd (
                .clk         (clk),
                .reset       (reset),
                .bit_in      (data_in[i]),
                .change_pulse(change_pulses[i])
            );
        end
    endgenerate

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            masked_data_in       <= {DATA_WIDTH{1'b0}};
            masked_change_pulses <= {DATA_WIDTH{1'b0}};
            word_change_pulse    <= 1'b0;
            match_detected       <= 1'b0;
            pattern_match_pulse  <= 1'b0;
            latched_pattern      <= {DATA_WIDTH{1'b0}};
        end else if (enable) begin
            // Latch the current match_pattern when requested.
            if (latch_pattern)
                latched_pattern <= match_pattern;

            // Mask data_in and register the per-bit change pulses.  The detected
            // change is first registered into masked_change_pulses, and the
            // word_change_pulse is asserted one further clock cycle later, so the
            // pulse appears one cycle after the change is captured.
            masked_data_in       <= data_in & mask;
            masked_change_pulses <= change_pulses & mask;
            word_change_pulse    <= |masked_change_pulses;

            // Compare the masked input data with the (masked) latched pattern.
            if ((data_in & mask) == (latched_pattern & mask)) begin
                match_detected      <= 1'b1;
                pattern_match_pulse <= 1'b1;
            end else begin
                match_detected      <= 1'b0;
                pattern_match_pulse <= 1'b0;
            end
        end else begin
            // When disabled, hold no pulses active.
            masked_change_pulses <= {DATA_WIDTH{1'b0}};
            word_change_pulse    <= 1'b0;
            pattern_match_pulse  <= 1'b0;
        end
    end

endmodule


// Bit_Change_Detector Module
module Bit_Change_Detector (
    input  wire clk,          // Clock signal
    input  wire reset,        // Reset signal to initialize the module
    input  wire bit_in,       // Single bit input to detect changes
    output reg  change_pulse  // Pulse signal indicating a change in the input bit
);

    reg bit_in_d;

    always @(posedge clk or posedge reset) begin
        if (reset)
            bit_in_d <= 1'b0;      // initialize stored previous value
        else
            bit_in_d <= bit_in;    // update the previous state
    end

    // Generate change_pulse immediately when the current bit differs from the
    // previously stored value.
    always @(*) begin
        change_pulse = bit_in ^ bit_in_d;
    end

endmodule
