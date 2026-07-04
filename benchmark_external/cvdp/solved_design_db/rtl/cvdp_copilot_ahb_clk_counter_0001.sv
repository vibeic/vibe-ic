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

    // Memory-mapped register offsets (same width as DATA_WIDTH)
    localparam [DATA_WIDTH-1:0] ADDR_START    = 'h00;
    localparam [DATA_WIDTH-1:0] ADDR_STOP     = 'h04;
    localparam [DATA_WIDTH-1:0] ADDR_COUNTER  = 'h08;
    localparam [DATA_WIDTH-1:0] ADDR_OVERFLOW = 'h0C;
    localparam [DATA_WIDTH-1:0] ADDR_MAXCNT   = 'h10;

    reg                  enable;   // counter enabled (set by START, cleared by STOP)
    reg                  overflow; // sticky overflow flag
    reg [DATA_WIDTH-1:0] maxcnt;   // configured maximum count value

    // ---------------------------------------------------------------
    // Synchronous control + counter, asynchronous active-low reset
    // ---------------------------------------------------------------
    always @(posedge HCLK or negedge HRESETn) begin
        if (!HRESETn) begin
            COUNTER  <= {DATA_WIDTH{1'b0}};
            overflow <= 1'b0;
            enable   <= 1'b0;
            maxcnt   <= {DATA_WIDTH{1'b0}};
        end else begin
            // AHB write decode (address + data presented in the same cycle)
            if (HSEL && HWRITE && HREADY) begin
                case (HADDR[DATA_WIDTH-1:0])
                    ADDR_START : enable <= 1'b1;
                    ADDR_STOP  : enable <= 1'b0;
                    ADDR_MAXCNT: maxcnt <= HWDATA;
                    default    : ; // no-op
                endcase
            end

            if (enable) begin
                COUNTER <= COUNTER + {{(DATA_WIDTH-1){1'b0}}, 1'b1};
                if ((COUNTER + {{(DATA_WIDTH-1){1'b0}}, 1'b1}) == maxcnt)
                    overflow <= 1'b1; // latch on reaching the max count
            end
        end
    end

    // ---------------------------------------------------------------
    // Combinational read data + OKAY response
    // ---------------------------------------------------------------
    always @(*) begin
        HRESP = 1'b0; // always OKAY
        case (HADDR[DATA_WIDTH-1:0])
            ADDR_COUNTER : HRDATA = COUNTER;
            ADDR_OVERFLOW: HRDATA = {{(DATA_WIDTH-1){1'b0}}, overflow};
            ADDR_MAXCNT  : HRDATA = maxcnt;
            default      : HRDATA = {DATA_WIDTH{1'b0}};
        endcase
    end

endmodule : ahb_clock_counter
