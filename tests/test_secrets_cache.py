"""Credential rotation and config caching without reading real credentials."""

import json
import os

import pytest

from config import secrets


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / 'api_keys.json'
    monkeypatch.setattr(secrets, '_CONFIG_PATH', path)
    for env, _ in secrets._SECRET_MAP.values():
        monkeypatch.delenv(env, raising=False)
    return path


def test_live_environment_override_after_an_initial_miss(config_file, monkeypatch):
    assert secrets.get_secret('gemini_api_key') == ''
    config_file.write_text('{"gemini_api_key":"file-value"}', encoding='utf-8')
    assert secrets.get_secret('gemini_api_key') == 'file-value'
    monkeypatch.setenv('GEMINI_API_KEY', 'override')
    assert secrets.get_secret('gemini_api_key') == 'override'
    monkeypatch.delenv('GEMINI_API_KEY')
    assert secrets.get_secret('gemini_api_key') == 'file-value'


def test_parse_once_and_invalidate_on_replacement_and_removal(config_file, monkeypatch):
    calls = 0
    original_load = json.load
    def count_load(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_load(*args, **kwargs)

    monkeypatch.setattr(secrets.json, 'load', count_load)
    config_file.write_text('{"gemini_api_key":"aaa","firms_map_key":"bbb"}', encoding='utf-8')
    for _ in range(5):
        assert secrets.get_secret('gemini_api_key') == 'aaa'
        assert secrets.get_secret('firms_map_key') == 'bbb'
    assert calls == 1

    stamp = config_file.stat()
    replacement = config_file.with_suffix('.new')
    replacement.write_text('{"gemini_api_key":"ccc","firms_map_key":"ddd"}', encoding='utf-8')
    os.utime(replacement, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    replacement.replace(config_file)
    assert secrets.get_secret('gemini_api_key') == 'ccc'
    assert calls == 2
    config_file.unlink()
    assert secrets.get_secret('gemini_api_key') == ''


@pytest.mark.parametrize('contents', ['[]', '{broken', '{"gemini_api_key": null}',
                                        '{"gemini_api_key":123}'])
def test_invalid_config_does_not_return_a_value(config_file, contents):
    config_file.write_text(contents, encoding='utf-8')
    assert secrets.get_secret('gemini_api_key') == ''
    assert secrets.get_secret('unknown') == ''
