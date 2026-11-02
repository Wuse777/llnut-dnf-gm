"""Copy an existing PVF-bound index and add creature mail type metadata."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from dnfgm.pvf import Reader


def enrich(pvf, catalog, output, encoding='gbk'):
    pvf, catalog, output = Path(pvf), Path(catalog), Path(output)
    with pvf.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    with sqlite3.connect(catalog.resolve().as_uri()+'?mode=ro', uri=True) as c:
        if dict(c.execute('SELECT key,value FROM metadata')).get('pvf_sha256') != sha:
            raise ValueError('PVF fingerprint does not match the index')
        rows = c.execute("SELECT id,source_path FROM items WHERE source_path LIKE 'equipment/%' AND (instr(lower(source_path),'creature')>0 OR instr(lower(source_path),'pet/')>0)").fetchall()
    reader = Reader(pvf, encoding)
    try:
        types = {}
        for item_id, path in rows:
            subtype = next((v for v in reader.fields(path).get('[sub type]', []) if type(v) is int), 0)
            types[str(item_id)] = 0 if subtype == 1 else 1
    finally:
        reader.close()
    # Never overwrite an installed catalogue. The operator swaps a verified
    # copy while GM is stopped, keeping the original for rollback.
    with output.open('xb') as target, catalog.open('rb') as source:
        shutil.copyfileobj(source, target)
    with sqlite3.connect(output) as c:
        c.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', ('creature_types',json.dumps(types)))
    return len(types)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pvf')
    parser.add_argument('catalog')
    parser.add_argument('output')
    parser.add_argument('--encoding', default='gbk')
    args = parser.parse_args()
    print('Creature mail profiles:', enrich(args.pvf, args.catalog, args.output, args.encoding))


if __name__ == '__main__':
    main()
