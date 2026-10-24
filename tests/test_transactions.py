from concurrent.futures import ThreadPoolExecutor
import uuid
import pytest
from dnfgm_m0.lab import Rejected, UnknownCommit, connect


def currency(**kw):
    return dict(action="currency", uid=900001, currency="cera", delta=100, **kw)


def value(lab, sql):
    c = connect(lab.socket)
    try:
        with c.cursor() as cur:
            cur.execute(sql)
            return cur.fetchone()[0]
    finally:
        c.close()


def test_duplicate_is_exactly_once(lab):
    req = currency()
    first = lab.perform("same", req)
    assert lab.perform("same", req) == first
    assert value(lab, "SELECT cera FROM taiwan_billing.cash_cera") == 1100
    assert value(lab, "SELECT COUNT(*) FROM dnf_gm.audit") == 1


def test_concurrent_duplicate(lab):
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: lab.perform("concurrent", currency()), range(12)))
    assert all(x == {"before": 1000, "after": 1100} for x in results)
    assert value(lab, "SELECT COUNT(*) FROM dnf_gm.audit") == 1


def test_concurrent_independent_credits(lab):
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: lab.perform(str(uuid.uuid4()), currency()), range(12)))
    assert value(lab, "SELECT cera FROM taiwan_billing.cash_cera") == 2200


def test_reusing_key_with_different_request(lab):
    lab.perform("key", currency())
    req = currency(); req["delta"] = 2
    with pytest.raises(Rejected, match="conflict"):
        lab.perform("key", req)


def test_rollback_before_commit(lab):
    with pytest.raises(RuntimeError):
        lab.perform("failure", currency(), fail_before_commit=True)
    assert lab.result("failure") is None
    assert value(lab, "SELECT cera FROM taiwan_billing.cash_cera") == 1000
    assert value(lab, "SELECT COUNT(*) FROM dnf_gm.audit") == 0


def test_lost_reply_query_existing_result(lab):
    with pytest.raises(UnknownCommit):
        lab.perform("replylost", currency(), lose_reply=True)
    assert lab.result("replylost")["result"]["after"] == 1100
    assert value(lab, "SELECT cera FROM taiwan_billing.cash_cera") == 1100


@pytest.mark.parametrize("delta", [-1001, 2**32, 0, True, "1"])
def test_bad_amounts(lab, delta):
    req = currency();req["delta"] = delta
    with pytest.raises(Rejected):
        lab.perform("badamount", req)
    assert lab.result("badamount") is None


def test_overflow(lab):
    req = currency();req["delta"] = 2**32 - 1
    with pytest.raises(Rejected):lab.perform("overflow", req)


def test_stale_preview(lab):
    with pytest.raises(Rejected, match="Stale"):
        lab.perform("stale", currency(expected_before=999))


def test_wrong_target(lab):
    req = currency();req["uid"] = 900002
    with pytest.raises(Rejected, match="synthetic"):
        lab.perform("wrong", req)


def test_sql_injection_rejected(lab):
    req = currency();req["currency"] = "cera; DROP DATABASE d_taiwan"
    with pytest.raises(Rejected):lab.perform("injection", req)


def test代币券_is_separate(lab):
    req=currency();req["currency"]="cera_point"
    lab.perform("points",req)
    assert value(lab,"SELECT cera_point FROM taiwan_billing.cash_cera_point") == 1100
    assert value(lab,"SELECT cera FROM taiwan_billing.cash_cera") == 1000


def mail(**kw):
    return dict(action="mail", uid=900001, charac_no=900001, items=[{"id":990001,"quantity":1},{"id":990002,"quantity":20}], **kw)


def test_mail_ids_duplicate_and_utf8(lab):
    req=mail();result=lab.perform("mail",req)
    assert len(result["postal_ids"]) == 2
    assert lab.perform("mail",req)==result
    assert value(lab,"SELECT COUNT(*) FROM taiwan_cain_2nd.postal") == 2
    assert value(lab,"SELECT charac_name FROM taiwan_cain.charac_info WHERE charac_no=900001") == "GM测试角色"


def test_partial_gift_rollback(lab):
    req=mail();req["items"].append({"id":123,"quantity":1})
    with pytest.raises(Rejected):lab.perform("partial",req)
    assert value(lab,"SELECT COUNT(*) FROM taiwan_cain_2nd.postal") == 0
    assert lab.result("partial") is None


@pytest.mark.parametrize("quantity", [0, 2, -1, True])
def test_equipment_quantity(lab,quantity):
    req=mail();req["items"]=[{"id":990001,"quantity":quantity}]
    with pytest.raises(Rejected):lab.perform("badqty",req)


def test_wrong_character_owner(lab):
    req=mail();req["charac_no"]=900002
    with pytest.raises(Rejected,match="owner"):lab.perform("owner",req)


def test_deleted_character(lab):
    c=connect(lab.socket)
    with c.cursor() as cur:cur.execute("UPDATE taiwan_cain.charac_info SET delete_flag=1 WHERE charac_no=900001")
    c.commit();c.close()
    with pytest.raises(Rejected):lab.perform("deleted",mail())


def test_attachment_count(lab):
    req=mail();req["items"]=[{"id":990002,"quantity":1}]*21
    with pytest.raises(Rejected):lab.perform("many",req)


def test_owned_ban_unban(lab):
    assert lab.perform("ban",dict(action="ban",uid=900001))["blocked"]
    assert not lab.perform("unban",dict(action="unban",uid=900001))["blocked"]


def test_do_not_overwrite_other_punishment(lab):
    c=connect(lab.socket)
    with c.cursor() as cur:
        cur.execute("INSERT INTO d_taiwan.member_punish_info(m_id,punish_type,admin_id) VALUES(900001,1,'other')")
    c.commit();c.close()
    with pytest.raises(Rejected,match="another"):lab.perform("external",dict(action="unban",uid=900001))


def test_lock_timeout_rolls_back_operation(lab):
    import pymysql
    c=connect(lab.socket)
    try:
        with c.cursor() as cur:
            cur.execute("SELECT cera FROM taiwan_billing.cash_cera WHERE account='900001' FOR UPDATE")
        with pytest.raises(pymysql.OperationalError) as error:
            lab.perform('locktimeout',currency())
        assert error.value.args[0] == 1205
    finally:
        c.rollback();c.close()
    assert lab.result('locktimeout') is None
    assert value(lab,'SELECT cera FROM taiwan_billing.cash_cera') == 1000


def test_audit_failure_rolls_back_balance(lab):
    import pymysql
    c=connect(lab.socket)
    with c.cursor() as cur:cur.execute('DROP TABLE dnf_gm.audit')
    c.close()
    with pytest.raises(pymysql.ProgrammingError):lab.perform('auditfailure',currency())
    assert lab.result('auditfailure') is None
    assert value(lab,'SELECT cera FROM taiwan_billing.cash_cera') == 1000
