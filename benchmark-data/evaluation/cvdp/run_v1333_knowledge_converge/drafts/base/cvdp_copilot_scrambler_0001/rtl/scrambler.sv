module scrambler #(
    parameter DATA_WIDTH = 128   // Width of input data
) (
    input  logic                  clk,        // Clock signal
    input  logic                  rst_n,      // Active-low reset
    input  logic [DATA_WIDTH-1:0] data_in,    // Input data
    input  logic [3:0]            mode,       // Mode to select polynomial
    output logic [DATA_WIDTH-1:0] data_out    // Scrambled data
);

    localparam LFSR_WIDTH = 16;    // Width of the LFSR
    localparam [LFSR_WIDTH-1:0] LFSR_INIT = {1'b0,1'b1,{(LFSR_WIDTH-2){1'b0}}};
    // LFSR registers and feedback logic
    logic [LFSR_WIDTH-1:0] lfsr;
    logic feedback;

    // Polynomial selection based on mode.
    // The LFSR shifts left ({lfsr[LFSR_WIDTH-2:0], feedback}), so the outgoing
    // MSB (bit LFSR_WIDTH-1) is the x^16 feedback term. A term x^p taps bit p-1.
    always_comb begin
        case (mode)
            4'b0000: feedback = lfsr[LFSR_WIDTH-1] ^ lfsr[14];                    // Mode 0: ( x^{16} + x^{15} + 1 )
            4'b0001: feedback = lfsr[LFSR_WIDTH-1] ^ lfsr[13];                    // Mode 1: ( x^{16} + x^{14} + 1 )
            4'b0010: feedback = lfsr[LFSR_WIDTH-1] ^ lfsr[7]  ^ lfsr[0];          // Mode 2: ( x^{16} + x^{8} + x + 1 )
            4'b0011: feedback = lfsr[LFSR_WIDTH-1] ^ lfsr[7];                     // Mode 3: ( x^{16} + x^{8} + 1 )
            4'b0100: feedback = lfsr[LFSR_WIDTH-1] ^ lfsr[12] ^ lfsr[1];          // Mode 4: ( x^{16} + x^{13} + x^2 + 1 )
            4'b0101: feedback = lfsr[LFSR_WIDTH-1] ^ lfsr[11];                    // Mode 5: ( x^{16} + x^{12} + 1 )
            4'b0110: feedback = lfsr[LFSR_WIDTH-1] ^ lfsr[2]  ^ lfsr[0];          // Mode 6: ( x^{16} + x^3 + x + 1 )
            4'b0111: feedback = lfsr[LFSR_WIDTH-1] ^ lfsr[10] ^ lfsr[3];          // Mode 7: ( x^{16} + x^{11} + x^4 + 1 )
            default: feedback = lfsr[LFSR_WIDTH-1] ^ lfsr[0];                     // Default:( x^{16} + x + 1 )
        endcase
    end

    // LFSR shift logic
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            lfsr <= LFSR_INIT; // Initialize LFSR with a fixed value
        end else begin
            lfsr <= {lfsr[LFSR_WIDTH-2:0], feedback};
        end
    end

    // Scramble data block
    genvar i;
    generate
        for (i = 0; i < DATA_WIDTH; i++) begin
            assign data_out[i] = data_in[i] ^ lfsr[i % LFSR_WIDTH];
        end
    endgenerate

endmodule
