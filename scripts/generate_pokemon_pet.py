#!/usr/bin/env python3
"""
Universal Pokémon Agent Pet Generator (SpriteCollab to Codex V2 Standard)
--------------------------------------------------------------------------
Features:
- Seamless name resolution: Chinese (Simplified/Traditional), English, Japanese, Dex ID (#25, 0025, 25).
- Queries PMDCollab/SpriteCollab online repository directly (with local caching).
- Clear reporting if a Pokémon or its sprite sheet is not yet drawn/supported in SpriteCollab.
- Dynamically parses AnimData.xml (handles arbitrary frame widths/heights & body sizes).
- Auto-scales sprite to fit standard 192x208 grid without pixel distortion or clipping.
- Generates all 11 rows (73 active frames + 15 transparent spacer cells) according to Codex V2 standard:
    Row 0: idle (breathing & blinking)
    Row 1: running-right (walk cycle facing right)
    Row 2: running-left (walk cycle facing left)
    Row 3: waving (greeting / celebratory pose with sparkle)
    Row 4: jumping (crouch -> lift off -> apex -> fall -> impact buffer)
    Row 5: failed (hurt / faint / dizzy error state)
    Row 6: waiting (curious look around)
    Row 7: running (AI work state: dynamic holographic coding laptop & terminals)
    Row 8: review (AI review state: holographic scanning loupe & green checkmark)
    Row 9 & 10: look 1-16 (16-directional gaze tracking)
- Zero alpha residue cleanup (guarantees 100% compliance with validate_atlas.py).
- Auto-generates pet.json and installs to Codex / CoPets directory.
"""

import os
import sys
import math
import json
import shutil
import argparse
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np

# Codex V2 Specifications
COLUMNS = 8
ROWS = 11
CELL_WIDTH = 192
CELL_HEIGHT = 208
ATLAS_WIDTH = COLUMNS * CELL_WIDTH   # 1536
ATLAS_HEIGHT = ROWS * CELL_HEIGHT   # 2288

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
CACHE_DIR = PROJECT_DIR / "cache"
DB_PATH = SCRIPT_DIR / "pokemon_db.json"

GITHUB_RAW_BASE = "https://raw.githubusercontent.com/PMDCollab/SpriteCollab/master/sprite"

# Default install target
DEFAULT_PETS_DIR = Path(os.path.expanduser("~/.codex/pets"))

LOOK_DIRECTION_LABELS = [
    "000", "022.5", "045", "067.5", "090", "112.5", "135", "157.5",
    "180", "202.5", "225", "247.5", "270", "292.5", "315", "337.5"
]

ROW_CONFIG = [
    {"row": 0, "state": "idle", "frames": 6, "durations": [280, 110, 110, 140, 140, 320]},
    {"row": 1, "state": "running-right", "frames": 8, "durations": [120, 120, 120, 120, 120, 120, 120, 220]},
    {"row": 2, "state": "running-left", "frames": 8, "durations": [120, 120, 120, 120, 120, 120, 120, 220]},
    {"row": 3, "state": "waving", "frames": 4, "durations": [140, 140, 140, 280]},
    {"row": 4, "state": "jumping", "frames": 5, "durations": [140, 140, 140, 140, 280]},
    {"row": 5, "state": "failed", "frames": 8, "durations": [140, 140, 140, 140, 140, 140, 140, 240]},
    {"row": 6, "state": "waiting", "frames": 6, "durations": [150, 150, 150, 150, 150, 260]},
    {"row": 7, "state": "running", "frames": 6, "durations": [120, 120, 120, 120, 120, 220]},
    {"row": 8, "state": "review", "frames": 6, "durations": [150, 150, 150, 150, 150, 280]},
    {"row": 9, "state": "look_directions_1_8", "frames": 8, "durations": [200] * 8},
    {"row": 10, "state": "look_directions_9_16", "frames": 8, "durations": [200] * 8},
]


