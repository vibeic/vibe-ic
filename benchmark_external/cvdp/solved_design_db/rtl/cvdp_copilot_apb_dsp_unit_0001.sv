module apb_dsp_unit (
    input  wire        pclk,        // APB clock
    input  wire        presetn,     // active-low async reset
    input  wire [9:0]  paddr,       // address bus
    input  wire        pselx,       // select
    input  wire        penable,     // enable
    input  wire        pwrite,      // 1 = write, 0 = read
    input  wire [7:0]  pwdata,      // write data
    input  wire        sram_valid,  // posedge latches r_write_data -> SRAM
    output reg         pready,      // transfer ready
    output reg [7:0]   prdata,      // read data
    output reg         pslverr      // error response
);

    // ---- Configuration registers ----
    reg [7:0] r_operand_1;      // 0x0 : address of operand 1
    reg [7:0] r_operand_2;      // 0x1 : address of operand 2
    reg [7:0] r_Enable;         // 0x2 : 0=off 1=add 2=mul 3=write
    reg [7:0] r_write_address;  // 0x3 : memory write address
    reg [7:0] r_write_data;     // 0x4 : memory write data
    // 0x5 : computed result (read-only, see dsp_result)

    // ---- 1 KB SRAM ----
    reg [7:0] sram [0:1023];

    // ---- DSP combinational result ----
    reg [15:0] dsp_result;
    always @(*) begin
        case (r_Enable)
            8'd1:    dsp_result = sram[r_operand_1] + sram[r_operand_2]; // addition
            8'd2:    dsp_result = sram[r_operand_1] * sram[r_operand_2]; // multiplication
            default: dsp_result = 16'd0;
        endcase
    end

    // ---- SRAM write on the rising edge of sram_valid (write mode) ----
    // Spec: "At positive edge of this signal, data in r_write_data is latched
    //        to address in r_write_address" (when r_Enable == write mode).
    always @(posedge sram_valid) begin
        if (r_Enable == 8'd3)
            sram[r_write_address] <= r_write_data;
    end

    // ---- APB slave (no wait states: PREADY always high) ----
    always @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            pready          <= 1'b0;
            prdata          <= 8'd0;
            pslverr         <= 1'b0;
            r_operand_1     <= 8'd0;
            r_operand_2     <= 8'd0;
            r_Enable        <= 8'd0;
            r_write_address <= 8'd0;
            r_write_data    <= 8'd0;
        end else begin
            pready  <= 1'b1;
            pslverr <= 1'b0;
            if (pselx && penable) begin
                if (pwrite) begin
                    case (paddr)
                        10'h0:   r_operand_1     <= pwdata;
                        10'h1:   r_operand_2     <= pwdata;
                        10'h2:   r_Enable        <= pwdata;
                        10'h3:   r_write_address <= pwdata;
                        10'h4:   r_write_data    <= pwdata;
                        default: pslverr         <= 1'b1; // write to unmapped CSR addr
                    endcase
                end else begin
                    case (paddr)
                        10'h0:   prdata <= r_operand_1;
                        10'h1:   prdata <= r_operand_2;
                        10'h2:   prdata <= r_Enable;
                        10'h3:   prdata <= r_write_address;
                        10'h4:   prdata <= r_write_data;
                        10'h5:   prdata <= dsp_result[7:0];  // computed result
                        default: prdata <= sram[paddr];      // memory read-back
                    endcase
                end
            end
        end
    end

endmodule
