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
