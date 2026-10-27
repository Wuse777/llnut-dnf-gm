"""Pure, testable bootstrap SQL builder. Never log returned SQL."""
from pathlib import Path
import re

def bootstrap_sql(config,ph):
    sql=(Path(__file__).resolve().parents[1]/'migrations/001.sql').read_text()
    sql += '\n'+(Path(__file__).resolve().parents[1]/'migrations/002-catalog-policy.sql').read_text()
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
    for t in ['audit','gift_versions']:grant('SELECT,INSERT','dnf_gm.'+t)
    grant('INSERT','dnf_gm.failures')
    grant('SELECT(UID,accountname)','d_taiwan.accounts')
    sql += character_read_sql(user)
    sql += catalog_policy_sql(user)
    sql += mail_gold_sql(user)
    sql += equipment_unlock_sql(user)
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
            f'GRANT SELECT(charac_no,exp,fatigue,used_fatigue,last_play_time) ON taiwan_cain.charac_stat TO {user};\n'
            f'GRANT SELECT(charac_no,money,coin,inventory_capacity,inventory,equipslot) ON taiwan_cain_2nd.inventory TO {user};\n')


def catalog_policy_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    return (f'GRANT SELECT,UPDATE(revision) ON dnf_gm.catalog_policy_state TO {user};\n'
            f'GRANT SELECT,INSERT(pvf_sha256,item_id,enabled,reason,revision),UPDATE(enabled,reason,revision) ON dnf_gm.catalog_policy_items TO {user};\n')


def mail_gold_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    # No inventory UPDATE, table-wide SELECT, DDL or gold UPDATE privilege.
    return f'GRANT SELECT(gold),INSERT(gold) ON taiwan_cain_2nd.postal TO {user};\n'


def equipment_unlock_sql(user="'dnf_gm_app'@'127.0.0.1'"):
    # No inventory UPDATE or table-wide write permissions.
    return f'GRANT SELECT(charac_no,item_lock_info),UPDATE(item_lock_info) ON taiwan_cain_2nd.charac_item_lock_info TO {user};\n'
