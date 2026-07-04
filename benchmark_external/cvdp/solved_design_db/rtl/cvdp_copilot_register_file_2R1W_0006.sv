module cvdp_copilot_register_file_2R1W #(
    parameter DATA_WIDTH = 32,  // Configurable data width
    parameter DEPTH      = 32   // Number of register entries
) (
    // Inputs
    input  logic [DATA_WIDTH-1:0] din,    // Input data
    input  logic [4:0] wad1,              // Write address
    input  logic [4:0] rad1,              // Read address 1
    input  logic [4:0] rad2,              // Read address 2
    input  logic wen1,                    // Write-enable signal
    input  logic ren1,                    // Read-enable signal 1
    input  logic ren2,                    // Read-enable signal 2
    input  logic clk,                     // Clock signal
    input  logic resetn,                  // Active-low reset
    input  logic test_mode,               // BIST activation (active high)

    // Outputs
    output logic [DATA_WIDTH-1:0] dout1,   // Output data 1
    output logic [DATA_WIDTH-1:0] dout2,   // Output data 2
    output logic collision,                // Collision flag
    output logic bist_done,                // BIST sequence complete
    output logic bist_fail                 // BIST detected a mismatch
);

    localparam ADDRW = 5;  // address width for up to 32 entries

    // -------------------------------
    // Internal Registers and Wires
    // -------------------------------
    logic [DATA_WIDTH-1:0] rf_mem [0:DEPTH-1];
    logic [DEPTH-1:0]      rf_valid;       // Validity of each register entry
    integer i;

    // -------------------------------
    // BIST control
    // -------------------------------
    localparam [1:0] BIST_IDLE  = 2'b00,
                     BIST_WRITE = 2'b01,
                     BIST_READ  = 2'b10,
                     BIST_DONE  = 2'b11;

    logic [1:0]       bist_state;
    logic [ADDRW:0]   bist_addr;     // 0..DEPTH (extra bit for the terminal count)

    // Deterministic march pattern: each location's expected data is its address.
    function automatic logic [DATA_WIDTH-1:0] pat(input logic [ADDRW-1:0] a);
        pat = { {(DATA_WIDTH-ADDRW){1'b0}}, a };
    endfunction

    // NOTE on clocking: every flop in this design is clocked by the primary `clk`.
    // The original starter RTL gated the write clock through an enable latch, which
    // made the gated clock lag `clk` by a delta cycle; a single-cycle `wen1` pulse
    // driven off `clk` then raced that lagged edge and was dropped. Using the
    // ungated `clk` for the synchronous write makes single-cycle writes reliable
    // and keeps the write path aligned with the BIST FSM (also on `clk`).

    // -------------------------------
    // Register File Memory (single driver): BIST write during test_mode,
    // otherwise the normal write port. Normal writes are disabled in test_mode.
    // -------------------------------
    always_ff @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            for (i = 0; i < DEPTH; i = i + 1) begin
                rf_mem[i] <= {DATA_WIDTH{1'b0}};
            end
            rf_valid <= {DEPTH{1'b0}};
        end
        else if (test_mode) begin
            if (bist_state == BIST_WRITE) begin
                rf_mem[bist_addr[ADDRW-1:0]]   <= pat(bist_addr[ADDRW-1:0]);
                rf_valid[bist_addr[ADDRW-1:0]] <= 1'b1;
            end
        end
        else if (wen1) begin
            rf_mem[wad1]    <= din;  // Write operation
            rf_valid[wad1]  <= 1'b1; // Mark written address as valid
        end
    end

    // -------------------------------
    // BIST FSM + compare (plain clock)
    // -------------------------------
    always_ff @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            bist_state <= BIST_IDLE;
            bist_addr  <= '0;
            bist_done  <= 1'b0;
            bist_fail  <= 1'b0;
        end
        else if (test_mode) begin
            case (bist_state)
                BIST_IDLE: begin
                    bist_state <= BIST_WRITE;
                    bist_addr  <= '0;
                    bist_done  <= 1'b0;
                    bist_fail  <= 1'b0;
                end
                BIST_WRITE: begin
                    if (bist_addr == (DEPTH-1)) begin
                        bist_addr  <= '0;
                        bist_state <= BIST_READ;
                    end else begin
                        bist_addr <= bist_addr + 1'b1;
                    end
                end
                BIST_READ: begin
                    if (rf_mem[bist_addr[ADDRW-1:0]] != pat(bist_addr[ADDRW-1:0]))
                        bist_fail <= 1'b1;
                    if (bist_addr == (DEPTH-1)) begin
                        bist_state <= BIST_DONE;
                    end else begin
                        bist_addr <= bist_addr + 1'b1;
                    end
                end
                BIST_DONE: begin
                    bist_done <= 1'b1;
                end
                default: bist_state <= BIST_IDLE;
            endcase
        end
        else begin
            bist_state <= BIST_IDLE;
            bist_done  <= 1'b0;
            bist_fail  <= 1'b0;
        end
    end

    // -------------------------------
    // Read Data Output Logic for Port 1 (COMBINATIONAL read).
    // A 2R1W register file uses zero-latency read ports: a value written on a prior
    // edge is visible the moment ren1+rad1 are presented, with no extra
    // registered-read delay. Disabled in test_mode (normal ops off during BIST).
    // -------------------------------
    always_comb begin
        if (!test_mode && ren1)
            dout1 = rf_valid[rad1] ? rf_mem[rad1] : '0;
        else
            dout1 = '0;
    end

    // -------------------------------
    // Read Data Output Logic for Port 2 (COMBINATIONAL read).
    // -------------------------------
    always_comb begin
        if (!test_mode && ren2)
            dout2 = rf_valid[rad2] ? rf_mem[rad2] : '0;
        else
            dout2 = '0;
    end

    // -------------------------------
    // Collision Detection Logic with Original Clock (disabled in test_mode)
    // -------------------------------
    always_ff @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            collision <= 1'b0;
        end
        else if (test_mode) begin
            collision <= 1'b0;
        end
        else begin
            collision <= (
                (ren1 && ren2 && (rad1 == rad2)) ||          // Both reads to the same address
                (wen1 && ren1 && (wad1 == rad1)) ||          // Write and read to the same address
                (wen1 && ren2 && (wad1 == rad2))             // Write and read to the same address
            );
        end
    end

endmodule
