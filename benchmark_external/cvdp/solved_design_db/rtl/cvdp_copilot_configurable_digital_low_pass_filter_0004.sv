// advanced_decimator_with_adaptive_peak_detection
//
// Decimation + signed peak detection.
//
// Behaviour (matched to the shipped cocotb reference model):
//   - Input samples are packed into data_in with sample slot s occupying
//     bits [DATA_WIDTH*s +: DATA_WIDTH] (slot 0 == LSB).
//   - Decimation selects one slot for every DEC_FACTOR slots:
//         data_out slot q = data_in slot (q * DEC_FACTOR),  q = 0 .. M-1
//     where M = N / DEC_FACTOR.
//   - peak_value = signed maximum across the M decimated slots.
//   - Latency is exactly 1 clock cycle: the input bus and valid are
//     registered on the rising edge (async active-high reset clears them);
//     decimation, peak detection and output packing are combinational from
//     the registered data.

module advanced_decimator_with_adaptive_peak_detection #(
    parameter int N          = 8,
    parameter int DATA_WIDTH = 16,
    parameter int DEC_FACTOR = 4
) (
    input  wire                                       clk,
    input  wire                                       reset,
    input  wire                                       valid_in,
    input  wire [DATA_WIDTH*N-1:0]                    data_in,
    output reg                                        valid_out,
    output wire [DATA_WIDTH*(N/DEC_FACTOR)-1:0]       data_out,
    output wire [DATA_WIDTH-1:0]                       peak_value
);

    localparam int M = N / DEC_FACTOR;

    // ------------------------------------------------------------------
    // 1. Input registering + validation control (sequential, async reset)
    // ------------------------------------------------------------------
    reg [DATA_WIDTH*N-1:0] data_reg;

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            data_reg  <= '0;
            valid_out <= 1'b0;
        end else begin
            data_reg  <= data_in;
            valid_out <= valid_in;
        end
    end

    // ------------------------------------------------------------------
    // 2. Decimation + output packing (combinational from registered data)
    //    data_out slot q = data_reg slot (q * DEC_FACTOR)
    // ------------------------------------------------------------------
    genvar q;
    generate
        for (q = 0; q < M; q = q + 1) begin : gen_decimate
            assign data_out[DATA_WIDTH*q +: DATA_WIDTH] =
                   data_reg[DATA_WIDTH*(q*DEC_FACTOR) +: DATA_WIDTH];
        end
    endgenerate

    // ------------------------------------------------------------------
    // 3. Peak detection (signed maximum across decimated samples)
    // ------------------------------------------------------------------
    reg signed [DATA_WIDTH-1:0] peak_comb;
    integer k;
    always @(*) begin
        peak_comb = $signed(data_out[DATA_WIDTH-1:0]); // slot 0
        for (k = 1; k < M; k = k + 1) begin
            if ($signed(data_out[DATA_WIDTH*k +: DATA_WIDTH]) > peak_comb)
                peak_comb = $signed(data_out[DATA_WIDTH*k +: DATA_WIDTH]);
        end
    end

    assign peak_value = peak_comb;

endmodule
