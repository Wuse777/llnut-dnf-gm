"""Fixed namespace and canonical name columns for QF1031; no executable SQL."""
SERVER_ID=3  # Same fixed shard as the existing login_account_3 adapter.
# schema, table, name column, identifying columns, owner column (if applicable).
LINKS={
    'guild_member':('d_taiwan','guild_member','charac_name',('guild_id','charac_no','server_id','m_id'),'m_id'),
    'guild_master':('d_taiwan','guild_info','master_name',('guild_id','master_no','server_id','master_id'),'master_id'),
    'guild_recommend':('d_taiwan','guild_recommend','charac_name',('no','guild_id','charac_no','server_id'),None),
    'representative':('d_taiwan','dnf_master_charac','charac_name',('m_id','global_type','server_id','charac_no'),'m_id'),
    'blacklist':('taiwan_cain_2nd','charac_black_list','charac_name',('m_id','charac_no'),None),
}
