"""Offline-only: merge matching client default poses into a NEW private pack."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dnfgm.character_assets import build_character_assets


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pvf',type=Path,required=True)
    parser.add_argument('--npk-dir',type=Path,required=True)
    parser.add_argument('--source-pack',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--encoding',default='gbk')
    parser.add_argument('--outfits',type=Path,help='Optional JSON array of exact {job,items:[{slot,id}]} recipes')
    args=parser.parse_args()
    outfits=[]
    if args.outfits:
        if args.outfits.is_symlink() or args.outfits.stat().st_size>1024*1024:parser.error('outfits must be a regular JSON file <=1 MiB')
        outfits=json.loads(args.outfits.read_text(encoding='utf-8-sig'))
    print(json.dumps(build_character_assets(args.pvf,args.npk_dir,args.source_pack,args.output,args.encoding,outfits),ensure_ascii=False))


if __name__=='__main__':main()
