#!/usr/bin/env python3
"""Generate summary PDF — using reportlab CID fonts for CJK support"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# Register CJK CID font (built into reportlab, no external file needed)
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))

FONT = 'STSong-Light'

output_path = '~/AI_IC_design/AI_Native_IC_Design_Infrastructure_Summary.pdf'
doc = SimpleDocTemplate(output_path, pagesize=A4, topMargin=20*mm, bottomMargin=15*mm, leftMargin=15*mm, rightMargin=15*mm)

sTitle = ParagraphStyle('t', fontName=FONT, fontSize=18, leading=24, alignment=1)
sH1 = ParagraphStyle('h1', fontName=FONT, fontSize=13, leading=18, spaceAfter=6, spaceBefore=12)
sH2 = ParagraphStyle('h2', fontName=FONT, fontSize=10, leading=14, spaceAfter=4, spaceBefore=8)
sBody = ParagraphStyle('b', fontName=FONT, fontSize=9, leading=12)
sSmall = ParagraphStyle('s', fontName=FONT, fontSize=7.5, leading=10, textColor=colors.grey)

def T(data, cw=None):
    t = Table(data, colWidths=cw, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2C3E50')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,-1), FONT),
        ('FONTSIZE', (0,0), (-1,-1), 7.5),
        ('LEADING', (0,0), (-1,-1), 10),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#ECF0F1')]),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('LEFTPADDING', (0,0), (-1,-1), 3),
    ]))
    return t

E = []

# Title
E.append(Paragraph('AI-Native IC Design', sTitle))
E.append(Paragraph('Infrastructure & Tools Summary', sTitle))
E.append(Spacer(1, 4*mm))
E.append(Paragraph('Server: <host> (<lan-ip>) | Date: 2026-04-07 | Docker: IIC-OSIC-TOOLS (22.1 GB)', sSmall))
E.append(Spacer(1, 6*mm))

# 1. EDA Tools
E.append(Paragraph('1. Open-Source EDA Tools', sH1))

E.append(T([
    ['Category', 'Tool', 'Version', 'Function', 'MCP Tool'],
    ['Digital Sim', 'Icarus Verilog', '13.0', 'Verilog simulation', 'eda_simulate'],
    ['Digital Sim', 'Verilator', '5.044', 'Lint + fast sim', 'eda_lint'],
    ['Digital Sim', 'GHDL', '6.0.0-dev', 'VHDL simulation', '-'],
    ['Synthesis', 'Yosys', '0.62', 'RTL synthesis', 'eda_synth'],
    ['Formal', 'SymbiYosys', '0.62', 'Formal verification', 'eda_formal'],
    ['Formal', 'Yices SMT', '2.7.0', 'SMT solver', '(via formal)'],
    ['P&R', 'OpenROAD', '26Q1', 'Place & route', 'eda_pnr'],
    ['P&R', 'LibreLane', 'v2.4.12', 'RTL-to-GDS automation', '-'],
    ['Layout', 'Magic', '8.3.603', 'Layout editor + DRC', '-'],
    ['Layout', 'KLayout', '0.30.6', 'GDS viewer/gen + DRC', 'eda_gds'],
    ['LVS', 'Netgen', '(installed)', 'LVS verification', '-'],
    ['SPICE', 'ngspice', '(installed)', 'Circuit simulation', '-'],
    ['SPICE', 'Xyce (Sandia)', '(installed)', 'Parallel SPICE', '-'],
    ['Schematic', 'Xschem', '3.4.8', 'Schematic capture', '-'],
    ['Waveform', 'GTKWave', '(installed)', 'VCD waveform viewer', '-'],
    ['Timing', 'OpenSTA', '(via OpenROAD)', 'Static timing analysis', 'eda_sta'],
], [50, 70, 50, 130, 60]))

E.append(Spacer(1, 4*mm))
E.append(Paragraph('Python: cocotb 2.0.1, pyverilog 1.3.0, amaranth 0.5.6, gdsfactory 9.34.1, PySpice 1.5, librelane 2.4.12', sSmall))

E.append(PageBreak())

# 2. PDKs
E.append(Paragraph('2. Process Design Kits (PDKs)', sH1))

E.append(T([
    ['PDK', 'Node', 'Voltage', 'Std Cell Library', 'Corners', 'Source'],
    ['GF180MCU', '180nm', '3.3V/5V', 'mcu7t5v0 (7T), mcu9t5v0 (9T)', '15 libs (ss/tt/ff)', 'GlobalFoundries+Google'],
    ['SKY130', '130nm', '1.8V', 'sc_hd, sc_hvl', '18 libs', 'SkyWater+Google'],
    ['IHP SG13G2', '130nm SiGe', '1.2V/3.3V', 'available', '-', 'IHP GmbH'],
], [55, 40, 40, 110, 55, 80]))

E.append(Spacer(1, 3*mm))
E.append(Paragraph('GF180MCU includes: I/O cells, SRAM IP, primitive devices, OpenLane config, KLayout DRC rules', sBody))
E.append(Paragraph('SSD2 backup: ~/eda/pdks/gf180mcu-pdk/ (68 MB)', sSmall))

E.append(Spacer(1, 6*mm))

# 3. MCP Server
E.append(Paragraph('3. MCP EDA Server (7 Tools for AI Agent)', sH1))
E.append(Paragraph('Location: the bundled MCP server (plugins/vibe-ic/mcp-eda/) | Runtime: Node.js + @modelcontextprotocol/sdk', sSmall))
E.append(Spacer(1, 3*mm))

E.append(T([
    ['MCP Tool', 'Backend', 'Input', 'Output'],
    ['eda_synth', 'Yosys', 'Verilog + top + PDK', 'Netlist + cells + area'],
    ['eda_lint', 'Verilator', 'Verilog + top', 'Error/warning count'],
    ['eda_simulate', 'iverilog', 'Source + testbench', 'PASS/FAIL'],
    ['eda_formal', 'SymbiYosys+Yices', 'Design + assertions', 'PROVED/FAILED'],
    ['eda_pnr', 'OpenROAD', 'Netlist + PDK + clock', 'DEF + area + slack'],
    ['eda_gds', 'KLayout', 'DEF + cell GDS', 'GDS file'],
    ['eda_sta', 'OpenSTA', 'Netlist + clock', 'WNS + TNS + report'],
], [55, 65, 115, 120]))

E.append(Spacer(1, 6*mm))

# 4. Verified Designs
E.append(Paragraph('4. Verified IC Designs (GF180MCU 180nm)', sH1))

E.append(T([
    ['Design', 'Function', 'Cells', 'Area (um2)', 'Die Size', 'GDS', 'DRC'],
    ['SN74HC163', '4-bit counter', '25', '604', '45x45 um', '1.5 MB', '0 errors'],
    ['BENCH-A', 'AID bus ctrl (11 mod)', '2,693', '89,176', '492x492 um', '1.7 MB', '0 (global rt)'],
], [55, 85, 35, 55, 55, 40, 50]))

E.append(Spacer(1, 3*mm))
E.append(Paragraph('SN74HC163: RTL > Sim > Lint > Formal > Synth > P&R > DRC > GDS (full closed-loop)', sBody))
E.append(Paragraph('BENCH-A: RTL > Lint > Synth > P&R > GDS (detailed route pending tie-cell fix)', sBody))

E.append(PageBreak())

# 5. Skills
E.append(Paragraph('5. AI-Native IC Design Plugin Skills (33 total)', sH1))

E.append(T([
    ['Plugin', 'Skill', 'Tested', 'Notes Added'],
    ['ic-frontend (13)', 'spec-to-rtl, rtl-review, rtl-repair, synth-wrapper-gen(NEW),', 'Yes', 'rtl-review, ppa-predict,'],
    ['', 'ppa-predict, testbench-gen, assertion-gen, formal-verify,', '', 'formal-verify have'],
    ['', 'cdc-check, rdc-check, hls-c2rtl, equiv-check, coverage', '', 'PRACTICAL_NOTES.md'],
    ['ic-backend (10)', 'sta-review, drc-fix, tapeout-checklist, placement-optimize,', 'Yes', 'sta-review, drc-fix have'],
    ['', 'cts-plan, dft-insert, eco-plan, lvs-triage, upf-author, ir-drop', '', 'PRACTICAL_NOTES.md'],
    ['ic-methodology (4)', 'flow-orchestrate, spec-review, arch-explore, regression', 'Yes', 'GF180_FLOW_RECIPE.md'],
    ['ic-silicon-analog (6)', 'analog-sizing, analog-layout, ams-sim, atpg, bringup, yield', '-', '-'],
], [70, 195, 30, 85]))

E.append(Spacer(1, 6*mm))

# 6. Path to Chip
E.append(Paragraph('6. Path to Physical Chip (10 weeks / 2.5 months)', sH1))

E.append(T([
    ['Week', 'Activity', 'Who', 'Output'],
    ['1', 'Vibe Coding: natural language > RTL > GDS', 'AI + EDA', 'DRC-clean GDS'],
    ['2', 'Human review + analog design if needed', 'Human', 'Tapeout package'],
    ['3', 'Submit to Efabless chipIgnite', 'Human', 'Order (~$10K USD)'],
    ['4-8', 'GF180MCU foundry manufacturing', 'Foundry', 'Wafer'],
    ['9-10', 'Packaging + testing', 'Foundry+Human', 'Physical chip'],
], [30, 175, 65, 85]))

E.append(Spacer(1, 4*mm))

E.append(T([
    ['Shuttle', 'PDK', 'Cost', 'Timeline', 'Best For'],
    ['Efabless chipIgnite', 'GF180MCU', '~$10K', '8-10 wk', 'Commercial/research'],
    ['Google Open MPW', 'SKY130', 'Free', '12-16 wk', 'Academic/open-source'],
    ['Tiny Tapeout', 'SKY130', '$100-300', '12-16 wk', 'Education/experiment'],
], [75, 55, 45, 50, 95]))

E.append(Spacer(1, 6*mm))

# 7. AI Coverage
E.append(Paragraph('7. AI Automation Coverage: 86% of IC Design Steps', sH1))

E.append(T([
    ['Category', 'Steps', 'LLM Native', 'AI+EDA', 'Human Required'],
    ['Frontend (spec>RTL)', '6', '6 (100%)', '0', '0'],
    ['Verification', '4', '2', '2', '0'],
    ['Backend (synth>GDS)', '6', '1', '5', '0'],
    ['Signoff', '3', '1', '1', '1'],
    ['Manufacturing', '2', '0', '0', '2'],
    ['TOTAL', '21', '10 (48%)', '8 (38%)', '3 (14%)'],
], [80, 35, 65, 65, 65]))

E.append(Spacer(1, 8*mm))
E.append(Paragraph('Vibe Coding for ASIC: 86% automated. Anyone can design an IC with natural language.', sBody))
E.append(Spacer(1, 4*mm))
E.append(Paragraph('Generated by Claude Opus 4.6 | AI-Native IC Design Project | Reyer | 2026-04-07', sSmall))

doc.build(E)
print(f'PDF generated: {output_path}')
