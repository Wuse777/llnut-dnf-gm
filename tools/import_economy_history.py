"""Import a bounded page of existing GM reward reporting history; no game writes or resend."""
import argparse
import json
from dnfgm.config import load_settings
from dnfgm.db import Database
from dnfgm.economy import Economy


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--after-id',type=int,default=0)
    parser.add_argument('--limit',type=int,default=50)
    args=parser.parse_args()
    if args.after_id<0 or not 1<=args.limit<=100:
        parser.error('after-id >= 0 and limit 1..100 required')
    print(json.dumps(Economy(Database(load_settings())).import_history(args.after_id,args.limit)))


if __name__=='__main__':
    main()
