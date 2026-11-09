# 版本化界面偏好与装备筛选

[文档中心](README.md) · [开发指南](DEVELOPMENT.md)

管理库迁移017保存当前单管理员的界面选择，不存奖励草稿、操作编号、密码或任意客户端文件路径。收藏和最近选择继续使用原有 `item_preferences`，玩家导航继续使用 `player_preferences`，不会复制到新表。安装和升级必须执行迁移及 `ui_preferences_sql` 专用权限；应用不自动建表或修改游戏权限。

## 装备筛选来源

`tools/enrich_catalog_equipment.py SOURCE PVF NEW_OUTPUT` 在新的只读索引副本中增加职业、武器类别和套装元数据，不覆盖原文件，也不改变物品发放策略。PVF与源索引SHA-256必须一致。新索引标记 `equipment_filters_version=1`；旧索引保留基本目录功能，使用新增筛选时返回409，不能静默省略条件。

- `job` 是PVF明确的 `[usable job]` 代码，如 `[mage]`。选择已知职业时包含明确标为 `[all]` 的通用装备；未知输入按字面查找，不扩大范围。
- `weapon_type` 是明确武器装备在PVF目录中的类别码，如 `staff`、`katana`。中文名称仅翻译这些代码，不根据物品名称猜测。
- `set_id` 是PVF明确的正整数 `[set item master]`；主件可由自己的 `[set name]` 确定。套装名称只从对应主件的明确声明读取，缺失时显示编号，不根据装备名称拼接套装。

`GET /dnf-gm/api/v1/catalog` 新增这三个参数，并返回 `facets.jobs`、`weapon_types`、`sets`、`extended_equipment_metadata`。`set_id` 不传表示不限；0和负数无效。套装选项最多返回2000项，`sets_truncated` 标示是否截断，指定准确套装编号仍可查询。物品详情新增 `usable_jobs`、`weapon_type_name`、`set_id`、`set_name`。这些是PVF显示资料，不保证角色当前可穿戴，也不改变发放权限。目录搜索与批量物品策略共用同一组SQL谓词。

## 偏好接口

所有接口使用已有会话；PUT、DELETE和试衣POST还需要同源Origin与 `X-CSRF-Token`。

| 方法和路径（前缀 `/dnf-gm/api/v1`） | 用途 |
| --- | --- |
| `GET /ui-preferences?kind=catalog-filter` | 当前PVF下此类已保存偏好，最多30项 |
| `GET /ui-preferences/{kind}/{name}` | 读取指定名称及当前版本，未保存时为version0、payload=null |
| `PUT /ui-preferences/{kind}/{name}` | 保存 `{pvf_sha256,expected_version,payload}` |
| `DELETE /ui-preferences/{kind}/{name}` | 删除 `{pvf_sha256,expected_version}`，保留递增版本的墓碑 |

`kind` 仅接受 `catalog-filter`、`appearance`、`layout`；名称为1–48个可见字符，不含路径分隔符。旧PVF保存请求返回409，不自动迁移方案。版本冲突也返回409，页面必须重新读取并让管理员决定是否覆盖；禁止后台静默重试覆盖。相同版本、相同内容重复保存不递增版本。删除后的名称保留版本，重新创建须基于该版本，避免旧页面把已删偏好复活。

每类每PVF最多30个有效偏好、累计最多100个名称。管理库独立锁串行控制版本和数量，不锁游戏、奖励或维护申请行。偏好可在维护期间保存，不绕过任何游戏写入屏障。

| 类型 | payload |
| --- | --- |
| `catalog-filter` | 与 `CatalogFilters` 相同的扁平字段，加 `sort=id/level_asc/level_desc/name`；不含页码 |
| `appearance` | `job:0..255`、`grow_type:0..127`、`sex:-1..1`、`direction:right/mirror_left`、`animation:idle/walk/attack`、`slots:[{slot,item_id}]` |
| `layout` | `theme:light/dark/auto`、Soybean布局 `layout`、`density:comfortable/compact`、`sidebar_collapsed`、`show_job_art`、`tab_visible` |

外观只接受帽子、头发、脸、胸部、上衣、皮肤、腰部、裤子、鞋的精确PVF avatar槽码，如 `[hat avatar]`。每部位唯一，最多9项，只保存物品编号。`mirror_left` 仅代表前端左向镜像，不是另一套原生方向帧。保存方案不会验证客户端呈现成功，也不会更改角色实际存档。

## 本地试衣和图集

`POST /appearance/preview` 接受外观payload并额外要求 `pvf_sha256`。后端重新核对当前索引与运行PVF，返回限定的外观v2清单，标记 `scope=local_fitting` 与 `source_kind=local_fitting`。此请求不创建奖励操作、不修改游戏行。过期方案不能直接套用到另一个PVF。

`GET /assets/{pvf_sha}/{digest}.atlas.png` 是单独的会话鉴权图集接口，不复用512px物品图标读取器，不接受路径或任意清单。实际角色外观、静态示意和本地试衣必须在界面明确区分。生产定向系统消息继续保持停用；这些偏好和外观接口不启用任何消息桥接或游戏控制能力。
