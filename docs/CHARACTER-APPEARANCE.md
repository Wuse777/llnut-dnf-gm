# 客户端外观：首帧兼容与实际部件动画

2026-11-09：v0.6.0 增加按真实存档部件与独立 ANI 时间线合成的外观工作区，支持已适配的待机、行走和首个站立普通攻击片段，并解析同角色有效背包中的透明装扮实例关系。当前只读快照的六个角色均可生成待机／行走预览，其中两个可生成普通攻击片段。光效、染色混色、职业常驻层、光环和隐藏开关仍按覆盖清单说明，不能声称完整还原。实现、资源预算和验收矩阵见 [外观 v2](APPEARANCE-V2.md)。

旧版 11 个基础职业默认等待首帧、物品图标和插画仍保持兼容。早期 5 个明确上衣配方仅用于离线合成验证，没有放进实际角色包冒充穿戴。全部客户端图片与派生索引保留在私有包，开源仓库与 Release 不包含这些内容；`client_verified` 仍为 false。下文的首帧配方和 `outfit` 接口说明适用于 v1 兼容路径。

默认预览只按 PVF 的基础 `job` 精确关联。身份来自 `character/character.lst`、对应 CHR 的 `[job]`／`[body image path]`／`[waiting motion]`，帧号与位置来自完整解析的 ANI，默认装扮及图层顺序来自各职业 EQU／LAY。AT 职业、黑暗武士和缔造者按各自 CHR 解析，不用任意数据库性别数字推断另一套身体素材。

它展示客户端默认着装站姿，不代表角色当前时装、武器、装备光效或精确转职／觉醒头像。没有匹配预览时，界面应保留装备槽位和明确的示意／缺图状态。

## 在维护电脑生成新包

先按 [图片包指南](ASSETS.md) 生成物品图标包，再合并角色预览。源包不改变；输出必须是不存在的新目录。

```bash
PYTHONPATH=src .venv/bin/python tools/build_character_assets.py \
  --pvf /private/Script.pvf \
  --npk-dir /private/client/ImagePacks2 \
  --source-pack /private/game-assets/icons-current \
  --output /private/game-assets/appearance-new
```

Windows 使用 PowerShell 7+，例如将 Python 换为 `.venv/Scripts/python.exe`，使用各自本地绝对路径。工具不修改客户端文件，不在 Web 请求或小内存服务器里解析 NPK／PVF。输出保留源包的物品／插画记录，对既有 PNG 逐个核对摘要并复制。

默认站姿需要完整且唯一的皮肤、上衣、下装、鞋及头发配方；重复但完全一致的默认 EQU 可去重。未知 ANI 参数、非恒等缩放／旋转／颜色／翻转、缺失脚本、冲突成员或不支持像素格式均记为 `unsupported`，不会用透明空图冒充成功。每个图层不超过 512×512，合成结果亦不超过 512×512；只裁透明外边距，保留源图层的位置关系。

## 可选显式装扮配方

`--outfits /private/outfits.json` 接受 UTF-8 JSON 数组，每份配方包含基础职业与明确的装扮物品 ID。以下为格式示例，编号须替换为自己匹配 PVF 中实际存在的物品：

```json
[
  {"job":0,"items":[
    {"slot":"[coat avatar]","id":990001},
    {"slot":"[hair avatar]","id":990002}
  ]}
]
```

支持的精确 PVF 部位为 `[hat avatar]`、`[hair avatar]`、`[face avatar]`、`[breast avatar]`、`[coat avatar]`、`[skin avatar]`、`[waist avatar]`、`[pants avatar]`、`[shoes avatar]`。每部位最多一个正整数 ID；最多 256 份配方，输入文件不超过 1 MiB。未指定部位沿用该职业默认装扮。

物品必须在 `equipment/equipment.lst` 中唯一定位，EQU 的 `[equipment type]` 必须与指定部位一致，重复 `[animation job]` 段必须精确匹配当前 CHR 职业。不接受另一职业的任意外观、克隆装扮的猜测来源或未知物品 ID；任何指定部位无法解析时，整份配方记为不支持，不偷偷回退默认图。

