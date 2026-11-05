"""Run the existing IO and pad-assignment producers in the native chain."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

from librelane.steps import Step, StepError, StepException


@Step.factory.register()
class PackageInterface(Step):
    id = 'VibeIC.PackageInterface'
    name = 'Native package and pad interface planning'
    inputs = []
    outputs = []

    def run(self, state_in, **kwargs):
        import io_pad_chip_top_gen
        import pad_assignment_gen

        project = Path(str(self.config['DESIGN_DIR']))
        directory = Path(self.step_dir)
        pdk_options = ['--pdk-root', str(self.config['PDK_ROOT']),
                       '--pdk', self.config['PDK']]
        io_options = list(pdk_options)
        for level, key in [('high', 'SYNTH_TIEHI_CELL'), ('low', 'SYNTH_TIELO_CELL')]:
            cell = self.config.get(key)
            if cell:
                master, pin = str(cell).rsplit('/', 1)
                io_options.extend([f'--tie-{level}-cell', master, f'--tie-{level}-pin', pin])
        libraries = self.toolbox.filter_views(self.config, self.config['LIB'])
        if libraries:
            io_options.extend(['--tie-liberty', str(libraries[0])])
        for option, nets, pin in [('power', 'VDD_NETS', 'VDD_PIN'),
                                  ('ground', 'GND_NETS', 'GND_PIN')]:
            rails = self.config.get(nets) or [self.config[pin]]
            if len(rails) == 1:
                io_options.extend([f'--{option}-net', str(rails[0])])
        io_report = project / 'reports/phase3/io_pad_chip_top.json'
        code = io_pad_chip_top_gen.main([str(project), *io_options])
        io = json.loads(io_report.read_text())
        shutil.copyfile(io_report, directory / 'io_pad_chip_top.json')
        if code == 1:
            raise StepError(f"io_pad_chip_top_gen stopped: {io.get('rule', io.get('verdict'))}")
        if code or io.get('verdict') != 'WROTE':
            raise StepException(f"NOT_MEASURED: io_pad_chip_top_gen: {io.get('rule', io.get('verdict'))}")
        output = directory / 'pad_assignment.json'
        code = pad_assignment_gen.main([str(project), *pdk_options, '--json', str(output),
            '--out', str(project / 'phase3/stage3/pnr/pad_assignment.json')])
        assignment = json.loads(output.read_text())
        if code == 1:
            raise StepError(f"pad_assignment_gen stopped: {assignment.get('reason', assignment.get('verdict'))}")
        if code or assignment.get('verdict') != 'WROTE':
            raise StepException(f"NOT_MEASURED: pad_assignment_gen: {assignment.get('reason', assignment.get('verdict'))}")
        return {}, {'package_interface__pad__count': len(io['pad_instances']),
                    'package_interface__question__count': assignment['questions_answered'],
                    'package_interface__unanswered__count': len(assignment['questions_unanswered'])}
