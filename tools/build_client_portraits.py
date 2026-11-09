"""Compile verified local client profession artwork into a NEW private asset pack."""
import argparse
import json
from dnfgm.client_portraits import compile_portraits

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source');p.add_argument('pvf');p.add_argument('npk_dir')
    p.add_argument('mapping');p.add_argument('output')
    a=p.parse_args()
    print(json.dumps(compile_portraits(a.source,a.pvf,a.npk_dir,a.mapping,a.output),ensure_ascii=False,indent=2))
