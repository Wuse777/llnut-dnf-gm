"""Transaction compatibility proof against an isolated local MySQL 5.7 socket.

This module cannot connect to production: TCP configuration is intentionally absent.
"""
import hashlib
import json
from pathlib import Path
import pymysql

UINT32_MAX = 2**32 - 1

class Rejected(ValueError):
    pass

class UnknownCommit(RuntimeError):
    """Caller must query the operation ID, not blindly replay a write."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def connect(socket: str):
    p = Path(socket).resolve()
    if not p.is_socket():
        raise Rejected("Local MySQL socket missing")
    c = pymysql.connect(unix_socket=str(p), user="root", charset="utf8mb4", autocommit=False,
                        connect_timeout=3, read_timeout=5, write_timeout=5)
    with c.cursor() as cur:
        cur.execute("SELECT VERSION(), @@server_id")
        version, server_id = cur.fetchone()
        if not version.startswith("5.7.") or server_id != 57044:
            c.close()
            raise Rejected("Not the isolated M0 MySQL 5.7 server")
        cur.execute("SET SESSION innodb_lock_wait_timeout=2")
        cur.execute("SET SESSION sql_mode='NO_ENGINE_SUBSTITUTION'")
    c.rollback()
    return c


class Laboratory:
    def __init__(self, socket: str):
        self.socket = socket

    def result(self, operation_id):
        c = connect(self.socket)
        try:
            with c.cursor() as cur:
                cur.execute("SELECT fingerprint,result FROM dnf_gm.operations WHERE operation_id=%s", (operation_id,))
                row = cur.fetchone()
                return {"fingerprint": row[0], "result": json.loads(row[1])} if row else None
        finally:
            c.close()

    def perform(self, operation_id, request, *, fail_before_commit=False, lose_reply=False):
        if not operation_id or len(operation_id) > 64:
            raise Rejected("Invalid operation ID")
        fingerprint = hashlib.sha256(canonical(request).encode()).hexdigest()
        c = connect(self.socket)
        commit_attempted = False
        try:
            c.begin()
            with c.cursor() as cur:
                # Reservation and business changes commit together. A duplicate INSERT waits
                # for a concurrent transaction; after rollback only the result is queried.
                cur.execute("INSERT INTO dnf_gm.operations(operation_id,fingerprint,result) VALUES(%s,%s,'{}')",
                            (operation_id, fingerprint))
                uid = request.get("uid")
                if type(uid) is not int or uid != 900001:
                    raise Rejected("Not the synthetic M0 account")
                cur.execute("SELECT accountname FROM d_taiwan.accounts WHERE UID=%s", (uid,))
                if cur.fetchone() != ("gm_m0_fixture",):
                    raise Rejected("Account identity mismatch")
                action = request.get("action")
                if action == "currency":
                    result = self._currency(cur, uid, request)
                elif action == "mail":
                    result = self._mail(cur, uid, request)
                elif action in ("ban", "unban"):
                    result = self._ban(cur, uid, request)
                else:
                    raise Rejected("Unsupported action")
                cur.execute("UPDATE dnf_gm.operations SET result=%s WHERE operation_id=%s", (canonical(result), operation_id))
                cur.execute("INSERT INTO dnf_gm.audit(operation_id,request_json,result_json) VALUES(%s,%s,%s)",
                            (operation_id, canonical(request), canonical(result)))
                if fail_before_commit:
                    raise RuntimeError("injected pre-commit failure")
            commit_attempted = True
            c.commit()
            if lose_reply:
                raise UnknownCommit("Injected response loss; query original operation ID")
            return result
        except pymysql.IntegrityError as e:
            c.rollback()
            if e.args[0] != 1062:
                raise
            saved = self.result(operation_id)
            if not saved or saved["fingerprint"] != fingerprint:
                raise Rejected("Idempotency key conflict") from None
            return saved["result"]
        except Exception as e:
            if commit_attempted:
                if isinstance(e, UnknownCommit):
                    raise
                raise UnknownCommit("Commit outcome unknown; query original operation ID") from None
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def _currency(cur, uid, request):
        choices = {"cera": ("cash_cera", "cera"), "cera_point": ("cash_cera_point", "cera_point")}
        if request.get("currency") not in choices:
            raise Rejected("Unknown currency")
        table, column = choices[request["currency"]]
        delta = request.get("delta")
        if type(delta) is not int or not delta or abs(delta) > UINT32_MAX:
            raise Rejected("Invalid amount")
        # Identifiers originate exclusively in the constant mapping, not user input.
        cur.execute(f"SELECT {column} FROM taiwan_billing.{table} WHERE account=%s FOR UPDATE", (str(uid),))
        row = cur.fetchone()
        if row is None:
            raise Rejected("Missing balance; do not silently create a billing account")
        before = row[0]
        if "expected_before" in request and request["expected_before"] != before:
            raise Rejected("Stale preview")
        after = before + delta
        if not 0 <= after <= UINT32_MAX:
            raise Rejected("Balance out of range")
        cur.execute(f"UPDATE taiwan_billing.{table} SET {column}=%s,mod_date=NOW() WHERE account=%s AND {column}=%s",
                    (after, str(uid), before))
        if cur.rowcount != 1:
            raise Rejected("Balance changed concurrently")
        return {"before": before, "after": after}

    @staticmethod
    def _mail(cur, uid, request):
        charac_no = request.get("charac_no")
        cur.execute("SELECT m_id,delete_flag FROM taiwan_cain.charac_info WHERE charac_no=%s FOR UPDATE", (charac_no,))
        if cur.fetchone() != (uid, 0):
            raise Rejected("Wrong owner or deleted character")
        items = request.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 20:
            raise Rejected("Expected 1--20 attachments")
        ids = []
        for item in items:
            # Synthetic IDs are NOT real-game safe IDs. Real PVF validation is a separate gate.
            allowed = {990001: (1, 0), 990002: (99, 0)}
            item_id, quantity = item.get("id"), item.get("quantity")
            if type(item_id) is not int or item_id not in allowed or type(quantity) is not int or not 1 <= quantity <= allowed[item_id][0]:
                raise Rejected("Unsupported synthetic item or quantity")
            cur.execute("INSERT INTO taiwan_cain_2nd.postal(occ_time,send_charac_name,receive_charac_no,item_id,add_info) "
                        "VALUES(NOW(),'GM-M0',%s,%s,%s)", (charac_no, item_id, quantity))
            ids.append(cur.lastrowid)
        return {"postal_ids": ids, "state": "inserted_not_client_verified"}

    @staticmethod
    def _ban(cur, uid, request):
        # Laboratory semantics only. Production gateway compatibility is separately verified.
        cur.execute("SELECT apply_flag,admin_id FROM d_taiwan.member_punish_info WHERE m_id=%s AND punish_type=1 FOR UPDATE", (uid,))
        row = cur.fetchone()
        if row and row[1] != "GM-M0":
            raise Rejected("Refusing to overwrite another punishment")
        enabled = request["action"] == "ban"
        if row:
            cur.execute("UPDATE d_taiwan.member_punish_info SET apply_flag=%s WHERE m_id=%s AND punish_type=1 AND admin_id='GM-M0'", (int(enabled), uid))
        elif enabled:
            cur.execute("INSERT INTO d_taiwan.member_punish_info(m_id,punish_type,apply_flag,start_time,end_time,admin_id,reason) "
                        "VALUES(%s,1,1,NOW(),'2099-01-01','GM-M0','compatibility test')", (uid,))
        else:
            raise Rejected("No owned ban to remove")
        return {"blocked": enabled, "client_verified": False}
