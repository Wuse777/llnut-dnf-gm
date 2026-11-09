"""Pure, testable bootstrap SQL builder. Never log returned SQL."""
from pathlib import Path
import re

def bootstrap_sql(config,ph):
    sql=(Path(__file__).resolve().parents[1]/'migrations/001.sql').read_text()
    sql += '\n'+(Path(__file__).resolve().parents[1]/'migrations/002-catalog-policy.sql').read_text()
    sql += '\n'+(Path(__file__).resolve().parents[1]/'migrations/003-all-items.sql').read_text(encoding='utf-8')
    sql += '\n'+(Path(__file__).resolve().parents[1]/'migrations/004-mail-center.sql').read_text(encoding='utf-8')
    name=config.get('db_user','dnf_gm_app')
    host=config.get('db_account_host','127.0.0.1')
    if not re.fullmatch(r'[A-Za-z0-9_]{1,32}', name) or name.lower() in ('root','game'):
        raise ValueError('Invalid dedicated database user')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,255}', host):
        raise ValueError('Exact database account host required; wildcard grants forbidden')
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,}',config['db_password']):
        raise ValueError('Unsafe database password literal')
    user=f"'{name}'@'{host}'"
    sql+=f"\nCREATE USER {user} IDENTIFIED BY '{config['db_password']}' WITH MAX_USER_CONNECTIONS 3;\n"
    def grant(rights,table):
        nonlocal sql
        sql+=f'GRANT {rights} ON {table} TO {user};\n'
    for t in ['schema_versions','admins']:grant('SELECT','dnf_gm.'+t)
    grant('UPDATE(last_totp)','dnf_gm.admins')
    for t in ['operations','gift_templates','owned_bans']:grant('SELECT,INSERT,UPDATE','dnf_gm.'+t)
    grant('SELECT,INSERT,UPDATE,DELETE','dnf_gm.sessions')
    for t in ['audit','gift_versions','mail_batches','mail_deliveries']:grant('SELECT,INSERT','dnf_gm.'+t)
    grant('SELECT(id,operation_id,error_type,created_at),INSERT','dnf_gm.failures')
    grant('SELECT(UID,accountname)','d_taiwan.accounts')
    sql += character_read_sql(user)
    sql += character_outfit_read_sql(user)
    sql += warehouse_read_sql(user)
    sql += (Path(__file__).resolve().parents[1]/'migrations/005-item-preferences.sql').read_text()
    sql += item_preferences_sql(user)
    sql += (Path(__file__).resolve().parents[1]/'migrations/006-reward-jobs.sql').read_text()
    sql += (Path(__file__).resolve().parents[1]/'migrations/007-native-controls.sql').read_text()
    sql += native_controls_sql(user)
    sql += (Path(__file__).resolve().parents[1]/'migrations/008-schedules.sql').read_text()
    sql += schedules_sql(user)
    sql += (Path(__file__).resolve().parents[1]/'migrations/009-inventory-operations.sql').read_text()
    sql += inventory_management_sql(user)
    sql += character_maintenance_sql(user)
    sql += character_rename_sql(user)
    sql += character_rescue_sql(user)
    sql += character_skills_sql(user)
    sql += character_skill_reset_sql(user)
    sql += character_profession_sql(user)
    sql += character_levels_sql(user)
    sql += character_quests_sql(user)
    sql += quest_repair_sql(user)
    sql += (Path(__file__).resolve().parents[1]/'migrations/010-support-desk.sql').read_text()
    sql += support_sql(user)
    sql += (Path(__file__).resolve().parents[1]/'migrations/011-economy-ledger.sql').read_text()
    sql += economy_sql(user)
    sql += (Path(__file__).resolve().parents[1]/'migrations/012-capabilities.sql').read_text()
    sql += capability_policy_sql(user)
    sql += (Path(__file__).resolve().parents[1]/'migrations/013-gameplay-fence.sql').read_text()
    sql += (Path(__file__).resolve().parents[1]/'migrations/014-operation-outcomes.sql').read_text()
    sql += (Path(__file__).resolve().parents[1]/'migrations/015-player-preferences.sql').read_text()
    sql += player_preferences_sql(user)
    sql += (Path(__file__).resolve().parents[1]/'migrations/016-backup-schedule.sql').read_text()
    sql += backup_schedule_sql(user)
    sql += (Path(__file__).resolve().parents[1]/'migrations/017-ui-preferences.sql').read_text()
    sql += ui_preferences_sql(user)
    sql += gameplay_fence_sql(user)
    sql += reward_jobs_sql(user)
    sql += catalog_policy_sql(user)
    sql += mail_gold_sql(user)
    sql += equipment_unlock_sql(user)
    sql += rewards_sql(user)
    sql += mail_center_sql(user)
    grant('SELECT(m_id,login_status,m_channel_no)','taiwan_login.login_account_3')
    for table,col in [('cash_cera','cera'),('cash_cera_point','cera_point')]:
        grant(f'SELECT(account,{col}),UPDATE({col},mod_date)','taiwan_billing.'+table)
    grant('INSERT(charac_no,send_charac_name,letter_text,reg_date,stat)','taiwan_cain_2nd.letter')
    grant('SELECT(postal_id,receive_time,delete_flag),INSERT(occ_time,send_charac_name,receive_charac_no,item_id,add_info,endurance,letter_id)','taiwan_cain_2nd.postal')
    grant('SELECT(m_id,punish_type,apply_flag,start_time,end_time,admin_id,reason),INSERT(m_id,punish_type,occ_time,punish_value,apply_flag,start_time,end_time,admin_id,reason),UPDATE(apply_flag,start_time,end_time,admin_id,reason)','d_taiwan.member_punish_info')
    if not re.fullmatch(r'\$argon2id\$[A-Za-z0-9$=,+/]+',ph):raise ValueError('Invalid password hash')
    sql+=f"INSERT INTO dnf_gm.admins(id,username,password_hash,totp_encrypted) VALUES(1,'admin','{ph}','');\n"
    return sql


