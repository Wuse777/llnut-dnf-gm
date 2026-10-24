"""Only local synthetic rows; never connect a production database as a fixture."""
import pytest
from dnfgm.encoding import inspect_name, mysql_latin1_text
from dnfgm.service import wire_name
from fastapi import HTTPException

P = '/dnf-gm/api/v1'


@pytest.mark.parametrize('name', ['风筝', '丁', '不', '丏', '丐', '丝', '示例角色', 'abc123'])
def test_runtime_mysql_latin1_name_candidate(name):
    raw = name.encode('utf-8')
    stored = mysql_latin1_text(raw)
    result = inspect_name(stored, raw)
    assert result['client_name_candidate'] == name
    assert result['stored_name'] == stored


def test_observed_name_0x9d_regression():
    raw = bytes.fromhex('e9a38ee7ad9d')
    stored = 'é£Žç\xad\u009d'
    assert mysql_latin1_text(raw) == stored
    assert inspect_name(stored, raw)['client_name_candidate'] == '风筝'
    # Do not silently extend outbound mail writes while fixing name reads.
    with pytest.raises(HTTPException) as error:
        wire_name('风筝')
    assert error.value.status_code == 422


@pytest.mark.parametrize('stored,raw', [
    ('真正中文', b'????'), ('abc', b'changed'), ('é', b'\xe9'),
    *[(chr(byte), bytes((byte,))) for byte in (0x81, 0x8d, 0x8f, 0x90, 0x9d)],
    ('风筝', bytes.fromhex('e9a38ee7ad9d')),
])
def test_runtime_still_rejects_lossy_mismatched_or_invalid_utf8(stored, raw):
    result = inspect_name(stored, raw)
    assert result['client_name_candidate'] is None
    assert result['stored_name'] == stored
    assert result['name_encoding'] == 'unverified'


def test_all_256_bytes_match_actual_mysql57_mapping(env):
    _, _, db, _ = env
    raw = bytes(range(256))
    with db.connect() as con, con.cursor() as q:
        q.execute('SELECT CONVERT(CONVERT(CAST(%s AS BINARY) USING latin1) USING utf8mb4) AS mapped_name', (raw,))
        assert q.fetchone()['mapped_name'] == mysql_latin1_text(raw)


@pytest.mark.parametrize('name', ['风筝', '丁不丏丐丝', '中文%_\\'])
def test_character_list_search_and_preview_are_lossless_and_read_only(env, name):
    c, _, db, _ = env
    stored = mysql_latin1_text(name.encode('utf-8'))
    with db.connect() as con, con.cursor() as q:
        q.execute('UPDATE taiwan_cain.charac_info SET charac_name=%s WHERE charac_no=900001', (stored,))
        con.commit()
    for params in ({'uid': 900001}, {'q': name}, {'q': name[:1]}, {'q': '900001'}):
        r = c.get(P+'/characters', params=params)
        assert r.status_code == 200, r.text
        row = next(item for item in r.json()['items'] if item['charac_no'] == 900001)
        assert row['charac_name'] == name
        assert row['stored_name'] == stored
        assert row['encoding_state'] == 'utf8_via_latin1_candidate'
    assert c.get(P+'/characters', params={'uid':900002, 'q':name}).json()['items'] == []
    assert c.get(P+'/characters', params={'q':"' OR 1=1--"}).json()['items'] == []
    r = c.post(P+'/operations/preview', json={
        'action':'mail', 'uid':900001, 'charac_no':900001,
        'reason':'local name regression preview only', 'message':'GM rewards',
        'items':[{'id':990002, 'quantity':1}],
    })
    assert r.status_code == 200, r.text
    target = r.json()['preview']['target']['character']
    assert target['charac_name'] == name and target['charac_no'] == 900001
    with db.connect() as con, con.cursor() as q:
        q.execute('SELECT charac_name FROM taiwan_cain.charac_info WHERE charac_no=900001')
        assert q.fetchone()['charac_name'] == stored
        q.execute('SELECT COUNT(*) n FROM taiwan_cain_2nd.postal')
        assert q.fetchone()['n'] == 0
