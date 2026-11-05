"""MySQL-side fence for transactions surviving loss of their app connection.

The application holds a shared InnoDB record lock until its transaction ends.
Only the root coordinator uses the exclusive read, with persistent filesystem
admission frozen. An OS file lock alone cannot prove that a remote COMMIT ended.
This module never changes gameplay data or replays an operation.
"""
from .release_files import Refused

PROTOCOL = 1


def check_table(q):
    q.execute("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME='gameplay_fence'")
    table = q.fetchone()
    if not table or table['ENGINE'] != 'InnoDB':
        raise Refused('maintenance_transaction_fence_schema_unproven')


def check_protocol(row):
    if not row or row != {'id': 1, 'protocol_version': PROTOCOL}:
        raise Refused('maintenance_transaction_fence_protocol_unproven')
    return PROTOCOL


def inspect_protocol(q):
    """Health read only: does not contend with the exclusive maintenance lock."""
    check_table(q)
    q.execute('SELECT id,protocol_version FROM dnf_gm.gameplay_fence WHERE id=1')
    return check_protocol(q.fetchone())


def lock_transactions(q, *, exclusive=False):
    check_table(q)
    # Actual locking/current read, not a consistent MVCC snapshot. The single
    # row is never replaced or used as a counter by application credentials.
    q.execute('SELECT id,protocol_version FROM dnf_gm.gameplay_fence WHERE id=1 ' +
              ('FOR UPDATE' if exclusive else 'LOCK IN SHARE MODE'))
    return check_protocol(q.fetchone())
