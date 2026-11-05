"""Build matching learned-skill/default-skill metadata in a NEW local catalog."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from dnfgm.pvf import Reader
from dnfgm.skill_rules import RULE_VERSION,PROGRAM_SHA,profiles,native_group


def enrich(source,pvf,output):
    source,pvf,output=map(Path,(source,pvf,output))
    if output.exists():raise FileExistsError('Refusing to overwrite a catalog')
    with pvf.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as c:
        meta=dict(c.execute('SELECT key,value FROM metadata'))
        if meta.get('pvf_sha256')!=sha:raise ValueError('PVF/catalog mismatch')
    reader=Reader(pvf,meta.get('encoding','gbk'));rows=[]
    try:
        jobs=dict(reader.mapping('character/character.lst'))
        for job,path in reader.mapping('skill/skilllist.lst'):
            definitions={}
            for sid,skill_path in reader.mapping(('skill/'+path).lower()):
                if type(sid) is not int or not 1<=sid<=255 or str(sid) in definitions:raise ValueError('Invalid/duplicate skill ID')
                f=reader.fields(('skill/'+skill_path).lower())
                group=f.get('[skill class]',[None]);typ=f.get('[type]',[]);name=f.get('[name]',[])
                definitions[str(sid)]={'name':name[0] if name and isinstance(name[0],str) else '',
                    'group':native_group(group[0] if len(group)==1 else None,bool(f.get('[feature skill type]',[0])[0]),len(f.get('[skill fitness growtype]',[]))),
                    'active':True if typ==['[active]'] else False if typ==['[passive]'] else None}
            default=profiles(reader.tokens(('character/'+jobs[job]).lower()))
            rows.append((job,json.dumps({'job':job,'definitions':definitions,'defaults':default},ensure_ascii=False,sort_keys=True,separators=(',',':'))))
        experts={}
        for kind,path in reader.mapping('character/expertjob.lst'):
            f=reader.fields(('character/'+path).lower());skills=f.get('[skill]',[]);exps=f.get('[expertness exp]',[])
            if len(skills)%2 or len(exps)%3:raise ValueError('Unsupported expert skill/experience script')
            experts[str(kind)]={'skills':list(zip(skills[::2],skills[1::2])),'thresholds':exps[::3]}
        limits=reader.fields('character/expertjob.etc').get('[expertjob level limit]',[])
        if len(limits)%2:raise ValueError('Unsupported expert level limits')
        expert_rules={'experts':experts,'level_limits':dict(zip(limits[::2],limits[1::2]))}
    finally:reader.close()
    if len(rows)!=len(jobs):raise ValueError('Missing job skill list')
    created=False
    try:
        with output.open('xb') as target,source.open('rb') as origin:
            created=True;shutil.copyfileobj(origin,target)
        with sqlite3.connect(output) as c:
            c.execute('DROP TABLE IF EXISTS skill_rules')
            c.execute('CREATE TABLE skill_rules(job INTEGER PRIMARY KEY,payload_json TEXT NOT NULL)')
            c.executemany('INSERT INTO skill_rules VALUES(?,?)',rows)
            c.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)',[
                ('skill_rules_version',RULE_VERSION),('skill_rules_program_sha256',PROGRAM_SHA),
                ('skill_expert_rules',json.dumps(expert_rules,sort_keys=True,separators=(',',':')))])
        return {'pvf_sha256':sha,'jobs':len(rows),'skills':sum(len(json.loads(payload)['definitions']) for _,payload in rows),
            'experts':len(experts),'item_permissions_changed':False}
    except Exception:
        if created:output.unlink(missing_ok=True)
        raise

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','pvf','output'):p.add_argument(name)
    a=p.parse_args();print(json.dumps(enrich(a.source,a.pvf,a.output),ensure_ascii=False))
