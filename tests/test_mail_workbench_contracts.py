"""Bounded SQL and display-only catalog contracts without a game database."""
from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace
import sqlite3

import pytest
from fastapi import HTTPException
from pymysql.err import OperationalError

from dnfgm.catalog import Catalog
from dnfgm.mail_center import MailCenter, search_read


class MailDatabase:
    def __init__(self, count=50, sample=None):
        self.count = count
        self.sample = sample or []
        self.statements = []

    @contextmanager
    def connect(self):
        yield self

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, args=()):
        self.statements.append((sql,args))
        self.rows = [dict(operation_id=f'{i:032x}',postal_count=999,recorded_count=998)
                     for i in range(self.count)] if 'FROM dnf_gm.mail_batches b' in sql else self.sample

    def fetchall(self):
        return self.rows


def test_summary_has_a_fixed_per_batch_read_budget_and_parameterized_filters():
    db = MailDatabase()
    result = MailCenter(db).list(uid=9,item_id=7,template_id=3,text="x' OR 1=1 --",receipt='claimed_marker',
        created_from=date(2026,11,9),created_to=date(2026,11,9))
    listed, summary = db.statements
    assert "x' OR 1=1 --" not in listed[0] and "%x' OR 1=1 --%" in listed[1]
    assert datetime(2026,11,8,16) in listed[1] and datetime(2026,11,9,16) in listed[1]
    assert 'LIMIT 51 OFFSET %s' in listed[0] and 'LIMIT 1 OFFSET 199' in listed[0]
    assert summary[0].count('LIMIT 201') == len(summary[1]) == 50
    assert len(result['items']) == 50 and result['items'][0]['receipt_summary']['unrecorded'] == 1
    assert result['items'][0]['receipt_summary']['checked_attachments'] == 0


def test_extra_sample_row_proves_more_without_inflating_receipts_or_unrecorded():
    sample = [dict(operation_id='0'*32,ordinal=201-i,live_postal_id=i+1,
                   receive_time='0000-00-00 00:00:00' if i<200 else '2026-11-09 00:00:00',delete_flag=0)
              for i in range(201)]
    result = MailCenter(MailDatabase(count=1,sample=sample)).list()
    summary = result['items'][0]['receipt_summary']
    assert summary['checked_attachments'] == summary['unclaimed_marker'] == 200 and summary['has_more']
    assert summary['claimed_marker'] == 0 and summary['unrecorded'] == 1


@pytest.mark.parametrize('code',[3024,2013,2006])
def test_interrupted_mail_search_reports_unknown_instead_of_empty_success(code):
    class Cursor:
        def execute(self,*args):raise OperationalError(code,'private database failure')
    with pytest.raises(HTTPException) as error:
        search_read(Cursor(),'SELECT 1')
    assert error.value.status_code == 503 and '结果未知' in error.value.detail
    assert 'private' not in error.value.detail


def test_catalog_labels_read_in_chunks_and_cannot_activate_delivery_policy(tmp_path):
    path = tmp_path/'catalog.sqlite'
    with sqlite3.connect(path) as c:
        c.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);'
            'CREATE TABLE items(id INTEGER PRIMARY KEY,name TEXT,level INTEGER,category TEXT,durability INTEGER,allowed INTEGER);')
        c.execute('INSERT INTO metadata VALUES(\'pvf_sha256\',?)',('a'*64,))
        c.executemany('INSERT INTO items VALUES(?,?,1,\'special\',0,0)',[(i,'未批准展示物品 '+str(i)) for i in range(1,1002)])
    settings=SimpleNamespace(catalog_file=str(path),pvf_sha256='a'*64,status_file=str(tmp_path/'missing-status'))
    catalog=Catalog(settings)
    labels=catalog.read_labels([*range(1,1002),0,-1,True,'7',4294967296])
    assert labels['state'] == 'ok' and len(labels['items']) == 1001
    assert labels['items'][1001]['name'] == '未批准展示物品 1001'
    with sqlite3.connect(path) as c:
        assert c.execute('SELECT SUM(allowed) FROM items').fetchone()[0] == 0
    with catalog.connect() as c:
        with pytest.raises(sqlite3.OperationalError): c.execute('UPDATE items SET allowed=1')
    settings.pvf_sha256='b'*64
    assert catalog.read_labels([1]) == {'state':'mismatch','items':{},'jobs':{}}
