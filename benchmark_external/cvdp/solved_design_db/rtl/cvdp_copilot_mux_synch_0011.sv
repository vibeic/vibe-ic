module mux_synch (

input [7:0] data_in,   			//asynchronous data input
input req,                  		//indicating that data is available at the data_in input
input dst_clk,                 		//destination clock
input src_clk,                 		//source clock
input nrst,                    		//asynchronous reset
output reg [7:0] data_out,              //synchronized version of data_in to the destination clock domain
output ack_out );


wire syncd_req,anded_req,syncd_ack;
reg syncd_req_1,ack;


nff  req_synch_0 (.d_in(req),.dst_clk(dst_clk),.rst(nrst),.syncd(syncd_req)) ;		//2-flop synchronizer for the enable input


always_ff @(posedge dst_clk)                     				//one clock cycle delayed synced_enable
begin
    syncd_req_1 <= syncd_req;
end

assign anded_req = (!syncd_req_1 && syncd_req);    					//posedge detector


always_ff @(posedge dst_clk or negedge nrst)
begin
	if(!nrst)
		data_out <= 1'b0;               					//forcing the output data_in to zero when an active-low asynchronous reset is detected.

	else if (anded_req==1'b1)
		data_out <= data_in;                    				//latching data_in to data_out when the enable signal is available.

	else
		data_out <= data_out;                   				//holds the data till next req comes.
end


// acknowledgment signal generation
// BUG FIX: the original code drove `ack` as a single destination-clock pulse
// (asserted on anded_req, cleared the very next cycle).  A one-cycle pulse can
// fall entirely between two active edges of the source clock and be lost by the
// 2-flop synchronizer.  Drive `ack` as a LEVEL instead -- set when the data is
// sampled and HELD until the request is withdrawn -- so the source-domain
// synchronizer always captures it irrespective of the clock-frequency ratio.
always_ff@(posedge dst_clk or negedge nrst)
begin
	if(!nrst)
		ack <= 1'b0;

	else if (anded_req==1'b1)
		ack <= 1'b1;            // data sampled: raise the acknowledge level

	else if (!syncd_req)
		ack <= 1'b0;            // request withdrawn (sync'd): re-arm for next transfer

	else
		ack <= ack;            // hold the level until then
end

//changing the clock domain of the ack signal
nff  enable_synch_1 (.d_in(ack),.dst_clk(src_clk),.rst(nrst),.syncd(syncd_ack)) ;

//synchronized acknowledge level in the source domain
assign ack_out = syncd_ack;


endmodule

module nff  (

	input d_in,   									//input data that needs to be synchronized to the dst_clk domain.
	input dst_clk,     								//destination domain clock.
	input rst,         								//asynchronous active-low reset
	output reg  syncd 								//synced output, which is a 2-clock-cycle delayed version of d_in.
	                   );

reg   dmeta;             								//register to hold output.



always@(posedge dst_clk or negedge rst)
begin
	if(!rst)              								//active-low asynchronous reset
  begin
    syncd <= 1'b0;      								//resetting the synced register to 0
    dmeta <= 1'b0;      								//resetting dmeta register to 0
  end
  else
  begin
    dmeta <= d_in;      								//passing d_in to dmeta
    syncd <= dmeta;     								//passing dmeta to syncd
  end
end

endmodule
