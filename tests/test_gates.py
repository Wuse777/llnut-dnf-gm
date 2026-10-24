from dnfgm_m0.gates import REQUIRED, evaluate

def test_database_success_does_not_pass_client_tests():
    r=evaluate({"checks":{"mysql57_transactions":{"status":"passed"}}})
    assert not r["m0_passed"] and "online_cera" in r["pending_or_failed"]

def test_every_m0_gate_required_and_public_still_closed():
    r=evaluate({"checks":{k:{"status":"passed"} for k in REQUIRED}})
    assert r["m0_passed"] and not r["public_release_allowed"]
