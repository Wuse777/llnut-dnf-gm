"""Build a NEW private PNG/SQLite pack from matching local PVF + client NPK files.

No runtime uploads, no material bundled with source. Without --npk-dir this
indexes references and reports missing artwork; it does NOT invent icons.
"""
import argparse
import json
from dnfgm.asset_builder import build_assets
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pvf');parser.add_argument('catalog');parser.add_argument('output')
    parser.add_argument('--npk-dir');parser.add_argument('--portraits',help='Private JSON mappings to authorized local RGB/RGBA PNGs')
    args=parser.parse_args()
    print(json.dumps(build_assets(args.pvf,args.catalog,args.output,args.npk_dir,args.portraits),ensure_ascii=False,indent=2))
