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

### 第一步：调用生成脚本

在终端中执行内置脚本 `generate_pokemon_pet.py`，传入用户的查询参数：

```bash
python scripts/generate_pokemon_pet.py --query "<宝可梦名称或图鉴号>"
```

> **注意**：
> - 脚本内置了全世代 1~1025 只宝可梦的全国图鉴数据库（支持简体中文、繁体中文、英文、日文及数字编号）。
> - 脚本会自动联网检测 SpriteCollab GitHub 仓库的素材收录状态。

---

### 第二步：解析脚本返回的 JSON 结果并响应用户

脚本执行完毕后会输出标准 JSON。根据 `status` 字段，以友好自然的语气向用户汇报：

#### 情况 A：成功生成并部署 (`status == "SUCCESS"`)
- **脚本输出示例**：
  ```json
  {
    "status": "SUCCESS",
    "pokemon": { "id": 25, "dex": "0025", "en": "Pikachu", "zh_hans": "皮卡丘" },
    "petId": "pikachu",
    "installPath": "C:\\Users\\...\\.codex\\pets\\pikachu",
    "message": "🎉 成功为【皮卡丘】(#0025 Pikachu) 生成官方逐帧 AI Agent 桌宠！"
  }
  ```
- **向用户回复要点**：
  1. 告知用户已成功基于官方 SpriteCollab 原版逐帧动画为该宝可梦制作完成；
  2. 简述包含的完整 Agent 动作（待机呼吸、左右迈步、跳跃、工作写代码全息屏、代码审查通过、16方向视线追踪等）；
  3. 告知已部署至桌宠目录，提示用户在桌面宠物面板中切换或刷新即可立即看到！

#### 情况 B：SpriteCollab 尚未收录 (`status == "NOT_AVAILABLE_IN_SPRITECOLLAB"`)
- **脚本输出示例**：
  ```json
  {
    "status": "NOT_AVAILABLE_IN_SPRITECOLLAB",
    "pokemon": { "id": 999, "dex": "0999", "en": "Gimmighoul", "zh_hans": "索财灵" },
    "message": "【索财灵】(#0999 Gimmighoul) 暂未收录在 SpriteCollab 项目中..."
  }
  ```
- **向用户回复要点**：
  1. 明确如实告知：“目前 SpriteCollab 项目中还没有收录【XXX】的逐帧动作素材，社区民间画师仍在补充绘制中。”
  2. 推荐用户尝试已完备收录的经典角色（如皮卡丘、小火龙、妙蛙种子、杰尼龟、可达鸭、耿鬼、伊布、超梦等）。

#### 情况 C：未识别名称 (`status == "NOT_FOUND_IN_POKEDEX"`)
- **向用户回复要点**：
  1. 提示未在全国宝可梦图鉴中找到该名称，确认是否输入了别名、数码宝贝或其他角色；
  2. 引导用户提供标准中文译名、英文名或全国图鉴编号（如 `#25`）。

---

## 规格标准（Codex V2 / CoPets）

生成图集完全符合以下技术规范并通过 `validate_atlas.py` 严格校验：
- **尺寸规格**：`1536 × 2288` (8 列 × 11 行，单帧 `192 × 208` 像素)
- **动作映射表 (73 独立帧 + 15 占位帧)**：
  - Row 0: `idle` (6 帧, 默认静止站姿，不频繁晃动；可通过 `--idle-style static|sleep|breathe` 切换为打盹或微呼吸)
  - Row 1: `running-right` (8 帧, 经典右向迈步走)
  - Row 2: `running-left` (8 帧, 经典左向迈步走)
  - Row 3: `waving` (4 帧, 鼠标点击/打招呼触发原 `Idle-Anim` 活跃动态与星光)
  - Row 4: `jumping` (5 帧, 下蹲蓄力 $\to$ 腾空滞空 $\to$ 下落冲击)
  - Row 5: `failed` (8 帧, 受击/眩晕/汗滴报错状态)
  - Row 6: `waiting` (6 帧, 探头张望等待用户输入)
  - Row 7: `running` (6 帧, 工作状态: 攻击聚气 + 赛博全息代码终端)
  - Row 8: `review` (6 帧, 审查状态: 放大镜全息扫描 + 绿色通过对勾)
  - Row 9 & 10: `look 1-16` (16 帧, 顺时针 360° 全方位 16 个精确注视朝向)
- **图集质量**：无损 WebP + PNG，完全消除 Alpha 透明像素的 RGB 残留值（0 残留）。
