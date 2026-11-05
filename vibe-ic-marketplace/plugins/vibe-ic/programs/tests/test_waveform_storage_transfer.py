"""Neutral storage-connection qualification through emitted RTL and Icarus.

Scope: one high-transparent latch plus one falling-edge register. No scorer,
external corpus, timing setup convention, or implementation string assertions.
"""
import json
import shutil
import subprocess

import pytest
import sequential_waveform_synth as waveform
import spec_artifact_registry as registry
from _hostpaths import require_repo


TRANSITIONS = [(0, 0, 0), (7, 1, 1), (11, 1, 0), (19, 1, 1),
               (23, 0, 0), (31, 0, 1), (37, 1, 0), (41, 1, 0),
               (47, 0, 1), (53, 0, 0), (61, 1, 1), (67, 1, 0),
               (71, 0, 0), (79, 0, 1), (83, 1, 1), (89, 0, 0), (97, 0, 0)]


def observations(source):
    retained = sampled = 'x'
    previous_clock = 0
    rows = []
    for time, clock, data in TRANSITIONS:
        if previous_clock == 1 and clock == 0:
            sampled = data if source == 'direct' else retained
        if clock:
            retained = data
        rows.append([time, clock, data, retained, sampled])
        previous_clock = clock
    return rows


def prompt_for(rows, reverse=False):
    header = '''Module name: storage_pair
Implement the sequential behavior in this waveform. Ports are single bits.
 - input clk
 - input payload
 - output retained
 - output sampled
'''
    names = ['retained', 'sampled']
    if reverse:
        names.reverse()
    table = 'time clk payload ' + ' '.join(names) + '\n'
    for t, c, d, p, q in rows:
        values = [q, p] if reverse else [p, q]
        table += f'{t}ns {c} {d} ' + ' '.join(map(str, values)) + '\n'
    return header + table


def simulate(tmp_path, rtl, rows):
    assert shutil.which('iverilog') and shutil.which('vvp'), 'native Icarus required'
    design = tmp_path / 'storage_pair.sv'
    bench = tmp_path / 'probe.sv'
    executable = tmp_path / 'probe.vvp'
    design.write_text(rtl)
    lines = ['`timescale 1ns/1ps', 'module probe;',
             'reg clk, payload; wire retained, sampled;',
             'storage_pair dut(.*);', 'initial begin']
    previous_time = 0
    for time, clock, data, retained, sampled in rows:
        lines.append(f'#{time - previous_time}; {{clk,payload}} = {{1\'b{clock},1\'b{data}}}; #1;')
        for name, expected in [('retained', retained), ('sampled', sampled)]:
            if expected != 'x':
                lines.append(f'if ({name} !== 1\'b{expected}) $fatal(1,"{time} {name}");')
        previous_time = time + 1
    lines += ['$display("STORAGE_PROBE=PASS"); $finish;', 'end', 'endmodule']
    bench.write_text('\n'.join(lines))
    compile_result = subprocess.run(['iverilog', '-g2012', '-s', 'probe', '-o',
        str(executable), str(bench), str(design)], cwd=tmp_path, capture_output=True, text=True)
    assert compile_result.returncode == 0, compile_result.stderr
    return subprocess.run(['vvp', str(executable)], cwd=tmp_path, capture_output=True, text=True)


@pytest.mark.parametrize('source', ['direct', 'peer'])
@pytest.mark.parametrize('reverse', [False, True])
def test_generated_connection_replays_every_observation(tmp_path, source, reverse):
    rows = observations(source)
    rtl = waveform.synth(prompt_for(rows, reverse), 'storage_pair')
    assert rtl is not None
    run = simulate(tmp_path, rtl, rows)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize('source', ['direct', 'peer'])
def test_existing_registry_and_capture_route(tmp_path, source):
    artifact = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                            'benchmark', 'CAPTURE_ROUTING.json')
    route = json.loads(artifact.read_text())['steps']['phase2.latch_intent']
    assert 'programs/sequential_waveform_synth.py' in route['bucket_A_related']
    rows = observations(source)
    _, rtl = registry.generate(prompt_for(rows), 'storage_pair')
    assert rtl is not None
    run = simulate(tmp_path, rtl, rows)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize('source', ['direct', 'peer'])
def test_value_control_rejects_opposite_connection(tmp_path, source):
    rhs = 'retained' if source == 'direct' else 'payload'
    mutant = f'''module storage_pair(input clk, payload, output reg retained, sampled);
always @(*) if (clk) retained = payload;
always @(negedge clk) sampled <= {rhs};
endmodule
'''
    run = simulate(tmp_path, mutant, observations(source))
    assert run.returncode != 0, 'coincident edges must discriminate the wrong source'
    assert '23 sampled' in run.stdout


@pytest.mark.parametrize('defect', ['off_edge', 'latch_mismatch', 'hidden_hold',
                                    'hidden_latch_hold', 'unknown_source', 'malformed', 'time_reversal'])
def test_unsupported_waveforms_decline(defect):
    rows = observations('peer')
    if defect == 'off_edge':
        rows[5][4] = 0
    elif defect == 'latch_mismatch':
        rows[2][3] = 1
    elif defect == 'hidden_hold':
        rows[5][4] = 'x'
        rows[6][4] = rows[7][4] = 0  # x cannot erase the already sampled state
    elif defect == 'hidden_latch_hold':
        rows[4][3] = 'x'
        rows[5][3] = 0
    elif defect == 'unknown_source':
        rows[4][1] = 'x'
    elif defect == 'malformed':
        rows[-1][4] = 'bad'
    else:
        rows[-1][0] = 2
    assert waveform.synth(prompt_for(rows), 'storage_pair') is None


def test_unobserved_initial_outputs_remain_unconstrained(tmp_path):
    rows = observations('peer')
    rows[0][3:] = ['x', 'x']
    rtl = waveform.synth(prompt_for(rows), 'storage_pair')
    assert rtl is not None
    run = simulate(tmp_path, rtl, rows)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize('source', ['direct', 'peer'])
def test_defined_initial_observations_are_reproduced(tmp_path, source):
    rows = observations(source)
    for row in rows:
        if row[4] == 'x':
            row[4] = 0
    rows[0][3] = 0
    rtl = waveform.synth(prompt_for(rows), 'storage_pair')
    assert rtl is not None
    run = simulate(tmp_path, rtl, rows)
    assert run.returncode == 0, run.stdout + run.stderr


def test_unknown_peer_observation_does_not_erase_known_storage(tmp_path):
    rows = observations('peer')
    rows[4][3] = 'x'
    rows[5][4] = 'x'
    rtl = waveform.synth(prompt_for(rows), 'storage_pair')
    assert rtl is not None
    run = simulate(tmp_path, rtl, rows)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize('source', ['direct', 'peer'])
def test_incompatible_initial_drive_declines_instead_of_false_match(source):
    rows = observations(source)
    rows[0][3:] = [0, 1]
    assert waveform.synth(prompt_for(rows), 'storage_pair') is None


def test_undiscriminated_connections_still_replay(tmp_path):
    rows = observations('peer')
    for row in rows:
        if row[0] in (23, 47, 89):
            row[2] = row[3]  # direct input and retained source now agree at every fall
    rtl = waveform.synth(prompt_for(rows), 'storage_pair')
    assert rtl is not None
    run = simulate(tmp_path, rtl, rows)
    assert run.returncode == 0, run.stdout + run.stderr
