"""Bound source/deployment/documentation records; no live Git or network access."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

REVISION=re.compile(r"^[a-f0-9]{7,40}(?:-dirty)?$")
RELEASE=re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$")
SHA=re.compile(r"^[a-f0-9]{64}$")


def build_record(root,revision,release_id,*,now=None):
    root=Path(root)
    if not REVISION.fullmatch(revision) or not RELEASE.fullmatch(release_id):
        raise ValueError("Invalid source revision or release identifier")
    documents=[]
    for name in ("README.md","CHANGELOG.md","SECURITY.md","CONTRIBUTING.md","THIRD_PARTY.md"):
        p=root/name
        if p.exists():documents.append(p)
    docs=root/"docs"
    if docs.is_symlink():raise ValueError("Documentation symlinks are not permitted")
    if docs.exists():
        for p in docs.rglob("*"):
            if p.is_symlink():raise ValueError("Documentation symlinks are not permitted")
            if p.is_file() and p.suffix==".md":documents.append(p)
    if not (root/"README.md").is_file() or not 1<=len(documents)<=4096:
        raise ValueError("Missing or excessive documentation")
    manifest=[];total=0
    for p in sorted(documents,key=lambda p:p.relative_to(root).as_posix()):
        if p.is_symlink():raise ValueError("Documentation symlinks are not permitted")
        with p.open("rb") as f:content=f.read(1024*1024+1)
        total+=len(content)
        if len(content)>1024*1024 or total>32*1024*1024:raise ValueError("Documentation exceeds build budget")
        manifest.append({"file":p.relative_to(root).as_posix(),"size":len(content),"sha256":hashlib.sha256(content).hexdigest()})
    checksum=hashlib.sha256(json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    built_at=time.time() if now is None else now
    if type(built_at) not in (int,float) or not math.isfinite(built_at) or built_at<=0:raise ValueError("Invalid build time")
    return {"format":1,"source_revision":revision,"release_id":release_id,"built_at":built_at,
            "documentation":{"source_revision":revision,"manifest_sha256":checksum,"file_count":len(manifest)}}


def write_record(root,record):
    root=Path(root);target=root/"RELEASE_RECORD.json";temporary=root/".release-record.tmp"
    created=False
    try:
        with temporary.open("x",encoding="utf-8") as f:
            created=True
            json.dump(record,f,ensure_ascii=False,indent=2);f.write("\n");f.flush();os.fsync(f.fileno())
        os.chmod(temporary,0o644);os.replace(temporary,target)
    finally:
        # Never delete a preexisting temporary path belonging to another build.
        if created:temporary.unlink(missing_ok=True)
    return target


def read_record(root,revision):
    unknown={"release":{"state":"unknown","id":None,"built_at":None},
             "documentation":{"state":"unknown","source_revision":None,"manifest_sha256":None,"file_count":None}}
    try:
        p=Path(root)/"RELEASE_RECORD.json"
        if p.is_symlink():return unknown
        with p.open("rb") as f:raw=f.read(8193)
        if len(raw)>8192:return unknown
        r=json.loads(raw)
        if not isinstance(r,dict) or type(r.get("format")) is not int or r["format"]!=1:return unknown
        if not revision or r.get("source_revision")!=revision:
            return {key:{**value,"state":"mismatch"} for key,value in unknown.items()}
        release=r.get("release_id");built_at=r.get("built_at")
        if not isinstance(release,str) or not RELEASE.fullmatch(release):return unknown
        if type(built_at) not in (int,float) or not math.isfinite(built_at) or built_at<=0:return unknown
        output={**unknown,"release":{"state":"recorded","id":release,"built_at":built_at}}
        d=r.get("documentation")
        if not isinstance(d,dict):return output
        if d.get("source_revision")!=revision:
            output["documentation"]={**unknown["documentation"],"state":"mismatch"};return output
        digest=d.get("manifest_sha256");count=d.get("file_count")
        if not isinstance(digest,str) or not SHA.fullmatch(digest) or type(count) is not int or not 1<=count<=4096:return output
        output["documentation"]={"state":"recorded","source_revision":revision,"manifest_sha256":digest,"file_count":count}
        return output
    except (OSError,ValueError,TypeError,OverflowError):return unknown
