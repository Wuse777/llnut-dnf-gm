"""Release decisions use evidence, never API/database success as a client verdict."""
REQUIRED = (
    "backup_restore", "mysql57_transactions", "schema_fingerprint",
    "gateway_ban_unban", "client_ban_unban", "pvf_mail_compatibility", "character_encoding", "online_cera",
    "online_cera_point", "concurrent_spend", "online_equipment_mail",
    "online_stackable_mail", "mailbox_inventory_full", "relogin_persistence",
)

def evaluate(evidence: dict) -> dict:
    checks = evidence.get("checks", {})
    missing = [name for name in REQUIRED if checks.get(name, {}).get("status") != "passed"]
    override = evidence.get("owner_override", {})
    approved = override.get("implement_before_manual_acceptance") is True
    return {
        "m0_passed": not missing,
        "formal_development_allowed": not missing or approved,
        "public_release_allowed": False,  # Technical/security deployment evidence is checked separately.
        "owner_requested_public_test": override.get("public_test_release") is True,
        "manual_acceptance_waived_as_development_blocker": approved,
        "pending_or_failed": missing,
    }
