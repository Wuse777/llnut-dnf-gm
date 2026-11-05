# 私有图片包与可视化物品视图（开发版）

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
- v1/v5、DXT、其他压缩变体尚未适配；明确标为unsupported，不用空白图或错误色彩冒充成功。
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

截至2026-11-04：本地真实PVF的66,456项中，66,455项有图片引用，1项没有可用引用；已搜索的本地目录未发现匹配NPK。真实图标、真实职业头像和具体客户端格式覆盖**未验证**。现有测试只用合成图像，测试图片不作为游戏素材交付。此开发批次未发布、未部署。

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
