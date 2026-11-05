"""Real native launches and per-child accounting without an external time binary."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'librelane_plugins'))
from librelane_plugin_vibeic import GateLevelSim


def _resources(log):
    values = dict(line.split('=', 1) for line in Path(str(log) + '.resources.txt').read_text().splitlines())
    assert set(values) == {'max_rss_kib', 'user_s', 'system_s', 'elapsed_s'}
    measured = {key: float(value) for key, value in values.items()}
    assert measured['max_rss_kib'] > 0
    assert measured['elapsed_s'] > 0
    assert measured['user_s'] >= 0 and measured['system_s'] >= 0
    return measured




@pytest.mark.parametrize('exit_code,limit', [(0, 10), (7, 10), (124, 0.2)])
def test_native_resources_preserve_exit_timeout_cwd_and_complete_logs(tmp_path, exit_code, limit):
    log = str(tmp_path / 'child.log')
    code = ("import os,sys,time; print(os.getcwd(), flush=True); "
            "print('child diagnostic', file=sys.stderr, flush=True); "
            + ('time.sleep(10)' if exit_code == 124 else f'sys.exit({exit_code})'))
    rc = GateLevelSim._run([sys.executable, '-c', code], log, limit, cwd=str(tmp_path))
    assert rc == exit_code
    text = Path(log).read_text()
    assert str(tmp_path) in text and 'child diagnostic' in text
    assert Path(log + '.stderr').read_text().strip() == 'child diagnostic'
    assert ('VIBEIC_GLS_TIMEOUT' in text) == (exit_code == 124)
    _resources(log)


def test_parallel_resource_records_belong_to_each_child(tmp_path):
    def run(size):
        log = str(tmp_path / f'{size}.log')
        code = ("import json,resource,time; "
                f"data = bytearray({size} * 1024 * 1024); "
                "time.sleep(0.05); "
                "print(json.dumps({'rss': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))")
        assert GateLevelSim._run([sys.executable, '-c', code], log, 10) == 0
        own_rss = json.loads(Path(log).read_text())['rss']
        if sys.platform == 'darwin':
            own_rss /= 1024
        measured = _resources(log)
        assert own_rss <= measured['max_rss_kib'] <= own_rss + 4096
        return measured
    run(128)  # A previous child's peak must not be attributed to later children.
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(list(pool.map(run, [16, 48, 24, 64]))) == 4
