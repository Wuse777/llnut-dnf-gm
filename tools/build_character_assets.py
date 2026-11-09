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
    parser.add_argument('--animations',action='store_true',help='Append private v2 component atlases and exact ANI timelines')
    parser.add_argument('--avatar-items',type=Path,help='Optional JSON array of exact avatar or weapon item IDs for the v2 library')
    args=parser.parse_args()
    outfits=[]
    if args.outfits:
        if args.outfits.is_symlink() or args.outfits.stat().st_size>1024*1024:parser.error('outfits must be a regular JSON file <=1 MiB')
        outfits=json.loads(args.outfits.read_text(encoding='utf-8-sig'))
    result=build_character_assets(args.pvf,args.npk_dir,args.source_pack,args.output,args.encoding,outfits,
                                 preserve_appearance=not args.animations)
    if args.animations:
        from dnfgm.appearance_assets import enrich_appearance_assets
        items=sorted({item['id'] for outfit in outfits for item in outfit['items']})
        if args.avatar_items:
            if args.avatar_items.is_symlink() or args.avatar_items.stat().st_size>1024*1024:parser.error('avatar-items must be a regular JSON file <=1 MiB')
            items=json.loads(args.avatar_items.read_text(encoding='utf-8-sig'))
        result['appearance']=enrich_appearance_assets(args.pvf,args.npk_dir,args.output,items,args.encoding)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