配方是离线生成请求。运行时只有在已核实所有实际穿戴装扮部位、当前基础职业和 PVF 指纹，并完全匹配已生成配方后，才能将其作为当前装扮预览；部分查询结果、背包拥有物品和示例配方都不能证明实际穿戴。任何缺少的读取权限、未知槽位或不支持的克隆／幻化信息都应阻止该声称。

`canonical_outfit_recipe(job, items)` 对部位字符串排序，仅保留 `{job, items:[{slot,id}]}`，使用 `json.dumps(..., sort_keys=True, separators=(',', ':'), ensure_ascii=True)` 的 ASCII 字节计算 SHA-256。配方不含角色编号、账号 ID 或本地路径；数据库数值槽位只用于确认穿戴区域，具体部位始终使用同指纹 PVF 的 `equipment_details.part_code`。不同数据库行顺序产生同一摘要，任一职业或物品变化产生新摘要。

## 实际穿戴存档读取与原生证据

当前适配器已实现实际服装存档的只读查询。证据仅适用于已核实的 `df_game_r`，SHA-256 为 `8859c99d8290dc5fb58151444138cf2697b2bfff12d47d6159596a03f20b5261`；更换服务端版本应重新核实，不自动扩大到其他版本。

- `DB_LoadInventory::_GetUserAvatar`（`0x0840be8a`，长度 `0xbea`）的 SQL 常量 `0x08c4609c` 读取 `user_items`，条件为当前角色、`expire_date>NOW()`、`stat=0`，调用给出的上限为 115。`stat=0` 同时覆盖穿戴和时装背包，单凭此值不能证明穿戴；零日期不会被这个原生加载条件接纳。
- `CInventory::IsEquipAvatar`（`0x084fb638`）扫描十个穿戴槽；`CInventory::get_avatar_slot_no`（`0x0850cd1c`）扫描另外 105 个背包槽。已核实数值 `slot=0..9` 为穿戴区域、`10..114` 为背包区域。没有据此猜测每个数字对应的中文部位。
- `Inter_LoadInven::dispatch_sig`（`0x084c3f92`，相关段 `0x084c4222..0x084c42da`）将 `clear_avatar_id` 交给 `GetItemIdByAddInfo`，从时装背包的身份关联中找最终物品，再经 `SetClearAvatar` 设置替代外观。它不是可直接查询 PVF 的物品 ID。`CUser::updateCharacViewVisibleData`（`0x08651322`，相关段 `0x08651403..0x08651449`）优先使用解析后的替代外观。
- `_GetUserAvatar` 的 `0x0840c61a..0x0840c722` 将 `color1/color2` 作为两个短整数读取；`CInventory::MoveClearAvatar`（`0x08508fd0`）通过 `map<int,AvatarVariation::colorRGB>` 查找颜色。它们是待解析的标识，不是 RGB 值，也不能直接当作 PVF 的图像变化编号。

v1 兼容查询绑定已有 `charac_info` 所有者与未删除状态，限定 `slot BETWEEN 0 AND 9 AND stat=0 AND expire_date>NOW()`，最多读取 11 行以识别超过十个槽位的异常。它拒绝重复数值槽、非法物品 ID、非零 `clear_avatar_id/color1/color2`；PVF 部位未知或重复时整份拒绝，不能拿部分衣服生成“当前外观”。无记录时明确标为没有有效穿戴存档。

v2 则读取有效区域 `0..114`，新增 `ui_id` 最小列读取权限，并按原生关联在背包 `10..114` 中解析 `clear_avatar_id`。透明来源身份、部位或关联链无法确认时拒绝；染色像素规则仍未确认，非零染色继续拒绝绘制。解析到精确 `[aurora avatar]` 时单独保留其身份并标注光环未绘制，不阻断其余九个已确认时装部位。两条路径分别返回 `outfit` 与 `appearance`，不改变旧首帧摘要语义。