def character_read_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    # Explicit approved column list; no game writes or table-wide SELECT.
    columns = ('m_id,charac_no,charac_name,lev,delete_flag,job,grow_type,sex,exp,'
               'fatigue,max_fatigue,premium_fatigue,max_premium_fatigue,guild_id,create_time,last_play_time,'
               'maxHP,maxMP,phy_attack,phy_defense,mag_attack,mag_defense,hp_regen,mp_regen,'
               'move_speed,attack_speed,cast_speed,hit_recovery,jump,inven_weight,charac_weight')
    return (f'GRANT SELECT({columns}) ON taiwan_cain.charac_info TO {user};\n'
            f'GRANT SELECT(charac_no,exp,fatigue,premium_fatigue,used_fatigue,last_play_time) ON taiwan_cain.charac_stat TO {user};\n'
            f'GRANT SELECT(charac_no,money,coin,inventory_capacity,inventory,equipslot) ON taiwan_cain_2nd.inventory TO {user};\n')


def character_outfit_read_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return f'GRANT SELECT(charac_no,slot,it_id,stat,expire_date,clear_avatar_id,color1,color2,ui_id) ON taiwan_cain_2nd.user_items TO {user};\n'


def ui_preferences_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return (f'GRANT SELECT,UPDATE(revision) ON dnf_gm.ui_preference_state TO {user};\n'
            f'GRANT SELECT,INSERT,UPDATE(version,payload_json,deleted,updated_at) ON dnf_gm.ui_preferences TO {user};\n')


def catalog_policy_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return (f'GRANT SELECT,UPDATE(revision) ON dnf_gm.catalog_policy_state TO {user};\n'
            f'GRANT SELECT,INSERT(pvf_sha256,item_id,enabled,reason,revision),UPDATE(enabled,reason,revision) ON dnf_gm.catalog_policy_items TO {user};\n')


def mail_gold_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    # No inventory UPDATE, table-wide SELECT, DDL or gold UPDATE privilege.
    return f'GRANT SELECT(gold),INSERT(gold) ON taiwan_cain_2nd.postal TO {user};\n'


def equipment_unlock_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    # No inventory UPDATE or table-wide write permissions.
    return f'GRANT SELECT(charac_no,item_lock_info),UPDATE(item_lock_info) ON taiwan_cain_2nd.charac_item_lock_info TO {user};\n'


