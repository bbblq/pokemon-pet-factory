# Pokémon AI Agent Pet Factory (跨 Agent 通用宝可梦桌宠 Skill)

一个开箱即用的跨平台 AI Agent Skill 与自动化工具包，直接将 [PMDCollab/SpriteCollab](https://github.com/PMDCollab/SpriteCollab) 项目中的 1000+ 宝可梦官方级逐帧动作素材，转化为无瑕疵的 **Codex V2 / CoPets** 标准 AI Agent 桌宠。

---

## 🌟 核心特性

- 🚀 **零生图模型，零 GPU 成本**：完全基于 SpriteCollab 原版像素资产与数学对齐，告别 AI 生图的抽搐、模糊与风格割裂。
- 🔍 **智能多语言识别**：支持输入中文（简体/繁体）、英文、日文或图鉴编号（如 `皮卡丘`、`Pikachu`、`#25`、`0025`）。
- 🛡️ **智能收录校验**：如果该宝可梦在 SpriteCollab 中尚未绘制完成（如部分第 9 世代角色），会自动告知用户并推荐可用角色；如果已收录，2 秒内完成下载、拼装、挂载 Agent 动作并部署。
- 🎨 **100% 符合 Codex V2 规范**：
  - 标准 `1536 × 2288` (8×11 单元格，单格 `192 × 208`)
  - 完整 11 种 Agent 生命周期（待机、左右行走、打招呼、跳跃、报错眩晕、等待输入、全息写代码、放大镜代码审查、360° 16方向视线追踪）
  - 自动通过 `validate_atlas.py` 官方校验（0 报错、0 警告、0 透明残留像素）。

---

## 📁 目录结构

```text
pokemon-pet-factory/
├── SKILL.md                         # 核心 Skill 规范文件（兼容各大 AI Agent）
├── README.md                        # 安装与使用说明
└── scripts/
    ├── generate_pokemon_pet.py      # 核心全自动转换与生成器
    └── pokemon_db.json              # 官方 1~1025 全世代全国图鉴多语言数据库
```

---

## 📦 如何安装给各类 AI Agent？

### 1. Antigravity IDE
将整个 `pokemon-pet-factory` 目录复制到 Antigravity 自定义技能目录：
```powershell
# 复制到全局技能目录
Copy-Item -Recurse "K:\PET\pokemon-pet-factory" "$HOME\.gemini\antigravity\builtin\skills\pokemon-pet-factory"
# 或放在当前工作区的 .gemini/skills/ 目录下
```

### 2. OpenAI Codex
复制到 Codex 技能目录：
```powershell
Copy-Item -Recurse "K:\PET\pokemon-pet-factory" "$HOME\.codex\skills\pokemon-pet-factory"
```

### 3. Claude Code / Cursor / Windsurf
直接在项目根目录创建 `.claude/skills/` 或保留在当前工作区即可，任何具有运行 Python 脚本能力的 AI Agent 都会自动读取 `SKILL.md` 并执行。

---

## 💻 命令行直接使用（无需 Agent 也能用）

你也可以在终端直接执行命令生成任意宝可梦：

```bash
# 生成皮卡丘
python scripts/generate_pokemon_pet.py --query "皮卡丘"

# 生成伊布
python scripts/generate_pokemon_pet.py --query "eevee"

# 生成耿鬼
python scripts/generate_pokemon_pet.py --query 94

# 仅检查 SpriteCollab 是否收录某只宝可梦
python scripts/generate_pokemon_pet.py --query "索财灵" --check-only
```

---

## 🧪 依赖环境

- Python 3.8+
- `Pillow`
- `requests`
- `numpy`
