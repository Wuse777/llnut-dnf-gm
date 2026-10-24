import os
from pathlib import Path
import pytest
from dnfgm_m0.lab import connect, Laboratory

@pytest.fixture
def lab():
    socket = os.environ.get("DNF_GM_M0_SOCKET")
    if not socket:
        pytest.skip("Set DNF_GM_M0_SOCKET to isolated MySQL 5.7 server_id=57044")
    c = connect(socket)
    root = Path(__file__).resolve().parents[1]
    with c.cursor() as cur:
        for db in ("dnf_gm", "d_taiwan", "taiwan_cain", "taiwan_cain_2nd", "taiwan_billing", "taiwan_login"):
            cur.execute(f"DROP DATABASE IF EXISTS {db}")
        for filename in ("game-schema.sql", "management.sql"):
            text = "\n".join(line for line in (root / "fixtures" / filename).read_text().splitlines() if not line.lstrip().startswith("--"))
            for statement in text.split(";"):
                if statement.strip():
                    cur.execute(statement)
        cur.execute("INSERT INTO d_taiwan.accounts VALUES (900001,'gm_m0_fixture'),(900002,'not_a_test_target')")
        cur.execute("INSERT INTO taiwan_billing.cash_cera VALUES ('900001',1000,0,NOW(),NOW())")
        cur.execute("INSERT INTO taiwan_billing.cash_cera_point VALUES ('900001',1000,NOW(),NOW())")
        cur.execute("INSERT INTO taiwan_cain.charac_info(m_id,charac_no,charac_name,element_resist,spec_property,VIP) VALUES(900001,900001,'GM测试角色','','','0'),(900002,900002,'其他角色','','','0')")
    c.commit()
    c.close()
    return Laboratory(socket)
