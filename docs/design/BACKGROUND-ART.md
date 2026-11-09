# 工作台背景素材

2026-11-09 使用内置 imagegen 工具生成原创奇幻场景，保存在 `web/src/assets/arad-sky-city-v1.webp`；手机编码版本为 `arad-sky-city-mobile-v1.webp`。这是 DNF／阿拉德冒险氛围的原创场景，不是官方宣传壁纸、真实地图截图或客户端提取文件。

使用位置为登录页和工作台横幅。文字区域加深浅遮罩，表单保持不透明；手机使用较小的 WebP。背景不承载任何业务状态，缺图不会影响操作。

最终生成提示词：

> Use case: stylized-concept. Asset type: high-resolution website background for a Chinese DNF game master admin workspace. Generate a polished original fantasy game environment illustration inspired by the adventurous atmosphere of Dungeon & Fighter / Arad, not a UI mockup. Panoramic 16:9 landscape, ideally 2560x1440 or larger. An ancient pale-stone sky citadel with slender spires rises from a coastal mountain city into luminous clouds, weathered blue roofs, a narrow cobbled path leading from the lower-left toward the distant towers, a few warm golden lanterns and banners; subtle floating ruins in the far distance. Layered mountains, atmospheric depth, intricate hand-painted 2D action RPG background art with crisp architecture and restrained detail, contemporary premium game key art finish. Color palette: blue-hour indigo, muted periwinkle, slate blue, warm amber highlights, soft cloud ivory. Composition: architecture and strongest detail concentrated in the left two-thirds and center distance, right third calm mist/clouds suitable to sit behind a solid white login card; center/top includes clear scenic focal points that also work as a shallow desktop dashboard banner crop. Mood: adventurous and serene, spectacular sense of scale, tasteful, rich but not neon. No characters, no guns, no UI, no text, no logos, no watermark, no borders. Full opaque image, no transparent background.

原始生成结果为 1672×941 PNG。只对输出做 WebP 编码及手机等比缩小，不在服务端运行生图或原始图片处理。原始生成文件留在维护者本机；公开仓库只包含用于网页的压缩版本。

## 公会补给台 · v0.6.4

2026-11-09 同样通过内置 imagegen 生成原创场景，用于物品目录及奖励编辑器的短横幅。背景中的武器、包裹和卷轴是装饰，不能视为真实游戏物品。图标、职业插画和纸娃娃仍走私有游戏素材链路。

- 网页素材：`web/src/assets/arad-guild-counter-v1.webp`，1672×941，182,514 字节。
- 手机素材：`web/src/assets/arad-guild-counter-mobile-v1.webp`，800×450，48,782 字节。
- 只随对应业务页面加载；文字有独立的实色背景渐变，暗色降低图片亮度，图片不承载操作状态。

最终生成提示词：

> Use case: stylized-concept. Asset type: original fantasy environment artwork for a compact decorative banner in a Chinese Dungeon & Fighter GM admin application. Primary request: an adventurers' guild supply counter in an Arad-inspired hand-painted 2D action RPG world, matching a pale stone sky city and restrained blue-violet admin theme. Scene: warmly lit pale-stone guild room, an elegantly crafted wooden counter with a few neatly wrapped reward parcels and sealed parchment scrolls, small brass coin trays, a beautifully crafted sword in a stand in the background and an open arched window overlooking distant blue mountains and floating stone ruins. No people. This is scenic atmosphere, not an item icon or an inventory UI. Composition: panoramic landscape 16:9, render at high resolution; strongest objects and rich architectural detail in right two-thirds, left third quiet atmospheric blue shadow so this image can be cropped into a shallow 3:1 web banner. Eye-level cinematic framing, visually tidy composition. Style: premium hand-painted fantasy game key art, finely detailed materials, clean shapes, soft atmospheric depth, subtle warm gold accents, cool indigo and slate blue shadows, no neon. Constraints: original environment rather than an official screenshot. No characters, no text, no letters, no logos, no watermarks, no UI, no borders, full opaque background.
