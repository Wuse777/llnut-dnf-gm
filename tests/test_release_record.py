from pathlib import Path
import json
import pytest
from dnfgm.capabilities import release_identity
from dnfgm.release_record import build_record,write_record,read_record


def fixture(root):
    (root/'README.md').write_text('# Public documentation\n')
    (root/'docs').mkdir();(root/'docs'/'GUIDE.md').write_text('Manual\n')
    (root/'SOURCE_REVISION').write_text('a'*40+'\n')


def test_bound_release_and_documentation_are_displayed_without_local_paths(tmp_path):
    fixture(tmp_path);r=build_record(tmp_path,'a'*40,'20261106-fixture',now=100)
    assert r['documentation']['file_count']==2
    write_record(tmp_path,r);identity=release_identity(tmp_path)
    assert identity['source_revision']=='a'*40
    assert identity['release']=={'state':'recorded','id':'20261106-fixture','built_at':100}
    assert identity['documentation']['source_revision']=='a'*40
    assert str(tmp_path) not in json.dumps(identity)
    (tmp_path/'docs'/'GUIDE.md').write_text('Changed manual\n')
    assert build_record(tmp_path,'a'*40,'20261106-fixture',now=100)['documentation']['manifest_sha256']!=r['documentation']['manifest_sha256']


def test_absent_mismatched_and_invalid_records_do_not_invent_versions(tmp_path):
    fixture(tmp_path);assert release_identity(tmp_path)['release']['state']=='unknown'
    r=build_record(tmp_path,'b'*40,'20261106-other',now=100);write_record(tmp_path,r)
    assert release_identity(tmp_path)['release']['state']=='mismatch'
    assert release_identity(tmp_path)['documentation']['source_revision'] is None
    r=build_record(tmp_path,'a'*40,'20261106-fixture',now=100);r['release_id']='/private/secret'
    write_record(tmp_path,r);assert read_record(tmp_path,'a'*40)['release']['state']=='unknown'
    (tmp_path/'RELEASE_RECORD.json').write_text('x'*8193)
    assert read_record(tmp_path,'a'*40)['release']['state']=='unknown'


def test_build_refuses_symlinks_and_preserves_another_builds_temporary_file(tmp_path):
    fixture(tmp_path);(tmp_path/'docs'/'LINK.md').symlink_to(tmp_path/'README.md')
    with pytest.raises(ValueError,match='symlinks'):build_record(tmp_path,'a'*40,'fixture',now=100)
    (tmp_path/'docs'/'LINK.md').unlink();record=build_record(tmp_path,'a'*40,'fixture',now=100)
    (tmp_path/'.release-record.tmp').write_text('another build')
    with pytest.raises(FileExistsError):write_record(tmp_path,record)
    assert (tmp_path/'.release-record.tmp').read_text()=='another build'
    assert not (tmp_path/'RELEASE_RECORD.json').exists()
