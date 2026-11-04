"""PVF-scoped administrator favorites and recent draft selections, not rewards."""
from contextlib import closing
from fastapi import HTTPException


class ItemPreferences:
    def __init__(self, db, catalog):
        self.db, self.catalog = db, catalog

    def update(self, item_id, pvf_sha256, favorite=None):
        with closing(self.catalog.connect()) as catalog:
            sha = self.catalog.meta(catalog).get('pvf_sha256')
            if sha != pvf_sha256:
                raise HTTPException(409, '物品索引版本已改变，请刷新目录后重试')
            if not catalog.execute('SELECT id FROM items WHERE id=?', (item_id,)).fetchone() and favorite is not False:
                raise HTTPException(404, '当前索引中没有该物品')
        with self.db.connect() as c, c.cursor() as q:
            # Each action touches only its own columns: favorite/selection cannot
            # clobber each other under concurrent requests. Repeated PUT is a no-op.
            if favorite is None:
                q.execute('INSERT INTO dnf_gm.item_preferences(pvf_sha256,item_id,selected_at) '
                          'VALUES(%s,%s,UTC_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE selected_at=UTC_TIMESTAMP(6)',
                          (sha,item_id))
            elif favorite is False:
                # Unfavoriting an absent/removed item is idempotent and must not
                # create unbounded unknown-item rows in the preference table.
                q.execute('UPDATE dnf_gm.item_preferences SET '
                          'favorited_at=IF(favorite=0,favorited_at,UTC_TIMESTAMP(6)),favorite=0 '
                          'WHERE pvf_sha256=%s AND item_id=%s', (sha,item_id))
            else:
                q.execute('INSERT INTO dnf_gm.item_preferences(pvf_sha256,item_id,favorite,favorited_at) '
                          'VALUES(%s,%s,%s,UTC_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE '
                          'favorited_at=IF(favorite=VALUES(favorite),favorited_at,UTC_TIMESTAMP(6)),favorite=VALUES(favorite)',
                          (sha,item_id,int(favorite)))
            q.execute('SELECT item_id,favorite,favorited_at,selected_at FROM dnf_gm.item_preferences '
                      'WHERE pvf_sha256=%s AND item_id=%s', (sha,item_id))
            result=q.fetchone() or {'item_id':item_id,'favorite':False,'favorited_at':None,'selected_at':None}
            c.commit()
        return {**result, 'favorite':bool(result['favorite']), 'pvf_sha256':sha}

    def list(self, collection, page):
        # Sorting/where identifiers are selected internally, never interpolated input.
        if collection not in ('favorites','recent'):
            raise HTTPException(422, '未知的物品集合')
        condition, order = ('favorite=1','favorited_at') if collection=='favorites' else ('selected_at IS NOT NULL','selected_at')
        with closing(self.catalog.connect()) as catalog:
            sha=self.catalog.meta(catalog).get('pvf_sha256')
            with self.db.connect() as c, c.cursor() as q:
                q.execute('SELECT COUNT(*) total FROM dnf_gm.item_preferences WHERE pvf_sha256=%s AND '+condition,(sha,))
                total=q.fetchone()['total']
                q.execute('SELECT item_id,favorite,favorited_at,selected_at FROM dnf_gm.item_preferences '
                          'WHERE pvf_sha256=%s AND '+condition+' ORDER BY '+order+' DESC,item_id DESC LIMIT 50 OFFSET %s',
                          (sha,(page-1)*50))
                entries=q.fetchall()
                _, overrides=self.catalog.policy(q,sha,ids=[x['item_id'] for x in entries])
                creature_types=self.catalog.creature_types(catalog)
                result=[]
                for entry in entries:
                    row=catalog.execute('SELECT * FROM items WHERE id=?',(entry['item_id'],)).fetchone()
                    item=self.catalog.annotate(row,overrides,creature_types) if row else {
                        'id':entry['item_id'],'name':'索引中已不存在','sendable':False,
                        'policy_reason':'索引中没有该物品，请重新核对','policy_state':'blocked', 'category':'unknown'}
                    item.pop('source_path',None)
                    result.append({**item,**entry,'favorite':bool(entry['favorite']),'pvf_sha256':sha})
        self.catalog.assets.decorate(sha,result)
        return {'items':result,'page':page,'total':total,'pvf_sha256':sha,'collection':collection,
                'note':'最近选择只表示加入过草稿，不代表发放或领取；收藏不改变发放策略。'}

    @staticmethod
    def decorate(q, sha, items):
        """Display-only; do not add preferences to any reward fingerprint."""
        if not items:
            return
        q.execute('SELECT item_id,favorite,selected_at FROM dnf_gm.item_preferences WHERE pvf_sha256=%s '
                  'AND item_id IN ('+','.join(['%s']*len(items))+')',(sha,*(i['id'] for i in items)))
        prefs={p['item_id']:p for p in q.fetchall()}
        for item in items:
            p=prefs.get(item['id'],{})
            item.update(favorite=bool(p.get('favorite',False)),selected_at=p.get('selected_at'),pvf_sha256=sha)
