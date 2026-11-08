# 私有图片包与可视化物品视图

> 当前状态（2026-11-08）：已取得与维护实例 PVF 完全匹配的本地客户端。1,585 个 NPK 目录可读，66,456 项物品中 66,450 项已解析为图标，去重后 29,195 张 PNG；另保留原 11 职业官方宣传插画。剩余 3 项缺客户端成员、1 项无引用、2 项引用帧越界，未假填成功。构建／安装和验证范围见[本批报告](reports/CLIENT-ASSETS-20261108.md)。

## 本期素材安排（2026-11-08）

维护者已提供匹配的本地 `ImagePacks2` 与 `Script.pvf`，此前“素材暂缓”安排结束。原始文件、提取 PNG、物品索引和图片包只用于私有部署，不进入开源仓库或 Release。公开截图继续使用合成数据／占位图；公开版具备相同解析与显示能力，需自行提供有权使用的素材。

图片可解析、PVF 指纹一致和浏览器可显示分别核对，`client_verified` 仍为 false；尚未逐项在运行中的游戏客户端核对视觉效果。职业宣传插画继续明确标注，未冒充当前像素职业头像或角色实际外观。

本模块提供离线客户端图片解析、PVF版本绑定、需登录的图片接口，以及物品图标、职业头像、角色容器格子/列表与详情。**功能链路可用不代表已取得或验收真实游戏素材**。公开仓库不包含NPK、PVF、真实PNG、派生索引或真实玩家数据。

## 1. 在维护电脑生成，不在小内存服务器解析

使用部署者有权使用、与服务器版本匹配的客户端 `ImagePacks2` 目录及服务器匹配的PVF、物品索引。工具只读取指定目录下的 `.npk` 文件，不递归遍历其他磁盘。

```bash
PYTHONPATH=src .venv/bin/python tools/build_assets.py \
  /private/Script.pvf /private/catalog.sqlite /private/game-assets/new-version \
  --npk-dir /private/client/ImagePacks2 \
  --portraits /private/portraits.json
```

- 输出必须是**不存在的新目录**；不覆盖正在使用的包。
- `--portraits`可省略。头像是显式映射的授权PNG，不从职业编号猜测图片文件，也不把人物身体帧冒充职业头像。
- `--npk-dir`可省略以检查PVF引用覆盖；此模式只有引用和缺失状态，**不会产生真实物品图标**。
- PVF和catalog的SHA必须一致。包内记录源NPK文件名与SHA用于私下追踪，不通过HTTP返回这些路径或文件名。
- 头像映射 JSON 使用 UTF-8 编码，Windows 的中文路径和来源标签无需改为系统代码页。
- 同名IMG存在于多份NPK时标为冲突，不按任意文件顺序覆盖；维护者应选择经过核验的明确来源目录后重新生成。
- 工具失败清理本次新输出，不修改已有资源包。应保留旧包用于回滚。

头像映射文件的示例（使用合适的本地PNG路径）：

```json
[
  {"job":0,"grow_type":1,"sex":0,"png":"portraits/example.png"},
  {"job":1,"grow_type":-1,"sex":-1,"png":"portraits/example-fallback.png"}
]
```

`-1`表示维护者明确指定的通配映射；优先匹配确切转职和性别。PNG限RGB/RGBA8、非交错、最大512×512和2MiB；重新编码会去掉附加文本等元数据。示例编号并非对某职业素材正确性的认证。

## 2. 支持范围与错误语义

- NPK目录、IMG v2/v4、ARGB1555/ARGB4444/BGRA8888、raw/zlib、链接帧及v4调色板；透明画布复原。
- 新增DXT1／DXT3／DXT5标准块解码（格式18／19／20），支持zlib包裹及声明长度准确的raw块。4×4块按行读取，支持边缘不足4像素的裁剪、透明画布及链接帧；独立处理DXT1透明模式、DXT3显式Alpha和DXT5两种Alpha插值。
- v1/v5、sprite压缩7及palette与DXT混合组合仍未适配；raw DXT声明长度与标准物理块长度不符时不猜测后续帧偏移。明确标为unsupported，不用空白图或错误色彩冒充成功。
- DXT格式能力仅由标准向量和合成NPK→IMG→PNG包验证，**不是已经取得真实物品图标或通过客户端实物核对**。不在网页请求里解析NPK，不新增Pillow、原生解码库或外部程序依赖。
- 同一 IMG 中未选中帧的越界放置不再连带拒绝正常图标；所有帧的尺寸与载荷边界仍检查，当前帧（包括链接目标）越界继续标为 unsupported。
- 图片尺寸、解压输出、目录数量、文件偏移、链接循环均有边界检查。这些只约束素材解析，不改变邮件道具发放数量规则。
- 状态区分ready、missing、missing_reference、ambiguous、unsupported；`client_verified`始终为false，本工具不替代客户端视觉核对。
- 当前引用不包含额外图标标记层、动画播放或角色时装纸娃娃。

