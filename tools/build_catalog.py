"""Parse a LOCAL matching PVF into a read-only SQLite metadata index."""
import argparse,json
from dnfgm.pvf import build_index
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('pvf');p.add_argument('output');p.add_argument('--encoding',default='gbk',choices=['big5','gbk','utf-8']);p.add_argument('--review')
a=p.parse_args()
print(json.dumps(build_index(a.pvf,a.output,a.encoding,a.review),ensure_ascii=False,indent=2))
