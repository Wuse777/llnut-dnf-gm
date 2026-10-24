from contextlib import contextmanager
from threading import BoundedSemaphore
import pymysql


class Busy(RuntimeError):
    pass


class Database:
    """No more than 3 concurrent connections, including audit/auth traffic."""
    def __init__(self, settings, factory=None):
        self.settings = settings
        self.slots = BoundedSemaphore(3)
        self.factory = factory

    @contextmanager
    def connect(self):
        if not self.slots.acquire(timeout=1):
            raise Busy('Database concurrency limit reached')
        c = None
        try:
            s = self.settings
            c = self.factory() if self.factory else pymysql.connect(
                host=s.db_host, port=s.db_port, user=s.db_user, password=s.db_password,
                charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor,
                autocommit=False, connect_timeout=3, read_timeout=4, write_timeout=4)
            with c.cursor() as q:
                q.execute("SET SESSION time_zone='+00:00'")
                # Legacy game mail uses the zero-date unclaimed sentinel. Keep strict
                # value checking, but allow that existing schema's default, session only.
                q.execute("SET SESSION sql_mode='STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'")
                q.execute('SET SESSION innodb_lock_wait_timeout=2')
                q.execute('SET SESSION max_execution_time=1500')
            c.rollback()
            yield c
        finally:
            if c:
                c.close()
            self.slots.release()