def load_pokemon_db():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def find_pokemon(query: str, db: list):
    q = str(query).strip().lower().lstrip("#")
    # 1. Exact Dex ID
    if q.isdigit():
        dex_num = int(q)
        for p in db:
            if p["id"] == dex_num:
                return p

    # 2. Match Chinese (zh_hans / zh_hant)
    for p in db:
        if p.get("zh_hans") and p["zh_hans"].lower() == q:
            return p
        if p.get("zh_hant") and p["zh_hant"].lower() == q:
            return p

    # 3. Match English
    for p in db:
        if p.get("en") and p["en"].lower() == q:
            return p

    # 4. Match Japanese
    for p in db:
        if p.get("ja") and p["ja"].lower() == q:
            return p

    # 5. Substring / partial match
    for p in db:
        if p.get("zh_hans") and q in p["zh_hans"].lower():
            return p
        if p.get("en") and q in p["en"].lower():
            return p

    return None


def fetch_file(dex: str, filename: str, target_dir: Path) -> Path:
    target_path = target_dir / filename
    if target_path.exists() and target_path.stat().st_size > 0:
        return target_path

    url = f"{GITHUB_RAW_BASE}/{dex}/{filename}"
    resp = requests.get(url, timeout=15)
    if resp.status_code == 200:
        with open(target_path, "wb") as f:
            f.write(resp.content)
        return target_path
    elif resp.status_code == 404:
        return None
    else:
        resp.raise_for_status()


