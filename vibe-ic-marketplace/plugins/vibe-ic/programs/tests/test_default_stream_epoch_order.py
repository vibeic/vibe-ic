"""Real Default finishing/readback; controlled native process writes, no IC claim."""





















def test_shipped_xor_named_docker_retains_its_original_launch_envelope(tmp_path, monkeypatch):
    """The real Docker parser retains its old resource flags; neutral exec leaf."""
    import _native373_current as native
    import _watchdog as watchdog
    from _stated_eda_image import mock_docker_route, stated_image
    mock_docker_route(monkeypatch)
    monkeypatch.setenv('VIBEIC_DOCKER_MEMORY', '4g')
    image = stated_image()
    commands = []
    def neutral_process(argv, **kwargs):
        commands.append(list(argv))
        return watchdog.SupervisedResult(0, 'SOURCE_CONTROL Docker exec leaf', '', 'natural')
    monkeypatch.setattr(watchdog, 'run_host_supervised', neutral_process)
    runner = native.ShippedXorRunner(tmp_path, image)
    assert runner.kind == 'docker_run' and runner.detail == image + ':klayout'
    rc, _, _ = runner.run(tmp_path / 'xor.rb', {})
    assert rc == 0 and len(commands) == 1
    argv = commands[0]
    assert argv[:2] == ['docker', 'run'] and '--name' in argv
    assert argv[argv.index('--cpus') + 1] == '2'
    assert argv[argv.index('--memory') + 1] == argv[argv.index('--memory-swap') + 1] == '4g'
    assert '--rm' in argv and argv[argv.index('--network') + 1] == 'none'
    assert argv[argv.index(image) + 1:argv.index(image) + 5] == ['--skip', '/usr/bin/time', '-v', 'klayout']
    assert runner.execution['argv'] == [v for i, v in enumerate(argv) if i not in (2, 3)]
