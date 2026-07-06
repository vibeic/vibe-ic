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

    // Polynomial selection based on mode
    always_comb begin
        case (mode)
            4'b0000: feedback = lfsr[LFSR_WIDTH-16] ^ lfsr[LFSR_WIDTH-15];                // Mode 0: ( x^{16} + x^{15} + 1 )
            4'b0001: feedback = lfsr[LFSR_WIDTH-16] ^ lfsr[LFSR_WIDTH-14];                // Mode 1: ( x^{16} + x^{14} + 1 )
            4'b0010: feedback = lfsr[LFSR_WIDTH-16] ^ lfsr[LFSR_WIDTH-8] ^ lfsr[1];      // Mode 2: ( x^{16} + x^{8} + x + 1 )
            4'b0011: feedback = lfsr[LFSR_WIDTH-16] ^ lfsr[LFSR_WIDTH-8];                // Mode 3: ( x^{16} + x^{8} + 1 )
            4'b0100: feedback = lfsr[LFSR_WIDTH-16] ^ lfsr[LFSR_WIDTH-13] ^ lfsr[4];      // Mode 4: ( x^{16} + x^{13} + x^2 + 1 )
            4'b0101: feedback = lfsr[LFSR_WIDTH-16] ^ lfsr[LFSR_WIDTH-12];                // Mode 5: ( x^{16} + x^{12} + 1 )
            4'b0110: feedback = lfsr[LFSR_WIDTH-16] ^ lfsr[3] ^ lfsr[0];                 // Mode 6: ( x^{16} + x^3 + x + 1 )
            4'b0111: feedback = lfsr[LFSR_WIDTH-16] ^ lfsr[LFSR_WIDTH-11] ^ lfsr[4];      // Mode 7: ( x^{16} + x^{11} + x^4 + 1 )
            default: feedback = lfsr[LFSR_WIDTH-16];                                     // Default:( x^{16} + 1 )
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