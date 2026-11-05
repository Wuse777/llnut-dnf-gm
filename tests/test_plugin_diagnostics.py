"""Only synthetic plugin files/snapshots. Never execute native plugin code."""
import hashlib
import json
import time
from types import SimpleNamespace
from dnfgm.plugin_diagnostics import source_fingerprint,report,REVIEWED_SCRIPT_SHA256,MAX_SCRIPT_BYTES


def test_collector_fingerprint_is_bounded_and_never_follows_links(tmp_path):
    source=tmp_path/'frida.js';source.write_bytes(b'synthetic config with a private password')
    expected={'schema':1,'source_state':'observed','source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    assert source_fingerprint(source)==expected
    alias=tmp_path/'link';alias.symlink_to(source)
    for path in (alias,tmp_path,tmp_path/'missing'):
        assert source_fingerprint(path)['source_state']=='unavailable'
    source.write_bytes(b'x'*(MAX_SCRIPT_BYTES+1));assert source_fingerprint(source)['source_state']=='unavailable'


def test_report_does_not_turn_disk_evidence_into_runtime_controls(tmp_path):
    status=tmp_path/'status.json';settings=SimpleNamespace(status_file=str(status))
    data={'collected_at':time.time(),'core_ok':True,'plugin_source':{'schema':1,'source_state':'observed','source_sha256':REVIEWED_SCRIPT_SHA256},'private_password':'synthetic-secret-do-not-expose'}
    status.write_text(json.dumps(data));r=report(settings)
    assert r['state']=='matched' and len(r['startup'])==6
    assert r['runtime_state']=='not_verified' and not r['editable']
    assert r['configuration']['editable_gameplay_keys']==[]
    assert 'synthetic-secret-do-not-expose' not in json.dumps(r)
    data['plugin_source']['source_sha256']='a'*64;status.write_text(json.dumps(data))
    assert report(settings)['state']=='unreviewed' and report(settings)['startup']==[]
    data['plugin_source']['source_sha256']=REVIEWED_SCRIPT_SHA256;data['collected_at']-=60;status.write_text(json.dumps(data))
    r=report(settings);assert r['state']=='unknown' and r['source_sha256'] is None and r['startup']==[]
