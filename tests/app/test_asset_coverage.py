"""Read-only authenticated coverage on a small synthetic matching catalog."""
import json
import sqlite3
from fastapi.testclient import TestClient
from test_application import P
from test_assets import install
from dnfgm.portrait_pack import enrich_portraits


def test_coverage_auth_filter_attribution_and_no_private_paths(env,tmp_path):
    client,settings,_,_=env;url,png=install(settings,tmp_path)
    source=settings.assets_dir
    with sqlite3.connect(source+'/manifest.sqlite') as c:
        c.execute("INSERT INTO metadata VALUES('counts','{\"ready\":1,\"missing\":1}')")
        c.execute("INSERT INTO item_images(item_id,state) VALUES(990002,'missing')")
    (tmp_path/'synthetic.png').write_bytes(png);mapping=tmp_path/'mapping.json'
    mapping.write_text(json.dumps([{'job':0,'png':'synthetic.png','label':'合成示意','kind':'official_promotional','page':'https://dnf.qq.com/'}]))
    target=tmp_path/'new';enrich_portraits(source,mapping,target);settings.assets_dir=str(target)
    with TestClient(client.app) as anonymous:assert anonymous.get(P+'/assets/coverage').status_code==401
    response=client.get(P+'/assets/coverage?state=missing&page=1');assert response.status_code==200,response.text
    result=response.json();assert [r['id'] for r in result['items']]==[990002] and not result['has_more']
    assert result['portraits'][0]['image']['source_kind']=='official_promotional' and not result['client_verified']
    assert str(tmp_path) not in response.text and 'source_img' not in response.text
    assert client.get(P+'/assets/coverage?state=unknown').status_code==422
    assert client.get(P+'/assets/coverage?page=0').status_code==422
    assert client.get(url).status_code==200
