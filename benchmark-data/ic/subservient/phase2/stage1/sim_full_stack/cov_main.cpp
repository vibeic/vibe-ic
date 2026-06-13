#include "Vtb_cov_top.h"
#include "verilated.h"
#include "verilated_cov.h"
int main(int argc,char**argv){
  Verilated::commandArgs(argc,argv);
  Vtb_cov_top* t=new Vtb_cov_top;
  t->rst_in=1; t->clk=0;
  for(int c=0;c<8;c++){ t->clk=!t->clk; t->eval(); }
  t->rst_in=0;
  for(long c=0;c<200000;c++){ t->clk=!t->clk; t->eval(); }
  VerilatedCov::write("coverage.dat");
  delete t; return 0;
}
