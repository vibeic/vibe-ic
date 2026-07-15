// cvdp_copilot_apb_gpio
// APB-compatible GPIO peripheral with configurable width, bidirectional
// direction control, edge/level interrupt generation, and two-stage input
// synchronization.  Single-cycle (zero wait-state) APB slave: pready is held
// high and pslverr is held low per the specification.
module cvdp_copilot_apb_gpio #(
    parameter GPIO_WIDTH = 8
) (
    // -------- APB interface --------
    input  wire                    pclk,      // rising-edge clock
    input  wire                    preset_n,  // active-low async reset
    input  wire                    psel,      // peripheral select
    input  wire [7:2]              paddr,     // word-aligned address
    input  wire                    penable,   // transfer enable (ACCESS phase)
    input  wire                    pwrite,    // 1 = write, 0 = read
    input  wire [31:0]             pwdata,    // write data
    output reg  [31:0]             prdata,    // read data
    output wire                    pready,    // always high (no wait states)
    output wire                    pslverr,   // always low (no errors)

    // -------- GPIO pins --------
    input  wire [GPIO_WIDTH-1:0]   gpio_in,     // pad inputs
    output wire [GPIO_WIDTH-1:0]   gpio_out,    // pad outputs (from reg_out)
    output wire [GPIO_WIDTH-1:0]   gpio_enable, // direction: 1=output, 0=input
    output wire [GPIO_WIDTH-1:0]   gpio_int,    // per-pin interrupt
    output wire                    comb_int     // OR of all gpio_int
);

    // -----------------------------------------------------------------
    // Register-map word offsets (paddr is byte-address bits [7:2], i.e.
    // already word-aligned -> compare against byte_addr>>2).
    // -----------------------------------------------------------------
    localparam [5:0] ADDR_INPUT  = 6'd0;  // 0x00 GPIO Input Data   (RO)
    localparam [5:0] ADDR_OUTPUT = 6'd1;  // 0x04 GPIO Output Data
    localparam [5:0] ADDR_OE     = 6'd2;  // 0x08 GPIO Output Enable
    localparam [5:0] ADDR_IE     = 6'd3;  // 0x0C GPIO Interrupt Enable
    localparam [5:0] ADDR_ITYPE  = 6'd4;  // 0x10 GPIO Interrupt Type (edge/level)
    localparam [5:0] ADDR_IPOL   = 6'd5;  // 0x14 GPIO Interrupt Polarity
    localparam [5:0] ADDR_ISTATE = 6'd6;  // 0x18 GPIO Interrupt State (RO)

    // -----------------------------------------------------------------
    // Configuration registers
    // -----------------------------------------------------------------
    reg [GPIO_WIDTH-1:0] reg_out;    // output data
    reg [GPIO_WIDTH-1:0] reg_oe;     // output enable / direction
    reg [GPIO_WIDTH-1:0] reg_ie;     // interrupt enable
    reg [GPIO_WIDTH-1:0] reg_itype;  // interrupt type  : 1=edge, 0=level
    reg [GPIO_WIDTH-1:0] reg_ipol;   // interrupt polar : 1=active-high, 0=active-low

    // -----------------------------------------------------------------
    // Two-stage input synchronizer (metastability mitigation)
    // -----------------------------------------------------------------
    reg [GPIO_WIDTH-1:0] gpio_in_s1;
    reg [GPIO_WIDTH-1:0] gpio_in_s2;    // synchronized value used everywhere
    reg [GPIO_WIDTH-1:0] gpio_in_s2_d;  // delayed by one cycle for edge detect

    always @(posedge pclk or negedge preset_n) begin
        if (!preset_n) begin
            gpio_in_s1   <= {GPIO_WIDTH{1'b0}};
            gpio_in_s2   <= {GPIO_WIDTH{1'b0}};
            gpio_in_s2_d <= {GPIO_WIDTH{1'b0}};
        end else begin
            gpio_in_s1   <= gpio_in;
            gpio_in_s2   <= gpio_in_s1;
            gpio_in_s2_d <= gpio_in_s2;
        end
    end

    // -----------------------------------------------------------------
    // APB write logic : commit during ACCESS phase (psel & penable & pwrite).
    // pready is always high so penable is asserted for exactly one cycle per
    // transaction -> each register updates exactly once.  Read-only and
    // undefined addresses are ignored.
    // -----------------------------------------------------------------
    always @(posedge pclk or negedge preset_n) begin
        if (!preset_n) begin
            reg_out   <= {GPIO_WIDTH{1'b0}};
            reg_oe    <= {GPIO_WIDTH{1'b0}};
            reg_ie    <= {GPIO_WIDTH{1'b0}};
            reg_itype <= {GPIO_WIDTH{1'b0}};
            reg_ipol  <= {GPIO_WIDTH{1'b0}};
        end else if (psel && penable && pwrite) begin
            case (paddr)
                ADDR_OUTPUT: reg_out   <= pwdata[GPIO_WIDTH-1:0];
                ADDR_OE    : reg_oe    <= pwdata[GPIO_WIDTH-1:0];
                ADDR_IE    : reg_ie    <= pwdata[GPIO_WIDTH-1:0];
                ADDR_ITYPE : reg_itype <= pwdata[GPIO_WIDTH-1:0];
                ADDR_IPOL  : reg_ipol  <= pwdata[GPIO_WIDTH-1:0];
                default    : ; // RO (input/state) or undefined -> no effect
            endcase
        end
    end

    // -----------------------------------------------------------------
    // APB read logic : combinational, zero added latency.  prdata reflects
    // the addressed register during a qualified read (psel & penable & ~pwrite)
    // and is 0 when idle or for undefined addresses.  All fields are
    // zero-extended into the 32-bit data bus.
    // -----------------------------------------------------------------
    always @(*) begin
        prdata = 32'b0;
        if (psel && penable && !pwrite) begin
            case (paddr)
                ADDR_INPUT : prdata = {{(32-GPIO_WIDTH){1'b0}}, gpio_in_s2};
                ADDR_OUTPUT: prdata = {{(32-GPIO_WIDTH){1'b0}}, reg_out};
                ADDR_OE    : prdata = {{(32-GPIO_WIDTH){1'b0}}, reg_oe};
                ADDR_IE    : prdata = {{(32-GPIO_WIDTH){1'b0}}, reg_ie};
                ADDR_ITYPE : prdata = {{(32-GPIO_WIDTH){1'b0}}, reg_itype};
                ADDR_IPOL  : prdata = {{(32-GPIO_WIDTH){1'b0}}, reg_ipol};
                ADDR_ISTATE: prdata = {{(32-GPIO_WIDTH){1'b0}}, gpio_int};
                default    : prdata = 32'b0;
            endcase
        end
    end

    // -----------------------------------------------------------------
    // GPIO drive
    // -----------------------------------------------------------------
    assign gpio_out    = reg_out;
    assign gpio_enable = reg_oe;

    // -----------------------------------------------------------------
    // Interrupt generation (combinational, single-cycle response off the
    // synchronized inputs).
    //   itype = 1 : edge-sensitive,  0 : level-sensitive
    //   ipol  = 1 : active-high (rising edge / logic-high level)
    //   ipol  = 0 : active-low  (falling edge / logic-low  level)
    // Each pin is independent; comb_int is the logical OR of all pins.
    // (Simultaneous interrupts naturally coexist; comb_int asserts once.)
    // -----------------------------------------------------------------
    wire [GPIO_WIDTH-1:0] rising  =  gpio_in_s2 & ~gpio_in_s2_d;
    wire [GPIO_WIDTH-1:0] falling = ~gpio_in_s2 &  gpio_in_s2_d;

    wire [GPIO_WIDTH-1:0] edge_int  = (reg_ipol  & rising)     | (~reg_ipol  & falling);
    wire [GPIO_WIDTH-1:0] level_int = (reg_ipol  & gpio_in_s2) | (~reg_ipol  & ~gpio_in_s2);
    wire [GPIO_WIDTH-1:0] raw_int   = (reg_itype & edge_int)   | (~reg_itype & level_int);

    assign gpio_int = reg_ie & raw_int;
    assign comb_int = |gpio_int;

    // -----------------------------------------------------------------
    // Static APB status
    // -----------------------------------------------------------------
    assign pready  = 1'b1;
    assign pslverr = 1'b0;

endmodule
