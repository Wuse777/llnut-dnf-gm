"""Low-level compatibility probes and updated gold-mail API boundaries.

Run only with the socket-only MySQL 5.7 laboratory (conftest enforces server_id).
These prove SQL persistence/rollback and API/grant boundaries, not receipt
by the game client. Historical investigation is recorded separately in acceptance/.
"""
import importlib.util
from pathlib import Path
import os
import pymysql
import pytest


def insert_candidate(q, amount, fail_at=None):
    q.execute('SELECT m_id,delete_flag FROM taiwan_cain.charac_info WHERE charac_no=900001 FOR UPDATE')
    assert q.fetchone() == {'m_id': 900001, 'delete_flag': 0}
    q.execute("INSERT INTO taiwan_cain_2nd.letter(charac_no,send_charac_name,letter_text,reg_date,stat) VALUES(900001,'GM-GOLD-LAB','Gold mail SQL compatibility probe',UTC_TIMESTAMP(),0)")
    letter = q.lastrowid
    if fail_at == 'letter':
        raise RuntimeError('injected after letter')
    # item_id=0 is a candidate pure-gold encoding, not client-verified semantics.
    q.execute("INSERT INTO taiwan_cain_2nd.postal(occ_time,send_charac_name,receive_charac_no,item_id,add_info,endurance,gold,letter_id) VALUES(UTC_TIMESTAMP(),'GM-GOLD-LAB',900001,0,0,0,%s,%s)", (amount, letter))
    postal = q.lastrowid
    if fail_at == 'postal':
        raise RuntimeError('injected after postal')
    return letter, postal


@pytest.mark.parametrize('amount', [1, 1000, 100000000, 4294967295])
def test_candidate_persists_in_separate_connection_without_claiming(env, amount):
    _, _, db, _ = env
    with db.connect() as c, c.cursor() as q:
        letter, postal = insert_candidate(q, amount)
        c.commit()
    with db.connect() as c, c.cursor() as q:
        q.execute('SELECT p.gold,p.item_id,p.add_info,p.endurance,p.delete_flag,CAST(p.receive_time AS CHAR) AS received,l.charac_no FROM taiwan_cain_2nd.postal p JOIN taiwan_cain_2nd.letter l ON l.letter_id=p.letter_id WHERE p.postal_id=%s AND l.letter_id=%s', (postal, letter))
        assert q.fetchone() == dict(gold=amount, item_id=0, add_info=0, endurance=0,
                                   delete_flag=0, received='0000-00-00 00:00:00', charac_no=900001)
        q.execute("SELECT cera FROM taiwan_billing.cash_cera WHERE account='900001'")
        assert q.fetchone()['cera'] == 1000


@pytest.mark.parametrize('stage', ['letter', 'postal'])
def test_candidate_failure_rolls_back_entire_mail(env, stage):
    _, _, db, _ = env
    with pytest.raises(RuntimeError):
        with db.connect() as c, c.cursor() as q:
            insert_candidate(q, 1000, stage)
    with db.connect() as c, c.cursor() as q:
        for table in ('postal', 'letter'):
            q.execute('SELECT COUNT(*) AS n FROM taiwan_cain_2nd.' + table)
            assert q.fetchone()['n'] == 0


@pytest.mark.parametrize('amount', [-1, 4294967296])
def test_strict_session_rejects_uint32_overflow_and_rolls_back(env, amount):
    _, _, db, _ = env
    with pytest.raises(pymysql.err.DataError) as error:
        with db.connect() as c, c.cursor() as q:
            insert_candidate(q, amount)
    assert error.value.args[0] == 1264
    with db.connect() as c, c.cursor() as q:
        for table in ('postal', 'letter'):
            q.execute('SELECT COUNT(*) AS n FROM taiwan_cain_2nd.' + table)
            assert q.fetchone()['n'] == 0


def test_current_api_accepts_gold_only_preview_without_delivering(env):
    client, _, db, _ = env
    r = client.post('/dnf-gm/api/v1/operations/preview', json={
        'action': 'mail', 'uid': 900001, 'charac_no': 900001,
        'reason': 'Gold compatibility probe', 'message': 'SQL laboratory only',
        'items': [], 'gold': 1000})
    assert r.status_code == 200, r.text
    assert r.json()['preview']['gold'] == 1000
    assert r.json()['preview']['rewards']['items'] == []
    with db.connect() as c, c.cursor() as q:
        for table in ('postal', 'letter'):
            q.execute('SELECT COUNT(*) AS n FROM taiwan_cain_2nd.' + table)
            assert q.fetchone()['n'] == 0


def test_current_minimal_grants_allow_only_gold_insert_and_select(env):
    _, _, db, _ = env
    path = Path(__file__).resolve().parents[2] / 'deploy/grants.py'
    spec = importlib.util.spec_from_file_location('gold_probe_grants', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    user = "'gm_gold_probe'@'localhost'"
    sql = module.bootstrap_sql({'db_password': 'laboratory-only-password'}, '$argon2id$v=19$m=1,t=1,p=1$c2FsdA$aGFzaA')
    sql = sql.replace("'dnf_gm_app'@'127.0.0.1'", user)
    sql = sql[:sql.rfind('INSERT INTO dnf_gm.admins')]
    with db.connect() as c, c.cursor() as q:
        q.execute('DROP USER IF EXISTS ' + user)
        for statement in sql.split(';'):
            if statement.strip():
                q.execute(statement)
    try:
        c = pymysql.connect(unix_socket=os.environ['DNF_GM_M0_SOCKET'], user='gm_gold_probe',
                            password='laboratory-only-password', autocommit=False)
        try:
            with c.cursor() as q:
                q.execute("SET SESSION sql_mode='STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'")
                q.execute("INSERT INTO taiwan_cain_2nd.postal(occ_time,send_charac_name,receive_charac_no,item_id,add_info,endurance,gold,letter_id) VALUES(UTC_TIMESTAMP(),'GM-GOLD-LAB',900001,0,0,0,1000,0)")
                q.execute('SELECT gold FROM taiwan_cain_2nd.postal WHERE postal_id=%s', (q.lastrowid,))
                assert q.fetchone() == (1000,)
                with pytest.raises(pymysql.err.OperationalError) as error:
                    q.execute('UPDATE taiwan_cain_2nd.postal SET gold=2')
                assert error.value.args[0] in (1142,1143)
                with pytest.raises(pymysql.err.OperationalError):
                    q.execute('UPDATE taiwan_cain_2nd.inventory SET money=2')
                c.rollback()
        finally:
            c.close()
    finally:
        with db.connect() as c, c.cursor() as q:
            q.execute('DROP USER IF EXISTS ' + user)