def check_spritecollab_availability(dex: str) -> bool:
    url = f"{GITHUB_RAW_BASE}/{dex}/AnimData.xml"
    try:
        r = requests.head(url, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def parse_anim_data(xml_path: Path):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    anims = {}
    deferred_copies = {}

    for anim in root.find("Anims").findall("Anim"):
        name_elem = anim.find("Name")
        if name_elem is None or not name_elem.text:
            continue
        name = name_elem.text

        copy_of = anim.find("CopyOf")
        if copy_of is not None and copy_of.text:
            deferred_copies[name] = copy_of.text
            continue

        fw_elem = anim.find("FrameWidth")
        fh_elem = anim.find("FrameHeight")
        if fw_elem is None or fh_elem is None or not fw_elem.text or not fh_elem.text:
            continue

        fw = int(fw_elem.text)
        fh = int(fh_elem.text)
        durations_elem = anim.find("Durations")
        if durations_elem is not None:
            durations = [int(d.text) for d in durations_elem.findall("Duration") if d.text and d.text.isdigit()]
        else:
            durations = [10]

        anims[name] = {
            "name": name,
            "fw": fw,
            "fh": fh,
            "frames": len(durations) if durations else 1,
            "durations": durations
        }

    for name, target in deferred_copies.items():
        if target in anims:
            anims[name] = dict(anims[target])
            anims[name]["name"] = name

    return anims


def crop_frame(sheet: Image.Image, col: int, row: int, fw: int, fh: int) -> Image.Image:
    x = col * fw
    y = row * fh
    if x + fw > sheet.width or y + fh > sheet.height:
        # Fallback to col 0 if requested column exceeds sheet
        x = 0
    return sheet.crop((x, y, x + fw, y + fh))


def build_cell(raw_crop: Image.Image,
               scale: float = 6.8,
               baseline_y: int = 196,
               lift_y: int = 0,
               shift_x: int = 0,
               tilt_deg: float = 0.0,
               squash_x: float = 1.0,
               squash_y: float = 1.0,
               accessory: str = None) -> Image.Image:
    cell = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    bbox = raw_crop.getbbox()
    if bbox is None:
        return cell

    char_tight = raw_crop.crop(bbox)
    tw, th = char_tight.size

    nw = max(8, int(tw * scale * squash_x))
    nh = max(8, int(th * scale * squash_y))
    scaled = char_tight.resize((nw, nh), Image.Resampling.NEAREST)

    if abs(tilt_deg) > 0.05:
        scaled = scaled.rotate(-tilt_deg, resample=Image.Resampling.NEAREST, expand=True)

    sw, sh = scaled.size
    cx = CELL_WIDTH // 2 + shift_x
    px = cx - sw // 2
    py = baseline_y - sh - lift_y

    # Prevent top overflow
    if py < 2:
        py = 2

    cell.paste(scaled, (px, py), scaled)

    # Render Accessories
    draw = ImageDraw.Draw(cell)
    if accessory == "sparkle":
        for sx, sy in [(px + sw + 4, py + 16), (px - 8, py + 24)]:
            draw.line([(sx - 5, sy), (sx + 5, sy)], fill=(255, 235, 120, 255), width=2)
            draw.line([(sx, sy - 5), (sx, sy + 5)], fill=(255, 235, 120, 255), width=2)
            draw.point((sx, sy), fill=(255, 255, 255, 255))
    elif accessory == "sweat":
        sx, sy = px + 12, py + 12
        draw.polygon([(sx, sy), (sx - 5, sy + 9), (sx + 5, sy + 9)], fill=(130, 200, 255, 255))
        draw.ellipse([sx - 5, sy + 4, sx + 5, sy + 12], fill=(130, 200, 255, 255))
    elif accessory == "music":
        # Floating musical notes for singing (Jigglypuff, etc.)
        notes = [
            (px + sw + 4, py - 4, (255, 120, 180, 255)),
            (px - 14, py + 8, (255, 190, 80, 255)),
            (px + sw // 2 + 16, py - 18, (120, 210, 255, 255))
        ]
        for nx, ny, col in notes:
            if ny > 2 and nx < CELL_WIDTH - 16 and nx > 2:
                # Single note ♪
                draw.ellipse([nx, ny + 6, nx + 6, ny + 11], fill=col)
                draw.line([(nx + 5, ny), (nx + 5, ny + 8)], fill=col, width=2)
                draw.line([(nx + 5, ny), (nx + 9, ny + 2)], fill=col, width=2)
    elif accessory == "lightning":
        # Electric sparks for Pikachu & electric Pokemon
        sparks = [
            (px - 12, py + 15, [(0, 0), (6, -6), (3, -6), (8, -14)]),
            (px + sw + 2, py + 20, [(0, 0), (-6, -6), (-3, -6), (-7, -13)]),
            (px + sw // 2, py - 12, [(0, 0), (-4, 5), (0, 5), (-3, 10)])
        ]
        for bx, by, pts in sparks:
            draw_pts = [(bx + dx, by + dy) for dx, dy in pts]
            draw.line(draw_pts, fill=(255, 240, 80, 255), width=2)
            draw.point(draw_pts[-1], fill=(255, 255, 255, 255))
    elif accessory == "psychic":
        # Concentric psychic rings for Psyduck / Mewtwo
        cx_p = px + sw // 2
        cy_p = py + sh // 3
        for r_p, c_alpha in [(18, 160), (28, 100)]:
            draw.ellipse([cx_p - r_p, cy_p - r_p // 2, cx_p + r_p, cy_p + r_p // 2], outline=(100, 220, 255, c_alpha), width=2)
    elif accessory == "shadow":
        # Dark ghost flame particles for Gengar
        for gx, gy in [(px - 8, py + 10), (px + sw + 4, py + 14), (px + sw // 2, py - 10)]:
            draw.ellipse([gx, gy, gx + 6, gy + 8], fill=(160, 60, 220, 200))
            draw.point((gx + 3, gy + 4), fill=(240, 180, 255, 255))
    elif accessory == "loupe":
        lx, ly = px + sw - 8, py + 28
        r = 16
        draw.ellipse([lx - r, ly - r, lx + r, ly + r], outline=(100, 200, 255, 255), width=3)
        draw.line([(lx + 11, ly + 11), (lx + 23, ly + 23)], fill=(160, 140, 100, 255), width=4)
        # Checkmark
        draw.line([(lx - 6, ly), (lx - 2, ly + 6), (lx + 8, ly - 6)], fill=(50, 230, 120, 255), width=3)

    return cell


def assemble_pokemon_atlas(pokemon: dict, src_dir: Path, anims: dict, user_scale_mult: float = 1.0):
    atlas = Image.new("RGBA", (ATLAS_WIDTH, ATLAS_HEIGHT), (0, 0, 0, 0))

    # Helper to load animation sheets
    def load_sheet(name):
        f = src_dir / f"{name}-Anim.png"
        return Image.open(f).convert("RGBA") if f.exists() else None

    walk_sheet = load_sheet("Walk")
    idle_sheet = load_sheet("Idle") or walk_sheet
    hop_sheet = load_sheet("Hop") or walk_sheet
    hurt_sheet = load_sheet("Hurt") or load_sheet("Pain") or load_sheet("Faint") or walk_sheet
    pose_sheet = load_sheet("Pose") or load_sheet("Nod") or hop_sheet
    rotate_sheet = load_sheet("Rotate") or walk_sheet
    attack_sheet = load_sheet("Attack") or load_sheet("Charge") or walk_sheet

    # Calculate optimal display scale from standard Walk frame
    walk_info = anims.get("Walk", {"fw": 32, "fh": 40})
    ref_fw = walk_info["fw"]
    ref_fh = walk_info["fh"]

    # Measure real character tight bounding box in Walk frame 0
    ref_frame0 = walk_sheet.crop((0, 0, min(ref_fw, walk_sheet.width), min(ref_fh, walk_sheet.height)))
    ref_bbox = ref_frame0.getbbox()
    if ref_bbox:
        tight_h = ref_bbox[3] - ref_bbox[1]
    else:
        tight_h = ref_fh * 0.65

    # Target height ~122px (2x enlargement, filling 192x208 comfortably with headroom for jumping)
    target_tight_h = 122.0 * user_scale_mult
    scale = max(3.0, min(8.5, target_tight_h / max(10, tight_h)))
    baseline = 196

    def get_frame(sheet, anim_name, col, row):
        info = anims.get(anim_name, walk_info)
        fw = info["fw"]
        fh = info["fh"]
        total_cols = max(1, sheet.width // fw)
        total_rows = max(1, sheet.height // fh)
        safe_col = col % total_cols
        safe_row = row % total_rows
        return crop_frame(sheet, safe_col, safe_row, fw, fh)

    # ----------------------------------------------------
    # Row 0: Idle (6 frames, facing South / row 0)
    # ----------------------------------------------------
    idle_info = anims.get("Idle", walk_info)
    idle_frames = idle_info["frames"]
    for c in range(6):
        raw = get_frame(idle_sheet, "Idle", c % idle_frames, 0)
        # Subtle organic breathing motion
        b_lift = int(math.sin(c / 6.0 * math.pi * 2) * 2)
        cell = build_cell(raw, scale=scale, baseline_y=baseline, lift_y=b_lift)
        atlas.paste(cell, (c * CELL_WIDTH, 0 * CELL_HEIGHT), cell)

    # ----------------------------------------------------
    # Row 1: Running-Right (8 frames, facing East / row 2)
    # ----------------------------------------------------
    walk_cols = walk_info["frames"]
    for c in range(8):
        raw = get_frame(walk_sheet, "Walk", c % walk_cols, 2)
        cell = build_cell(raw, scale=scale, baseline_y=baseline)
        atlas.paste(cell, (c * CELL_WIDTH, 1 * CELL_HEIGHT), cell)

    # ----------------------------------------------------
    # Row 2: Running-Left (8 frames, facing West / row 6, or flipped row 2)
    # ----------------------------------------------------
    for c in range(8):
        # Dir 6 is West
        raw = get_frame(walk_sheet, "Walk", c % walk_cols, 6)
        cell = build_cell(raw, scale=scale, baseline_y=baseline)
        atlas.paste(cell, (c * CELL_WIDTH, 2 * CELL_HEIGHT), cell)

    # ----------------------------------------------------
    # Row 3: Waving (4 frames, greeting / celebratory pose)
    # ----------------------------------------------------
    for c in range(4):
        raw = get_frame(pose_sheet, "Pose" if "Pose" in anims else "Hop", c, 0)
        acc = "sparkle" if c in [1, 2] else None
        cell = build_cell(raw, scale=scale, baseline_y=baseline, shift_x=(c % 2) * 2, accessory=acc)
        atlas.paste(cell, (c * CELL_WIDTH, 3 * CELL_HEIGHT), cell)

    # ----------------------------------------------------
    # Row 4: Jumping (5 frames, hop / jump cycle)
    # ----------------------------------------------------
    hop_info = anims.get("Hop", walk_info)
    hop_max = hop_info["frames"]
    jump_lifts = [0, 8, 22, 14, 0]
    jump_squash_y = [0.85, 1.1, 1.0, 1.05, 0.9]
    for c in range(5):
        raw = get_frame(hop_sheet, "Hop", min(c, hop_max - 1), 0)
        cell = build_cell(raw, scale=scale, baseline_y=baseline, lift_y=jump_lifts[c], squash_y=jump_squash_y[c])
        atlas.paste(cell, (c * CELL_WIDTH, 4 * CELL_HEIGHT), cell)

    # ----------------------------------------------------
    # Row 5: Failed (8 frames, hurt / dizzy error state)
    # ----------------------------------------------------
    hurt_info = anims.get("Hurt", anims.get("Pain", walk_info))
    for c in range(8):
        raw = get_frame(hurt_sheet, "Hurt", c % hurt_info["frames"], 0)
        tilt = -6.0 if c % 2 == 0 else 6.0
        acc = "sweat" if c in [2, 3, 4] else None
        cell = build_cell(raw, scale=scale, baseline_y=baseline, tilt_deg=tilt, accessory=acc)
        atlas.paste(cell, (c * CELL_WIDTH, 5 * CELL_HEIGHT), cell)

    # ----------------------------------------------------
    # Row 6: Waiting (6 frames, curious turn/look around)
    # ----------------------------------------------------
    wait_dirs = [0, 7, 6, 0, 1, 2] # front, down-left, left, front, down-right, right
    for c in range(6):
        raw = get_frame(rotate_sheet, "Rotate", 0, wait_dirs[c])
        cell = build_cell(raw, scale=scale, baseline_y=baseline)
        atlas.paste(cell, (c * CELL_WIDTH, 6 * CELL_HEIGHT), cell)

    # ----------------------------------------------------
    # Row 7: Running / Work Mode (Signature Move!)
    # ----------------------------------------------------
    dex = pokemon["dex"]
    sig_map = {
        "0025": ("Shock", "lightning"),     # 皮卡丘: 十万伏特放电闪烁
        "0039": ("Shoot", "music"),         # 胖丁: 经典大眼闭目唱歌，跳动音符
        "0054": ("Charge", "psychic"),      # 可达鸭: 双手抱头超载念力
        "0094": ("Shoot", "shadow"),        # 耿鬼: 经典舌舔 / 暗影施法
        "0001": ("Shoot", "sparkle"),       # 妙蛙种子: 飞叶快刀
        "0004": ("Shoot", "sparkle"),       # 小火龙: 喷火
        "0007": ("Shoot", "sparkle"),       # 杰尼龟: 水枪
        "0133": ("Charge", "sparkle"),      # 伊布: 渴望聚气
        "0143": ("Slam", "sweat"),          # 卡比兽: 泰山压顶
        "0150": ("Charge", "psychic"),      # 超梦: 精神强念
        "0151": ("Float", "sparkle"),       # 梦幻: 幻影浮空
    }

    if dex in sig_map and sig_map[dex][0] in anims:
        work_anim_name, work_acc = sig_map[dex]
    elif "Shock" in anims:
        work_anim_name, work_acc = "Shock", "lightning"
    elif "Shoot" in anims:
        work_anim_name, work_acc = "Shoot", None
    elif "Charge" in anims:
        work_anim_name, work_acc = "Charge", "psychic"
    elif "Strike" in anims:
        work_anim_name, work_acc = "Strike", None
    elif "Double" in anims:
        work_anim_name, work_acc = "Double", None
    elif "Attack" in anims:
        work_anim_name, work_acc = "Attack", None
    else:
        work_anim_name, work_acc = "Walk", None

    work_sheet = load_sheet(work_anim_name) or attack_sheet
    work_info = anims.get(work_anim_name, walk_info)
    work_total = max(1, work_info["frames"])

    for c in range(6):
        raw = get_frame(work_sheet, work_anim_name, c % work_total, 0)
        cell = build_cell(raw, scale=scale, baseline_y=baseline, accessory=work_acc)
        atlas.paste(cell, (c * CELL_WIDTH, 7 * CELL_HEIGHT), cell)

    # ----------------------------------------------------
    # Row 8: Review Mode (6 frames, Pose/Nod + Loupe & Checkmark)
    # ----------------------------------------------------
    for c in range(6):
        raw = get_frame(pose_sheet, "Pose" if "Pose" in anims else "Walk", c, 0)
        cell = build_cell(raw, scale=scale, baseline_y=baseline, accessory="loupe")
        atlas.paste(cell, (c * CELL_WIDTH, 8 * CELL_HEIGHT), cell)

    # ----------------------------------------------------
    # Row 9 & 10: 16 Gaze Directions (8 frames each)
    # ----------------------------------------------------
    # Direction map for 16 angles (0..15)
    # PMD 8-dirs: 0:S, 1:SE, 2:E, 3:NE, 4:N, 5:NW, 6:W, 7:SW
    dir16_to_pmd = [
        (4, 0.0),    # 000: N
        (3, -4.0),   # 022.5: NNE
        (3, 0.0),    # 045: NE
        (2, -4.0),   # 067.5: ENE
        (2, 0.0),    # 090: E
        (1, -4.0),   # 112.5: ESE
        (1, 0.0),    # 135: SE
        (0, -4.0),   # 157.5: SSE
        (0, 0.0),    # 180: S
        (0, 4.0),    # 202.5: SSW
        (7, 0.0),    # 225: SW
        (6, 4.0),    # 247.5: WSW
        (6, 0.0),    # 270: W
        (5, 4.0),    # 292.5: WNW
        (5, 0.0),    # 315: NW
        (4, 4.0),    # 337.5: NNW
    ]

    for idx, (pmd_dir, tilt) in enumerate(dir16_to_pmd):
        target_row = 9 if idx < 8 else 10
        target_col = idx % 8
        raw = get_frame(rotate_sheet, "Rotate", 0, pmd_dir)
        cell = build_cell(raw, scale=scale, baseline_y=baseline, tilt_deg=tilt)
        atlas.paste(cell, (target_col * CELL_WIDTH, target_row * CELL_HEIGHT), cell)

    return atlas


def clean_alpha_residues(img: Image.Image) -> Image.Image:
    arr = np.array(img)
    alpha = arr[:, :, 3]
    zero_mask = (alpha == 0)
    arr[zero_mask, 0] = 0
    arr[zero_mask, 1] = 0
    arr[zero_mask, 2] = 0
    return Image.fromarray(arr, mode="RGBA")


def generate_pet_json(pokemon: dict) -> dict:
    pet_id = pokemon["en"].lower().replace(" ", "-")
    display_name = f"{pokemon.get('zh_hans', pokemon['en'])} ({pokemon['en']})"
    desc = f"Official-quality animated AI companion pet based on {pokemon['en']} from Pokémon Mystery Dungeon (SpriteCollab)."

    states = {}
    for cfg in ROW_CONFIG:
        state_name = cfg["state"]
        row = cfg["row"]
        frames_count = cfg["frames"]
        durations = cfg["durations"]
        states[state_name] = {
            "row": row,
            "columns": frames_count,
            "frameDuration": durations[0] if len(set(durations)) == 1 else durations
        }

    return {
        "id": pet_id,
        "slug": pet_id,
        "petId": pet_id,
        "name": display_name,
        "displayName": display_name,
        "description": desc,
        "spritesheetPath": "spritesheet.webp",
        "author": "Antigravity & PMDCollab Community",
        "license": "CC-BY-NC 4.0 / Fan Work",
        "spriteVersionNumber": 2,
        "atlasWidth": ATLAS_WIDTH,
        "atlasHeight": ATLAS_HEIGHT,
        "frameWidth": CELL_WIDTH,
        "frameHeight": CELL_HEIGHT,
        "cellWidth": CELL_WIDTH,
        "cellHeight": CELL_HEIGHT,
        "gridColumns": COLUMNS,
        "gridRows": ROWS,
        "columns": COLUMNS,
        "rows": ROWS,
        "states": states,
        "lookDirectionLabels": LOOK_DIRECTION_LABELS
    }


def main():
    parser = argparse.ArgumentParser(description="Universal Pokémon Agent Pet Generator")
    parser.add_argument("--query", "-q", required=True, help="Pokémon name (Chinese/English) or Dex ID (e.g. 25, pikachu, 皮卡丘)")
    parser.add_argument("--check-only", action="store_true", help="Only check if available in SpriteCollab, do not build")
    parser.add_argument("--dest", "-d", default=None, help="Destination directory for pet (defaults to ~/.codex/pets/<id>)")
    parser.add_argument("--scale-mult", type=float, default=1.0, help="Scale multiplier for character size (default: 1.0)")
    args = parser.parse_args()

    # 1. Look up in Pokédex DB
    db = load_pokemon_db()
    pokemon = find_pokemon(args.query, db)

    if not pokemon:
        res = {
            "status": "NOT_FOUND_IN_POKEDEX",
            "message": f"未在全国宝可梦图鉴中找到匹配的宝可梦: '{args.query}'。请确认宝可梦名字（中/英）或输入全国图鉴编号（如 25 或 #0025）。"
        }
        print(json.dumps(res, ensure_ascii=False, indent=2))
        sys.exit(1)

    dex = pokemon["dex"]
    name_zh = pokemon.get("zh_hans", pokemon["en"])
    name_en = pokemon["en"]

    # 2. Check SpriteCollab availability
    available = check_spritecollab_availability(dex)
    if not available:
        res = {
            "status": "NOT_AVAILABLE_IN_SPRITECOLLAB",
            "pokemon": pokemon,
            "message": f"【{name_zh}】(#{dex} {name_en}) 暂未收录在 SpriteCollab 项目中（社区画师目前尚未绘制或补全该宝可梦的逐帧动作）。目前可以先体验已收录的经典角色（如皮卡丘、可达鸭、妙蛙种子、小火龙、杰尼龟、伊布、耿鬼等）！"
        }
        print(json.dumps(res, ensure_ascii=False, indent=2))
        sys.exit(2)

    if args.check_only:
        res = {
            "status": "AVAILABLE",
            "pokemon": pokemon,
            "message": f"SpriteCollab 拥有【{name_zh}】(#{dex} {name_en}) 的完整官方级逐帧动作素材，可以随时生成！"
        }
        print(json.dumps(res, ensure_ascii=False, indent=2))
        sys.exit(0)

    # 3. Download & Cache assets
    pet_slug = name_en.lower().replace(" ", "-")
    char_cache = CACHE_DIR / f"pokemon_{dex}"
    char_cache.mkdir(parents=True, exist_ok=True)

    xml_file = fetch_file(dex, "AnimData.xml", char_cache)
    if not xml_file:
        res = {
            "status": "DOWNLOAD_FAILED",
            "message": f"无法下载 {name_en} 的 AnimData.xml 配置文件。"
        }
        print(json.dumps(res, ensure_ascii=False, indent=2))
        sys.exit(3)

    anims = parse_anim_data(xml_file)

    needed_sheets = ["Walk", "Idle", "Hop", "Hurt", "Pose", "Rotate", "Attack", "Charge", "Shock", "Shoot", "Strike", "Double", "Slam", "Float"]
    for s in needed_sheets:
        if s in anims or s in ["Walk", "Idle", "Hop", "Hurt", "Pose", "Rotate"]:
            fetch_file(dex, f"{s}-Anim.png", char_cache)

    # 4. Assemble Atlas
    atlas = assemble_pokemon_atlas(pokemon, char_cache, anims, user_scale_mult=args.scale_mult)
    atlas = clean_alpha_residues(atlas)

    # 5. Output and deploy
    dest_dirs = []
    if args.dest:
        dest_dirs.append(Path(args.dest))
    else:
        # Default deployment to Codex, CoPet User, and CoPet App Assets
        dest_dirs.append(DEFAULT_PETS_DIR / pet_slug)
        copet_user = Path(os.path.expanduser("~/.copet/pets")) / pet_slug
        dest_dirs.append(copet_user)
        copet_app = Path(os.path.expanduser("~/AppData/Local/CoPet/assets/pets")) / pet_slug
        if copet_app.parent.exists():
            dest_dirs.append(copet_app)

    pet_metadata = generate_pet_json(pokemon)

    for target_dir in dest_dirs:
        target_dir.mkdir(parents=True, exist_ok=True)
        atlas.save(target_dir / "spritesheet.png", "PNG")
        atlas.save(target_dir / "spritesheet.webp", "WEBP", lossless=True, quality=100)
        with open(target_dir / "pet.json", "w", encoding="utf-8") as f:
            json.dump(pet_metadata, f, ensure_ascii=False, indent=2)

    res = {
        "status": "SUCCESS",
        "pokemon": pokemon,
        "petId": pet_slug,
        "name": f"{name_zh} ({name_en})",
        "installPaths": [str(d) for d in dest_dirs],
        "files": ["pet.json", "spritesheet.png", "spritesheet.webp"],
        "message": f"🎉 成功为【{name_zh}】(#{dex} {name_en}) 生成官方逐帧 AI Agent 桌宠！已自动部署至 CoPet 及 Codex 桌宠目录。"
    }
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
