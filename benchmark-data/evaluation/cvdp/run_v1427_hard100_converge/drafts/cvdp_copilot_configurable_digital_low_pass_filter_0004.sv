// ============================================================================
// advanced_decimator_with_adaptive_peak_detection
// ----------------------------------------------------------------------------
// Packed-bus decimation + signed peak detection.
//
// Behavior (per spec):
//   1. Register the packed input bus (and valid) on the rising edge of clk;
//      an asynchronous active-high reset clears both -> fixed 1-cycle latency.
//   2. Combinationally unpack the registered bus into N signed samples.
//   3. Decimation: select one sample every DEC_FACTOR positions -> N/DEC_FACTOR
//      samples.
//   4. Peak detection: signed maximum over the decimated samples (starts from
//      the first decimated sample, then keeps the running max).
//   5. Pack the decimated samples into data_out (combinational).
//   6. valid_out is the registered valid_in (cleared on reset).
//
//   data_out and peak_value are combinational functions of the registered
//   input, so they are valid in the same cycle valid_out asserts (latency = 1).
//
// Indexing convention is taken from the spec's worked example:
//   data_in  = {16'd10,16'd20,16'd30,16'd40,16'd50,16'd60,16'd70,16'd80}
//   data_out = {16'd10,16'd50},  peak_value = 16'd50
// So logical sample index 0 = the FIRST-written element = the MOST-significant
// slot of the packed bus. Input sample k occupies bits
// [(N-1-k)*DATA_WIDTH +: DATA_WIDTH]; decimated sample q = input sample
// q*DEC_FACTOR and is packed at [(DEC_N-1-q)*DATA_WIDTH +: DATA_WIDTH] of
// data_out. (Verified against the example: MSB-first reproduces {10,50}/50;
// a naive LSB-first mapping would wrongly yield {40,80}/80.)
// ============================================================================
module advanced_decimator_with_adaptive_peak_detection #(
    parameter integer N          = 8,   // total number of input samples (> 1)
    parameter integer DATA_WIDTH = 16,  // bit-width of each sample (> 1)
    parameter integer DEC_FACTOR = 4    // decimation factor (integer divisor of N)
) (
    input  wire                                     clk,
    input  wire                                     reset,      // async, active-high
    input  wire                                     valid_in,
    input  wire  [DATA_WIDTH*N-1:0]                 data_in,    // N packed signed samples
    output reg                                      valid_out,
    output reg   [DATA_WIDTH*(N/DEC_FACTOR)-1:0]    data_out,   // N/DEC_FACTOR packed samples
    output reg   [DATA_WIDTH-1:0]                   peak_value  // signed peak of decimated set
);

    // Number of decimated output samples.
    localparam integer DEC_N = N / DEC_FACTOR;

    // ------------------------------------------------------------------
    // 1) Input registering (1-cycle pipeline): packed data + valid together,
    //    asynchronous active-high reset clears both.
    // ------------------------------------------------------------------
    reg [DATA_WIDTH*N-1:0] data_reg;

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            data_reg  <= {(DATA_WIDTH*N){1'b0}};
            valid_out <= 1'b0;
        end else begin
            data_reg  <= data_in;
            valid_out <= valid_in;
        end
    end

    // ------------------------------------------------------------------
    // 2)-5) Combinational unpack / decimate / signed peak / pack from data_reg.
    // ------------------------------------------------------------------
    integer                      q;
    reg signed [DATA_WIDTH-1:0]  dec_sample;  // current decimated sample
    reg signed [DATA_WIDTH-1:0]  peak_c;      // running signed maximum

    always @(*) begin
        data_out = {(DATA_WIDTH*DEC_N){1'b0}};

        // Initialize peak with the first decimated sample (input sample index 0,
        // i.e. the most-significant slot of the packed bus).
        peak_c = $signed(data_reg[(N-1)*DATA_WIDTH +: DATA_WIDTH]);

        for (q = 0; q < DEC_N; q = q + 1) begin
            // decimated sample q = input sample (q*DEC_FACTOR)
            dec_sample = $signed(data_reg[(N-1-(q*DEC_FACTOR))*DATA_WIDTH +: DATA_WIDTH]);

            // pack MSB-first: logical index 0 in the most-significant slot
            data_out[(DEC_N-1-q)*DATA_WIDTH +: DATA_WIDTH] = dec_sample;

            // signed running maximum over the decimated samples
            if (dec_sample > peak_c)
                peak_c = dec_sample;
        end

        peak_value = peak_c;
    end

endmodule
