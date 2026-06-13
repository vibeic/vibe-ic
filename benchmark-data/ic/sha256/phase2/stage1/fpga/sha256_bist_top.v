//============================================================================
// sha256_bist_top.v -- self-contained on-FPGA BIST harness for the sha256
// memory-mapped accelerator (DE10-Lite / MAX10).
//
// The sha256 core has a memory-mapped (cs/we/address/write_data) interface,
// NOT a serial board-pin contract, so the board-appropriate digital
// verification is an ON-CHIP BIST engine: a small FSM that drives the DUT's
// register interface to run a NIST FIPS-180-4 known-answer test pattern,
// reads back the 256-bit digest, and compares it bit-exact against the golden
// constant. Result is shown on the LEDs (no host cable needed).
//
// Test patterns driven through the bus (each is a full register-interface
// transaction sequence = "pattern"):
//   P1: write BLOCK0..15 with padded "abc"        (16 patterns)
//   P2: write CTRL = MODE=1|INIT                   (1 pattern)
//   P3: poll STATUS.READY                          (N patterns)
//   P4: read DIGEST0..7                            (8 patterns)
//   P5: compare vs golden ba7816bf..f20015ad
// LEDR[0] = TEST_PASS (1 when digest matches golden)
// LEDR[1] = TEST_DONE
// LEDR[9] = heartbeat (proves clock alive)
// LEDR[8:2] = low 7 bits of the BIST FSM state (observability)
//============================================================================
`default_nettype none

module sha256_bist_top (
    input  wire        CLOCK_50,
    input  wire [1:0]  KEY,       // KEY[0] = active-LOW reset
    output wire [9:0]  LEDR
);
    wire clk = CLOCK_50;
    wire rst_n = KEY[0];          // active-LOW push-button reset

    // ---- DUT register-interface wires ----
    reg         cs, we;
    reg  [7:0]  address;
    reg  [31:0] write_data;
    wire [31:0] read_data;
    wire        error;

    sha256 dut (
        .clk(clk), .reset_n(rst_n),
        .cs(cs), .we(we), .address(address), .write_data(write_data),
        .read_data(read_data), .error(error)
    );

    // ---- golden "abc" SHA-256 digest (NIST FIPS-180-4) ----
    localparam [255:0] GOLD =
        256'hba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad;

    // padded "abc" block words BLOCK0..15 (BLOCK0 = MSW)
    function [31:0] abc_word; input [3:0] idx; begin
        case (idx)
            4'd0:   abc_word = 32'h61626380;
            4'd15:  abc_word = 32'h00000018;
            default:abc_word = 32'h00000000;
        endcase
    end endfunction

    // ---- BIST FSM ----
    localparam [3:0] B_RESET   = 4'd0,
                     B_LOADBLK = 4'd1,
                     B_WRBLK   = 4'd2,
                     B_CTRL    = 4'd3,
                     B_POLL    = 4'd4,
                     B_RDDIG   = 4'd5,
                     B_CMP     = 4'd6,
                     B_DONE    = 4'd7;
    reg [3:0]  bstate;
    reg [4:0]  idx;            // block-word / digest-word index
    reg [255:0] got;
    reg        test_pass, test_done;
    reg [1:0]  phase;          // 0=drive,1=settle inside a bus op
    reg        seen_busy;      // poll: confirm READY went LOW before waiting HIGH
    reg [9:0]  poll_wait;      // small launch-latency wait counter

    always @(posedge clk) begin
        if (!rst_n) begin
            cs<=0; we<=0; address<=0; write_data<=0;
            bstate<=B_LOADBLK; idx<=0; got<=0;
            test_pass<=0; test_done<=0; phase<=0;
            seen_busy<=0; poll_wait<=0;
        end else begin
            cs<=0; we<=0;           // default deassert
            case (bstate)
            //--------------------------------------------------
            B_LOADBLK: begin
                idx<=0; bstate<=B_WRBLK; phase<=0;
            end
            //--------------------------------------------------
            B_WRBLK: begin
                // write BLOCK[idx] = abc_word(idx); one cycle per write
                cs<=1; we<=1; address<=8'h10+{3'b0,idx}; write_data<=abc_word(idx[3:0]);
                if (idx==5'd15) begin idx<=0; bstate<=B_CTRL; end
                else            idx<=idx+5'd1;
            end
            //--------------------------------------------------
            B_CTRL: begin
                // CTRL = MODE(bit2)=1, INIT(bit0)=1
                cs<=1; we<=1; address<=8'h08; write_data<=32'h00000005;
                bstate<=B_POLL; phase<=0; seen_busy<=0; poll_wait<=0;
            end
            //--------------------------------------------------
            B_POLL: begin
                // Wait a few cycles for the core to LAUNCH (READY->0), confirm it
                // went BUSY (seen_busy), THEN wait for READY->1. This avoids the
                // race where the just-issued INIT hasn't yet pulled READY low.
                cs<=1; we<=0; address<=8'h09;
                if (phase==2'd1) begin
                    if (!seen_busy) begin
                        if (read_data[0]==1'b0) seen_busy<=1'b1;   // core is busy
                        else if (poll_wait<10'd20) poll_wait<=poll_wait+10'd1; // wait launch
                        phase<=0;
                    end else begin
                        // already saw busy: now wait for completion
                        if (read_data[0]==1'b1) begin idx<=0; bstate<=B_RDDIG; phase<=0; end
                        else phase<=0;
                    end
                end else phase<=phase+2'd1;
            end
            //--------------------------------------------------
            B_RDDIG: begin
                // read DIGEST[idx] (0x20+idx); combinational read settles same cycle
                cs<=1; we<=0; address<=8'h20+{3'b0,idx};
                if (phase==2'd1) begin
                    got[(7-idx)*32 +: 32] <= read_data;
                    if (idx==5'd7) begin bstate<=B_CMP; phase<=0; end
                    else begin idx<=idx+5'd1; phase<=0; end
                end else phase<=phase+2'd1;
            end
            //--------------------------------------------------
            B_CMP: begin
                test_pass <= (got==GOLD);
                test_done <= 1'b1;
                bstate    <= B_DONE;
            end
            //--------------------------------------------------
            B_DONE: begin
                test_done <= 1'b1;
            end
            default: bstate<=B_DONE;
            endcase
        end
    end

    // ---- heartbeat (clock-alive) ----
    reg [25:0] hb = 0;
    always @(posedge clk) hb <= hb + 26'd1;

    assign LEDR[0]   = test_pass;
    assign LEDR[1]   = test_done;
    assign LEDR[8:2] = {3'b0, bstate};
    assign LEDR[9]   = hb[25];

endmodule

`default_nettype wire
