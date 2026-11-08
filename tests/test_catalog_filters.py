import json,sqlite3
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from dnfgm.catalog import Catalog
from dnfgm.config import Settings
from dnfgm.models import CatalogFilters


def catalog(tmp_path,details=True):
    p=tmp_path/'catalog.sqlite'
    with sqlite3.connect(p) as c:
        c.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE items(id INTEGER PRIMARY KEY,name TEXT,category TEXT,level INTEGER,stack_limit INTEGER,durability INTEGER,allowed INTEGER,reviewed INTEGER,source_path TEXT);')
        c.execute('INSERT INTO metadata VALUES(?,?)',('pvf_sha256','a'*64))
        c.execute('INSERT INTO metadata VALUES(?,?)',('equipment_attributes_version','2'))
        c.executemany('INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?)',[(i,'样本'+str(i),'equipment',i%100,1,30,1,0,'equipment/synthetic.equ') for i in range(1,121)])
        if details:
            c.executescript('CREATE TABLE equipment_details(item_id INTEGER PRIMARY KEY,part_code TEXT,rarity INTEGER);CREATE TABLE equipment_attributes(item_id INTEGER PRIMARY KEY,attributes_json TEXT);')
            c.executemany('INSERT INTO equipment_details VALUES(?,?,?)',[(i,'[weapon]' if i%2 else '[coat]',i%3) for i in range(1,121)])
            c.execute('INSERT INTO equipment_attributes VALUES(?,?)',(1,json.dumps([{'tag':'[physical attack]','label':'物理攻击','values':[20,30]}])))
    return Catalog(Settings(catalog_file=str(p),pvf_sha256='a'*64,status_file=str(tmp_path/'absent')))


def test_combined_filters_count_page_and_explicit_zero(tmp_path):
    c=catalog(tmp_path)
    result=c.search(part='[weapon]',rarity=0,min_level=10,max_level=80,sort='level_desc')
    expected=[i for i in range(1,121) if i%2 and i%3==0 and 10<=i%100<=80]
    assert result['total']==len(expected)
    assert [i['id'] for i in result['items']]==sorted(expected,key=lambda i:(-(i%100),i))
    assert all(i['rarity']==0 and i['part_name']=='武器' for i in result['items'])
    assert result['facets']['equipment_metadata'] is True
    assert c.search(page=2)['total']==120 and len(c.search(page=2)['items'])==50


def test_policy_rows_and_visible_search_have_identical_predicates(tmp_path):
    catalog_=catalog(tmp_path);filters={'q':'样本','part':'[coat]','rarity':2,'min_level':15,'max_level':60}
    with catalog_.connect() as c:
        selected=[r['id'] for r in catalog_.rows(c,filters,{})]
    assert selected==[r['id'] for r in catalog_.search(**filters)['items']]


def test_unknown_part_is_literal_and_attributes_display_without_inference(tmp_path):
    c=catalog(tmp_path)
    assert c.search(part="[weapon]' OR 1=1 --")['total']==0
    item=c.search(q='1')['items'][0]
    assert item['base_attributes'][0]['values']==[20,30]
    assert 'source_path' not in item and 'rarity_name' not in item


def test_old_indexes_keep_basic_search_but_refuse_silent_filter_omission(tmp_path):
    c=catalog(tmp_path,False)
    assert c.search(min_level=10)['total']>0
    assert c.search()['facets']['equipment_metadata'] is False
    with pytest.raises(HTTPException) as e:c.search(rarity=0)
    assert e.value.status_code==409


def test_bad_ranges_sort_and_policy_inputs_are_rejected(tmp_path):
    c=catalog(tmp_path)
    with pytest.raises(HTTPException):c.search(min_level=90,max_level=1)
    with pytest.raises(HTTPException):c.search(sort='id; DROP TABLE items')
    with pytest.raises(ValidationError):CatalogFilters(min_level=90,max_level=1)
    with pytest.raises(ValidationError):CatalogFilters(rarity=True)
