#!/usr/bin/env python3
"""Run on a prepared release, before generating SHA256SUMS."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from dnfgm.release_record import build_record,write_record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--release-id")
    args=parser.parse_args();root=args.root.resolve()
    revision=args.revision or (root/"SOURCE_REVISION").read_text().strip()
    record=build_record(root,revision,args.release_id or root.name)
    write_record(root,record)
    print("Source, deployment and documentation build record written; no network or database access.")

if __name__=="__main__":main()
