

module user_project_wrapper
(
  wb_clk_i,
  wb_rst_i,
  wbs_stb_i,
  wbs_cyc_i,
  wbs_we_i,
  wbs_sel_i,
  wbs_dat_i,
  wbs_adr_i,
  wbs_ack_o,
  wbs_dat_o,
  la_data_in,
  la_data_out,
  la_oenb,
  io_in,
  io_out,
  io_oeb,
  user_clock2,
  user_irq,
  sin,
  shift,
  sout,
  tck,
  test
);

  input sin;
  output sout;
  input shift;
  input tck;
  input test;
  wire __clk_source__;
  wire __chain_0__;
  assign __chain_0__ = sin;
  input wb_clk_i;
  wire wb_clk_i;
  input wb_rst_i;
  wire wb_rst_i;
  input wbs_stb_i;
  wire wbs_stb_i;
  input wbs_cyc_i;
  wire wbs_cyc_i;
  input wbs_we_i;
  wire wbs_we_i;
  input [3:0] wbs_sel_i;
  wire [3:0] wbs_sel_i;
  input [31:0] wbs_dat_i;
  wire [31:0] wbs_dat_i;
  input [31:0] wbs_adr_i;
  wire [31:0] wbs_adr_i;
  output wbs_ack_o;
  wire wbs_ack_o;
  output [31:0] wbs_dat_o;
  wire [31:0] wbs_dat_o;
  input [127:0] la_data_in;
  wire [127:0] la_data_in;
  output [127:0] la_data_out;
  wire [127:0] la_data_out;
  input [127:0] la_oenb;
  wire [127:0] la_oenb;
  input [37:0] io_in;
  wire [37:0] io_in;
  output [37:0] io_out;
  wire [37:0] io_out;
  output [37:0] io_oeb;
  wire [37:0] io_oeb;
  input user_clock2;
  wire user_clock2;
  output [2:0] user_irq;
  wire [2:0] user_irq;
  wire _000_;
  wire _001_;
  wire _002_;
  wire _003_;
  wire _004_;
  wire _005_;
  wire _006_;
  wire _007_;
  wire _008_;
  wire _009_;
  wire _010_;
  wire _011_;
  wire _012_;
  wire _013_;
  wire _014_;
  wire _015_;
  wire _016_;
  wire _017_;
  wire _018_;
  wire _019_;
  wire _020_;
  wire _021_;
  wire _022_;
  wire _023_;
  wire _024_;
  wire _025_;
  wire _026_;
  wire _027_;
  wire _028_;
  wire _029_;
  wire _030_;
  wire _031_;
  wire _032_;
  wire _033_;
  wire _034_;
  wire _035_;
  wire _036_;
  wire _037_;
  wire _038_;
  wire _039_;
  wire _040_;
  wire _041_;
  wire _042_;
  wire _043_;
  wire _044_;
  wire _045_;
  wire _046_;
  wire _047_;
  wire _048_;
  wire _049_;
  wire _050_;
  wire _051_;
  wire _052_;
  wire _053_;
  wire _054_;
  wire _055_;
  wire _056_;
  wire _057_;
  wire _058_;
  wire _059_;
  wire _060_;
  wire _061_;
  wire _062_;
  wire _063_;
  wire _064_;
  wire _065_;
  wire _066_;
  wire _067_;
  wire _068_;
  wire _069_;
  wire _070_;
  wire _071_;
  wire _072_;
  wire _073_;
  wire _074_;
  wire _075_;
  wire _076_;
  wire _077_;
  wire _078_;
  wire _079_;
  wire _080_;
  wire _081_;
  wire _082_;
  wire _083_;
  wire _084_;
  wire _085_;
  wire _086_;
  wire _087_;
  wire _088_;
  wire _089_;
  wire _090_;
  wire _091_;
  wire _092_;
  wire _093_;
  wire _094_;
  wire _095_;
  wire _096_;
  wire _097_;
  wire _098_;
  wire _099_;
  wire _100_;
  wire _101_;
  wire _102_;
  wire _103_;
  wire _104_;
  wire _105_;
  wire _106_;
  wire _107_;
  wire _108_;
  wire _109_;
  wire _110_;
  wire _111_;
  wire _112_;
  wire _113_;
  wire _114_;
  wire _115_;
  wire _116_;
  wire _117_;
  wire _118_;
  wire _119_;
  wire _120_;
  wire _121_;
  wire _122_;
  wire _123_;
  wire _124_;
  wire _125_;
  wire _126_;
  wire _127_;
  wire _128_;
  wire _129_;
  wire _130_;
  wire _131_;
  wire _132_;
  wire _133_;
  wire _134_;
  wire _135_;
  wire _136_;
  wire _137_;
  wire _138_;
  wire _139_;
  wire _140_;
  wire _141_;
  wire _142_;
  wire _143_;
  wire _144_;
  wire _145_;
  wire _146_;
  wire _147_;
  wire _148_;
  wire _149_;
  wire _150_;
  wire _151_;
  wire _152_;
  wire _153_;
  wire _154_;
  wire _155_;
  wire _156_;
  wire _157_;
  wire _158_;
  wire \mprj.clk ;
  wire [15:0] \mprj.count ;
  wire \mprj.counter.clk ;
  wire [15:0] \mprj.counter.count ;
  wire [15:0] \mprj.counter.la_input ;
  wire [15:0] \mprj.counter.rdata ;
  wire \mprj.counter.ready ;
  wire \mprj.counter.reset ;
  wire [15:0] \mprj.counter.wdata ;
  wire [3:0] \mprj.counter.wstrb ;
  wire [15:0] \mprj.io_in ;
  wire [15:0] \mprj.io_oeb ;
  wire [15:0] \mprj.io_out ;
  wire [127:0] \mprj.la_data_in ;
  wire [127:0] \mprj.la_data_out ;
  wire [127:0] \mprj.la_oenb ;
  wire [15:0] \mprj.rdata ;
  wire \mprj.rst ;
  wire \mprj.wb_clk_i ;
  wire \mprj.wb_rst_i ;
  wire \mprj.wbs_ack_o ;
  wire [31:0] \mprj.wbs_adr_i ;
  wire \mprj.wbs_cyc_i ;
  wire [31:0] \mprj.wbs_dat_i ;
  wire [31:0] \mprj.wbs_dat_o ;
  wire [3:0] \mprj.wbs_sel_i ;
  wire \mprj.wbs_stb_i ;
  wire \mprj.wbs_we_i ;
  wire [15:0] \mprj.wdata ;
  wire [3:0] \mprj.wstrb ;

  sky130_fd_sc_hd__nor2_1
  _159_
  (
    .A(_096_),
    .B(_099_),
    .Y(_100_)
  );


  sky130_fd_sc_hd__nor2_1
  _160_
  (
    .A(io_oeb[0]),
    .B(_100_),
    .Y(_008_)
  );


  sky130_fd_sc_hd__nor2_1
  _161_
  (
    .A(\mprj.counter.count [10]),
    .B(_062_),
    .Y(_101_)
  );


  sky130_fd_sc_hd__nor3_1
  _162_
  (
    .A(_039_),
    .B(_063_),
    .C(_101_),
    .Y(_102_)
  );


  sky130_fd_sc_hd__nor3b_1
  _163_
  (
    .A(la_oenb[58]),
    .B(_158_),
    .C_N(la_data_in[58]),
    .Y(_103_)
  );


  sky130_fd_sc_hd__o21ai_0
  _164_
  (
    .A1(_102_),
    .A2(_103_),
    .B1(_019_),
    .Y(_104_)
  );


  sky130_fd_sc_hd__nand2_1
  _165_
  (
    .A(\mprj.counter.count [10]),
    .B(_039_),
    .Y(_105_)
  );


  sky130_fd_sc_hd__nand2_1
  _166_
  (
    .A(_070_),
    .B(_105_),
    .Y(_106_)
  );


  sky130_fd_sc_hd__o221ai_1
  _167_
  (
    .A1(wbs_dat_i[10]),
    .A2(_070_),
    .B1(_102_),
    .B2(_106_),
    .C1(_018_),
    .Y(_107_)
  );


  sky130_fd_sc_hd__a21oi_1
  _168_
  (
    .A1(_104_),
    .A2(_107_),
    .B1(io_oeb[0]),
    .Y(_009_)
  );


  sky130_fd_sc_hd__nor2_1
  _169_
  (
    .A(\mprj.counter.count [9]),
    .B(_061_),
    .Y(_108_)
  );


  sky130_fd_sc_hd__nor3_1
  _170_
  (
    .A(_039_),
    .B(_062_),
    .C(_108_),
    .Y(_109_)
  );


  sky130_fd_sc_hd__nor3b_1
  _171_
  (
    .A(la_oenb[57]),
    .B(_158_),
    .C_N(la_data_in[57]),
    .Y(_110_)
  );


  sky130_fd_sc_hd__o21ai_0
  _172_
  (
    .A1(_109_),
    .A2(_110_),
    .B1(_019_),
    .Y(_111_)
  );


  sky130_fd_sc_hd__nand2_1
  _173_
  (
    .A(\mprj.counter.count [9]),
    .B(_039_),
    .Y(_112_)
  );


  sky130_fd_sc_hd__nand2_1
  _174_
  (
    .A(_070_),
    .B(_112_),
    .Y(_113_)
  );


  sky130_fd_sc_hd__o221ai_1
  _175_
  (
    .A1(wbs_dat_i[9]),
    .A2(_070_),
    .B1(_109_),
    .B2(_113_),
    .C1(_018_),
    .Y(_114_)
  );


  sky130_fd_sc_hd__a21oi_1
  _176_
  (
    .A1(_111_),
    .A2(_114_),
    .B1(io_oeb[0]),
    .Y(_010_)
  );


  sky130_fd_sc_hd__a21oi_1
  _177_
  (
    .A1(\mprj.counter.count [7]),
    .A2(_060_),
    .B1(\mprj.counter.count [8]),
    .Y(_115_)
  );


  sky130_fd_sc_hd__nor3_1
  _178_
  (
    .A(_039_),
    .B(_061_),
    .C(_115_),
    .Y(_116_)
  );


  sky130_fd_sc_hd__a21oi_1
  _179_
  (
    .A1(la_data_in[56]),
    .A2(_021_),
    .B1(_116_),
    .Y(_117_)
  );


  sky130_fd_sc_hd__a211oi_1
  _180_
  (
    .A1(\mprj.counter.count [8]),
    .A2(_039_),
    .B1(_069_),
    .C1(_116_),
    .Y(_118_)
  );


  sky130_fd_sc_hd__o21ai_0
  _181_
  (
    .A1(wbs_dat_i[8]),
    .A2(_070_),
    .B1(_018_),
    .Y(_119_)
  );


  sky130_fd_sc_hd__o22a_1
  _182_
  (
    .A1(_018_),
    .A2(_117_),
    .B1(_118_),
    .B2(_119_),
    .X(_120_)
  );


  sky130_fd_sc_hd__nor2_1
  _183_
  (
    .A(io_oeb[0]),
    .B(_120_),
    .Y(_011_)
  );


  sky130_fd_sc_hd__a21oi_1
  _184_
  (
    .A1(\mprj.counter.count [7]),
    .A2(_060_),
    .B1(_039_),
    .Y(_121_)
  );


  sky130_fd_sc_hd__o21a_1
  _185_
  (
    .A1(\mprj.counter.count [7]),
    .A2(_060_),
    .B1(_121_),
    .X(_122_)
  );


  sky130_fd_sc_hd__nor3b_1
  _186_
  (
    .A(la_oenb[55]),
    .B(_158_),
    .C_N(la_data_in[55]),
    .Y(_123_)
  );


  sky130_fd_sc_hd__o21ai_0
  _187_
  (
    .A1(_122_),
    .A2(_123_),
    .B1(_019_),
    .Y(_124_)
  );


  sky130_fd_sc_hd__nand2_1
  _188_
  (
    .A(\mprj.counter.count [7]),
    .B(_039_),
    .Y(_125_)
  );


  sky130_fd_sc_hd__nand2_1
  _189_
  (
    .A(_045_),
    .B(_125_),
    .Y(_126_)
  );


  sky130_fd_sc_hd__o221ai_1
  _190_
  (
    .A1(wbs_dat_i[7]),
    .A2(_045_),
    .B1(_122_),
    .B2(_126_),
    .C1(_018_),
    .Y(_127_)
  );


  sky130_fd_sc_hd__a21oi_1
  _191_
  (
    .A1(_124_),
    .A2(_127_),
    .B1(io_oeb[0]),
    .Y(_012_)
  );


  sky130_fd_sc_hd__a21oi_1
  _192_
  (
    .A1(\mprj.counter.count [5]),
    .A2(_059_),
    .B1(\mprj.counter.count [6]),
    .Y(_128_)
  );


  sky130_fd_sc_hd__nor3_1
  _193_
  (
    .A(_039_),
    .B(_060_),
    .C(_128_),
    .Y(_129_)
  );


  sky130_fd_sc_hd__a21oi_1
  _194_
  (
    .A1(la_data_in[54]),
    .A2(_029_),
    .B1(_129_),
    .Y(_130_)
  );


  sky130_fd_sc_hd__a211oi_1
  _195_
  (
    .A1(\mprj.counter.count [6]),
    .A2(_039_),
    .B1(_044_),
    .C1(_129_),
    .Y(_131_)
  );


  sky130_fd_sc_hd__o21ai_0
  _196_
  (
    .A1(wbs_dat_i[6]),
    .A2(_045_),
    .B1(_018_),
    .Y(_132_)
  );


  sky130_fd_sc_hd__o22a_1
  _197_
  (
    .A1(_018_),
    .A2(_130_),
    .B1(_131_),
    .B2(_132_),
    .X(_133_)
  );


  sky130_fd_sc_hd__nor2_1
  _198_
  (
    .A(io_oeb[0]),
    .B(_133_),
    .Y(_013_)
  );


  sky130_fd_sc_hd__xnor2_1
  _199_
  (
    .A(\mprj.counter.count [5]),
    .B(_059_),
    .Y(_134_)
  );


  sky130_fd_sc_hd__nor2_1
  _200_
  (
    .A(_039_),
    .B(_134_),
    .Y(_135_)
  );


  sky130_fd_sc_hd__a21oi_1
  _201_
  (
    .A1(la_data_in[53]),
    .A2(_032_),
    .B1(_135_),
    .Y(_136_)
  );


  sky130_fd_sc_hd__a211oi_1
  _202_
  (
    .A1(\mprj.counter.count [5]),
    .A2(_039_),
    .B1(_044_),
    .C1(_135_),
    .Y(_137_)
  );


  sky130_fd_sc_hd__o21ai_0
  _203_
  (
    .A1(wbs_dat_i[5]),
    .A2(_045_),
    .B1(_018_),
    .Y(_138_)
  );


  sky130_fd_sc_hd__o22a_1
  _204_
  (
    .A1(_018_),
    .A2(_136_),
    .B1(_137_),
    .B2(_138_),
    .X(_139_)
  );


  sky130_fd_sc_hd__nor2_1
  _205_
  (
    .A(io_oeb[0]),
    .B(_139_),
    .Y(_014_)
  );


  sky130_fd_sc_hd__nor2_1
  _206_
  (
    .A(\mprj.counter.count [4]),
    .B(_058_),
    .Y(_140_)
  );


  sky130_fd_sc_hd__nor3_1
  _207_
  (
    .A(_039_),
    .B(_059_),
    .C(_140_),
    .Y(_141_)
  );


  sky130_fd_sc_hd__a21oi_1
  _208_
  (
    .A1(la_data_in[52]),
    .A2(_020_),
    .B1(_141_),
    .Y(_142_)
  );


  sky130_fd_sc_hd__a211oi_1
  _209_
  (
    .A1(\mprj.counter.count [4]),
    .A2(_039_),
    .B1(_044_),
    .C1(_141_),
    .Y(_143_)
  );


  sky130_fd_sc_hd__o21ai_0
  _210_
  (
    .A1(wbs_dat_i[4]),
    .A2(_045_),
    .B1(_018_),
    .Y(_144_)
  );


  sky130_fd_sc_hd__o22a_1
  _211_
  (
    .A1(_018_),
    .A2(_142_),
    .B1(_143_),
    .B2(_144_),
    .X(_145_)
  );


  sky130_fd_sc_hd__nor2_1
  _212_
  (
    .A(io_oeb[0]),
    .B(_145_),
    .Y(_015_)
  );


  sky130_fd_sc_hd__nor2_1
  _213_
  (
    .A(\mprj.counter.count [3]),
    .B(_057_),
    .Y(_146_)
  );


  sky130_fd_sc_hd__nor3_1
  _214_
  (
    .A(_039_),
    .B(_058_),
    .C(_146_),
    .Y(_147_)
  );


  sky130_fd_sc_hd__a21oi_1
  _215_
  (
    .A1(la_data_in[51]),
    .A2(_027_),
    .B1(_147_),
    .Y(_148_)
  );


  sky130_fd_sc_hd__a211oi_1
  _216_
  (
    .A1(\mprj.counter.count [3]),
    .A2(_039_),
    .B1(_044_),
    .C1(_147_),
    .Y(_149_)
  );


  sky130_fd_sc_hd__o21ai_0
  _217_
  (
    .A1(wbs_dat_i[3]),
    .A2(_045_),
    .B1(_018_),
    .Y(_150_)
  );


  sky130_fd_sc_hd__o22a_1
  _218_
  (
    .A1(_018_),
    .A2(_148_),
    .B1(_149_),
    .B2(_150_),
    .X(_151_)
  );


  sky130_fd_sc_hd__nor2_1
  _219_
  (
    .A(io_oeb[0]),
    .B(_151_),
    .Y(_016_)
  );


  sky130_fd_sc_hd__a21oi_1
  _220_
  (
    .A1(\mprj.counter.count [0]),
    .A2(\mprj.counter.count [1]),
    .B1(\mprj.counter.count [2]),
    .Y(_152_)
  );


  sky130_fd_sc_hd__nor3_1
  _221_
  (
    .A(_039_),
    .B(_057_),
    .C(_152_),
    .Y(_153_)
  );


  sky130_fd_sc_hd__a21oi_1
  _222_
  (
    .A1(la_data_in[50]),
    .A2(_030_),
    .B1(_153_),
    .Y(_154_)
  );


  sky130_fd_sc_hd__a211oi_1
  _223_
  (
    .A1(\mprj.counter.count [2]),
    .A2(_039_),
    .B1(_044_),
    .C1(_153_),
    .Y(_155_)
  );


  sky130_fd_sc_hd__o21ai_0
  _224_
  (
    .A1(wbs_dat_i[2]),
    .A2(_045_),
    .B1(_018_),
    .Y(_156_)
  );


  sky130_fd_sc_hd__o22a_1
  _225_
  (
    .A1(_018_),
    .A2(_154_),
    .B1(_155_),
    .B2(_156_),
    .X(_157_)
  );


  sky130_fd_sc_hd__nor2_1
  _226_
  (
    .A(io_oeb[0]),
    .B(_157_),
    .Y(_017_)
  );


  sky130_fd_sc_hd__nor2_1
  _227_
  (
    .A(io_oeb[0]),
    .B(_019_),
    .Y(_003_)
  );


  sky130_fd_sc_hd__mux2_1
  _228_
  (
    .A0(la_data_in[65]),
    .A1(wb_rst_i),
    .S(la_oenb[65]),
    .X(io_oeb[0])
  );


  sky130_fd_sc_hd__mux2_1
  _229_
  (
    .A0(la_data_in[64]),
    .A1(wb_clk_i),
    .S(la_oenb[64]),
    .X(\mprj.counter.clk )
  );


  sky130_fd_sc_hd__and2_0
  _230_
  (
    .A(wbs_cyc_i),
    .B(wbs_stb_i),
    .X(_158_)
  );


  sky130_fd_sc_hd__nor2b_1
  _231_
  (
    .A(\mprj.counter.ready ),
    .B_N(_158_),
    .Y(_018_)
  );


  sky130_fd_sc_hd__nand2b_1
  _232_
  (
    .A_N(\mprj.counter.ready ),
    .B(_158_),
    .Y(_019_)
  );


  sky130_fd_sc_hd__nor2_1
  _233_
  (
    .A(io_oeb[0]),
    .B(_019_),
    .Y(_000_)
  );


  sky130_fd_sc_hd__nor2_1
  _234_
  (
    .A(la_oenb[52]),
    .B(_158_),
    .Y(_020_)
  );


  sky130_fd_sc_hd__nor2_1
  _235_
  (
    .A(la_oenb[56]),
    .B(_158_),
    .Y(_021_)
  );


  sky130_fd_sc_hd__nor2_1
  _236_
  (
    .A(la_oenb[62]),
    .B(_158_),
    .Y(_022_)
  );


  sky130_fd_sc_hd__nor2_1
  _237_
  (
    .A(la_oenb[60]),
    .B(_158_),
    .Y(_023_)
  );


  sky130_fd_sc_hd__a22oi_1
  _238_
  (
    .A1(wbs_cyc_i),
    .A2(wbs_stb_i),
    .B1(la_oenb[60]),
    .B2(la_oenb[61]),
    .Y(_024_)
  );


  sky130_fd_sc_hd__nor2_1
  _239_
  (
    .A(la_oenb[48]),
    .B(_158_),
    .Y(_025_)
  );


  sky130_fd_sc_hd__nor2_1
  _240_
  (
    .A(la_oenb[63]),
    .B(_158_),
    .Y(_026_)
  );


  sky130_fd_sc_hd__nor2_1
  _241_
  (
    .A(la_oenb[51]),
    .B(_158_),
    .Y(_027_)
  );


  sky130_fd_sc_hd__nor2_1
  _242_
  (
    .A(la_oenb[49]),
    .B(_158_),
    .Y(_028_)
  );


  sky130_fd_sc_hd__nor2_1
  _243_
  (
    .A(la_oenb[54]),
    .B(_158_),
    .Y(_029_)
  );


  sky130_fd_sc_hd__nor2_1
  _244_
  (
    .A(la_oenb[50]),
    .B(_158_),
    .Y(_030_)
  );


  sky130_fd_sc_hd__nor2_1
  _245_
  (
    .A(la_oenb[59]),
    .B(_158_),
    .Y(_031_)
  );


  sky130_fd_sc_hd__nor2_1
  _246_
  (
    .A(la_oenb[53]),
    .B(_158_),
    .Y(_032_)
  );


  sky130_fd_sc_hd__a22oi_1
  _247_
  (
    .A1(wbs_cyc_i),
    .A2(wbs_stb_i),
    .B1(la_oenb[59]),
    .B2(la_oenb[53]),
    .Y(_033_)
  );


  sky130_fd_sc_hd__a22oi_1
  _248_
  (
    .A1(wbs_cyc_i),
    .A2(wbs_stb_i),
    .B1(la_oenb[48]),
    .B2(la_oenb[52]),
    .Y(_034_)
  );


  sky130_fd_sc_hd__a22oi_1
  _249_
  (
    .A1(wbs_cyc_i),
    .A2(wbs_stb_i),
    .B1(la_oenb[63]),
    .B2(la_oenb[56]),
    .Y(_035_)
  );


  sky130_fd_sc_hd__or4_1
  _250_
  (
    .A(_024_),
    .B(_033_),
    .C(_034_),
    .D(_035_),
    .X(_036_)
  );


  sky130_fd_sc_hd__a31oi_1
  _251_
  (
    .A1(la_oenb[51]),
    .A2(la_oenb[54]),
    .A3(la_oenb[50]),
    .B1(_158_),
    .Y(_037_)
  );


  sky130_fd_sc_hd__a41oi_1
  _252_
  (
    .A1(la_oenb[62]),
    .A2(la_oenb[57]),
    .A3(la_oenb[58]),
    .A4(la_oenb[55]),
    .B1(_158_),
    .Y(_038_)
  );


  sky130_fd_sc_hd__or4_1
  _253_
  (
    .A(_028_),
    .B(_036_),
    .C(_037_),
    .D(_038_),
    .X(_039_)
  );


  sky130_fd_sc_hd__a21oi_1
  _254_
  (
    .A1(\mprj.counter.count [0]),
    .A2(\mprj.counter.count [1]),
    .B1(_039_),
    .Y(_040_)
  );


  sky130_fd_sc_hd__o21ai_0
  _255_
  (
    .A1(\mprj.counter.count [0]),
    .A2(\mprj.counter.count [1]),
    .B1(_040_),
    .Y(_041_)
  );


  sky130_fd_sc_hd__nand2_1
  _256_
  (
    .A(la_data_in[49]),
    .B(_028_),
    .Y(_042_)
  );


  sky130_fd_sc_hd__a21oi_1
  _257_
  (
    .A1(_041_),
    .A2(_042_),
    .B1(_018_),
    .Y(_043_)
  );


  sky130_fd_sc_hd__and2_0
  _258_
  (
    .A(wbs_sel_i[0]),
    .B(wbs_we_i),
    .X(_044_)
  );


  sky130_fd_sc_hd__nand2_1
  _259_
  (
    .A(wbs_sel_i[0]),
    .B(wbs_we_i),
    .Y(_045_)
  );


  sky130_fd_sc_hd__a21oi_1
  _260_
  (
    .A1(\mprj.counter.count [1]),
    .A2(_039_),
    .B1(_044_),
    .Y(_046_)
  );


  sky130_fd_sc_hd__o21ai_0
  _261_
  (
    .A1(wbs_dat_i[1]),
    .A2(_045_),
    .B1(_018_),
    .Y(_047_)
  );


  sky130_fd_sc_hd__a21oi_1
  _262_
  (
    .A1(_041_),
    .A2(_046_),
    .B1(_047_),
    .Y(_048_)
  );


  sky130_fd_sc_hd__nor2_1
  _263_
  (
    .A(_043_),
    .B(_048_),
    .Y(_049_)
  );


  sky130_fd_sc_hd__nor2_1
  _264_
  (
    .A(io_oeb[0]),
    .B(_049_),
    .Y(_001_)
  );


  sky130_fd_sc_hd__nand2_1
  _265_
  (
    .A(la_data_in[48]),
    .B(_025_),
    .Y(_050_)
  );


  sky130_fd_sc_hd__o21ai_0
  _266_
  (
    .A1(\mprj.counter.count [0]),
    .A2(_039_),
    .B1(_050_),
    .Y(_051_)
  );


  sky130_fd_sc_hd__o21ai_0
  _267_
  (
    .A1(\mprj.counter.count [0]),
    .A2(_039_),
    .B1(_045_),
    .Y(_052_)
  );


  sky130_fd_sc_hd__a21oi_1
  _268_
  (
    .A1(\mprj.counter.count [0]),
    .A2(_039_),
    .B1(_052_),
    .Y(_053_)
  );


  sky130_fd_sc_hd__o21ai_0
  _269_
  (
    .A1(wbs_dat_i[0]),
    .A2(_045_),
    .B1(_018_),
    .Y(_054_)
  );


  sky130_fd_sc_hd__nor2_1
  _270_
  (
    .A(_053_),
    .B(_054_),
    .Y(_055_)
  );


  sky130_fd_sc_hd__a21oi_1
  _271_
  (
    .A1(_019_),
    .A2(_051_),
    .B1(_055_),
    .Y(_056_)
  );


  sky130_fd_sc_hd__nor2_1
  _272_
  (
    .A(io_oeb[0]),
    .B(_056_),
    .Y(_002_)
  );


  sky130_fd_sc_hd__and3_1
  _273_
  (
    .A(\mprj.counter.count [0]),
    .B(\mprj.counter.count [1]),
    .C(\mprj.counter.count [2]),
    .X(_057_)
  );


  sky130_fd_sc_hd__and4_1
  _274_
  (
    .A(\mprj.counter.count [0]),
    .B(\mprj.counter.count [1]),
    .C(\mprj.counter.count [2]),
    .D(\mprj.counter.count [3]),
    .X(_058_)
  );


  sky130_fd_sc_hd__and2_0
  _275_
  (
    .A(\mprj.counter.count [4]),
    .B(_058_),
    .X(_059_)
  );


  sky130_fd_sc_hd__and4_1
  _276_
  (
    .A(\mprj.counter.count [4]),
    .B(\mprj.counter.count [5]),
    .C(\mprj.counter.count [6]),
    .D(_058_),
    .X(_060_)
  );


  sky130_fd_sc_hd__and3_1
  _277_
  (
    .A(\mprj.counter.count [7]),
    .B(\mprj.counter.count [8]),
    .C(_060_),
    .X(_061_)
  );


  sky130_fd_sc_hd__and4_1
  _278_
  (
    .A(\mprj.counter.count [7]),
    .B(\mprj.counter.count [8]),
    .C(\mprj.counter.count [9]),
    .D(_060_),
    .X(_062_)
  );


  sky130_fd_sc_hd__and2_0
  _279_
  (
    .A(\mprj.counter.count [10]),
    .B(_062_),
    .X(_063_)
  );


  sky130_fd_sc_hd__and4_1
  _280_
  (
    .A(\mprj.counter.count [10]),
    .B(\mprj.counter.count [11]),
    .C(\mprj.counter.count [12]),
    .D(_062_),
    .X(_064_)
  );


  sky130_fd_sc_hd__nand3_1
  _281_
  (
    .A(\mprj.counter.count [11]),
    .B(\mprj.counter.count [12]),
    .C(_063_),
    .Y(_065_)
  );


  sky130_fd_sc_hd__a31o_1
  _282_
  (
    .A1(\mprj.counter.count [13]),
    .A2(\mprj.counter.count [14]),
    .A3(_064_),
    .B1(\mprj.counter.count [15]),
    .X(_066_)
  );


  sky130_fd_sc_hd__a41oi_1
  _283_
  (
    .A1(\mprj.counter.count [13]),
    .A2(\mprj.counter.count [14]),
    .A3(\mprj.counter.count [15]),
    .A4(_064_),
    .B1(_039_),
    .Y(_067_)
  );


  sky130_fd_sc_hd__a22oi_1
  _284_
  (
    .A1(la_data_in[63]),
    .A2(_026_),
    .B1(_066_),
    .B2(_067_),
    .Y(_068_)
  );


  sky130_fd_sc_hd__and2_0
  _285_
  (
    .A(wbs_we_i),
    .B(wbs_sel_i[1]),
    .X(_069_)
  );


  sky130_fd_sc_hd__nand2_1
  _286_
  (
    .A(wbs_we_i),
    .B(wbs_sel_i[1]),
    .Y(_070_)
  );


  sky130_fd_sc_hd__a221oi_1
  _287_
  (
    .A1(\mprj.counter.count [15]),
    .A2(_039_),
    .B1(_066_),
    .B2(_067_),
    .C1(_069_),
    .Y(_071_)
  );


  sky130_fd_sc_hd__o21ai_0
  _288_
  (
    .A1(wbs_dat_i[15]),
    .A2(_070_),
    .B1(_018_),
    .Y(_072_)
  );


  sky130_fd_sc_hd__o22a_1
  _289_
  (
    .A1(_018_),
    .A2(_068_),
    .B1(_071_),
    .B2(_072_),
    .X(_073_)
  );


  sky130_fd_sc_hd__nor2_1
  _290_
  (
    .A(io_oeb[0]),
    .B(_073_),
    .Y(_004_)
  );


  sky130_fd_sc_hd__a21o_1
  _291_
  (
    .A1(\mprj.counter.count [13]),
    .A2(_064_),
    .B1(\mprj.counter.count [14]),
    .X(_074_)
  );


  sky130_fd_sc_hd__a31oi_1
  _292_
  (
    .A1(\mprj.counter.count [13]),
    .A2(\mprj.counter.count [14]),
    .A3(_064_),
    .B1(_039_),
    .Y(_075_)
  );


  sky130_fd_sc_hd__a22oi_1
  _293_
  (
    .A1(la_data_in[62]),
    .A2(_022_),
    .B1(_074_),
    .B2(_075_),
    .Y(_076_)
  );


  sky130_fd_sc_hd__a221oi_1
  _294_
  (
    .A1(\mprj.counter.count [14]),
    .A2(_039_),
    .B1(_074_),
    .B2(_075_),
    .C1(_069_),
    .Y(_077_)
  );


  sky130_fd_sc_hd__o21ai_0
  _295_
  (
    .A1(wbs_dat_i[14]),
    .A2(_070_),
    .B1(_018_),
    .Y(_078_)
  );


  sky130_fd_sc_hd__o22a_1
  _296_
  (
    .A1(_018_),
    .A2(_076_),
    .B1(_077_),
    .B2(_078_),
    .X(_079_)
  );


  sky130_fd_sc_hd__nor2_1
  _297_
  (
    .A(io_oeb[0]),
    .B(_079_),
    .Y(_005_)
  );


  sky130_fd_sc_hd__a21oi_1
  _298_
  (
    .A1(\mprj.counter.count [13]),
    .A2(_064_),
    .B1(_039_),
    .Y(_080_)
  );


  sky130_fd_sc_hd__o21a_1
  _299_
  (
    .A1(\mprj.counter.count [13]),
    .A2(_064_),
    .B1(_080_),
    .X(_081_)
  );


  sky130_fd_sc_hd__nor3b_1
  _300_
  (
    .A(la_oenb[61]),
    .B(_158_),
    .C_N(la_data_in[61]),
    .Y(_082_)
  );


  sky130_fd_sc_hd__o21ai_0
  _301_
  (
    .A1(_081_),
    .A2(_082_),
    .B1(_019_),
    .Y(_083_)
  );


  sky130_fd_sc_hd__nand2_1
  _302_
  (
    .A(\mprj.counter.count [13]),
    .B(_039_),
    .Y(_084_)
  );


  sky130_fd_sc_hd__nand2_1
  _303_
  (
    .A(_070_),
    .B(_084_),
    .Y(_085_)
  );


  sky130_fd_sc_hd__o221ai_1
  _304_
  (
    .A1(wbs_dat_i[13]),
    .A2(_070_),
    .B1(_081_),
    .B2(_085_),
    .C1(_018_),
    .Y(_086_)
  );


  sky130_fd_sc_hd__a21oi_1
  _305_
  (
    .A1(_083_),
    .A2(_086_),
    .B1(io_oeb[0]),
    .Y(_006_)
  );


  sky130_fd_sc_hd__a31oi_1
  _306_
  (
    .A1(\mprj.counter.count [10]),
    .A2(\mprj.counter.count [11]),
    .A3(_062_),
    .B1(\mprj.counter.count [12]),
    .Y(_087_)
  );


  sky130_fd_sc_hd__nor2_1
  _307_
  (
    .A(_039_),
    .B(_087_),
    .Y(_088_)
  );


  sky130_fd_sc_hd__a22oi_1
  _308_
  (
    .A1(la_data_in[60]),
    .A2(_023_),
    .B1(_065_),
    .B2(_088_),
    .Y(_089_)
  );


  sky130_fd_sc_hd__a221oi_1
  _309_
  (
    .A1(\mprj.counter.count [12]),
    .A2(_039_),
    .B1(_065_),
    .B2(_088_),
    .C1(_069_),
    .Y(_090_)
  );


  sky130_fd_sc_hd__o21ai_0
  _310_
  (
    .A1(wbs_dat_i[12]),
    .A2(_070_),
    .B1(_018_),
    .Y(_091_)
  );


  sky130_fd_sc_hd__o22a_1
  _311_
  (
    .A1(_018_),
    .A2(_089_),
    .B1(_090_),
    .B2(_091_),
    .X(_092_)
  );


  sky130_fd_sc_hd__nor2_1
  _312_
  (
    .A(io_oeb[0]),
    .B(_092_),
    .Y(_007_)
  );


  sky130_fd_sc_hd__a31oi_1
  _313_
  (
    .A1(\mprj.counter.count [10]),
    .A2(\mprj.counter.count [11]),
    .A3(_062_),
    .B1(_039_),
    .Y(_093_)
  );


  sky130_fd_sc_hd__o21ai_0
  _314_
  (
    .A1(\mprj.counter.count [11]),
    .A2(_063_),
    .B1(_093_),
    .Y(_094_)
  );


  sky130_fd_sc_hd__nand2_1
  _315_
  (
    .A(la_data_in[59]),
    .B(_031_),
    .Y(_095_)
  );


  sky130_fd_sc_hd__a21oi_1
  _316_
  (
    .A1(_094_),
    .A2(_095_),
    .B1(_018_),
    .Y(_096_)
  );


  sky130_fd_sc_hd__a21oi_1
  _317_
  (
    .A1(\mprj.counter.count [11]),
    .A2(_039_),
    .B1(_069_),
    .Y(_097_)
  );


  sky130_fd_sc_hd__o21ai_0
  _318_
  (
    .A1(wbs_dat_i[11]),
    .A2(_070_),
    .B1(_018_),
    .Y(_098_)
  );


  sky130_fd_sc_hd__a21oi_1
  _319_
  (
    .A1(_094_),
    .A2(_097_),
    .B1(_098_),
    .Y(_099_)
  );


  sky130_fd_sc_hd__dfxtp_1
  _320_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? __chain_0__ : _003_),
    .Q(\mprj.counter.ready )
  );


  sky130_fd_sc_hd__dfxtp_1
  _321_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.ready  : _002_),
    .Q(\mprj.counter.count [0])
  );


  sky130_fd_sc_hd__dfxtp_1
  _322_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [0] : _001_),
    .Q(\mprj.counter.count [1])
  );


  sky130_fd_sc_hd__dfxtp_1
  _323_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [1] : _017_),
    .Q(\mprj.counter.count [2])
  );


  sky130_fd_sc_hd__dfxtp_1
  _324_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [2] : _016_),
    .Q(\mprj.counter.count [3])
  );


  sky130_fd_sc_hd__dfxtp_1
  _325_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [3] : _015_),
    .Q(\mprj.counter.count [4])
  );


  sky130_fd_sc_hd__dfxtp_1
  _326_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [4] : _014_),
    .Q(\mprj.counter.count [5])
  );


  sky130_fd_sc_hd__dfxtp_1
  _327_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [5] : _013_),
    .Q(\mprj.counter.count [6])
  );


  sky130_fd_sc_hd__dfxtp_1
  _328_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [6] : _012_),
    .Q(\mprj.counter.count [7])
  );


  sky130_fd_sc_hd__dfxtp_1
  _329_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [7] : _011_),
    .Q(\mprj.counter.count [8])
  );


  sky130_fd_sc_hd__dfxtp_1
  _330_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [8] : _010_),
    .Q(\mprj.counter.count [9])
  );


  sky130_fd_sc_hd__dfxtp_1
  _331_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [9] : _009_),
    .Q(\mprj.counter.count [10])
  );


  sky130_fd_sc_hd__dfxtp_1
  _332_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [10] : _008_),
    .Q(\mprj.counter.count [11])
  );


  sky130_fd_sc_hd__dfxtp_1
  _333_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [11] : _007_),
    .Q(\mprj.counter.count [12])
  );


  sky130_fd_sc_hd__dfxtp_1
  _334_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [12] : _006_),
    .Q(\mprj.counter.count [13])
  );


  sky130_fd_sc_hd__dfxtp_1
  _335_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [13] : _005_),
    .Q(\mprj.counter.count [14])
  );


  sky130_fd_sc_hd__dfxtp_1
  _336_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [14] : _004_),
    .Q(\mprj.counter.count [15])
  );


  sky130_fd_sc_hd__edfxtp_1
  _337_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.count [15] : \mprj.counter.count [0]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [0])
  );


  sky130_fd_sc_hd__edfxtp_1
  _338_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.rdata [0] : \mprj.counter.count [1]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [1])
  );


  sky130_fd_sc_hd__edfxtp_1
  _339_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.rdata [1] : \mprj.counter.count [2]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [2])
  );


  sky130_fd_sc_hd__edfxtp_1
  _340_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.rdata [2] : \mprj.counter.count [3]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [3])
  );


  sky130_fd_sc_hd__edfxtp_1
  _341_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.rdata [3] : \mprj.counter.count [4]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [4])
  );


  sky130_fd_sc_hd__edfxtp_1
  _342_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.rdata [4] : \mprj.counter.count [5]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [5])
  );


  sky130_fd_sc_hd__edfxtp_1
  _343_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.rdata [5] : \mprj.counter.count [6]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [6])
  );


  sky130_fd_sc_hd__edfxtp_1
  _344_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.rdata [6] : \mprj.counter.count [7]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [7])
  );


  sky130_fd_sc_hd__edfxtp_1
  _345_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.rdata [7] : \mprj.counter.count [8]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [8])
  );


  sky130_fd_sc_hd__edfxtp_1
  _346_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.rdata [8] : \mprj.counter.count [9]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [9])
  );


  sky130_fd_sc_hd__edfxtp_1
  _347_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.rdata [9] : \mprj.counter.count [10]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [10])
  );


  sky130_fd_sc_hd__edfxtp_1
  _348_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.rdata [10] : \mprj.counter.count [11]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [11])
  );


  sky130_fd_sc_hd__edfxtp_1
  _349_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.rdata [11] : \mprj.counter.count [12]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [12])
  );


  sky130_fd_sc_hd__edfxtp_1
  _350_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.rdata [12] : \mprj.counter.count [13]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [13])
  );


  sky130_fd_sc_hd__edfxtp_1
  _351_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.rdata [13] : \mprj.counter.count [14]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [14])
  );


  sky130_fd_sc_hd__edfxtp_1
  _352_
  (
    .CLK(\mprj.counter.clk ),
    .D((shift)? \mprj.counter.rdata [14] : \mprj.counter.count [15]),
    .DE(_000_),
    .Q(\mprj.counter.rdata [15])
  );


  sky130_fd_sc_hd__conb_1
  _353_
  (
    .LO(user_irq[0])
  );


  sky130_fd_sc_hd__conb_1
  _354_
  (
    .LO(user_irq[1])
  );


  sky130_fd_sc_hd__conb_1
  _355_
  (
    .LO(user_irq[2])
  );


  sky130_fd_sc_hd__conb_1
  _356_
  (
    .LO(la_data_out[16])
  );


  sky130_fd_sc_hd__conb_1
  _357_
  (
    .LO(la_data_out[17])
  );


  sky130_fd_sc_hd__conb_1
  _358_
  (
    .LO(la_data_out[18])
  );


  sky130_fd_sc_hd__conb_1
  _359_
  (
    .LO(la_data_out[19])
  );


  sky130_fd_sc_hd__conb_1
  _360_
  (
    .LO(la_data_out[20])
  );


  sky130_fd_sc_hd__conb_1
  _361_
  (
    .LO(la_data_out[21])
  );


  sky130_fd_sc_hd__conb_1
  _362_
  (
    .LO(la_data_out[22])
  );


  sky130_fd_sc_hd__conb_1
  _363_
  (
    .LO(la_data_out[23])
  );


  sky130_fd_sc_hd__conb_1
  _364_
  (
    .LO(la_data_out[24])
  );


  sky130_fd_sc_hd__conb_1
  _365_
  (
    .LO(la_data_out[25])
  );


  sky130_fd_sc_hd__conb_1
  _366_
  (
    .LO(la_data_out[26])
  );


  sky130_fd_sc_hd__conb_1
  _367_
  (
    .LO(la_data_out[27])
  );


  sky130_fd_sc_hd__conb_1
  _368_
  (
    .LO(la_data_out[28])
  );


  sky130_fd_sc_hd__conb_1
  _369_
  (
    .LO(la_data_out[29])
  );


  sky130_fd_sc_hd__conb_1
  _370_
  (
    .LO(la_data_out[30])
  );


  sky130_fd_sc_hd__conb_1
  _371_
  (
    .LO(la_data_out[31])
  );


  sky130_fd_sc_hd__conb_1
  _372_
  (
    .LO(la_data_out[32])
  );


  sky130_fd_sc_hd__conb_1
  _373_
  (
    .LO(la_data_out[33])
  );


  sky130_fd_sc_hd__conb_1
  _374_
  (
    .LO(la_data_out[34])
  );


  sky130_fd_sc_hd__conb_1
  _375_
  (
    .LO(la_data_out[35])
  );


  sky130_fd_sc_hd__conb_1
  _376_
  (
    .LO(la_data_out[36])
  );


  sky130_fd_sc_hd__conb_1
  _377_
  (
    .LO(la_data_out[37])
  );


  sky130_fd_sc_hd__conb_1
  _378_
  (
    .LO(la_data_out[38])
  );


  sky130_fd_sc_hd__conb_1
  _379_
  (
    .LO(la_data_out[39])
  );


  sky130_fd_sc_hd__conb_1
  _380_
  (
    .LO(la_data_out[40])
  );


  sky130_fd_sc_hd__conb_1
  _381_
  (
    .LO(la_data_out[41])
  );


  sky130_fd_sc_hd__conb_1
  _382_
  (
    .LO(la_data_out[42])
  );


  sky130_fd_sc_hd__conb_1
  _383_
  (
    .LO(la_data_out[43])
  );


  sky130_fd_sc_hd__conb_1
  _384_
  (
    .LO(la_data_out[44])
  );


  sky130_fd_sc_hd__conb_1
  _385_
  (
    .LO(la_data_out[45])
  );


  sky130_fd_sc_hd__conb_1
  _386_
  (
    .LO(la_data_out[46])
  );


  sky130_fd_sc_hd__conb_1
  _387_
  (
    .LO(la_data_out[47])
  );


  sky130_fd_sc_hd__conb_1
  _388_
  (
    .LO(la_data_out[48])
  );


  sky130_fd_sc_hd__conb_1
  _389_
  (
    .LO(la_data_out[49])
  );


  sky130_fd_sc_hd__conb_1
  _390_
  (
    .LO(la_data_out[50])
  );


  sky130_fd_sc_hd__conb_1
  _391_
  (
    .LO(la_data_out[51])
  );


  sky130_fd_sc_hd__conb_1
  _392_
  (
    .LO(la_data_out[52])
  );


  sky130_fd_sc_hd__conb_1
  _393_
  (
    .LO(la_data_out[53])
  );


  sky130_fd_sc_hd__conb_1
  _394_
  (
    .LO(la_data_out[54])
  );


  sky130_fd_sc_hd__conb_1
  _395_
  (
    .LO(la_data_out[55])
  );


  sky130_fd_sc_hd__conb_1
  _396_
  (
    .LO(la_data_out[56])
  );


  sky130_fd_sc_hd__conb_1
  _397_
  (
    .LO(la_data_out[57])
  );


  sky130_fd_sc_hd__conb_1
  _398_
  (
    .LO(la_data_out[58])
  );


  sky130_fd_sc_hd__conb_1
  _399_
  (
    .LO(la_data_out[59])
  );


  sky130_fd_sc_hd__conb_1
  _400_
  (
    .LO(la_data_out[60])
  );


  sky130_fd_sc_hd__conb_1
  _401_
  (
    .LO(la_data_out[61])
  );


  sky130_fd_sc_hd__conb_1
  _402_
  (
    .LO(la_data_out[62])
  );


  sky130_fd_sc_hd__conb_1
  _403_
  (
    .LO(la_data_out[63])
  );


  sky130_fd_sc_hd__conb_1
  _404_
  (
    .LO(la_data_out[64])
  );


  sky130_fd_sc_hd__conb_1
  _405_
  (
    .LO(la_data_out[65])
  );


  sky130_fd_sc_hd__conb_1
  _406_
  (
    .LO(la_data_out[66])
  );


  sky130_fd_sc_hd__conb_1
  _407_
  (
    .LO(la_data_out[67])
  );


  sky130_fd_sc_hd__conb_1
  _408_
  (
    .LO(la_data_out[68])
  );


  sky130_fd_sc_hd__conb_1
  _409_
  (
    .LO(la_data_out[69])
  );


  sky130_fd_sc_hd__conb_1
  _410_
  (
    .LO(la_data_out[70])
  );


  sky130_fd_sc_hd__conb_1
  _411_
  (
    .LO(la_data_out[71])
  );


  sky130_fd_sc_hd__conb_1
  _412_
  (
    .LO(la_data_out[72])
  );


  sky130_fd_sc_hd__conb_1
  _413_
  (
    .LO(la_data_out[73])
  );


  sky130_fd_sc_hd__conb_1
  _414_
  (
    .LO(la_data_out[74])
  );


  sky130_fd_sc_hd__conb_1
  _415_
  (
    .LO(la_data_out[75])
  );


  sky130_fd_sc_hd__conb_1
  _416_
  (
    .LO(la_data_out[76])
  );


  sky130_fd_sc_hd__conb_1
  _417_
  (
    .LO(la_data_out[77])
  );


  sky130_fd_sc_hd__conb_1
  _418_
  (
    .LO(la_data_out[78])
  );


  sky130_fd_sc_hd__conb_1
  _419_
  (
    .LO(la_data_out[79])
  );


  sky130_fd_sc_hd__conb_1
  _420_
  (
    .LO(la_data_out[80])
  );


  sky130_fd_sc_hd__conb_1
  _421_
  (
    .LO(la_data_out[81])
  );


  sky130_fd_sc_hd__conb_1
  _422_
  (
    .LO(la_data_out[82])
  );


  sky130_fd_sc_hd__conb_1
  _423_
  (
    .LO(la_data_out[83])
  );


  sky130_fd_sc_hd__conb_1
  _424_
  (
    .LO(la_data_out[84])
  );


  sky130_fd_sc_hd__conb_1
  _425_
  (
    .LO(la_data_out[85])
  );


  sky130_fd_sc_hd__conb_1
  _426_
  (
    .LO(la_data_out[86])
  );


  sky130_fd_sc_hd__conb_1
  _427_
  (
    .LO(la_data_out[87])
  );


  sky130_fd_sc_hd__conb_1
  _428_
  (
    .LO(la_data_out[88])
  );


  sky130_fd_sc_hd__conb_1
  _429_
  (
    .LO(la_data_out[89])
  );


  sky130_fd_sc_hd__conb_1
  _430_
  (
    .LO(la_data_out[90])
  );


  sky130_fd_sc_hd__conb_1
  _431_
  (
    .LO(la_data_out[91])
  );


  sky130_fd_sc_hd__conb_1
  _432_
  (
    .LO(la_data_out[92])
  );


  sky130_fd_sc_hd__conb_1
  _433_
  (
    .LO(la_data_out[93])
  );


  sky130_fd_sc_hd__conb_1
  _434_
  (
    .LO(la_data_out[94])
  );


  sky130_fd_sc_hd__conb_1
  _435_
  (
    .LO(la_data_out[95])
  );


  sky130_fd_sc_hd__conb_1
  _436_
  (
    .LO(la_data_out[96])
  );


  sky130_fd_sc_hd__conb_1
  _437_
  (
    .LO(la_data_out[97])
  );


  sky130_fd_sc_hd__conb_1
  _438_
  (
    .LO(la_data_out[98])
  );


  sky130_fd_sc_hd__conb_1
  _439_
  (
    .LO(la_data_out[99])
  );


  sky130_fd_sc_hd__conb_1
  _440_
  (
    .LO(la_data_out[100])
  );


  sky130_fd_sc_hd__conb_1
  _441_
  (
    .LO(la_data_out[101])
  );


  sky130_fd_sc_hd__conb_1
  _442_
  (
    .LO(la_data_out[102])
  );


  sky130_fd_sc_hd__conb_1
  _443_
  (
    .LO(la_data_out[103])
  );


  sky130_fd_sc_hd__conb_1
  _444_
  (
    .LO(la_data_out[104])
  );


  sky130_fd_sc_hd__conb_1
  _445_
  (
    .LO(la_data_out[105])
  );


  sky130_fd_sc_hd__conb_1
  _446_
  (
    .LO(la_data_out[106])
  );


  sky130_fd_sc_hd__conb_1
  _447_
  (
    .LO(la_data_out[107])
  );


  sky130_fd_sc_hd__conb_1
  _448_
  (
    .LO(la_data_out[108])
  );


  sky130_fd_sc_hd__conb_1
  _449_
  (
    .LO(la_data_out[109])
  );


  sky130_fd_sc_hd__conb_1
  _450_
  (
    .LO(la_data_out[110])
  );


  sky130_fd_sc_hd__conb_1
  _451_
  (
    .LO(la_data_out[111])
  );


  sky130_fd_sc_hd__conb_1
  _452_
  (
    .LO(la_data_out[112])
  );


  sky130_fd_sc_hd__conb_1
  _453_
  (
    .LO(la_data_out[113])
  );


  sky130_fd_sc_hd__conb_1
  _454_
  (
    .LO(la_data_out[114])
  );


  sky130_fd_sc_hd__conb_1
  _455_
  (
    .LO(la_data_out[115])
  );


  sky130_fd_sc_hd__conb_1
  _456_
  (
    .LO(la_data_out[116])
  );


  sky130_fd_sc_hd__conb_1
  _457_
  (
    .LO(la_data_out[117])
  );


  sky130_fd_sc_hd__conb_1
  _458_
  (
    .LO(la_data_out[118])
  );


  sky130_fd_sc_hd__conb_1
  _459_
  (
    .LO(la_data_out[119])
  );


  sky130_fd_sc_hd__conb_1
  _460_
  (
    .LO(la_data_out[120])
  );


  sky130_fd_sc_hd__conb_1
  _461_
  (
    .LO(la_data_out[121])
  );


  sky130_fd_sc_hd__conb_1
  _462_
  (
    .LO(la_data_out[122])
  );


  sky130_fd_sc_hd__conb_1
  _463_
  (
    .LO(la_data_out[123])
  );


  sky130_fd_sc_hd__conb_1
  _464_
  (
    .LO(la_data_out[124])
  );


  sky130_fd_sc_hd__conb_1
  _465_
  (
    .LO(la_data_out[125])
  );


  sky130_fd_sc_hd__conb_1
  _466_
  (
    .LO(la_data_out[126])
  );


  sky130_fd_sc_hd__conb_1
  _467_
  (
    .LO(la_data_out[127])
  );


  sky130_fd_sc_hd__conb_1
  _468_
  (
    .LO(wbs_dat_o[16])
  );


  sky130_fd_sc_hd__conb_1
  _469_
  (
    .LO(wbs_dat_o[17])
  );


  sky130_fd_sc_hd__conb_1
  _470_
  (
    .LO(wbs_dat_o[18])
  );


  sky130_fd_sc_hd__conb_1
  _471_
  (
    .LO(wbs_dat_o[19])
  );


  sky130_fd_sc_hd__conb_1
  _472_
  (
    .LO(wbs_dat_o[20])
  );


  sky130_fd_sc_hd__conb_1
  _473_
  (
    .LO(wbs_dat_o[21])
  );


  sky130_fd_sc_hd__conb_1
  _474_
  (
    .LO(wbs_dat_o[22])
  );


  sky130_fd_sc_hd__conb_1
  _475_
  (
    .LO(wbs_dat_o[23])
  );


  sky130_fd_sc_hd__conb_1
  _476_
  (
    .LO(wbs_dat_o[24])
  );


  sky130_fd_sc_hd__conb_1
  _477_
  (
    .LO(wbs_dat_o[25])
  );


  sky130_fd_sc_hd__conb_1
  _478_
  (
    .LO(wbs_dat_o[26])
  );


  sky130_fd_sc_hd__conb_1
  _479_
  (
    .LO(wbs_dat_o[27])
  );


  sky130_fd_sc_hd__conb_1
  _480_
  (
    .LO(wbs_dat_o[28])
  );


  sky130_fd_sc_hd__conb_1
  _481_
  (
    .LO(wbs_dat_o[29])
  );


  sky130_fd_sc_hd__conb_1
  _482_
  (
    .LO(wbs_dat_o[30])
  );


  sky130_fd_sc_hd__conb_1
  _483_
  (
    .LO(wbs_dat_o[31])
  );

  assign \mprj.wstrb  = { 2'hx, \mprj.counter.wstrb [1:0] };
  assign \mprj.count  = \mprj.counter.count ;
  assign \mprj.wdata  = wbs_dat_i[15:0];
  assign \mprj.rdata  = \mprj.counter.rdata ;
  assign \mprj.rst  = io_oeb[0];
  assign \mprj.clk  = \mprj.counter.clk ;
  assign \mprj.io_oeb  = { io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0] };
  assign \mprj.io_out  = \mprj.counter.count ;
  assign \mprj.io_in  = { io_in[37:30], io_in[7:0] };
  assign \mprj.la_oenb  = la_oenb;
  assign \mprj.la_data_out [15:0] = \mprj.counter.count ;
  assign \mprj.la_data_in  = la_data_in;
  assign \mprj.wbs_dat_o [15:0] = \mprj.counter.rdata ;
  assign \mprj.wbs_ack_o  = \mprj.counter.ready ;
  assign \mprj.wbs_adr_i  = wbs_adr_i;
  assign \mprj.wbs_dat_i  = wbs_dat_i;
  assign \mprj.wbs_sel_i  = wbs_sel_i;
  assign \mprj.wbs_we_i  = wbs_we_i;
  assign \mprj.wbs_cyc_i  = wbs_cyc_i;
  assign \mprj.wbs_stb_i  = wbs_stb_i;
  assign \mprj.wb_rst_i  = wb_rst_i;
  assign \mprj.wb_clk_i  = wb_clk_i;
  assign \mprj.counter.la_input  = la_data_in[63:48];
  assign \mprj.counter.wdata  = wbs_dat_i[15:0];
  assign \mprj.counter.wstrb [3:2] = 2'hx;
  assign \mprj.counter.reset  = io_oeb[0];
  assign io_oeb[37:1] = { io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], 22'hxxxxxx, io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0], io_oeb[0] };
  assign io_out = { \mprj.counter.count [15:8], 22'hxxxxxx, \mprj.counter.count [7:0] };
  assign la_data_out[15:0] = \mprj.counter.count ;
  assign wbs_dat_o[15:0] = \mprj.counter.rdata ;
  assign wbs_ack_o = \mprj.counter.ready ;
  assign sout = \mprj.counter.rdata [15];
  assign __clk_source__ = (test)? tck : wb_clk_i;

endmodule