输出结构：

```text
new-version/
  manifest.sqlite
  images/<PNG内容SHA256>.png
```

同内容图片去重。不会按NPK中提供的成员路径写文件，输出文件名只能是内容摘要。

## 3. 安装与回滚

先把完整新目录传至服务器私有目录，例如 `/var/lib/dnf-gm/game-assets/<版本>/`。用维护权限将目录设为root拥有、dnfgm组可读；目录0750、文件0640。运行账号不得对图片包有写权限。

在私有配置中设置：

```json
{"assets_dir":"/var/lib/dnf-gm/game-assets/<版本>"}
```

该字段默认为空，关闭图片功能不会关闭原有业务。设置配置后按常规升级流程仅重启GM服务，不重启游戏、mihomo、cliproxyapi或Docker。没有新增MySQL迁移、数据库授权、后台解析进程、公网端口或网页上传入口。

管理员登录后检查 `GET /dnf-gm/api/v1/assets/status`，再从物品查询返回的 `image.url`检查实际图片。检查同一物品名称/编号与图标、角色头像是否匹配，不将包状态ready等同于全部图片齐全。服务器新鲜PVF快照不匹配时图片被拒绝；快照过期时仍按配置与包的指纹校验，不宣称已实时核对服务器PVF。

回滚：将`assets_dir`恢复到之前的完整目录，或设为空，然后仅重启GM。不要边请求边覆盖清单/图片；图片URL绑定PVF与内容摘要，缺失或损坏返回404。切换图片包不改变礼包、邮件预览指纹或写权限，不使已经生成的业务预览失效。

## 4. 网页交互与安全

- 物品目录、邮件选物、礼包选物、收藏/最近、附件清单和角色容器显示图片。
- 角色详情支持格子/列表切换；格子保留存档槽位编号、数量和强化标记，30槽分页；筛选时不展示空格。空存档槽不表示游戏内已解锁格子。
- 点击物品打开只读详情；手机使用单列详情布局，保持收起/焦点恢复。手机物品详情已使用独立底部抽屉；完整人物外观仍未实现，不将其宣称为纸娃娃。
- 头像/图标未安装、缺失、版本不符或加载失败时保留文字与说明，不影响数量填写或奖励操作。
- 图片地址仅接受同源固定API格式；不可由物品名称注入HTML或外部URL。接口需要管理员会话，返回PNG与nosniff/no-store，登出后不提供公开静态资源绕过鉴权。
- 服务端只查询只读SQLite和小PNG；不导入PVF/NPK解析器，不接受客户端提供的磁盘路径，拒绝图片目录、文件和manifest符号链接、未登记摘要或摘要不一致内容。

## 5. 尚未完成的验收

历史状态（截至2026-11-04，已由上方2026-11-08进展更新）：本地真实PVF的66,456项中，66,455项有图片引用，1项没有可用引用；已搜索的本地目录未发现匹配NPK。真实图标、真实职业头像和具体客户端格式覆盖**未验证**。现有测试只用合成图像，测试图片不作为游戏素材交付。此开发批次未发布、未部署。

## 2026-11-05 生产界面更新

`5962f8b` 已部署分组穿戴格子和默认格子视图，未知扩展槽位仍保留，不猜测用途。首页使用随源码发布的原创 SVG 几何装饰，不是从 DNF 提取的素材。真实匹配的 NPK 图标/职业头像仍未安装，缺图状态继续明确显示。

## 2026-11-05 原创城镇插画与角色导航

首页和登录页使用原创蓝调城镇插画，不是官方DNF图片、物品图标或职业肖像。生成工具为内置 ImageGen；原始2048×683 PNG保留在维护电脑生成目录，不作为运行依赖。源码保存压缩后的 `web/src/assets/town-dusk.webp`（1600像素宽，约51KB）与 `town-dusk-small.webp`（800像素宽，约14KB），通过Vite输出带摘要URL。后处理仅等比例缩小及WebP编码，没有增加游戏素材。首页图片使用空alt、装饰语义和暗色遮罩；手机选择小图，控件及字体保留CPAMC主题变量；没有新增动画。

