"""Lossless native LibreLane stream-out for a DEF with explicit FILLS.

Only the pya-script boundary is specialized. Superclass State, output and
missing-GDS behavior remain native. The source-version patch is tracked by
vibeic/librelane#34; the installed script itself is never modified.
"""
from __future__ import annotations
from pathlib import Path
import sys

from librelane.steps import Step
from librelane.steps.klayout import StreamOut
from librelane.steps.step import StepError

PROGRAMS = Path(__file__).resolve().parents[2]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))
import librelane_fill_stream as bridge
from _atomic_artefact import write_json


@Step.factory.register()
class FillAwareStreamOut(StreamOut):
    id = 'Vibeic.FillAwareStreamOut'
    name = 'GDSII Stream Out With Verified DEF Fill'

    def run_pya_script(self, argv, **kwargs):
        # This is the exact command created by the installed superclass; all
        # option values and native input/output identity stay with that owner.
        if len(argv) < 3 or Path(argv[1]).resolve() != bridge.native_script().resolve():
            raise StepError('FILL_STREAM_NATIVE_COMMAND_UNSUPPORTED')
        bridge.patched_native_source(bridge.native_script().read_text())
        source = Path(argv[2])
        parsed = bridge.fill_records(source)
        try:
            map_index = argv.index('--lym') + 1
            output_index = argv.index('--output') + 1
        except ValueError as exc:
            raise StepError('FILL_STREAM_NATIVE_COMMAND_UNSUPPORTED') from exc
        mapping = bridge.derive_map(Path(argv[map_index]), None, source,
                                    Path(self.step_dir) / 'verified-fill.map')
        inputs = {str(p): bridge._sha(p) for p in [source, Path(argv[map_index])]}
        bare = Path(self.step_dir) / 'fill-proof-bare.def'
        bare.write_text(parsed['bare_def'])
        bare_gds = Path(self.step_dir) / 'fill-proof-bare.gds'
        commands = []
        for def_file, gds_file in [(bare, bare_gds), (source, Path(argv[output_index]))]:
            if any(bridge._sha(Path(p)) != sha for p, sha in inputs.items()):
                raise StepError('FILL_STREAM_INPUT_CHANGED')
            command = list(map(str, argv))
            command[1] = str(PROGRAMS / 'librelane_fill_stream_native.py')
            command[2], command[output_index] = str(def_file), str(gds_file)
            super().run_pya_script(command, **kwargs)
            commands.append(command)
        proof = bridge.geometry_proof(source, bare_gds, Path(argv[output_index]), mapping['layer_map'])
        write_json(Path(self.step_dir) / 'fill_stream_geometry.json', {
            'schema': bridge.SCHEMA, 'component_status': 'PASS',
            'geometry_proof': proof,
            'inputs': inputs, 'bare_gds': bridge._record(Path(self.step_dir), bare_gds),
            'filled_gds': bridge._record(Path(self.step_dir), Path(argv[output_index])),
            'commands': commands,
            'native_runtime': 'reviewed exact-source patch; installed image script unchanged',
            'final_geometry_adoption': 'NOT_MEASURED'})
