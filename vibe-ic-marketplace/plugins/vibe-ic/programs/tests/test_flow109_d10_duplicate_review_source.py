"""One read-only actual-consumer contrast; never executes a native producer."""
import json
import os
from pathlib import Path
import unittest

import flow109
import flow109_frontend as frontend


@unittest.skipUnless(os.environ.get('FLOW109_D10_SOURCE_CONTROL_INPUTS'),
                     'retained exact native evidence and Root-reviewed inputs required')
class DuplicateReviewedSource(unittest.TestCase):
    def test_two_reviewed_indices_for_same_exact_capture_are_one_source(self):
        inputs = json.loads(Path(os.environ['FLOW109_D10_SOURCE_CONTROL_INPUTS']).read_bytes())
        project = Path(inputs['project'])
        manifest = json.loads(Path(inputs['manifest']).read_bytes())
        context = flow109.execution_context(
            flow109.resolve_plan(manifest['features'], manifest['step_profiles']), 'D10', 'D10',
            runtime_tool_uses=manifest['runtime_tool_uses'],
            qualification_registry=manifest['qualification_registry'])
        registry = json.loads(Path(context['qualification_registry']).read_bytes())
        record = next(row for row in registry['uses']
                      if row['use_id'] == 'flow109.D10.default.verilator')
        references = []
        for reference in record['reference_evidence']:
            path = Path(reference['path'])
            if path.suffix == '.json':
                document = json.loads(path.read_bytes())
                if 'source_before' in document and 'models' in document:
                    references.append(document['source_before'])
        self.assertEqual(len(references), 2)
        self.assertEqual(references[0], references[1])
        self.assertEqual(references[0], inputs['expected_source_capture'])
        retained = json.loads(Path(inputs['positive_row']).read_bytes())['evidence']['p0_native']
        self.assertEqual(retained['cid'], inputs['retained_positive_CID'])
        self.assertEqual(retained['status'], 'PASS')
        output = Path(os.environ['FLOW109_D10_SOURCE_CONTROL_READBACK'])
        report = {'consumer': str(Path(frontend.__file__).resolve()),
                  'retained_positive_CID': retained['cid'],
                  'reviewed_indices': 2, 'unique_exact_path_SHA': 1,
                  'source_capture': references[0], 'native_or_P0_runs': 0,
                  'canonical_row_published': False}
        try:
            result = frontend.d10_native_qualification(project, context, retained, retained)
        except frontend.AdmissionRefusal as exc:
            report.update(status='REFUSED', code=exc.code, detail=str(exc), refusal=exc.report)
            output.write_text(json.dumps(report, indent=2) + '\n')
            raise
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual({row['use_id'] for row in result['uses']},
                         {'flow109.D10.default.yosys', 'flow109.D10.default.verilator'})
        self.assertEqual(len(set(result['reviewed_native_source_trees'])), 1)
        report.update(status='PASS', actual_consumer_result=result)
        output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
