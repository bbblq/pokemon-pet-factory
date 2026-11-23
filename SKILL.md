---
name: pokemon-pet-factory
description: 将 GitHub PMDCollab/SpriteCollab 的宝可梦官方级逐帧素材一键转化为符合 Codex V2 / CoPets 标准的 AI Agent 桌面桌宠。支持中英文名称或全国图鉴编号检索，自动检测素材收录状态、下载、自适应缩放、合成 Agent 专属动作并部署。
---

# Pokémon AI Agent Pet Factory (宝可梦官方逐帧桌宠工坊)

本 Skill 提供将开源项目 [PMDCollab/SpriteCollab](https://github.com/PMDCollab/SpriteCollab) 的宝可梦逐帧动作素材，全自动转换为标准 **Codex V2 / CoPets** 规范 AI Agent 桌面宠物的完整工具链。

无需任何生图模型、无需 GPU 显卡、零 API 成本。直接采用宝可梦官方不可思议迷宫（PMD）的像素级动作资产，保证逐帧对齐且 0 残留噪点。

---

## 适用场景与触发机制

当用户提出以下需求时，激活本 Skill：
- “帮我做一个 [宝可梦名字] 桌宠”（例如：`帮我做一个皮卡丘`、`我要耿鬼`、`做一只伊布`、`可达鸭` 等）
- “有没有 [宝可梦名字] 的桌宠素材？”
- 输入全国图鉴编号（例如：`#25`、`0025`、`#133` 等）要求生成桌宠。

---

## 执行流程与交互规范

任何 AI Agent 在接收到用户的宝可梦桌宠制作请求时，按以下三步执行：

### 第一步：检测收录状态并引导询问用户的『视线追踪模式』（若用户未指定）

1. 先运行 `--check-only` 快速检查 SpriteCollab 是否收录该宝可梦及是否包含独立 `Head-Anim` 头部素材：
   ```bash
   python scripts/generate_pokemon_pet.py --query "<宝可梦名称或图鉴号>" --check-only
   ```
2. **引导询问用户偏好**（如果用户在提问时没有明确指定用哪种眼神/头部追踪方式）：
   向用户确认已找到该宝可梦的官方素材，并友好询问用户希望采用哪种 **Codex V2 鼠标视线追踪模式（Look Style）**（也可以询问待机姿态 `--idle-style`）：
   - **选项 1：`head`（头部+眼神 3D 联动，推荐）** —— 身体静止站立，头部随鼠标左右转动、上下俯仰微倾，同时瞳孔高光联动注视（若官方含 `Head-Anim.png` 则自动采用原版 8 向独立头部素材，否则智能拆分头身）；
   - **选项 2：`eyes`（纯眼球追踪）** —— 身体与头部保持正面静止，仅眼眶、瞳孔与高光随鼠标做 360° 16 方向灵动偏移；
   - **选项 3：`all`（我全都要：同时生成『眼球版』和『头部版』两套桌宠）** —— 一次性生成 `<id>-eyes` 和 `<id>-head` 两个桌宠包导入 Codex，方便在面板里随时切换对比；
   - **选项 4：`body`（原版 8 向全身转向）** —— 适合无明显五官/闭眼/异形宝可梦，整个身体随鼠标朝向旋转。

---

### 第二步：根据用户选择调用生成脚本

在终端中执行内置脚本 `generate_pokemon_pet.py`，传入用户的查询参数与选择的 `--look-style`：

```bash
# 生成头部追踪版（默认）
python scripts/generate_pokemon_pet.py --query "<宝可梦名称或图鉴号>" --look-style head

# 生成纯眼球追踪版
python scripts/generate_pokemon_pet.py --query "<宝可梦名称或图鉴号>" --look-style eyes

# 同时生成『眼球版』+『头部版』两套桌宠包
python scripts/generate_pokemon_pet.py --query "<宝可梦名称或图鉴号>" --look-style all

# 可选附加参数：--idle-style static|sleep|breathe  或自定义 --pet-id / --display-name
```

> **注意**：
> - 脚本内置了全世代 1~1025 只宝可梦的全国图鉴数据库（支持简体中文、繁体中文、英文、日文及数字编号）。
> - 全程采用纯确定性像素算法与原版素材拼装，单套生成耗时仅约 2 秒（零 AI 生图、零 GPU 成本）。

---

### 第三步：解析脚本返回的 JSON 结果并响应用户

脚本执行完毕后会输出标准 JSON。根据 `status` 字段，以友好自然的语气向用户汇报：

#### 情况 A：成功生成并部署 (`status == "SUCCESS"`)
- **脚本输出示例**：
  ```json
  {
    "status": "SUCCESS",
    "pokemon": { "id": 7, "dex": "0007", "en": "Squirtle", "zh_hans": "杰尼龟" },
    "lookStyle": "all",
    "packages": [
      { "petId": "squirtle-eyes", "name": "杰尼龟-眼球追踪 (Squirtle Eyes)" },
      { "petId": "squirtle-head", "name": "杰尼龟-头部追踪 (Squirtle Head)" }
    ],
    "message": "🎉 成功为【杰尼龟】(#0007 Squirtle) 生成 2 款官方逐帧 AI Agent 桌宠（视线模式: all）！"
  }
  ```
- **向用户回复要点**：
  1. 告知用户已成功基于官方 SpriteCollab 原版逐帧动画为该宝可梦制作完成（并说明所采用的视线追踪模式）；
  2. 简述包含的完整 Agent 动作（待机、左右迈步、打招呼、跳跃、工作专属招式特效、代码审查放大镜、16 方向鼠标视线追踪 + `Row 0 Col 6` 扩展中性基准帧）；
  3. 告知已部署至 `~/.codex/pets/` 及 `~/.copet/pets/` 目录，提示用户在 ChatGPT / Codex 桌面宠物面板中点击 Refresh 刷新即可切换体验！

#### 情况 B：SpriteCollab 尚未收录 (`status == "NOT_AVAILABLE_IN_SPRITECOLLAB"`)
- **向用户回复要点**：
  1. 明确如实告知：“目前 SpriteCollab 项目中还没有收录【XXX】的逐帧动作素材，社区民间画师仍在补充绘制中。”
  2. 推荐用户尝试已完备收录的经典角色（如皮卡丘、小火龙、妙蛙种子、杰尼龟、可达鸭、耿鬼、伊布、胖丁、超梦等）。

#### 情况 C：未识别名称 (`status == "NOT_FOUND_IN_POKEDEX"`)
- **向用户回复要点**：
  1. 提示未在全国宝可梦图鉴中找到该名称，确认是否输入了别名或其他作品角色；
  2. 引导用户提供标准中文译名、英文名或全国图鉴编号（如 `#7`、`#25`）。

---

## 规格标准（Codex V2 / CoPets）

生成图集完全符合以下技术规范并通过官方 `validate_atlas.py --require-v2` 严格校验：
- **尺寸规格**：`1536 × 2288` (8 列 × 11 行，单帧 `192 × 208` 像素)
- **动作映射表 (74 有效格 = 73 动画/注视帧 + 1 扩展中性注视帧 + 14 透明占位格)**：
  - Row 0: `idle` (Col `0~5` 为 6 帧待机动画；**Col `6` 为 V2 强制要求的 `EXTENDED_NEUTRAL_LOOK_FRAME` 扩展中性注视帧**；Col `7` 全透明)
  - Row 1: `running-right` (8 帧, 经典右向迈步走)
  - Row 2: `running-left` (8 帧, 经典左向迈步走)
  - Row 3: `waving` (4 帧, 鼠标点击/打招呼触发原 `Idle-Anim` 活跃动态与星光)
  - Row 4: `jumping` (5 帧, 下蹲蓄力 $\to$ 腾空滞空 $\to$ 下落冲击)
  - Row 5: `failed` (8 帧, 受击/眩晕/汗滴报错状态)
  - Row 6: `waiting` (6 帧, 左右探头张望等待用户输入)
  - Row 7: `running` (6 帧, 工作状态: 宝可梦专属招牌招式动作 + 属性特效粒子)
  - Row 8: `review` (6 帧, 审查状态: 放大镜全息扫描 + 绿色通过对勾)
  - Row 9 & 10: `look 1-16` (16 帧, 从 `000°` 正上方 12 点钟方向顺时针 360° 全方位 16 个精确注视朝向，支持 `eyes` / `head` / `body` 三种模式)
- **图集质量**：无损 WebP (`exact=True`) + PNG，完全消除 Alpha 透明像素的 RGB 残留值（`transparent_rgb_residue_pixels: 0`）。

