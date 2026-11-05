"""Administrator navigation metadata. Names/ownership are always read fresh."""
from typing import Literal
from fastapi import HTTPException
from pydantic import Field,StrictBool,StrictInt
from .models import Model
from .service import one,character


class PlayerTarget(Model):
    uid:StrictInt=Field(ge=1,le=2147483647)
    charac_no:StrictInt=Field(default=0,ge=0,le=2147483647)


class PlayerFavorite(PlayerTarget):
    favorite:StrictBool


class PlayerPreferences:
    def __init__(self,db):self.db=db

    @staticmethod
    def validate(q,uid,charac_no):
        if not one(q,'SELECT UID FROM d_taiwan.accounts WHERE UID=%s',(uid,)):
            raise HTTPException(404,'账号已不存在，请刷新目标列表')
        if charac_no:
            row=one(q,'SELECT m_id,delete_flag FROM taiwan_cain.charac_info WHERE charac_no=%s',(charac_no,))
            if not row or row['m_id']!=uid or row['delete_flag']:
                raise HTTPException(409,'角色已删除、不存在或归属变化，请重新选择')

    def update(self,uid,charac_no,favorite=None):
        with self.db.connect() as c,c.cursor() as q:
            if favorite is not False:self.validate(q,uid,charac_no)
            if favorite is None:
                q.execute('INSERT INTO dnf_gm.player_preferences(uid,charac_no,visited_at) VALUES(%s,%s,UTC_TIMESTAMP(6)) '
                    'ON DUPLICATE KEY UPDATE visited_at=UTC_TIMESTAMP(6)',(uid,charac_no))
            elif favorite is False:
                q.execute('UPDATE dnf_gm.player_preferences SET favorite=0,favorited_at=NULL WHERE uid=%s AND charac_no=%s',(uid,charac_no))
            else:
                q.execute('INSERT INTO dnf_gm.player_preferences(uid,charac_no,favorite,favorited_at) VALUES(%s,%s,1,UTC_TIMESTAMP(6)) '
                    'ON DUPLICATE KEY UPDATE favorited_at=IF(favorite=1,favorited_at,UTC_TIMESTAMP(6)),favorite=1',(uid,charac_no))
            c.commit()
        return {'uid':uid,'charac_no':charac_no,'favorite':favorite,'navigation_only':True}

    def list(self,collection:Literal['recent','favorites'],page=1):
        if collection not in ('recent','favorites'):raise HTTPException(422,'未知玩家集合')
        condition,order=('favorite=1','favorited_at') if collection=='favorites' else ('visited_at IS NOT NULL','visited_at')
        with self.db.connect() as c,c.cursor() as q:
            q.execute('SELECT COUNT(*) total FROM dnf_gm.player_preferences WHERE '+condition)
            total=q.fetchone()['total']
            q.execute('SELECT uid,charac_no,favorite,favorited_at,visited_at FROM dnf_gm.player_preferences WHERE '+condition+
                ' ORDER BY '+order+' DESC,uid DESC,charac_no DESC LIMIT 12 OFFSET %s',((page-1)*12,))
            entries=q.fetchall();items=[]
            for entry in entries:
                uid,n=entry['uid'],entry['charac_no']
                account=one(q,'SELECT UID AS uid,accountname FROM d_taiwan.accounts WHERE UID=%s',(uid,))
                role=None;available=account is not None
                if n:
                    row=one(q,'SELECT m_id AS uid,charac_no,charac_name,lev,delete_flag,CAST(CONVERT(charac_name USING latin1) AS BINARY) AS client_name_bytes '
                        'FROM taiwan_cain.charac_info WHERE charac_no=%s AND m_id=%s',(n,uid))
                    role=character(row) if row else None
                    available=available and role is not None and not role['delete_flag']
                items.append({**entry,'favorite':bool(entry['favorite']),'account':account,'character':role,'available':bool(available)})
        return {'items':items,'collection':collection,'page':page,'page_size':12,'total':total,
            'note':'最近访问不等于已发奖；收藏只保存目标编号。打开后仍重新查询归属，所有奖励都需预览确认。'}
