"""Exercise the shell launcher's child ownership without real hardware or servers."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.skipif(shutil.which('bash') is None, reason='Bash launcher')


@pytest.fixture
def fake_launcher(tmp_path):
    root = Path(__file__).resolve().parent.parent
    launcher = tmp_path / 'launch.sh'
    shutil.copyfile(root / 'launch.sh', launcher)

    def script(path, body):
        path.write_text('#!/usr/bin/env bash\n' + body, encoding='utf-8')
        path.chmod(0o700)

    scripts = tmp_path / 'bin'
    scripts.mkdir()
    script(scripts / 'curl', 'exit 1\n')
    script(scripts / 'xdpyinfo', 'exit 1\n')
    script(scripts / 'python', '''
[[ "$1" == "-u" ]] || exit 0
for _ in {1..80}; do
    [[ ! -f gev-started ]] || exit 17
    sleep 0.025
done
exit 2
''')
    globe = tmp_path / 'apps' / 'gods-eye-view'
    globe.mkdir(parents=True)
    script(globe / 'launch-jarvis.sh', '''
trap 'touch gev-stopped; exit 0' TERM
touch gev-started
while :; do sleep 0.05; done
''')
    env = {
        'PATH': os.pathsep.join((str(scripts), os.environ['PATH'])),
        'HOME': str(tmp_path),
        'TMPDIR': str(tmp_path),
        'XDG_RUNTIME_DIR': str(tmp_path),
        'JARVIS_PYTHON': str(scripts / 'python'),
        'KD_START_GEV_DEV': '1',
    }
    return launcher, env


def test_start_and_stop_only_the_optional_child(fake_launcher):
    launcher, env = fake_launcher
    result = subprocess.run(['bash', str(launcher)], env={**env, 'DISPLAY': ':1'},
                            capture_output=True, text=True, timeout=6)
    assert result.returncode == 17, result.stderr
    assert (launcher.parent / 'gev-started').is_file()
    assert (launcher.parent / 'gev-stopped').is_file()


def test_invalid_display_does_not_spawn_the_globe(fake_launcher):
    launcher, env = fake_launcher
    result = subprocess.run(['bash', str(launcher)], env=env,
                            capture_output=True, text=True, timeout=6)
    assert result.returncode == 1
    assert 'No accessible local X display' in result.stderr
    assert not (launcher.parent / 'gev-started').exists()