def rewards_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return (f'GRANT SELECT(m_id,miles),INSERT(m_id,miles,daily_miles),UPDATE(m_id,miles) ON d_taiwan.member_miles TO {user};\n'
            f'GRANT INSERT(charac_no,it_id,jewel_socket,expire_date,reg_date,obtain_from,stat) ON taiwan_cain_2nd.user_items TO {user};\n'
            f'GRANT INSERT(charac_no,it_id,reg_date,stomach,creature_type) ON taiwan_cain_2nd.creature_items TO {user};\n'
            f'GRANT INSERT(avata_flag,creature_flag) ON taiwan_cain_2nd.postal TO {user};\n')


def mail_center_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return (f'GRANT SELECT(id,operation_id,error_type,created_at) ON dnf_gm.failures TO {user};\n'
            f'GRANT SELECT,INSERT ON dnf_gm.mail_batches TO {user};\n'
            f'GRANT SELECT,INSERT ON dnf_gm.mail_deliveries TO {user};\n'
            f'GRANT SELECT(receive_charac_no,letter_id,item_id,add_info,avata_flag,creature_flag) ON taiwan_cain_2nd.postal TO {user};\n')


def warehouse_read_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    # No raw unrelated blobs, game UPDATE, DELETE or table-wide SELECT.
    return (f'GRANT SELECT(charac_no,cargo,cargo_capacity) ON taiwan_cain_2nd.charac_inven_expand TO {user};\n'
            f'GRANT SELECT(m_id,money,capacity,cargo,occ_time) ON taiwan_cain.account_cargo TO {user};\n')


def item_preferences_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return (f'GRANT SELECT,INSERT(pvf_sha256,item_id,favorite,favorited_at,selected_at),'
            f'UPDATE(favorite,favorited_at,selected_at) ON dnf_gm.item_preferences TO {user};\n')


def reward_jobs_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return ''.join(f'GRANT SELECT,INSERT,UPDATE ON dnf_gm.{table} TO {user};\n'
                   for table in ('reward_jobs','reward_targets','reward_account_credits'))


def native_controls_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return f'GRANT SELECT,INSERT ON dnf_gm.native_controls TO {user};\n'


def schedules_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return ''.join(f'GRANT SELECT,INSERT,UPDATE ON dnf_gm.{table} TO {user};\n'
                   for table in ('schedules','schedule_runs'))


def inventory_management_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return ''.join(f'GRANT SELECT,INSERT ON dnf_gm.{table} TO {user};\n' for table in ('inventory_operations','inventory_snapshots'))


def inventory_storage_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    # Deliberately NOT part of bootstrap. Explicit maintenance activation only.
    return (f'GRANT UPDATE(inventory,equipslot) ON taiwan_cain_2nd.inventory TO {user};\n'
            f'GRANT UPDATE(cargo) ON taiwan_cain_2nd.charac_inven_expand TO {user};\n'
            f'GRANT UPDATE(cargo) ON taiwan_cain.account_cargo TO {user};\n')


def support_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return (''.join(f'GRANT SELECT,INSERT,UPDATE ON dnf_gm.{table} TO {user};\n' for table in ('player_profiles','support_cases','support_links','support_requests'))
            + f'GRANT SELECT,INSERT ON dnf_gm.support_events TO {user};\n')


def economy_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return ''.join(f'GRANT SELECT,INSERT ON dnf_gm.{table} TO {user};\n' for table in ('economy_operations','economy_values'))


def capability_policy_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return (f'GRANT SELECT,UPDATE(revision,enabled_json,updated_at) ON dnf_gm.capability_policy TO {user};\n'
            f'GRANT SELECT,INSERT ON dnf_gm.capability_requests TO {user};\n')


def initialize_owner_capabilities_sql():
    # Installation-time explicit owner activation; does not overwrite later web
    # choices. No game rows, rewards, schedules or maintenance windows created.
    import json
    from dnfgm.capability_policy import SWITCHES
    switches=list(SWITCHES)
    enabled=json.dumps(sorted(switches),separators=(',',':'))
    return ("START TRANSACTION;\nSELECT revision FROM dnf_gm.capability_policy WHERE id=1 FOR UPDATE;\n"
            "INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) "
            "SELECT 'owner-capabilities-initial','maintenance','capability-policy','安装时按所有者要求开放已实现功能','{}','{\"account_scope\":\"all\",\"revision\":1}' FROM dnf_gm.capability_policy WHERE id=1 AND revision=0;\n"
            f"UPDATE dnf_gm.capability_policy SET revision=1,enabled_json='{enabled}',updated_at=UNIX_TIMESTAMP() WHERE id=1 AND revision=0;\nCOMMIT;\n")


