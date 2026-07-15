module ahb_clock_counter #(
    parameter ADDR_WIDTH = 32, // Width of the address bus
    parameter DATA_WIDTH = 32  // Width of the data bus
)(
    input wire HCLK,                       // AHB Clock
    input wire HRESETn,                    // AHB Reset (Active Low)
    input wire HSEL,                       // AHB Select
    input wire [ADDR_WIDTH-1:0] HADDR,     // AHB Address
    input wire HWRITE,                     // AHB Write Enable
    input wire [DATA_WIDTH-1:0] HWDATA,    // AHB Write Data
    input wire HREADY,                     // AHB Ready Signal
    output reg [DATA_WIDTH-1:0] HRDATA,    // AHB Read Data
    output reg HRESP,                      // AHB Response
    output reg [DATA_WIDTH-1:0] COUNTER    // Counter Output
);

    // ------------------------------------------------------------------
    // Memory-mapped register offsets (same width as DATA_WIDTH per spec).
    // ------------------------------------------------------------------
    localparam [ADDR_WIDTH-1:0] ADDR_START    = 'h00; // W : write 1 to start/resume
    localparam [ADDR_WIDTH-1:0] ADDR_STOP     = 'h04; // W : write 1 to stop
    localparam [ADDR_WIDTH-1:0] ADDR_COUNTER  = 'h08; // R : current counter value
    localparam [ADDR_WIDTH-1:0] ADDR_OVERFLOW = 'h0C; // R : overflow flag
    localparam [ADDR_WIDTH-1:0] ADDR_MAXCNT   = 'h10; // W : maximum count value

    // ------------------------------------------------------------------
    // Internal state.
    // ------------------------------------------------------------------
    reg                  enable;    // start/stop control (counter running)
    reg                  overflow;  // sticky overflow flag (cleared only by reset)
    reg [DATA_WIDTH-1:0] max_count; // programmed maximum count value

    wire write_en = HSEL && HWRITE && HREADY;

    // Next counter value (natural wrap at 2**DATA_WIDTH).
    wire [DATA_WIDTH-1:0] counter_next = COUNTER + {{(DATA_WIDTH-1){1'b0}}, 1'b1};

    // ------------------------------------------------------------------
    // Synchronous control + counter datapath (asynchronous active-low
    // reset).  Single-phase MMIO decode: HADDR/HWRITE/HWDATA are sampled
    // together and a write commits when HREADY is high.  The counter
    // increment uses the currently registered `enable`, so counting
    // starts/stops the cycle after the corresponding control write.
    // ------------------------------------------------------------------
    always @(posedge HCLK or negedge HRESETn) begin
        if (!HRESETn) begin
            enable    <= 1'b0;
            overflow  <= 1'b0;
            max_count <= {DATA_WIDTH{1'b0}};
            COUNTER   <= {DATA_WIDTH{1'b0}};
        end else begin
            // ---- Memory-mapped register writes ----
            if (write_en) begin
                case (HADDR)
                    ADDR_START:  if (HWDATA[0]) enable <= 1'b1; // start / resume
                    ADDR_STOP:   if (HWDATA[0]) enable <= 1'b0; // stop (retain value)
                    ADDR_MAXCNT: max_count <= HWDATA;           // configure limit
                    default: ;                                  // no writable storage
                endcase
            end

            // ---- Counter operation ----
            // Free-running while enabled.  Compare the NEXT value against
            // the limit so the sticky overflow flag asserts in the very
            // cycle the counter value reaches max_count (no off-by-one).
            // Stop retains the counter value; only reset zeroes it.
            if (enable) begin
                COUNTER <= counter_next;
                if (counter_next >= max_count)
                    overflow <= 1'b1; // sticky until HRESETn
            end
        end
    end

    // ------------------------------------------------------------------
    // Combinational read data path: HRDATA is keyed purely off the
    // address (zero wait states) so the bus master samples the live
    // register value in the same cycle it is addressed.  HRESP is always
    // OKAY (0).
    // ------------------------------------------------------------------
    always @(*) begin
        HRESP  = 1'b0;                       // OKAY response, always
        case (HADDR)
            ADDR_COUNTER:  HRDATA = COUNTER;
            ADDR_OVERFLOW: HRDATA = {{(DATA_WIDTH-1){1'b0}}, overflow};
            ADDR_MAXCNT:   HRDATA = max_count;
            default:       HRDATA = {DATA_WIDTH{1'b0}};
        endcase
    end

endmodule : ahb_clock_counter
