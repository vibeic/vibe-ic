

module BoundaryScanRegister_input
(
  din,
  dout,
  sin,
  sout,
  clock,
  reset,
  testing,
  shift
);

  input din;
  output dout;
  input sin;
  output sout;
  input clock;input reset;input testing;input shift;
  reg store;

  always @(posedge clock or posedge reset) begin
    if(reset) begin
      store <= 1'b0;
    end else begin
      store <= (shift)? sin : dout;
    end
  end

  assign sout = store;
  assign dout = (testing)? store : din;

endmodule



module BoundaryScanRegister_output
(
  din,
  dout,
  sin,
  sout,
  clock,
  reset,
  testing,
  shift
);

  input din;
  output dout;
  input sin;
  output sout;
  input clock;input reset;input testing;input shift;
  reg store;

  always @(posedge clock or posedge reset) begin
    if(reset) begin
      store <= 1'b0;
    end else begin
      store <= (shift)? sin : dout;
    end
  end

  assign sout = store;
  assign dout = din;

endmodule



module \chip_top.original 
(
  clk,
  rst,
  x,
  y,
  p,
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
  input clk;
  wire clk;
  input rst;
  wire rst;
  input [31:0] x;
  wire [31:0] x;
  input y;
  wire y;
  output p;
  wire p;
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
  wire _159_;
  wire _160_;
  wire _161_;
  wire _162_;
  wire _163_;
  wire _164_;
  wire _165_;
  wire _166_;
  wire _167_;
  wire _168_;
  wire _169_;
  wire _170_;
  wire _171_;
  wire _172_;
  wire _173_;
  wire _174_;
  wire _175_;
  wire _176_;
  wire _177_;
  wire _178_;
  wire _179_;
  wire _180_;
  wire _181_;
  wire _182_;
  wire _183_;
  wire _184_;
  wire _185_;
  wire _186_;
  wire _187_;
  wire _188_;
  wire _189_;
  wire _190_;
  wire _191_;
  wire _192_;
  wire _193_;
  wire _194_;
  wire _195_;
  wire _196_;
  wire _197_;
  wire _198_;
  wire _199_;
  wire _200_;
  wire _201_;
  wire _202_;
  wire _203_;
  wire _204_;
  wire _205_;
  wire _206_;
  wire _207_;
  wire _208_;
  wire _209_;
  wire _210_;
  wire _211_;
  wire _212_;
  wire _213_;
  wire _214_;
  wire _215_;
  wire _216_;
  wire _217_;
  wire _218_;
  wire _219_;
  wire _220_;
  wire _221_;
  wire [31:0] c;
  wire pr;
  wire [31:0] s;
  wire yr;

  sky130_fd_sc_hd__nor3_1
  _222_
  (
    .A(rst),
    .B(_214_),
    .C(_215_),
    .Y(_062_)
  );


  sky130_fd_sc_hd__xor2_1
  _223_
  (
    .A(c[27]),
    .B(s[27]),
    .X(_216_)
  );


  sky130_fd_sc_hd__a21oi_1
  _224_
  (
    .A1(yr),
    .A2(x[27]),
    .B1(_216_),
    .Y(_217_)
  );


  sky130_fd_sc_hd__and3_1
  _225_
  (
    .A(yr),
    .B(x[27]),
    .C(_216_),
    .X(_218_)
  );


  sky130_fd_sc_hd__nor3_1
  _226_
  (
    .A(rst),
    .B(_217_),
    .C(_218_),
    .Y(_063_)
  );


  sky130_fd_sc_hd__xor2_1
  _227_
  (
    .A(c[26]),
    .B(s[26]),
    .X(_219_)
  );


  sky130_fd_sc_hd__a21oi_1
  _228_
  (
    .A1(yr),
    .A2(x[26]),
    .B1(_219_),
    .Y(_220_)
  );


  sky130_fd_sc_hd__and3_1
  _229_
  (
    .A(yr),
    .B(x[26]),
    .C(_219_),
    .X(_221_)
  );


  sky130_fd_sc_hd__nor3_1
  _230_
  (
    .A(rst),
    .B(_220_),
    .C(_221_),
    .Y(_064_)
  );


  sky130_fd_sc_hd__nand2_1
  _231_
  (
    .A(yr),
    .B(x[25]),
    .Y(_065_)
  );


  sky130_fd_sc_hd__nand2_1
  _232_
  (
    .A(c[25]),
    .B(s[25]),
    .Y(_066_)
  );


  sky130_fd_sc_hd__nor2_1
  _233_
  (
    .A(c[25]),
    .B(s[25]),
    .Y(_067_)
  );


  sky130_fd_sc_hd__xnor2_1
  _234_
  (
    .A(c[25]),
    .B(s[25]),
    .Y(_068_)
  );


  sky130_fd_sc_hd__xnor2_1
  _235_
  (
    .A(_065_),
    .B(_068_),
    .Y(_069_)
  );


  sky130_fd_sc_hd__nor2_1
  _236_
  (
    .A(rst),
    .B(_069_),
    .Y(_000_)
  );


  sky130_fd_sc_hd__nand2_1
  _237_
  (
    .A(yr),
    .B(x[24]),
    .Y(_070_)
  );


  sky130_fd_sc_hd__nand2_1
  _238_
  (
    .A(c[24]),
    .B(s[24]),
    .Y(_071_)
  );


  sky130_fd_sc_hd__nor2_1
  _239_
  (
    .A(c[24]),
    .B(s[24]),
    .Y(_072_)
  );


  sky130_fd_sc_hd__xnor2_1
  _240_
  (
    .A(c[24]),
    .B(s[24]),
    .Y(_073_)
  );


  sky130_fd_sc_hd__xnor2_1
  _241_
  (
    .A(_070_),
    .B(_073_),
    .Y(_074_)
  );


  sky130_fd_sc_hd__nor2_1
  _242_
  (
    .A(rst),
    .B(_074_),
    .Y(_001_)
  );


  sky130_fd_sc_hd__nand2_1
  _243_
  (
    .A(yr),
    .B(x[23]),
    .Y(_075_)
  );


  sky130_fd_sc_hd__nand2_1
  _244_
  (
    .A(c[23]),
    .B(s[23]),
    .Y(_076_)
  );


  sky130_fd_sc_hd__nor2_1
  _245_
  (
    .A(c[23]),
    .B(s[23]),
    .Y(_077_)
  );


  sky130_fd_sc_hd__xnor2_1
  _246_
  (
    .A(c[23]),
    .B(s[23]),
    .Y(_078_)
  );


  sky130_fd_sc_hd__xnor2_1
  _247_
  (
    .A(_075_),
    .B(_078_),
    .Y(_079_)
  );


  sky130_fd_sc_hd__nor2_1
  _248_
  (
    .A(rst),
    .B(_079_),
    .Y(_002_)
  );


  sky130_fd_sc_hd__nand2_1
  _249_
  (
    .A(yr),
    .B(x[22]),
    .Y(_080_)
  );


  sky130_fd_sc_hd__nand2_1
  _250_
  (
    .A(c[22]),
    .B(s[22]),
    .Y(_081_)
  );


  sky130_fd_sc_hd__nor2_1
  _251_
  (
    .A(c[22]),
    .B(s[22]),
    .Y(_082_)
  );


  sky130_fd_sc_hd__xnor2_1
  _252_
  (
    .A(c[22]),
    .B(s[22]),
    .Y(_083_)
  );


  sky130_fd_sc_hd__xnor2_1
  _253_
  (
    .A(_080_),
    .B(_083_),
    .Y(_084_)
  );


  sky130_fd_sc_hd__nor2_1
  _254_
  (
    .A(rst),
    .B(_084_),
    .Y(_003_)
  );


  sky130_fd_sc_hd__nand2_1
  _255_
  (
    .A(yr),
    .B(x[21]),
    .Y(_085_)
  );


  sky130_fd_sc_hd__nand2_1
  _256_
  (
    .A(c[21]),
    .B(s[21]),
    .Y(_086_)
  );


  sky130_fd_sc_hd__nor2_1
  _257_
  (
    .A(c[21]),
    .B(s[21]),
    .Y(_087_)
  );


  sky130_fd_sc_hd__xnor2_1
  _258_
  (
    .A(c[21]),
    .B(s[21]),
    .Y(_088_)
  );


  sky130_fd_sc_hd__xnor2_1
  _259_
  (
    .A(_085_),
    .B(_088_),
    .Y(_089_)
  );


  sky130_fd_sc_hd__nor2_1
  _260_
  (
    .A(rst),
    .B(_089_),
    .Y(_004_)
  );


  sky130_fd_sc_hd__nand2_1
  _261_
  (
    .A(yr),
    .B(x[20]),
    .Y(_090_)
  );


  sky130_fd_sc_hd__nand2_1
  _262_
  (
    .A(c[20]),
    .B(s[20]),
    .Y(_091_)
  );


  sky130_fd_sc_hd__nor2_1
  _263_
  (
    .A(c[20]),
    .B(s[20]),
    .Y(_092_)
  );


  sky130_fd_sc_hd__xnor2_1
  _264_
  (
    .A(c[20]),
    .B(s[20]),
    .Y(_093_)
  );


  sky130_fd_sc_hd__xnor2_1
  _265_
  (
    .A(_090_),
    .B(_093_),
    .Y(_094_)
  );


  sky130_fd_sc_hd__nor2_1
  _266_
  (
    .A(rst),
    .B(_094_),
    .Y(_005_)
  );


  sky130_fd_sc_hd__nand2_1
  _267_
  (
    .A(yr),
    .B(x[19]),
    .Y(_095_)
  );


  sky130_fd_sc_hd__nand2_1
  _268_
  (
    .A(c[19]),
    .B(s[19]),
    .Y(_096_)
  );


  sky130_fd_sc_hd__nor2_1
  _269_
  (
    .A(c[19]),
    .B(s[19]),
    .Y(_097_)
  );


  sky130_fd_sc_hd__xnor2_1
  _270_
  (
    .A(c[19]),
    .B(s[19]),
    .Y(_098_)
  );


  sky130_fd_sc_hd__xnor2_1
  _271_
  (
    .A(_095_),
    .B(_098_),
    .Y(_099_)
  );


  sky130_fd_sc_hd__nor2_1
  _272_
  (
    .A(rst),
    .B(_099_),
    .Y(_006_)
  );


  sky130_fd_sc_hd__nand2_1
  _273_
  (
    .A(yr),
    .B(x[18]),
    .Y(_100_)
  );


  sky130_fd_sc_hd__nand2_1
  _274_
  (
    .A(c[18]),
    .B(s[18]),
    .Y(_101_)
  );


  sky130_fd_sc_hd__nor2_1
  _275_
  (
    .A(c[18]),
    .B(s[18]),
    .Y(_102_)
  );


  sky130_fd_sc_hd__xnor2_1
  _276_
  (
    .A(c[18]),
    .B(s[18]),
    .Y(_103_)
  );


  sky130_fd_sc_hd__xnor2_1
  _277_
  (
    .A(_100_),
    .B(_103_),
    .Y(_104_)
  );


  sky130_fd_sc_hd__nor2_1
  _278_
  (
    .A(rst),
    .B(_104_),
    .Y(_007_)
  );


  sky130_fd_sc_hd__nand2_1
  _279_
  (
    .A(yr),
    .B(x[17]),
    .Y(_105_)
  );


  sky130_fd_sc_hd__nand2_1
  _280_
  (
    .A(c[17]),
    .B(s[17]),
    .Y(_106_)
  );


  sky130_fd_sc_hd__nor2_1
  _281_
  (
    .A(c[17]),
    .B(s[17]),
    .Y(_107_)
  );


  sky130_fd_sc_hd__xnor2_1
  _282_
  (
    .A(c[17]),
    .B(s[17]),
    .Y(_108_)
  );


  sky130_fd_sc_hd__xnor2_1
  _283_
  (
    .A(_105_),
    .B(_108_),
    .Y(_109_)
  );


  sky130_fd_sc_hd__nor2_1
  _284_
  (
    .A(rst),
    .B(_109_),
    .Y(_008_)
  );


  sky130_fd_sc_hd__nand2_1
  _285_
  (
    .A(yr),
    .B(x[16]),
    .Y(_110_)
  );


  sky130_fd_sc_hd__nand2_1
  _286_
  (
    .A(c[16]),
    .B(s[16]),
    .Y(_111_)
  );


  sky130_fd_sc_hd__nor2_1
  _287_
  (
    .A(c[16]),
    .B(s[16]),
    .Y(_112_)
  );


  sky130_fd_sc_hd__xnor2_1
  _288_
  (
    .A(c[16]),
    .B(s[16]),
    .Y(_113_)
  );


  sky130_fd_sc_hd__xnor2_1
  _289_
  (
    .A(_110_),
    .B(_113_),
    .Y(_114_)
  );


  sky130_fd_sc_hd__nor2_1
  _290_
  (
    .A(rst),
    .B(_114_),
    .Y(_009_)
  );


  sky130_fd_sc_hd__nand2_1
  _291_
  (
    .A(yr),
    .B(x[15]),
    .Y(_115_)
  );


  sky130_fd_sc_hd__nand2_1
  _292_
  (
    .A(c[15]),
    .B(s[15]),
    .Y(_116_)
  );


  sky130_fd_sc_hd__nor2_1
  _293_
  (
    .A(c[15]),
    .B(s[15]),
    .Y(_117_)
  );


  sky130_fd_sc_hd__xnor2_1
  _294_
  (
    .A(c[15]),
    .B(s[15]),
    .Y(_118_)
  );


  sky130_fd_sc_hd__xnor2_1
  _295_
  (
    .A(_115_),
    .B(_118_),
    .Y(_119_)
  );


  sky130_fd_sc_hd__nor2_1
  _296_
  (
    .A(rst),
    .B(_119_),
    .Y(_010_)
  );


  sky130_fd_sc_hd__nand2_1
  _297_
  (
    .A(yr),
    .B(x[14]),
    .Y(_120_)
  );


  sky130_fd_sc_hd__nand2_1
  _298_
  (
    .A(c[14]),
    .B(s[14]),
    .Y(_121_)
  );


  sky130_fd_sc_hd__nor2_1
  _299_
  (
    .A(c[14]),
    .B(s[14]),
    .Y(_122_)
  );


  sky130_fd_sc_hd__xnor2_1
  _300_
  (
    .A(c[14]),
    .B(s[14]),
    .Y(_123_)
  );


  sky130_fd_sc_hd__xnor2_1
  _301_
  (
    .A(_120_),
    .B(_123_),
    .Y(_124_)
  );


  sky130_fd_sc_hd__nor2_1
  _302_
  (
    .A(rst),
    .B(_124_),
    .Y(_011_)
  );


  sky130_fd_sc_hd__nand2_1
  _303_
  (
    .A(yr),
    .B(x[13]),
    .Y(_125_)
  );


  sky130_fd_sc_hd__nand2_1
  _304_
  (
    .A(c[13]),
    .B(s[13]),
    .Y(_126_)
  );


  sky130_fd_sc_hd__nor2_1
  _305_
  (
    .A(c[13]),
    .B(s[13]),
    .Y(_127_)
  );


  sky130_fd_sc_hd__xnor2_1
  _306_
  (
    .A(c[13]),
    .B(s[13]),
    .Y(_128_)
  );


  sky130_fd_sc_hd__xnor2_1
  _307_
  (
    .A(_125_),
    .B(_128_),
    .Y(_129_)
  );


  sky130_fd_sc_hd__nor2_1
  _308_
  (
    .A(rst),
    .B(_129_),
    .Y(_012_)
  );


  sky130_fd_sc_hd__nand2_1
  _309_
  (
    .A(yr),
    .B(x[12]),
    .Y(_130_)
  );


  sky130_fd_sc_hd__nand2_1
  _310_
  (
    .A(c[12]),
    .B(s[12]),
    .Y(_131_)
  );


  sky130_fd_sc_hd__nor2_1
  _311_
  (
    .A(c[12]),
    .B(s[12]),
    .Y(_132_)
  );


  sky130_fd_sc_hd__xnor2_1
  _312_
  (
    .A(c[12]),
    .B(s[12]),
    .Y(_133_)
  );


  sky130_fd_sc_hd__xnor2_1
  _313_
  (
    .A(_130_),
    .B(_133_),
    .Y(_134_)
  );


  sky130_fd_sc_hd__nor2_1
  _314_
  (
    .A(rst),
    .B(_134_),
    .Y(_013_)
  );


  sky130_fd_sc_hd__nand2_1
  _315_
  (
    .A(yr),
    .B(x[11]),
    .Y(_135_)
  );


  sky130_fd_sc_hd__nand2_1
  _316_
  (
    .A(c[11]),
    .B(s[11]),
    .Y(_136_)
  );


  sky130_fd_sc_hd__nor2_1
  _317_
  (
    .A(c[11]),
    .B(s[11]),
    .Y(_137_)
  );


  sky130_fd_sc_hd__xnor2_1
  _318_
  (
    .A(c[11]),
    .B(s[11]),
    .Y(_138_)
  );


  sky130_fd_sc_hd__xnor2_1
  _319_
  (
    .A(_135_),
    .B(_138_),
    .Y(_139_)
  );


  sky130_fd_sc_hd__nor2_1
  _320_
  (
    .A(rst),
    .B(_139_),
    .Y(_014_)
  );


  sky130_fd_sc_hd__nand2_1
  _321_
  (
    .A(yr),
    .B(x[10]),
    .Y(_140_)
  );


  sky130_fd_sc_hd__nand2_1
  _322_
  (
    .A(c[10]),
    .B(s[10]),
    .Y(_141_)
  );


  sky130_fd_sc_hd__nor2_1
  _323_
  (
    .A(c[10]),
    .B(s[10]),
    .Y(_142_)
  );


  sky130_fd_sc_hd__xnor2_1
  _324_
  (
    .A(c[10]),
    .B(s[10]),
    .Y(_143_)
  );


  sky130_fd_sc_hd__xnor2_1
  _325_
  (
    .A(_140_),
    .B(_143_),
    .Y(_144_)
  );


  sky130_fd_sc_hd__nor2_1
  _326_
  (
    .A(rst),
    .B(_144_),
    .Y(_015_)
  );


  sky130_fd_sc_hd__nand2_1
  _327_
  (
    .A(yr),
    .B(x[9]),
    .Y(_145_)
  );


  sky130_fd_sc_hd__nand2_1
  _328_
  (
    .A(c[9]),
    .B(s[9]),
    .Y(_146_)
  );


  sky130_fd_sc_hd__nor2_1
  _329_
  (
    .A(c[9]),
    .B(s[9]),
    .Y(_147_)
  );


  sky130_fd_sc_hd__xnor2_1
  _330_
  (
    .A(c[9]),
    .B(s[9]),
    .Y(_148_)
  );


  sky130_fd_sc_hd__xnor2_1
  _331_
  (
    .A(_145_),
    .B(_148_),
    .Y(_149_)
  );


  sky130_fd_sc_hd__nor2_1
  _332_
  (
    .A(rst),
    .B(_149_),
    .Y(_016_)
  );


  sky130_fd_sc_hd__nand2_1
  _333_
  (
    .A(yr),
    .B(x[8]),
    .Y(_150_)
  );


  sky130_fd_sc_hd__nand2_1
  _334_
  (
    .A(c[8]),
    .B(s[8]),
    .Y(_151_)
  );


  sky130_fd_sc_hd__nor2_1
  _335_
  (
    .A(c[8]),
    .B(s[8]),
    .Y(_152_)
  );


  sky130_fd_sc_hd__xnor2_1
  _336_
  (
    .A(c[8]),
    .B(s[8]),
    .Y(_153_)
  );


  sky130_fd_sc_hd__xnor2_1
  _337_
  (
    .A(_150_),
    .B(_153_),
    .Y(_154_)
  );


  sky130_fd_sc_hd__nor2_1
  _338_
  (
    .A(rst),
    .B(_154_),
    .Y(_017_)
  );


  sky130_fd_sc_hd__nand2_1
  _339_
  (
    .A(yr),
    .B(x[7]),
    .Y(_155_)
  );


  sky130_fd_sc_hd__nand2_1
  _340_
  (
    .A(c[7]),
    .B(s[7]),
    .Y(_156_)
  );


  sky130_fd_sc_hd__nor2_1
  _341_
  (
    .A(c[7]),
    .B(s[7]),
    .Y(_157_)
  );


  sky130_fd_sc_hd__xnor2_1
  _342_
  (
    .A(c[7]),
    .B(s[7]),
    .Y(_158_)
  );


  sky130_fd_sc_hd__xnor2_1
  _343_
  (
    .A(_155_),
    .B(_158_),
    .Y(_159_)
  );


  sky130_fd_sc_hd__nor2_1
  _344_
  (
    .A(rst),
    .B(_159_),
    .Y(_018_)
  );


  sky130_fd_sc_hd__nand2_1
  _345_
  (
    .A(yr),
    .B(x[6]),
    .Y(_160_)
  );


  sky130_fd_sc_hd__nand2_1
  _346_
  (
    .A(c[6]),
    .B(s[6]),
    .Y(_161_)
  );


  sky130_fd_sc_hd__nor2_1
  _347_
  (
    .A(c[6]),
    .B(s[6]),
    .Y(_162_)
  );


  sky130_fd_sc_hd__xnor2_1
  _348_
  (
    .A(c[6]),
    .B(s[6]),
    .Y(_163_)
  );


  sky130_fd_sc_hd__xnor2_1
  _349_
  (
    .A(_160_),
    .B(_163_),
    .Y(_164_)
  );


  sky130_fd_sc_hd__nor2_1
  _350_
  (
    .A(rst),
    .B(_164_),
    .Y(_019_)
  );


  sky130_fd_sc_hd__nand2_1
  _351_
  (
    .A(yr),
    .B(x[5]),
    .Y(_165_)
  );


  sky130_fd_sc_hd__nand2_1
  _352_
  (
    .A(c[5]),
    .B(s[5]),
    .Y(_166_)
  );


  sky130_fd_sc_hd__nor2_1
  _353_
  (
    .A(c[5]),
    .B(s[5]),
    .Y(_167_)
  );


  sky130_fd_sc_hd__xnor2_1
  _354_
  (
    .A(c[5]),
    .B(s[5]),
    .Y(_168_)
  );


  sky130_fd_sc_hd__xnor2_1
  _355_
  (
    .A(_165_),
    .B(_168_),
    .Y(_169_)
  );


  sky130_fd_sc_hd__nor2_1
  _356_
  (
    .A(rst),
    .B(_169_),
    .Y(_020_)
  );


  sky130_fd_sc_hd__nand2_1
  _357_
  (
    .A(yr),
    .B(x[4]),
    .Y(_170_)
  );


  sky130_fd_sc_hd__nand2_1
  _358_
  (
    .A(c[4]),
    .B(s[4]),
    .Y(_171_)
  );


  sky130_fd_sc_hd__nor2_1
  _359_
  (
    .A(c[4]),
    .B(s[4]),
    .Y(_172_)
  );


  sky130_fd_sc_hd__xnor2_1
  _360_
  (
    .A(c[4]),
    .B(s[4]),
    .Y(_173_)
  );


  sky130_fd_sc_hd__xnor2_1
  _361_
  (
    .A(_170_),
    .B(_173_),
    .Y(_174_)
  );


  sky130_fd_sc_hd__nor2_1
  _362_
  (
    .A(rst),
    .B(_174_),
    .Y(_021_)
  );


  sky130_fd_sc_hd__nand2_1
  _363_
  (
    .A(yr),
    .B(x[3]),
    .Y(_175_)
  );


  sky130_fd_sc_hd__nand2_1
  _364_
  (
    .A(c[3]),
    .B(s[3]),
    .Y(_176_)
  );


  sky130_fd_sc_hd__nor2_1
  _365_
  (
    .A(c[3]),
    .B(s[3]),
    .Y(_177_)
  );


  sky130_fd_sc_hd__xnor2_1
  _366_
  (
    .A(c[3]),
    .B(s[3]),
    .Y(_178_)
  );


  sky130_fd_sc_hd__xnor2_1
  _367_
  (
    .A(_175_),
    .B(_178_),
    .Y(_179_)
  );


  sky130_fd_sc_hd__nor2_1
  _368_
  (
    .A(rst),
    .B(_179_),
    .Y(_022_)
  );


  sky130_fd_sc_hd__nand2_1
  _369_
  (
    .A(yr),
    .B(x[2]),
    .Y(_180_)
  );


  sky130_fd_sc_hd__nand2_1
  _370_
  (
    .A(c[2]),
    .B(s[2]),
    .Y(_181_)
  );


  sky130_fd_sc_hd__nor2_1
  _371_
  (
    .A(c[2]),
    .B(s[2]),
    .Y(_182_)
  );


  sky130_fd_sc_hd__xnor2_1
  _372_
  (
    .A(c[2]),
    .B(s[2]),
    .Y(_183_)
  );


  sky130_fd_sc_hd__xnor2_1
  _373_
  (
    .A(_180_),
    .B(_183_),
    .Y(_184_)
  );


  sky130_fd_sc_hd__nor2_1
  _374_
  (
    .A(rst),
    .B(_184_),
    .Y(_023_)
  );


  sky130_fd_sc_hd__nand2_1
  _375_
  (
    .A(yr),
    .B(x[1]),
    .Y(_185_)
  );


  sky130_fd_sc_hd__nand2_1
  _376_
  (
    .A(c[1]),
    .B(s[1]),
    .Y(_186_)
  );


  sky130_fd_sc_hd__nor2_1
  _377_
  (
    .A(c[1]),
    .B(s[1]),
    .Y(_187_)
  );


  sky130_fd_sc_hd__xnor2_1
  _378_
  (
    .A(c[1]),
    .B(s[1]),
    .Y(_188_)
  );


  sky130_fd_sc_hd__xnor2_1
  _379_
  (
    .A(_185_),
    .B(_188_),
    .Y(_189_)
  );


  sky130_fd_sc_hd__nor2_1
  _380_
  (
    .A(rst),
    .B(_189_),
    .Y(_024_)
  );


  sky130_fd_sc_hd__a22oi_1
  _381_
  (
    .A1(x[30]),
    .A2(yr),
    .B1(c[30]),
    .B2(s[30]),
    .Y(_190_)
  );


  sky130_fd_sc_hd__nor2_1
  _382_
  (
    .A(c[30]),
    .B(s[30]),
    .Y(_191_)
  );


  sky130_fd_sc_hd__nor3_1
  _383_
  (
    .A(rst),
    .B(_190_),
    .C(_191_),
    .Y(_025_)
  );


  sky130_fd_sc_hd__a22oi_1
  _384_
  (
    .A1(yr),
    .A2(x[29]),
    .B1(c[29]),
    .B2(s[29]),
    .Y(_192_)
  );


  sky130_fd_sc_hd__nor2_1
  _385_
  (
    .A(c[29]),
    .B(s[29]),
    .Y(_193_)
  );


  sky130_fd_sc_hd__nor3_1
  _386_
  (
    .A(rst),
    .B(_192_),
    .C(_193_),
    .Y(_026_)
  );


  sky130_fd_sc_hd__a22oi_1
  _387_
  (
    .A1(yr),
    .A2(x[28]),
    .B1(c[28]),
    .B2(s[28]),
    .Y(_194_)
  );


  sky130_fd_sc_hd__nor2_1
  _388_
  (
    .A(c[28]),
    .B(s[28]),
    .Y(_195_)
  );


  sky130_fd_sc_hd__nor3_1
  _389_
  (
    .A(rst),
    .B(_194_),
    .C(_195_),
    .Y(_027_)
  );


  sky130_fd_sc_hd__a22oi_1
  _390_
  (
    .A1(yr),
    .A2(x[27]),
    .B1(c[27]),
    .B2(s[27]),
    .Y(_196_)
  );


  sky130_fd_sc_hd__nor2_1
  _391_
  (
    .A(c[27]),
    .B(s[27]),
    .Y(_197_)
  );


  sky130_fd_sc_hd__nor3_1
  _392_
  (
    .A(rst),
    .B(_196_),
    .C(_197_),
    .Y(_028_)
  );


  sky130_fd_sc_hd__a22oi_1
  _393_
  (
    .A1(yr),
    .A2(x[26]),
    .B1(c[26]),
    .B2(s[26]),
    .Y(_198_)
  );


  sky130_fd_sc_hd__nor2_1
  _394_
  (
    .A(c[26]),
    .B(s[26]),
    .Y(_199_)
  );


  sky130_fd_sc_hd__nor3_1
  _395_
  (
    .A(rst),
    .B(_198_),
    .C(_199_),
    .Y(_029_)
  );


  sky130_fd_sc_hd__a211oi_1
  _396_
  (
    .A1(_065_),
    .A2(_066_),
    .B1(_067_),
    .C1(rst),
    .Y(_030_)
  );


  sky130_fd_sc_hd__a211oi_1
  _397_
  (
    .A1(_070_),
    .A2(_071_),
    .B1(_072_),
    .C1(rst),
    .Y(_031_)
  );


  sky130_fd_sc_hd__a211oi_1
  _398_
  (
    .A1(_075_),
    .A2(_076_),
    .B1(_077_),
    .C1(rst),
    .Y(_032_)
  );


  sky130_fd_sc_hd__a211oi_1
  _399_
  (
    .A1(_080_),
    .A2(_081_),
    .B1(_082_),
    .C1(rst),
    .Y(_033_)
  );


  sky130_fd_sc_hd__a211oi_1
  _400_
  (
    .A1(_085_),
    .A2(_086_),
    .B1(_087_),
    .C1(rst),
    .Y(_034_)
  );


  sky130_fd_sc_hd__a211oi_1
  _401_
  (
    .A1(_090_),
    .A2(_091_),
    .B1(_092_),
    .C1(rst),
    .Y(_035_)
  );


  sky130_fd_sc_hd__a211oi_1
  _402_
  (
    .A1(_095_),
    .A2(_096_),
    .B1(_097_),
    .C1(rst),
    .Y(_036_)
  );


  sky130_fd_sc_hd__a211oi_1
  _403_
  (
    .A1(_100_),
    .A2(_101_),
    .B1(_102_),
    .C1(rst),
    .Y(_037_)
  );


  sky130_fd_sc_hd__a211oi_1
  _404_
  (
    .A1(_105_),
    .A2(_106_),
    .B1(_107_),
    .C1(rst),
    .Y(_038_)
  );


  sky130_fd_sc_hd__a211oi_1
  _405_
  (
    .A1(_110_),
    .A2(_111_),
    .B1(_112_),
    .C1(rst),
    .Y(_039_)
  );


  sky130_fd_sc_hd__a211oi_1
  _406_
  (
    .A1(_115_),
    .A2(_116_),
    .B1(_117_),
    .C1(rst),
    .Y(_040_)
  );


  sky130_fd_sc_hd__a211oi_1
  _407_
  (
    .A1(_120_),
    .A2(_121_),
    .B1(_122_),
    .C1(rst),
    .Y(_041_)
  );


  sky130_fd_sc_hd__a211oi_1
  _408_
  (
    .A1(_125_),
    .A2(_126_),
    .B1(_127_),
    .C1(rst),
    .Y(_042_)
  );


  sky130_fd_sc_hd__a211oi_1
  _409_
  (
    .A1(_130_),
    .A2(_131_),
    .B1(_132_),
    .C1(rst),
    .Y(_043_)
  );


  sky130_fd_sc_hd__a211oi_1
  _410_
  (
    .A1(_135_),
    .A2(_136_),
    .B1(_137_),
    .C1(rst),
    .Y(_044_)
  );


  sky130_fd_sc_hd__a211oi_1
  _411_
  (
    .A1(_140_),
    .A2(_141_),
    .B1(_142_),
    .C1(rst),
    .Y(_045_)
  );


  sky130_fd_sc_hd__a211oi_1
  _412_
  (
    .A1(_145_),
    .A2(_146_),
    .B1(_147_),
    .C1(rst),
    .Y(_046_)
  );


  sky130_fd_sc_hd__a211oi_1
  _413_
  (
    .A1(_150_),
    .A2(_151_),
    .B1(_152_),
    .C1(rst),
    .Y(_047_)
  );


  sky130_fd_sc_hd__a211oi_1
  _414_
  (
    .A1(_155_),
    .A2(_156_),
    .B1(_157_),
    .C1(rst),
    .Y(_048_)
  );


  sky130_fd_sc_hd__a211oi_1
  _415_
  (
    .A1(_160_),
    .A2(_161_),
    .B1(_162_),
    .C1(rst),
    .Y(_049_)
  );


  sky130_fd_sc_hd__a211oi_1
  _416_
  (
    .A1(_165_),
    .A2(_166_),
    .B1(_167_),
    .C1(rst),
    .Y(_050_)
  );


  sky130_fd_sc_hd__a211oi_1
  _417_
  (
    .A1(_170_),
    .A2(_171_),
    .B1(_172_),
    .C1(rst),
    .Y(_051_)
  );


  sky130_fd_sc_hd__a211oi_1
  _418_
  (
    .A1(_175_),
    .A2(_176_),
    .B1(_177_),
    .C1(rst),
    .Y(_052_)
  );


  sky130_fd_sc_hd__and3_1
  _419_
  (
    .A(yr),
    .B(x[31]),
    .C(c[31]),
    .X(_200_)
  );


  sky130_fd_sc_hd__a21oi_1
  _420_
  (
    .A1(yr),
    .A2(x[31]),
    .B1(c[31]),
    .Y(_201_)
  );


  sky130_fd_sc_hd__nor3_1
  _421_
  (
    .A(rst),
    .B(_200_),
    .C(_201_),
    .Y(_053_)
  );


  sky130_fd_sc_hd__nor2b_1
  _422_
  (
    .A(rst),
    .B_N(y),
    .Y(_054_)
  );


  sky130_fd_sc_hd__nand2_1
  _423_
  (
    .A(yr),
    .B(x[0]),
    .Y(_202_)
  );


  sky130_fd_sc_hd__nand2_1
  _424_
  (
    .A(c[0]),
    .B(s[0]),
    .Y(_203_)
  );


  sky130_fd_sc_hd__nor2_1
  _425_
  (
    .A(c[0]),
    .B(s[0]),
    .Y(_204_)
  );


  sky130_fd_sc_hd__xnor2_1
  _426_
  (
    .A(c[0]),
    .B(s[0]),
    .Y(_205_)
  );


  sky130_fd_sc_hd__xnor2_1
  _427_
  (
    .A(_202_),
    .B(_205_),
    .Y(_206_)
  );


  sky130_fd_sc_hd__nor2_1
  _428_
  (
    .A(rst),
    .B(_206_),
    .Y(_055_)
  );


  sky130_fd_sc_hd__nor2b_1
  _429_
  (
    .A(rst),
    .B_N(_200_),
    .Y(_056_)
  );


  sky130_fd_sc_hd__a211oi_1
  _430_
  (
    .A1(_180_),
    .A2(_181_),
    .B1(_182_),
    .C1(rst),
    .Y(_057_)
  );


  sky130_fd_sc_hd__a211oi_1
  _431_
  (
    .A1(_185_),
    .A2(_186_),
    .B1(_187_),
    .C1(rst),
    .Y(_058_)
  );


  sky130_fd_sc_hd__a211oi_1
  _432_
  (
    .A1(_202_),
    .A2(_203_),
    .B1(_204_),
    .C1(rst),
    .Y(_059_)
  );


  sky130_fd_sc_hd__xor2_1
  _433_
  (
    .A(c[30]),
    .B(s[30]),
    .X(_207_)
  );


  sky130_fd_sc_hd__a21oi_1
  _434_
  (
    .A1(x[30]),
    .A2(yr),
    .B1(_207_),
    .Y(_208_)
  );


  sky130_fd_sc_hd__and3_1
  _435_
  (
    .A(x[30]),
    .B(yr),
    .C(_207_),
    .X(_209_)
  );


  sky130_fd_sc_hd__nor3_1
  _436_
  (
    .A(rst),
    .B(_208_),
    .C(_209_),
    .Y(_060_)
  );


  sky130_fd_sc_hd__xor2_1
  _437_
  (
    .A(c[29]),
    .B(s[29]),
    .X(_210_)
  );


  sky130_fd_sc_hd__a21oi_1
  _438_
  (
    .A1(yr),
    .A2(x[29]),
    .B1(_210_),
    .Y(_211_)
  );


  sky130_fd_sc_hd__and3_1
  _439_
  (
    .A(yr),
    .B(x[29]),
    .C(_210_),
    .X(_212_)
  );


  sky130_fd_sc_hd__nor3_1
  _440_
  (
    .A(rst),
    .B(_211_),
    .C(_212_),
    .Y(_061_)
  );


  sky130_fd_sc_hd__xor2_1
  _441_
  (
    .A(c[28]),
    .B(s[28]),
    .X(_213_)
  );


  sky130_fd_sc_hd__a21oi_1
  _442_
  (
    .A1(yr),
    .A2(x[28]),
    .B1(_213_),
    .Y(_214_)
  );


  sky130_fd_sc_hd__and3_1
  _443_
  (
    .A(yr),
    .B(x[28]),
    .C(_213_),
    .X(_215_)
  );


  sky130_fd_sc_hd__dfxtp_1
  _444_
  (
    .CLK(__clk_source__),
    .D((shift)? __chain_0__ : _055_),
    .Q(pr)
  );


  sky130_fd_sc_hd__dfxtp_1
  _445_
  (
    .CLK(__clk_source__),
    .D((shift)? pr : _054_),
    .Q(yr)
  );


  sky130_fd_sc_hd__dfxtp_1
  _446_
  (
    .CLK(__clk_source__),
    .D((shift)? yr : _024_),
    .Q(s[0])
  );


  sky130_fd_sc_hd__dfxtp_1
  _447_
  (
    .CLK(__clk_source__),
    .D((shift)? s[0] : _023_),
    .Q(s[1])
  );


  sky130_fd_sc_hd__dfxtp_1
  _448_
  (
    .CLK(__clk_source__),
    .D((shift)? s[1] : _022_),
    .Q(s[2])
  );


  sky130_fd_sc_hd__dfxtp_1
  _449_
  (
    .CLK(__clk_source__),
    .D((shift)? s[2] : _021_),
    .Q(s[3])
  );


  sky130_fd_sc_hd__dfxtp_1
  _450_
  (
    .CLK(__clk_source__),
    .D((shift)? s[3] : _020_),
    .Q(s[4])
  );


  sky130_fd_sc_hd__dfxtp_1
  _451_
  (
    .CLK(__clk_source__),
    .D((shift)? s[4] : _019_),
    .Q(s[5])
  );


  sky130_fd_sc_hd__dfxtp_1
  _452_
  (
    .CLK(__clk_source__),
    .D((shift)? s[5] : _018_),
    .Q(s[6])
  );


  sky130_fd_sc_hd__dfxtp_1
  _453_
  (
    .CLK(__clk_source__),
    .D((shift)? s[6] : _017_),
    .Q(s[7])
  );


  sky130_fd_sc_hd__dfxtp_1
  _454_
  (
    .CLK(__clk_source__),
    .D((shift)? s[7] : _016_),
    .Q(s[8])
  );


  sky130_fd_sc_hd__dfxtp_1
  _455_
  (
    .CLK(__clk_source__),
    .D((shift)? s[8] : _015_),
    .Q(s[9])
  );


  sky130_fd_sc_hd__dfxtp_1
  _456_
  (
    .CLK(__clk_source__),
    .D((shift)? s[9] : _014_),
    .Q(s[10])
  );


  sky130_fd_sc_hd__dfxtp_1
  _457_
  (
    .CLK(__clk_source__),
    .D((shift)? s[10] : _013_),
    .Q(s[11])
  );


  sky130_fd_sc_hd__dfxtp_1
  _458_
  (
    .CLK(__clk_source__),
    .D((shift)? s[11] : _012_),
    .Q(s[12])
  );


  sky130_fd_sc_hd__dfxtp_1
  _459_
  (
    .CLK(__clk_source__),
    .D((shift)? s[12] : _011_),
    .Q(s[13])
  );


  sky130_fd_sc_hd__dfxtp_1
  _460_
  (
    .CLK(__clk_source__),
    .D((shift)? s[13] : _010_),
    .Q(s[14])
  );


  sky130_fd_sc_hd__dfxtp_1
  _461_
  (
    .CLK(__clk_source__),
    .D((shift)? s[14] : _009_),
    .Q(s[15])
  );


  sky130_fd_sc_hd__dfxtp_1
  _462_
  (
    .CLK(__clk_source__),
    .D((shift)? s[15] : _008_),
    .Q(s[16])
  );


  sky130_fd_sc_hd__dfxtp_1
  _463_
  (
    .CLK(__clk_source__),
    .D((shift)? s[16] : _007_),
    .Q(s[17])
  );


  sky130_fd_sc_hd__dfxtp_1
  _464_
  (
    .CLK(__clk_source__),
    .D((shift)? s[17] : _006_),
    .Q(s[18])
  );


  sky130_fd_sc_hd__dfxtp_1
  _465_
  (
    .CLK(__clk_source__),
    .D((shift)? s[18] : _005_),
    .Q(s[19])
  );


  sky130_fd_sc_hd__dfxtp_1
  _466_
  (
    .CLK(__clk_source__),
    .D((shift)? s[19] : _004_),
    .Q(s[20])
  );


  sky130_fd_sc_hd__dfxtp_1
  _467_
  (
    .CLK(__clk_source__),
    .D((shift)? s[20] : _003_),
    .Q(s[21])
  );


  sky130_fd_sc_hd__dfxtp_1
  _468_
  (
    .CLK(__clk_source__),
    .D((shift)? s[21] : _002_),
    .Q(s[22])
  );


  sky130_fd_sc_hd__dfxtp_1
  _469_
  (
    .CLK(__clk_source__),
    .D((shift)? s[22] : _001_),
    .Q(s[23])
  );


  sky130_fd_sc_hd__dfxtp_1
  _470_
  (
    .CLK(__clk_source__),
    .D((shift)? s[23] : _000_),
    .Q(s[24])
  );


  sky130_fd_sc_hd__dfxtp_1
  _471_
  (
    .CLK(__clk_source__),
    .D((shift)? s[24] : _064_),
    .Q(s[25])
  );


  sky130_fd_sc_hd__dfxtp_1
  _472_
  (
    .CLK(__clk_source__),
    .D((shift)? s[25] : _063_),
    .Q(s[26])
  );


  sky130_fd_sc_hd__dfxtp_1
  _473_
  (
    .CLK(__clk_source__),
    .D((shift)? s[26] : _062_),
    .Q(s[27])
  );


  sky130_fd_sc_hd__dfxtp_1
  _474_
  (
    .CLK(__clk_source__),
    .D((shift)? s[27] : _061_),
    .Q(s[28])
  );


  sky130_fd_sc_hd__dfxtp_1
  _475_
  (
    .CLK(__clk_source__),
    .D((shift)? s[28] : _060_),
    .Q(s[29])
  );


  sky130_fd_sc_hd__dfxtp_1
  _476_
  (
    .CLK(__clk_source__),
    .D((shift)? s[29] : _053_),
    .Q(s[30])
  );


  sky130_fd_sc_hd__dfxtp_1
  _477_
  (
    .CLK(__clk_source__),
    .D((shift)? s[30] : _059_),
    .Q(c[0])
  );


  sky130_fd_sc_hd__dfxtp_1
  _478_
  (
    .CLK(__clk_source__),
    .D((shift)? c[0] : _058_),
    .Q(c[1])
  );


  sky130_fd_sc_hd__dfxtp_1
  _479_
  (
    .CLK(__clk_source__),
    .D((shift)? c[1] : _057_),
    .Q(c[2])
  );


  sky130_fd_sc_hd__dfxtp_1
  _480_
  (
    .CLK(__clk_source__),
    .D((shift)? c[2] : _052_),
    .Q(c[3])
  );


  sky130_fd_sc_hd__dfxtp_1
  _481_
  (
    .CLK(__clk_source__),
    .D((shift)? c[3] : _051_),
    .Q(c[4])
  );


  sky130_fd_sc_hd__dfxtp_1
  _482_
  (
    .CLK(__clk_source__),
    .D((shift)? c[4] : _050_),
    .Q(c[5])
  );


  sky130_fd_sc_hd__dfxtp_1
  _483_
  (
    .CLK(__clk_source__),
    .D((shift)? c[5] : _049_),
    .Q(c[6])
  );


  sky130_fd_sc_hd__dfxtp_1
  _484_
  (
    .CLK(__clk_source__),
    .D((shift)? c[6] : _048_),
    .Q(c[7])
  );


  sky130_fd_sc_hd__dfxtp_1
  _485_
  (
    .CLK(__clk_source__),
    .D((shift)? c[7] : _047_),
    .Q(c[8])
  );


  sky130_fd_sc_hd__dfxtp_1
  _486_
  (
    .CLK(__clk_source__),
    .D((shift)? c[8] : _046_),
    .Q(c[9])
  );


  sky130_fd_sc_hd__dfxtp_1
  _487_
  (
    .CLK(__clk_source__),
    .D((shift)? c[9] : _045_),
    .Q(c[10])
  );


  sky130_fd_sc_hd__dfxtp_1
  _488_
  (
    .CLK(__clk_source__),
    .D((shift)? c[10] : _044_),
    .Q(c[11])
  );


  sky130_fd_sc_hd__dfxtp_1
  _489_
  (
    .CLK(__clk_source__),
    .D((shift)? c[11] : _043_),
    .Q(c[12])
  );


  sky130_fd_sc_hd__dfxtp_1
  _490_
  (
    .CLK(__clk_source__),
    .D((shift)? c[12] : _042_),
    .Q(c[13])
  );


  sky130_fd_sc_hd__dfxtp_1
  _491_
  (
    .CLK(__clk_source__),
    .D((shift)? c[13] : _041_),
    .Q(c[14])
  );


  sky130_fd_sc_hd__dfxtp_1
  _492_
  (
    .CLK(__clk_source__),
    .D((shift)? c[14] : _040_),
    .Q(c[15])
  );


  sky130_fd_sc_hd__dfxtp_1
  _493_
  (
    .CLK(__clk_source__),
    .D((shift)? c[15] : _039_),
    .Q(c[16])
  );


  sky130_fd_sc_hd__dfxtp_1
  _494_
  (
    .CLK(__clk_source__),
    .D((shift)? c[16] : _038_),
    .Q(c[17])
  );


  sky130_fd_sc_hd__dfxtp_1
  _495_
  (
    .CLK(__clk_source__),
    .D((shift)? c[17] : _037_),
    .Q(c[18])
  );


  sky130_fd_sc_hd__dfxtp_1
  _496_
  (
    .CLK(__clk_source__),
    .D((shift)? c[18] : _036_),
    .Q(c[19])
  );


  sky130_fd_sc_hd__dfxtp_1
  _497_
  (
    .CLK(__clk_source__),
    .D((shift)? c[19] : _035_),
    .Q(c[20])
  );


  sky130_fd_sc_hd__dfxtp_1
  _498_
  (
    .CLK(__clk_source__),
    .D((shift)? c[20] : _034_),
    .Q(c[21])
  );


  sky130_fd_sc_hd__dfxtp_1
  _499_
  (
    .CLK(__clk_source__),
    .D((shift)? c[21] : _033_),
    .Q(c[22])
  );


  sky130_fd_sc_hd__dfxtp_1
  _500_
  (
    .CLK(__clk_source__),
    .D((shift)? c[22] : _032_),
    .Q(c[23])
  );


  sky130_fd_sc_hd__dfxtp_1
  _501_
  (
    .CLK(__clk_source__),
    .D((shift)? c[23] : _031_),
    .Q(c[24])
  );


  sky130_fd_sc_hd__dfxtp_1
  _502_
  (
    .CLK(__clk_source__),
    .D((shift)? c[24] : _030_),
    .Q(c[25])
  );


  sky130_fd_sc_hd__dfxtp_1
  _503_
  (
    .CLK(__clk_source__),
    .D((shift)? c[25] : _029_),
    .Q(c[26])
  );


  sky130_fd_sc_hd__dfxtp_1
  _504_
  (
    .CLK(__clk_source__),
    .D((shift)? c[26] : _028_),
    .Q(c[27])
  );


  sky130_fd_sc_hd__dfxtp_1
  _505_
  (
    .CLK(__clk_source__),
    .D((shift)? c[27] : _027_),
    .Q(c[28])
  );


  sky130_fd_sc_hd__dfxtp_1
  _506_
  (
    .CLK(__clk_source__),
    .D((shift)? c[28] : _026_),
    .Q(c[29])
  );


  sky130_fd_sc_hd__dfxtp_1
  _507_
  (
    .CLK(__clk_source__),
    .D((shift)? c[29] : _025_),
    .Q(c[30])
  );


  sky130_fd_sc_hd__dfxtp_1
  _508_
  (
    .CLK(__clk_source__),
    .D((shift)? c[30] : _056_),
    .Q(c[31])
  );

  assign p = pr;
  assign sout = c[31];
  assign __clk_source__ = (test)? tck : clk;

endmodule



module chip_top
(
  clk,
  rst,
  x,
  y,
  p,
  sin,
  shift,
  sout,
  tck,
  test
);

  input sin;
  output sout;
  input rst;
  input shift;
  input tck;
  input test;
  input clk;
  wire __chain_0__;
  assign __chain_0__ = sin;
  input [31:0] x;
  wire [31:0] x__dout;
  wire __chain_1__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__0__
  (
    .din(x[0]),
    .dout(x__dout[0]),
    .sin(__chain_0__),
    .sout(__chain_1__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_2__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__1__
  (
    .din(x[1]),
    .dout(x__dout[1]),
    .sin(__chain_1__),
    .sout(__chain_2__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_3__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__2__
  (
    .din(x[2]),
    .dout(x__dout[2]),
    .sin(__chain_2__),
    .sout(__chain_3__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_4__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__3__
  (
    .din(x[3]),
    .dout(x__dout[3]),
    .sin(__chain_3__),
    .sout(__chain_4__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_5__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__4__
  (
    .din(x[4]),
    .dout(x__dout[4]),
    .sin(__chain_4__),
    .sout(__chain_5__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_6__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__5__
  (
    .din(x[5]),
    .dout(x__dout[5]),
    .sin(__chain_5__),
    .sout(__chain_6__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_7__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__6__
  (
    .din(x[6]),
    .dout(x__dout[6]),
    .sin(__chain_6__),
    .sout(__chain_7__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_8__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__7__
  (
    .din(x[7]),
    .dout(x__dout[7]),
    .sin(__chain_7__),
    .sout(__chain_8__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_9__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__8__
  (
    .din(x[8]),
    .dout(x__dout[8]),
    .sin(__chain_8__),
    .sout(__chain_9__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_10__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__9__
  (
    .din(x[9]),
    .dout(x__dout[9]),
    .sin(__chain_9__),
    .sout(__chain_10__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_11__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__10__
  (
    .din(x[10]),
    .dout(x__dout[10]),
    .sin(__chain_10__),
    .sout(__chain_11__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_12__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__11__
  (
    .din(x[11]),
    .dout(x__dout[11]),
    .sin(__chain_11__),
    .sout(__chain_12__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_13__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__12__
  (
    .din(x[12]),
    .dout(x__dout[12]),
    .sin(__chain_12__),
    .sout(__chain_13__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_14__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__13__
  (
    .din(x[13]),
    .dout(x__dout[13]),
    .sin(__chain_13__),
    .sout(__chain_14__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_15__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__14__
  (
    .din(x[14]),
    .dout(x__dout[14]),
    .sin(__chain_14__),
    .sout(__chain_15__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_16__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__15__
  (
    .din(x[15]),
    .dout(x__dout[15]),
    .sin(__chain_15__),
    .sout(__chain_16__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_17__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__16__
  (
    .din(x[16]),
    .dout(x__dout[16]),
    .sin(__chain_16__),
    .sout(__chain_17__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_18__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__17__
  (
    .din(x[17]),
    .dout(x__dout[17]),
    .sin(__chain_17__),
    .sout(__chain_18__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_19__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__18__
  (
    .din(x[18]),
    .dout(x__dout[18]),
    .sin(__chain_18__),
    .sout(__chain_19__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_20__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__19__
  (
    .din(x[19]),
    .dout(x__dout[19]),
    .sin(__chain_19__),
    .sout(__chain_20__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_21__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__20__
  (
    .din(x[20]),
    .dout(x__dout[20]),
    .sin(__chain_20__),
    .sout(__chain_21__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_22__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__21__
  (
    .din(x[21]),
    .dout(x__dout[21]),
    .sin(__chain_21__),
    .sout(__chain_22__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_23__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__22__
  (
    .din(x[22]),
    .dout(x__dout[22]),
    .sin(__chain_22__),
    .sout(__chain_23__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_24__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__23__
  (
    .din(x[23]),
    .dout(x__dout[23]),
    .sin(__chain_23__),
    .sout(__chain_24__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_25__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__24__
  (
    .din(x[24]),
    .dout(x__dout[24]),
    .sin(__chain_24__),
    .sout(__chain_25__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_26__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__25__
  (
    .din(x[25]),
    .dout(x__dout[25]),
    .sin(__chain_25__),
    .sout(__chain_26__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_27__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__26__
  (
    .din(x[26]),
    .dout(x__dout[26]),
    .sin(__chain_26__),
    .sout(__chain_27__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_28__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__27__
  (
    .din(x[27]),
    .dout(x__dout[27]),
    .sin(__chain_27__),
    .sout(__chain_28__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_29__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__28__
  (
    .din(x[28]),
    .dout(x__dout[28]),
    .sin(__chain_28__),
    .sout(__chain_29__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_30__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__29__
  (
    .din(x[29]),
    .dout(x__dout[29]),
    .sin(__chain_29__),
    .sout(__chain_30__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_31__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__30__
  (
    .din(x[30]),
    .dout(x__dout[30]),
    .sin(__chain_30__),
    .sout(__chain_31__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_32__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__31__
  (
    .din(x[31]),
    .dout(x__dout[31]),
    .sin(__chain_31__),
    .sout(__chain_32__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  input y;
  wire y__dout;
  wire __chain_33__;

  BoundaryScanRegister_input
  __BoundaryScanRegister_input__32__
  (
    .din(y),
    .dout(y__dout),
    .sin(__chain_32__),
    .sout(__chain_33__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );

  wire __chain_34__;
  output p;
  wire p_din;
  wire __chain_35__;

  BoundaryScanRegister_output
  __BoundaryScanRegister_output__33__
  (
    .din(p_din),
    .dout(p),
    .sin(__chain_34__),
    .sout(__chain_35__),
    .clock(tck),
    .reset(rst),
    .testing(test),
    .shift(shift)
  );


  \chip_top.original 
  __uuf__
  (
    .clk(clk),
    .rst(rst),
    .x(x__dout),
    .y(y__dout),
    .shift(shift),
    .tck(tck),
    .test(test),
    .sin(__chain_33__),
    .sout(__chain_34__),
    .p(p_din)
  );

  assign sout = __chain_35__;

endmodule


