"""Offline maintenance helper: hidden password input, hash-only output."""
from getpass import getpass
from dnfgm.security import PASSWORDS
password=getpass('New GM administrator password (>=20 characters): ')
if len(password)<20 or password!=getpass('Repeat password: '):raise SystemExit('Password too short or mismatch')
print(PASSWORDS.hash(password))
