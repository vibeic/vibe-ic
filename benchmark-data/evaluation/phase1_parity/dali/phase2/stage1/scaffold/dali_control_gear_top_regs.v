// Auto-generated register-file skeleton.
// Address decode + read/write hooks are stubbed; behavior is TODO.
// Top module: dali_control_gear_top

`timescale 1ns/1ps

module dali_control_gear_top_regs (
    input         clk,
    input         rst_n,
    input  [31:0] reg_addr,
    input         reg_we,
    input  [31:0] reg_wdata,
    output reg [31:0] reg_rdata
);

    // Register declarations
    reg [7:0] Power_On_Level; // offset  (dali write via store dtr as power on level / read via query)
    reg [7:0] System_Failure_Level; // offset 1 (dali write via store dtr as system failure level / read via query)
    reg [7:0] Minimum_Level; // offset 2 (dali write via store dtr as min level / read via query)
    reg [7:0] Maximum_Level; // offset 3 (dali write via store dtr as max level / read via query)
    reg [7:0] Fade_Rate; // offset 4 (dali write via store dtr as fade rate / read via query)
    reg [7:0] Fade_Time; // offset 5 (dali write via store dtr as fade time / read via query)
    reg [7:0] Short_Address; // offset 6 (dali write via store dtr as short address / special program / read via special query short address)
    reg [7:0] Group_0_7; // offset 7 (dali write via add/remove from group)
    reg [7:0] Group_8_15; // offset 8 (dali write via add/remove from group)
    reg [7:0] Scene_0_15; // offset 9..24 (dali write via store dtr as scene n / remove from scene n / read via query scene level n)
    reg [23:0] Random_Address; // offset 25..27 (internal — randomize generated; compare/withdraw compare)
    reg [7:0] Fast_Fade_Time; // offset 28 (dali write via store dtr as fast fade time / read via query)
    reg [7:0] Failure_Status; // offset 29 (internal status latched on fault; read via query 0x92/0x94)
    reg [7:0] Operating_Mode; // offset 30 (internal / vendor-specific)
    reg [7:0] Dimming_Curve; // offset 31 (internal — vendor-defined)
    reg [7:0] DTR; // offset RAM-only (dali special command dtr (0xa3))
    reg [7:0] DTR1; // offset RAM-only (dali special command dtr1 (0xc3))
    reg [7:0] DTR2; // offset RAM-only (dali special command dtr2 (0xc5))
    reg [23:0] Search_Address; // offset RAM-only (dali special search h/m/l (0xb1/0xb3/0xb5))
    reg [7:0] Actual_Level; // offset RAM (internal — read via query actual level (0xa0))

    // Reset
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            Power_On_Level <= 8'b0;
            System_Failure_Level <= 8'b0;
            Minimum_Level <= 8'b0;
            Maximum_Level <= 8'b0;
            Fade_Rate <= 8'b0;
            Fade_Time <= 8'b0;
            Short_Address <= 8'b0;
            Group_0_7 <= 8'b0;
            Group_8_15 <= 8'b0;
            Scene_0_15 <= 8'b0;
            Random_Address <= 24'b0;
            Fast_Fade_Time <= 8'b0;
            Failure_Status <= 8'b0;
            Operating_Mode <= 8'b0;
            Dimming_Curve <= 8'b0;
            DTR <= 8'b0;
            DTR1 <= 8'b0;
            DTR2 <= 8'b0;
            Search_Address <= 24'b0;
            Actual_Level <= 8'b0;
        end else if (reg_we) begin
            // TODO — address decode (per L4 offsets)
        end
    end

    // Read mux (TODO — match the offsets above)
    always @(*) begin
        reg_rdata = 32'b0;
    end

endmodule
