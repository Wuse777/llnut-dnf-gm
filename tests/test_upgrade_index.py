"""SQLite input bounds and readonly checks. No MySQL fixtures or production data."""
import sqlite3
import pytest
from fastapi import HTTPException
from dnfgm.upgrade_check import index


def catalog(path, metadata=None):
    with sqlite3.connect(path) as c:
        c.executescript('CREATE TABLE metadata(key TEXT,value TEXT); CREATE TABLE items(id INTEGER PRIMARY KEY,name TEXT,category TEXT,level INTEGER,stack_limit INTEGER,durability INTEGER,source_path TEXT);')
        c.executemany('INSERT INTO metadata VALUES(?,?)',metadata or [('pvf_sha256','a'*64)])


def test_index_is_query_only_and_does_not_allow_mutations(tmp_path):
    path=tmp_path/'index.sqlite';catalog(path)
    with pytest.raises(HTTPException) as error:
        with index(str(path)) as opened:
            assert opened['db'].execute('PRAGMA query_only').fetchone()[0]==1
            opened['db'].execute("INSERT INTO items VALUES(1,'x','x',0,0,0,'x')")
    assert error.value.status_code==503
    with sqlite3.connect(path) as c:assert c.execute('SELECT COUNT(*) FROM items').fetchone()[0]==0


@pytest.mark.parametrize('metadata',[[('pvf_sha256','a'*64),('pvf_sha256','a'*64)],[('pvf_sha256','x'*10000)],[('pvf_sha256','invalid')]])
def test_malformed_metadata_does_not_create_a_usable_target(tmp_path,metadata):
    path=tmp_path/'index.sqlite';catalog(path,metadata)
    with pytest.raises(HTTPException):
        with index(str(path)):pass


def test_leaf_symlink_and_invalid_file_are_rejected(tmp_path):
    path=tmp_path/'index.sqlite';catalog(path);link=tmp_path/'link.sqlite';link.symlink_to(path)
    for target in (link,tmp_path/'missing.sqlite'):
        with pytest.raises(HTTPException):
            with index(str(target)):pass
    assert not (tmp_path/'missing.sqlite').exists()


def test_readonly_statement_budget_bounds_expensive_views(tmp_path):
    path=tmp_path/'index.sqlite';catalog(path)
    with pytest.raises(HTTPException) as error:
        with index(str(path)) as opened:
            opened['db'].execute('WITH RECURSIVE sequence(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM sequence WHERE n<1000000000) SELECT SUM(n) FROM sequence').fetchone()
    assert error.value.status_code==503
