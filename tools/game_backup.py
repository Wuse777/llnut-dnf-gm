#!/usr/bin/env python3
"""Offline game restore-point verification on a socket-only MySQL5.7 lab.

There is deliberately no production restore or service-stop command. Use age
with the separately stored private identity to decrypt an offsite ciphertext
into a private new local file before invoking restore-check.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from dnfgm.game_backup import restore_game_drill, write_new


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    restore = commands.add_parser('restore-check')
    restore.add_argument('--artifact', required=True)
    restore.add_argument('--sha256', required=True)
    restore.add_argument('--lab-socket', required=True)
    restore.add_argument('--lab-datadir', required=True)
    restore.add_argument('--receipt', required=True)
    args = parser.parse_args()
    output = Path(args.receipt)
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError('New absolute private receipt required')
    receipt = restore_game_drill(args.artifact, args.sha256, socket=args.lab_socket, datadir=args.lab_datadir)
    write_new(output, receipt)
    print('Game restore-point definitions, stored values, row counts and relationships verified in the isolated lab.')


if __name__ == '__main__':
    try:main()
    except Exception:
        print('Game restore drill did not complete; no production restore was attempted.', file=sys.stderr)
        raise SystemExit(1) from None
