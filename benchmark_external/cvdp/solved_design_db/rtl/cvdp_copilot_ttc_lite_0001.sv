module ttc_counter_lite (
    input  wire        clk,
    input  wire        reset,        // active-high synchronous reset
    input  wire [3:0]  axi_addr,
    input  wire [31:0] axi_wdata,
    input  wire        axi_write_en,
    input  wire        axi_read_en,
    output reg  [31:0] axi_rdata,
    output reg         interrupt
);
    // Register-map addresses
    localparam [3:0] ADDR_COUNT   = 4'h0,
                     ADDR_MATCH   = 4'h1,
                     ADDR_RELOAD  = 4'h2,
                     ADDR_CONTROL = 4'h3,
                     ADDR_STATUS  = 4'h4;

    reg [15:0] count;
    reg [15:0] match_value;
    reg [15:0] reload_value;

    reg        enable;
    reg        interval_mode;
    reg        interrupt_enable;

    reg        matched;   // tracks that the current match has already been seen

    wire match = enable && (count == match_value);

    // ---------------- write / counter / interrupt ----------------
    always @(posedge clk) begin
        if (reset) begin
            count            <= 16'd0;
            match_value      <= 16'd0;
            reload_value     <= 16'd0;
            enable           <= 1'b0;
            interval_mode    <= 1'b0;
            interrupt_enable <= 1'b0;
            interrupt        <= 1'b0;
            matched          <= 1'b0;
        end else begin
            // ---- counter ----
            if (enable) begin
                if (count == match_value) begin
                    if (interval_mode)
                        count <= reload_value;   // interval mode: reload on match
                    else
                        count <= match_value;    // one-shot mode: hold at match
                end else begin
                    count <= count + 16'd1;
                end
            end

            // ---- match-event bookkeeping (one-shot per match) ----
            if (match)
                matched <= 1'b1;
            else
                matched <= 1'b0;

            // ---- interrupt: set on a new match (if enabled), cleared on
            //      a write to the status register (clear has priority) ----
            if (axi_write_en && (axi_addr == ADDR_STATUS))
                interrupt <= 1'b0;
            else if (match && !matched && interrupt_enable)
                interrupt <= 1'b1;

            // ---- register writes ----
            if (axi_write_en) begin
                case (axi_addr)
                    ADDR_MATCH:   match_value  <= axi_wdata[15:0];
                    ADDR_RELOAD:  reload_value <= axi_wdata[15:0];
                    ADDR_CONTROL: begin
                        enable           <= axi_wdata[0];
                        interval_mode    <= axi_wdata[1];
                        interrupt_enable <= axi_wdata[2];
                    end
                    default: ;
                endcase
            end
        end
    end

    // ---------------- read (combinational) ----------------
    always @(*) begin
        case (axi_addr)
            ADDR_COUNT:   axi_rdata = {16'd0, count};
            ADDR_MATCH:   axi_rdata = {16'd0, match_value};
            ADDR_RELOAD:  axi_rdata = {16'd0, reload_value};
            ADDR_CONTROL: axi_rdata = {29'd0, interrupt_enable, interval_mode, enable};
            ADDR_STATUS:  axi_rdata = {31'd0, interrupt};
            default:      axi_rdata = 32'd0;
        endcase
    end

endmodule
