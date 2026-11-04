"""Protected images + display-only fingerprints, isolated synthetic MySQL."""
import sqlite3
from pathlib import Path
import hashlib
from fastapi.testclient import TestClient
from dnfgm.asset_builder import SCHEMA
from dnfgm.npk_assets import Raster
from test_application import P,mail,confirm


def install(settings,tmp_path):
    root=tmp_path/'art';root.mkdir();(root/'images').mkdir()
    data=Raster(1,1,b'\xff\0\0\xff').png();digest=hashlib.sha256(data).hexdigest()
    (root/'images'/(digest+'.png')).write_bytes(data)
    with sqlite3.connect(root/'manifest.sqlite') as c:
        c.executescript(SCHEMA)
        c.executemany('INSERT INTO metadata VALUES(?,?)',{'format':'dnfgm-assets-v1','state':'ready','pvf_sha256':settings.pvf_sha256}.items())
        c.execute('INSERT INTO files VALUES(?,?,?)',(digest,1,1))
        c.execute("INSERT INTO item_images(item_id,sha256,state) VALUES(?,?,'ready')",(990001,digest))
    settings.assets_dir=str(root)
    return P+'/assets/'+settings.pvf_sha256+'/'+digest+'.png',data


def test_images_require_session_and_no_source_paths(env,tmp_path):
    client,settings,_,app=env;url,data=install(settings,tmp_path)
    anonymous=TestClient(app)
    assert anonymous.get(url).status_code==401
    assert anonymous.get(P+'/assets/status').status_code==401
    response=client.get(url);assert response.status_code==200 and response.content==data
    assert response.headers['content-type']=='image/png' and response.headers['cache-control']=='no-store'
    assert response.headers['x-content-type-options']=='nosniff'
    status=client.get(P+'/assets/status');assert status.status_code==200
    assert settings.assets_dir not in status.text
    assert client.get(url.replace('a'*64,'b'*64)).status_code==404
    anonymous.close()


def test_installing_art_does_not_invalidate_mail_preview(env,tmp_path):
    client,settings,_,_=env
    before=mail(client,items=[{'id':990001,'quantity':2}]);assert before.status_code==200,before.text
    install(settings,tmp_path)
    result=client.get(P+'/catalog?q=990001');assert result.status_code==200
    assert result.json()['items'][0]['image']['state']=='ready'
    assert 'image' not in before.json()['preview']['rewards']['items'][0]
    done=confirm(client,before.json()['operation_id']);assert done.status_code==200,done.text


def test_broken_pack_does_not_break_queries_or_writes(env,tmp_path):
    client,settings,_,_=env;install(settings,tmp_path)
    Path(settings.assets_dir,'manifest.sqlite').write_bytes(b'broken')
    result=client.get(P+'/catalog?q=990001');assert result.status_code==200
    assert result.json()['items'][0]['image']['state']=='unavailable'
    role=client.get(P+'/characters/900001');assert role.status_code==200,role.text
    assert role.json()['assets']['state']=='unavailable'
    preview=mail(client,items=[{'id':990001,'quantity':1}]);assert preview.status_code==200
    assert confirm(client,preview.json()['operation_id']).status_code==200


def test_character_art_not_shown_with_mismatched_catalog(env,tmp_path):
    client,settings,_,_=env;install(settings,tmp_path)
    with sqlite3.connect(settings.catalog_file) as c:
        c.execute("UPDATE metadata SET value=? WHERE key='pvf_sha256'",('b'*64,))
    r=client.get(P+'/characters/900001');assert r.status_code==200,r.text
    assert r.json()['catalog_state']=='mismatch'
    assert r.json()['portrait']['state']=='mismatch'
    assert r.json()['assets']['state']=='mismatch'
