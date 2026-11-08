# 第三方来源与许可

## CPAMC 视觉设计与主题变量

- 项目：Router-For.ME / Cli-Proxy-API-Management-Center。
- 参考版本：`v1.26.5`，Git tree `fe2963330f32a933f562282165f62ae52cf57145`，固定来源版本。
- 来源：`src/styles/themes.scss`、`variables.scss`、`layout.scss`、`components.scss`。
- `web/src/cpamc-tokens.css` 使用该版本的主题变量；字体栈、216/60px侧栏、控件尺寸、8/12px圆角与过渡时序参照该版本。Vue布局和GM交互独立实现。
- 许可证：MIT；原始声明见 [licenses/CPAMC-MIT.txt](licenses/CPAMC-MIT.txt)。浏览器产物亦包含 `third-party-notices.txt`。

## DNF GM 操作流程参考（仅研究，不复制实现）

- `onlyGuo/dnf-server-web-public`，tree `644539c1c9c172340d96bfb69f7d71538895d247`：研究账号／角色列表、角色上下文和邮件物品选择流程。
- `Zageku/DNF_pvf_python`，tree `8b01148bb93c0ddf47d0b35bd222646be039084d`：研究物品列表与邮件编辑分区。
- 未复制上述项目的业务代码、图片、数据库写入实现或未经确认许可证的组件；不引入其背包修改、群发、特殊装备或进程注入能力。

## 角色存档只读二进制格式参考

- 格式资料：`Zageku/DNF_pvf_python` 的 `dnfpkgtool/sqlManager2.py`（与上述固定 tree 对照）：4字节小端长度、zlib、61字节槽位及各字段偏移。
- 本项目 `character_detail.py` 为独立实现，只读解码；未复制该项目代码、图片、写入函数或组件。加入解压大小、长度、尾部数据校验，未知类型不猜数量，损坏数据不冒充空容器。
- 在当前清风1031实测12个穿戴槽、249个背包存档槽，并以当前PVF物品路径核对现有武器／称号／防具／首饰槽位。副装备槽名称为标准槽位标签，未宣称已完成对应客户端验证。
- 职业名称直接离线提取部署者的匹配 PVF的`character/character.lst`与`[growtype name]`，不复制第三方职业字典，也不猜测觉醒位标记。

- 仓库读取：对照同一格式资料与2026-11-04当前部署实际DDL，角色仓库使用`charac_inven_expand.cargo`，账号仓库使用`account_cargo.cargo`。专用测试角色仓库存档解码为152槽空容器；非空内容、共享归属及金币边界由合成数据测试覆盖，不把这些测试冒充游戏客户端验收。未复制第三方仓库业务实现。

## NPK / IMG 图片格式参考（独立实现）

- `dof-dev/godof`，commit `7a272861f6c733386239702a0b023a7b7f2cbd3f`：`npk/npk.go`、`npk/file.go`、`npk/consts.go`、`npk/img/v2.go`、`v4.go`、`npk/image/`及`formatter/`的格式定义，用于核对NPK目录、IMG元数据、像素顺序及调色板布局。
- `HsOjo/PyDnfEx`，commit `e417cefe43f54a40e20ef0df235aa1c8ecd8595a`：`pydnfex/img/image/link.py`，用于交叉核对格式17链接帧字段。
- 2026-11-06追加核对上述godof同一提交的`npk/image/consts.go`：格式18／19／20对应DXT1／3／5，压缩5／6分别raw／zlib。只读取格式定义，不采用其解码器或未验证的通用像素长度表。
- Microsoft官方Direct3D文档：`MicrosoftDocs/win32`的`desktop-src/direct3d10/d3d10-graphics-programming-guide-resources-block-compression.md`（核对时blob `4ff2dd9c512dddc7cc071ff234e5fefbcf5defd4`），以及Direct3D9的Opaque and 1-Bit Alpha Textures、Textures with Alpha Channels。用于独立实现BC1／BC2／BC3块布局、RGB565、显式／插值Alpha、物理块边界；不复制文档代码或插图。
- `npk_assets.py`、`asset_builder.py`独立实现；未复制这些项目代码、图片、客户端或素材，不将其安装为运行依赖。格式实现已进行合成数据测试，但尚缺匹配客户端NPK实物验证。支持与未支持范围见`docs/ASSETS.md`。

## ANI 默认站姿与装扮图层（独立实现）

- 格式资料：`sjy0727/DNFToolKit`，commit `c4d08cec8f675af1c8a640e27737502133eee49e` 的 `dnf-toolkit-pvf/src/main/java/com/dnf/toolkit/pvf/parser/AniParser.java`。仅核对二进制帧／路径／参数段与参数载荷类型；该文件中的二进制转换器为注释状态，不作为可直接使用的依赖。
- `character_assets.py` 独立实现有界 ANI 读取、CHR／EQU／LAY 精确身份核对与直通 Alpha 合成，未复制 Java 实现、第三方业务代码或客户端图片。未知参数、变换、冲突来源、缺失装扮映射均拒绝，不扫描二进制猜帧。
- 2026-11-09 使用部署者本地匹配客户端，离线解析出 11 个基础职业的默认着装等待首帧，并验证 5 个显式上衣配方可合成；透明 1×1／压缩 0×0 空图层经过像素／解压验证，不放宽物品图标解码器的越界策略。这是离线素材及合成核对，不等于实际玩家穿戴、精确觉醒头像或游戏客户端逐项验收。
- 原始 NPK／PVF、PNG、派生清单与配方包只保留在私有素材目录，不随源码或 Release 分发。能力和边界见 `docs/CHARACTER-APPEARANCE.md`。


## 解锁申请与存档关联（独立适配）

- 61字节槽位及增幅字段起点17沿用上述固定版本格式参考；该参考将20附近字段列为未知，因此不以第三方名称作为锁键证据。
- 针对当前部署的清风1031二进制作只读反汇编：`stAmplifyOption_t::GetLock()`读取结构内偏移3，`_verifyInventory`中物品与增幅指针相差17，故槽位字节20对应锁键。2026-11-04复核验证函数221条机器指令、GetLock六条机器指令与先前证据一致。此关联仅适用于已指纹适配的镜像，不推广至任意服务端。
- `unlock_center.py`独立实现，不包含第三方业务代码、游戏二进制、反汇编原文或玩家存档。当前生产只读检查未发现活跃申请；正向关联和游戏解除效果尚未验收，合成关联测试不是客户端证据。