角色详情14个入口按角色资料、装备与仓储、维护与排查、邮件与记录分组；手机使用分组下拉菜单。保留方向键/Home/End、操作忙碌状态及原确认规则。修复任务、改名、救援页重复tabpanel ID及误显示空容器错误的问题。没有修改业务API、权限或物品数量规则。

### 最终生成提示词

```text
Create a polished ORIGINAL decorative background illustration for a Chinese fantasy action-RPG server administration web dashboard. This is a project UI asset, NOT a screenshot or interface mockup. Panoramic composition, approximately 3:1 wide aspect ratio if possible. Quiet deserted medieval fantasy town at blue-hour dusk, finely hand-painted 2D side-scrolling action RPG atmosphere, weathered stone gate, modest timber rooftops, distant monumental floating stone ruins, a small warm amber magic crystal near the gate, desaturated charcoal-blue and slate, restrained warm copper light. No characters needed. Keep the LEFT 55 percent dark, very low contrast, almost empty atmospheric sky and soft distant silhouettes so white interface text can be overlaid by code. Put the detailed architecture and warm focal light only in the RIGHT 40 percent. Elegant understated professional tool aesthetic, not a flashy game advertisement, no neon, no saturated purple, no confetti. Subtle painterly textures, beautiful controlled lighting, crisp artistic background, absolutely no text, logos, UI widgets, numbers, buttons, watermarks, or recognizable copyrighted character designs. It should feel inspired by classic dungeon-fighting games but remain an original fictional environment. No frame or border.
```

素材仍不能代替缺失的匹配NPK；真实职业头像和道具图标未齐备的现状不变。

生产发布：`20261105-artwork-5d26cc5`，2026-11-05。针对性导航测试1条及前端构建通过，公网桌面/手机只读冒烟通过；保护服务PID未改变，未修改玩家数据。

## 2026-11-06：带出处的职业插画与覆盖诊断

新增「功能与版本 → 图片与职业头像」：图标可读取比例、缺失／无引用／冲突／不支持格式明细、分页和编号复制，以及职业头像映射预览。查询仅登录管理员可用，无额外权限开关，不披露NPK成员名、本地路径或私有配置。图片仍通过登录鉴权接口交付，不使用公开静态目录或第三方热链。

支持在**新图片包**中合并明确映射的头像并记录出处：

```bash
PYTHONPATH=src .venv/bin/python tools/enrich_asset_portraits.py \
  /private/existing-pack /private/portrait-map.json /private/new-pack
```

```json
[
  {"job":0,"grow_type":-1,"sex":-1,"png":"prepared.png",
   "kind":"official_promotional","label":"DNF官方职业插画",
   "page":"https://dnf.qq.com/act/a20241120yz/adventurer/index.html",
   "focus_x":50,"focus_y":20}
]
```

- PNG仍需提前在维护电脑准备为不超过512×512、2MiB的RGB/RGBA8非交错文件。程序重新编码去除附加文本，不在服务器解析大图。
- `kind`区分`official_promotional`（官方宣传插画）、`client`（维护者指定的客户端职业图）、`custom`（维护者示意图）；前者不会标成匹配当前NPK或角色实际外观。
- `grow_type:-1`是基础职业示意，不冒充精确转职／觉醒头像。若有独立匹配来源，可提供确切成长代码；查找时只屏蔽成长类型独立高位，不改动角色存档。
- `focus_x`／`focus_y`是浏览器展示焦点，范围0–100；物品像素图展示规则不变。
- 原物品图片引用与状态逐条保留，来源包不修改，输出拒绝覆盖。运行时只读小SQLite与小PNG，不导入离线PNG/NPK解析器。

本批准备了11种基础职业的官方设定站插画映射，使用公开页面中明确的职业编号对应关系，黑暗武士／缔造者按官方配置分别核对。官方素材并无本项目开源再授权，不随源码、测试或GitHub分发；只安装在私有素材目录。现代宣传图与旧客户端像素素材严格区分，不能据此宣称当前客户端一致。

**物品图标仍缺匹配NPK：** 原66,456项图片引用记录保持，66,455项缺客户端成员、1项无可用引用；本批真实物品图标数为0。职业插画可展示不等于图标已补齐。部署状态见实施台账；早期“未部署”文字仅指对应历史批次。


## 2026-11-06 DXT离线适配

仅离线工具增加DXT1／3／5；原物品发放数量、金币上限、已安装图片包与网页权限不变。原始素材取得后须使用新目录重建图片包，再检查覆盖和当前PVF引用，不因解码器升级直接把旧missing记录改成ready。最小验证与发布状态见[分项报告](reports/DXT-ASSETS-20261106.md)。
