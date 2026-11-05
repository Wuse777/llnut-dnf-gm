"""Merge explicit local PNG portrait mappings, retaining all item-image records."""
import argparse
import json
from dnfgm.portrait_pack import enrich_portraits
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source');p.add_argument('mapping');p.add_argument('output')
    args=p.parse_args()
    print(json.dumps(enrich_portraits(args.source,args.mapping,args.output),ensure_ascii=False,indent=2))
