import pytest
from dnfgm_m0.names import inspect_name


@pytest.mark.parametrize('name', ['示例角色', 'GM测试角色', 'abc123'])
def test_lossless_client_candidate(name):
    raw = name.encode('utf-8')
    stored = raw.decode('cp1252')
    out = inspect_name(stored, raw)
    assert out['stored_name'] == stored
    assert out['client_name_candidate'] == name
    assert out['name_encoding'] == ('ascii' if name.isascii() else 'utf8_via_latin1_candidate')


@pytest.mark.parametrize('stored,raw', [
    ('真正的中文', b'?????'),  # SQL CONVERT replacements cannot be trusted.
    ('é', b'\xe9'),           # Literal latin1 is not valid UTF-8.
    ('abc', b'changed'),      # Roundtrip mismatch.
    ('\x81', b'\x81'),       # Unsupported cp1252 codepoint, do not guess.
])
def test_lossy_invalid_and_unsupported_names_remain_unverified(stored, raw):
    out = inspect_name(stored, raw)
    assert out['stored_name'] == stored
    assert out['client_name_candidate'] is None
    assert out['name_encoding'] == 'unverified'


def test_actual_mysql57_latin1_conversion(lab):
    # Synthetic local-only row; use the production conversion with no live DB.
    from dnfgm_m0.lab import connect
    c = connect(lab.socket)
    try:
        name = '示例角色'
        with c.cursor() as cur:
            cur.execute('UPDATE taiwan_cain.charac_info SET charac_name=%s WHERE charac_no=900001',
                        (name.encode('utf-8').decode('cp1252'),))
            cur.execute('SELECT charac_name,CAST(CONVERT(charac_name USING latin1) AS BINARY) AS raw FROM taiwan_cain.charac_info WHERE charac_no=900001')
            row = cur.fetchone()
        assert inspect_name(row[0], row[1])['client_name_candidate'] == name
    finally:
        c.rollback()
        c.close()