def gameplay_fence_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    # MySQL5.7 locking SELECTs are tested with only SELECT on this fixed row.
    return f'GRANT SELECT ON dnf_gm.gameplay_fence TO {user};\n'


def character_maintenance_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    # Fixed consumed-fatigue columns only. Never writes caps or historical counters.
    return f"GRANT UPDATE(fatigue,premium_fatigue) ON taiwan_cain.charac_stat TO {user};\n"


def character_rename_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    """Only canonical name fields and their identifying columns, no broad writes."""
    from dnfgm.character_name_schema import LINKS
    sql=f'GRANT UPDATE(charac_name) ON taiwan_cain.charac_info TO {user};\n'
    for schema,table,column,keys,_ in LINKS.values():
        sql+=f"GRANT SELECT({','.join((*keys,column))}),UPDATE({column}) ON {schema}.{table} TO {user};\n"
    return sql


def character_rescue_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return (f'GRANT SELECT(village),UPDATE(village) ON taiwan_cain.charac_info TO {user};\n'
            f'GRANT SELECT(village,village_prev),UPDATE(village,village_prev) ON taiwan_cain.charac_stat TO {user};\n')


def character_quests_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    from dnfgm.character_quests import QUEST_COLUMNS
    return f'GRANT SELECT({",".join("`"+k+"`" for k in QUEST_COLUMNS)}) ON taiwan_cain.new_charac_quest TO {user};\n'


def player_preferences_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return (f'GRANT SELECT,INSERT(uid,charac_no,favorite,favorited_at,visited_at),'
            f'UPDATE(favorite,favorited_at,visited_at) ON dnf_gm.player_preferences TO {user};\n')


def quest_repair_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    # Only active task IDs/progress; never grant completion/notification writes.
    columns=','.join(f'`play_{i}` , `play_{i}_trigger`' for i in range(1,21))
    return f'GRANT SELECT(quest_notify),UPDATE({columns}) ON taiwan_cain.new_charac_quest TO {user};\n'


def backup_schedule_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return (f'GRANT SELECT,UPDATE(revision,enabled,hour,minute,retention_days,failure_alerts,updated_at) ON dnf_gm.backup_schedule TO {user};\n'
            f'GRANT SELECT,INSERT,UPDATE(state,result_json,error_code,started_at,finished_at) ON dnf_gm.backup_runs TO {user};\n')


def character_skills_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    from dnfgm.character_skills import POINTS, SCALARS, BLOBS
    return (f'GRANT SELECT(skill_tree_index) ON taiwan_cain.charac_info TO {user};\n'
            f'GRANT SELECT({",".join(("charac_no",*SCALARS,*BLOBS))}),UPDATE({",".join(POINTS)}) ON taiwan_cain_2nd.skill TO {user};\n')


def character_levels_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    from dnfgm.character_levels import WRITABLE
    return (f'GRANT SELECT(element_resist,spec_property),UPDATE({",".join(WRITABLE)}) ON taiwan_cain.charac_info TO {user};\n'
            f'GRANT UPDATE(exp) ON taiwan_cain.charac_stat TO {user};\n')


def character_skill_reset_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return (f'GRANT SELECT(expert_job) ON taiwan_cain.charac_info TO {user};\n'
            f'GRANT SELECT(expert_job_exp) ON taiwan_cain.charac_stat TO {user};\n'
            f'GRANT UPDATE(skill_slot,skill_slot_2nd,skill_slot_lethe,skill_slot_lethe_2nd) ON taiwan_cain_2nd.skill TO {user};\n')


def character_profession_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    # Growth and learned-skill columns are granted by the associated modules.
    # Never grant base-job, gender, costume or general character UPDATE.
    return f'GRANT UPDATE(grow_type) ON taiwan_cain.charac_info TO {user};\n'
