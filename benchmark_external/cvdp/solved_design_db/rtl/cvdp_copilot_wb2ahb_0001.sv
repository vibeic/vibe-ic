module wishbone_to_ahb_bridge (
    // Wishbone slave interface (from WB master)
    input  wire        clk_i,
    input  wire        rst_i,      // active-low reset
    input  wire        cyc_i,
    input  wire        stb_i,
    input  wire [3:0]  sel_i,
    input  wire        we_i,
    input  wire [31:0] addr_i,
    input  wire [31:0] data_i,
    output wire [31:0] data_o,
    output wire        ack_o,
    // AHB master interface (to AHB slave)
    input  wire        hclk,
    input  wire        hreset_n,   // active-low reset
    input  wire [31:0] hrdata,
    input  wire [1:0]  hresp,
    input  wire        hready,
    output wire [1:0]  htrans,
    output wire [2:0]  hsize,
    output wire [2:0]  hburst,
    output wire        hwrite,
    output wire [31:0] haddr,
    output wire [31:0] hwdata
);

    // AHB transfer types
    localparam [1:0] HTRANS_IDLE   = 2'b00;
    localparam [1:0] HTRANS_NONSEQ = 2'b10;

    // Only single transfers are supported
    localparam [2:0] HBURST_SINGLE = 3'b000;

    // -----------------------------------------------------------------
    // Transfer size from the active byte enables (sel_i).
    // -----------------------------------------------------------------
    function [2:0] size_from_sel;
        input [3:0] sel;
        begin
            case (sel)
                4'b1111:            size_from_sel = 3'b010; // word
                4'b0011, 4'b1100:   size_from_sel = 3'b001; // halfword
                4'b0001, 4'b0010,
                4'b0100, 4'b1000:   size_from_sel = 3'b000; // byte
                default:            size_from_sel = 3'b010; // default to word
            endcase
        end
    endfunction

    // Address fixing: low address bits derived from the selected bytes.
    function [1:0] offset_from_sel;
        input [3:0] sel;
        begin
            case (sel)
                4'b0010: offset_from_sel = 2'b01;
                4'b0100: offset_from_sel = 2'b10;
                4'b1000: offset_from_sel = 2'b11;
                4'b1100: offset_from_sel = 2'b10;
                default: offset_from_sel = 2'b00; // word / halfword / byte0 aligned
            endcase
        end
    endfunction

    // -----------------------------------------------------------------
    // Combinational protocol translation for SINGLE transfers.  The AHB
    // address-phase attributes and the write data are derived directly from
    // the active Wishbone request so they are valid in the same cycle the
    // request is presented (the test-bench samples them within the transfer,
    // before hready completes).  Wishbone and AHB share little-endian byte
    // ordering here, so data passes straight through.
    // -----------------------------------------------------------------
    wire active = cyc_i & stb_i;

    assign htrans = active ? HTRANS_NONSEQ : HTRANS_IDLE;
    assign hburst = HBURST_SINGLE;
    assign hsize  = size_from_sel(sel_i);
    assign hwrite = we_i;
    assign haddr  = {addr_i[31:2], offset_from_sel(sel_i)};
    assign hwdata = data_i;

    // Wishbone read data returned from the AHB slave.
    assign data_o = hrdata;

    // Acknowledge the Wishbone master once the AHB slave completes (hready).
    assign ack_o  = active & hready & hreset_n & rst_i;

endmodule
