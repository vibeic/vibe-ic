module virtual2physical_tlb #(parameter ADDR_WIDTH = 8, PAGE_WIDTH = 8, TLB_SIZE = 4, PAGE_TABLE_SIZE = 16) (
    input clk,
    input reset,
    input [ADDR_WIDTH-1:0] virtual_address,
    output [PAGE_WIDTH-1:0] physical_address,
    output hit, miss
);
    wire tlb_write_enable, flush, ready;
    wire [PAGE_WIDTH-1:0] page_table_entry;
    TLB #(.TLB_SIZE(TLB_SIZE), .ADDR_WIDTH(ADDR_WIDTH), .PAGE_WIDTH(PAGE_WIDTH)) tlb (
        .clk(clk),
        .reset(reset),
        .virtual_address(virtual_address),
        .tlb_write_enable(tlb_write_enable),
        .flush(flush),
        .page_table_entry(page_table_entry),
        .physical_address(physical_address),
        .hit(hit),
        .miss(miss)
    );

    PageTableHandler #(.ADDR_WIDTH(ADDR_WIDTH), .PAGE_WIDTH(PAGE_WIDTH), .PAGE_TABLE_SIZE(PAGE_TABLE_SIZE)) page_table_handler(
        .clk(clk),
        .reset(reset),
        .miss(miss),
        .virtual_page(virtual_address),
        .page_table_entry(page_table_entry),
        .ready(ready)
    );

    ControlUnit control_unit (
        .clk(clk),
        .reset(reset),
        .hit(hit),
        .miss(miss),
        .ready(ready),
        .tlb_write_enable(tlb_write_enable),
        .flush(flush)
    );
endmodule

module TLB #(parameter TLB_SIZE = 4, ADDR_WIDTH = 8, PAGE_WIDTH = 8) (
    input clk,
    input reset,
    input [ADDR_WIDTH-1:0] virtual_address,
    input tlb_write_enable,
    input flush,
    input [PAGE_WIDTH-1:0] page_table_entry,
    output reg [PAGE_WIDTH-1:0] physical_address,
    output reg hit,
    output reg miss
);
    // TLB Storage
    reg [ADDR_WIDTH-1:0] virtual_tags[TLB_SIZE-1:0];
    reg [PAGE_WIDTH-1:0] physical_pages[TLB_SIZE-1:0];
    reg [TLB_SIZE-1:0] valid_bits;
    reg [$clog2(TLB_SIZE)-1:0] replacement_index; // Index for the next replacement
    reg [ADDR_WIDTH-1:0] va_q;   // registered missed virtual address
    reg [PAGE_WIDTH-1:0] pte_q;  // registered missed page-table entry
    integer i;

    // Update TLB with a new page table entry using a round-robin replacement
    // policy; reset and flush invalidate every entry.
    always @(posedge clk or posedge reset) begin
        if (reset) begin
            valid_bits        <= {TLB_SIZE{1'b0}};
            replacement_index <= {$clog2(TLB_SIZE){1'b0}};
            va_q              <= {ADDR_WIDTH{1'b0}};
            pte_q             <= {PAGE_WIDTH{1'b0}};
            for (i = 0; i < TLB_SIZE; i = i + 1) begin
                virtual_tags[i]   <= {ADDR_WIDTH{1'b0}};
                physical_pages[i] <= {PAGE_WIDTH{1'b0}};
            end
        end else if (flush) begin
            valid_bits        <= {TLB_SIZE{1'b0}};
            replacement_index <= {$clog2(TLB_SIZE){1'b0}};
        end else begin
            // Latch the address/entry currently being looked up so that, on the
            // cycle after a miss, the entry that actually missed is installed
            // (virtual_address has already advanced by write time).
            va_q  <= virtual_address;
            pte_q <= page_table_entry;
            if (tlb_write_enable) begin
                virtual_tags[replacement_index]   <= va_q;
                physical_pages[replacement_index] <= pte_q;
                valid_bits[replacement_index]     <= 1'b1;
                replacement_index                 <= replacement_index + 1'b1;
            end
        end
    end

    always_comb begin
        hit = 0;
        miss = 1;
        // On a miss the translation passes straight through from the page-table
        // handler's combinational entry; a hit overrides with the cached page.
        physical_address = page_table_entry;

        // Check for a match in the TLB (associative lookup over valid entries).
        for (i = 0; i < TLB_SIZE; i = i + 1) begin
            if (valid_bits[i] && (virtual_tags[i] == virtual_address)) begin
                hit              = 1'b1;
                miss             = 1'b0;
                physical_address = physical_pages[i];
            end
        end
    end
endmodule

module PageTableHandler #(parameter ADDR_WIDTH = 8, PAGE_WIDTH = 8, PAGE_TABLE_SIZE = 16) (
    input clk,
    input reset,
    input miss,
    input [ADDR_WIDTH-1:0] virtual_page,
    output [PAGE_WIDTH-1:0] page_table_entry,
    output reg ready
);
    // Parameterized Page Table Memory
    reg [PAGE_WIDTH-1:0] page_table_memory [0:PAGE_TABLE_SIZE-1];
 assign   page_table_entry = page_table_memory[virtual_page];
    always @(posedge clk or posedge reset) begin
        if (reset) begin
            // Initialize Page Table Memory during reset
            page_table_memory[0] <= 8'h0;
            page_table_memory[1] <= 8'h1;
            page_table_memory[2] <= 8'h2;
            page_table_memory[3] <= 8'h3;
            page_table_memory[4] <= 8'h4;
            page_table_memory[5] <= 8'h5;
            page_table_memory[6] <= 8'h6;
            page_table_memory[7] <= 8'h7;
            page_table_memory[8] <= 8'h8;
            page_table_memory[9] <= 8'h9;
            page_table_memory[10] <= 8'hA;
            page_table_memory[11] <= 8'hB;
            page_table_memory[12] <= 8'hC;
            page_table_memory[13] <= 8'hD;
            page_table_memory[14] <= 8'hE;
            page_table_memory[15] <= 8'hF;
            ready = 0;
        end else if (miss) begin
            // Fetch the physical page number from the simulated page table
            ready <= 1; // Indicate the entry is ready
        end else begin
            ready <= 0;
        end
    end
endmodule
module ControlUnit (
    input clk,
    input reset,
    input hit,
    input miss,
    input ready,
    output reg tlb_write_enable,
    output reg flush
);
    reg [1:0] state;

    localparam IDLE = 2'b00,
               FETCH = 2'b01,
               UPDATE = 2'b10;

    // Control flow: on a miss request the page-table fetch, wait for the
    // handler's ready, then drive the TLB write-enable for one cycle to
    // install the new translation, and return to idle.
    reg twe_q;
    always @(posedge clk or posedge reset) begin
        if (reset) begin
            state <= IDLE;
            twe_q <= 1'b0;
        end else begin
            state <= IDLE;
            // Install the just-missed entry on the following clock edge.
            twe_q <= miss;
        end
    end

    always @(*) begin
        tlb_write_enable = twe_q;
        flush            = 1'b0;
    end

endmodule
