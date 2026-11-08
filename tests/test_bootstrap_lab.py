"""Checksum/cache checks use synthetic files; never download the lab or run MySQL."""
import hashlib
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('bootstrap_lab', Path(__file__).resolve().parents[1] / 'tools/bootstrap_lab.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def artifact(tmp_path, data=b'fixed synthetic runtime'):
    source = tmp_path / 'source.bin'
    source.write_bytes(data)
    return {'path': 'downloads/runtime.bin', 'url': source.as_uri(), 'sha256': hashlib.sha256(data).hexdigest()}


def test_verified_download_is_cached_and_rechecked_without_network(tmp_path, monkeypatch):
    entry = artifact(tmp_path)
    runtime = tmp_path / 'runtime'
    bootstrap.download(entry, runtime)
    target = runtime / entry['path']
    assert target.read_bytes() == b'fixed synthetic runtime'
    assert not target.with_suffix('.bin.part').exists()
    monkeypatch.setattr(bootstrap.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('valid cache should not download'))
    bootstrap.download(entry, runtime)
    target.write_bytes(b'tampered')
    with pytest.raises(SystemExit, match='Runtime checksum mismatch'):
        bootstrap.download(entry, runtime)
    assert target.read_bytes() == b'tampered'


def test_wrong_download_never_becomes_a_cached_runtime(tmp_path):
    entry = artifact(tmp_path)
    entry['sha256'] = '0' * 64
    runtime = tmp_path / 'runtime'
    with pytest.raises(SystemExit, match='Runtime checksum mismatch'):
        bootstrap.download(entry, runtime)
    assert not (runtime / entry['path']).exists()
    assert list((runtime / 'downloads').iterdir()) == []