通过校验后 API 返回 `outfit.state=ok` 与规范配方摘要，按当前 PVF、基础职业和配方摘要精确查询私有素材包。只有完全匹配的 `outfit_preview` 才标为 `source_kind=saved_avatar_outfit`；界面显示“服装存档首帧”，并说明不含武器、染色或变身效果。未生成、不可读或不支持时显示具体原因，并保留基础职业默认站姿／槽位示意。

新安装通过 `deploy/grants.py:character_outfit_read_sql` 仅授予 `user_items` 的 `charac_no,ui_id,slot,it_id,stat,expire_date,clear_avatar_id,color1,color2` 列 `SELECT`；既有实例升级应由维护流程增加相同列权限。没有此权限或旧表缺列时，对应外观区域返回 `unavailable`，不会使装备、背包、仓库及角色基本资料失败。此功能不增加游戏表更新权限。

2026-11-09 的 v2 私有只读抽查包含 30 条有效穿戴记录、16 条透明关联、0 条染色记录。六个角色的实际配方均可解析；三个穿戴九个基础时装部位，三个未穿戴时装，两套配方使用透明替代。v1 仍不将未生成的整套配方冒充首帧；v2 由实际部件库逐动作合成。私有导出不保留账号、角色身份或昵称。

## 清单扩展

沿用 `manifest.sqlite` 的 `files(sha256,width,height)` 与 `images/<SHA256>.png`，追加以下可选表：

```sql
CREATE TABLE job_previews(
  job INTEGER PRIMARY KEY,
  sha256 TEXT,
  state TEXT NOT NULL,
  pose TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE outfit_previews(
  job INTEGER NOT NULL,
  recipe_sha256 TEXT NOT NULL,
  sha256 TEXT,
  state TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(job, recipe_sha256)
);
```

默认记录固定 `pose=waiting_first_frame`、`source_kind=client_default_pose`。成功记录为 `state=ready` 并引用 `files`，失败记录 `state=unsupported` 且摘要为空。`metadata` 包含 `job_previews_version=1`、`job_previews=<ready 数量>`、`outfit_previews_version=1` 和 `outfit_previews=<ready 数量>`。未扩展的旧包仍可提供原有图标；运行时应把缺表视为没有对应预览。

`detail` 仅供私下诊断，可能含客户端逻辑成员名，不能直接通过 API 或浏览器暴露。运行时只查询只读 SQLite 和经过摘要验证的小 PNG；不接受浏览器指定磁盘路径，不动态执行素材解析。

## 私有安装与回滚

完整上传新目录，再按 [图片包安装步骤](ASSETS.md#3-安装与回滚) 设为 root 拥有、运行组只读，目录 0750、文件 0640。运行账号不能改图片包。核对新包 PVF 指纹和完整性后，在私有配置中切换 `assets_dir`，仅重启 GM；保留旧目录以便恢复原配置回滚。不要原地覆盖正在提供请求的清单或图片。

登录管理员后核对 11 个职业默认预览、若干实际图标和缺图回退；外观图片沿用会话鉴权、同源固定地址与摘要校验。服务器和源包 PVF 不同、文件损坏或摘要未登记时应拒绝图片。

## 后续验收边界

v1 保留静态等待首帧与显式配方接口，v2 提供实际部件、透明身份解析、独立时间线动画和可支持的基础武器。已提取的 36 条颜色查表记录不足以证明染色像素算法；普通攻击片段不涵盖连击链或技能。职业常驻层、称号／光环／强化特效、隐藏开关和精确觉醒阶段头像仍须分别证明，不能以文件可解码或默认职业素材齐全代替完整纸娃娃验收。

合成测试覆盖 ANI 完整性和变换拒绝、IMG 链接与空哨兵／越界检查、Alpha 图层顺序、配方摘要稳定性、错误身份拒绝，以及新包合并时原有图片保留。格式来源与独立实现说明见 [THIRD_PARTY.md](../THIRD_PARTY.md)。
