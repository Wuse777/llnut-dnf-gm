# 客户端转职插画证据与覆盖

2026-11-09 核对当前客户端后，确认 32 个转职的客户端插画。文字映射保存在
[`client-1031.json`](../tools/portrait-maps/client-1031.json)，包含精确 PVF/NPK SHA256、IMG 帧、PVF 职业名称和官方带标签原画的出处。仓库不包含这些图片。

核实方法是逐张比较客户端图片与 DNF Global 官方职业介绍页中 `title` 对应的 `img_1st` 原画，检查人物构图、姿势、服饰和武器细节；部分图片有镜像或裁切。然后用当前 PVF `character/character.lst` 与 `[growtype name]` 核实职业编号与转职编号。NPK 文件名、图片排列顺序不作为职业身份依据。

覆盖鬼剑士、女格斗、男枪、女法、圣职者、女枪各 4 个转职，暗夜使者 2 个、男格斗 4 个、男法 2 个，共 32 个。原有 11 张基础职业官方宣传画继续保留。其他自定义或占位转职未映射，详细缺口由离线工具输出到私有 `portrait-coverage.json`。

**没有确认独立觉醒阶段插画。** 当前 32 条映射只对应觉醒 0。角色存档按 `grow_type & 15` 提取转职、`(grow_type >> 4) & 7` 提取觉醒。查找顺序为完整阶段映射、同转职示意、基础职业示意；同转职回退返回 `match_level=profession` 和 `awakening_specific=false`，界面明确标注觉醒未匹配。没有把同一张图重复登记成各觉醒阶段。也未进行游戏客户端逐像素验收。

离线构建示例：

```sh
PYTHONPATH=src python tools/build_client_portraits.py \
  /private/source-pack /private/Script.pvf /private/ImagePacks2 \
  tools/portrait-maps/client-1031.json /private/new-pack
```

工具只读取原客户端和源包，输出路径必须不存在。先验证 PVF、NPK 和源包版本，再验证明确的职业名称；独立的离线 v2 插画解码器允许最大 2048 像素画布，输出归一化到 512 像素以内。运行时物品解码预算不变。继承图片和外观 v2 atlas 需验证登记信息与 SHA256，损坏会拒绝，图片不进入公开源码或 Release。
