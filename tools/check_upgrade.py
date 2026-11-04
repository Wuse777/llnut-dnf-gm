"""Export a private, read-only compatibility report; never installs a candidate."""
import argparse
import json
import os
from pathlib import Path
from dnfgm.config import load_settings
from dnfgm.db import Database
from dnfgm.upgrade_check import UpgradeCheck


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,help='New absolute private NDJSON file; existing files are never overwritten')
    args=parser.parse_args();path=Path(args.output)
    if not path.is_absolute():parser.error('Absolute output path required')
    settings=load_settings();checker=UpgradeCheck(settings,Database(settings));overview=checker.overview()
    if overview['state']!='ready':raise SystemExit('Candidate not configured; nothing exported')
    stream=checker.export(overview['fingerprint']);complete=False;count=0
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as output:
            for line in stream:
                output.write(line)
                result=json.loads(line)
                if result['type']=='complete':complete=True;count=result['count']
            output.flush();os.fsync(output.fileno())
    finally:stream.close()
    if not complete:raise SystemExit('Incomplete report retained; no compatibility or deployment approval')
    print(json.dumps({'complete':True,'references':count,'can_deploy':False}))


if __name__=='__main__':main()
