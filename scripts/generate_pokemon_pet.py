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
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image, ImageDraw

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
    {"row": 0, "state": "idle", "frames": 6, "durations": [800, 800, 800, 800, 800, 800]},
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
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pokemon-pet-factory/2.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                target_path.write_bytes(resp.read())
                return target_path
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return None


def check_spritecollab_availability(dex: str) -> bool:
    cached_xml = CACHE_DIR / f"pokemon_{dex}" / "AnimData.xml"
    if cached_xml.exists() and cached_xml.stat().st_size > 0:
        return True
    url = f"{GITHUB_RAW_BASE}/{dex}/AnimData.xml"
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "pokemon-pet-factory/2.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
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


from collections import Counter


def detect_eyes_generic(img_tight: Image.Image):
    """Automatically detect symmetric left/right eye clusters and dominant face skin color on any front sprite."""
    tw, th = img_tight.size
    px = img_tight.load()
    face_colors = []
    for y in range(2, max(3, int(th * 0.7))):
        for x in range(2, max(3, tw - 2)):
            c = px[x, y]
            if c[3] > 200 and c[:3] != (0, 0, 0) and not (c[0] > 240 and c[1] > 240 and c[2] > 240):
                face_colors.append(c)
    skin_color = Counter(face_colors).most_common(1)[0][0] if face_colors else (127, 207, 255, 255)

    whites = []
    for y in range(1, int(th * 0.72)):
        for x in range(1, tw - 1):
            r, g, b, a = px[x, y]
            if a > 200 and r > 235 and g > 235 and b > 235:
                whites.append((x, y))

    mid = (tw - 1) / 2.0
    left_w = [(x, y) for x, y in whites if 1 <= x < mid - 0.2]
    right_w = [(x, y) for x, y in whites if mid + 0.2 < x <= tw - 2]
    if not left_w or not right_w:
        return skin_color, None

    best_pair = None
    best_score = 999.0
    for lx, ly in left_w:
        for rx, ry in right_w:
            if abs(ly - ry) <= 1:
                sym_err = abs((mid - lx) - (rx - mid)) + abs(ly - ry) * 2
                if sym_err < best_score:
                    best_score = sym_err
                    best_pair = ((lx, ly), (rx, ry))
    if not best_pair:
        return skin_color, None

    eyes = []
    for sx, sy in best_pair:
        visited = set([(sx, sy)])
        queue = [(sx, sy)]
        while queue:
            cx, cy = queue.pop(0)
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = cx + dx, cy + dy
                if 1 <= nx < tw - 1 and 1 <= ny < int(th * 0.78) and (nx, ny) not in visited:
                    if abs(nx - sx) <= 2 and abs(ny - sy) <= 2:
                        c = px[nx, ny]
                        is_outer = (
                            nx <= 1
                            or nx >= tw - 2
                            or ny <= 1
                            or px[nx - 1, ny][3] == 0
                            or px[nx + 1, ny][3] == 0
                            or px[nx, ny - 1][3] == 0
                        )
                        if c[3] > 200 and c != skin_color and not (c[:3] == (0, 0, 0) and is_outer):
                            visited.add((nx, ny))
                            queue.append((nx, ny))
        ex0 = min(x for x, _ in visited)
        ey0 = min(y for _, y in visited)
        ex1 = max(x for x, _ in visited) + 1
        ey1 = max(y for _, y in visited) + 1
        eyes.append((ex0, ey0, ex1, ey1, visited))
    return skin_color, eyes


def apply_eye_shift_to_scaled(raw_img: Image.Image, scale: int, dx: float, dy: float) -> Image.Image:
    """Shift detected eye clusters and catchlights on an integer-scaled sprite."""
    s = max(1, round(scale))
    tw, th = raw_img.size
    scaled = raw_img.resize((tw * s, th * s), Image.Resampling.NEAREST)
    skin_color, eyes = detect_eyes_generic(raw_img)
    if not eyes:
        return scaled
    draw = ImageDraw.Draw(scaled)
    px = raw_img.load()
    ox = round(dx * (s * 0.65))
    oy = round(dy * (s * 0.65))
    hx = round(dx * (s * 0.45))
    hy = round(dy * (s * 0.45))

    eye_layers = []
    for ex0, ey0, ex1, ey1, visited in eyes:
        non_white = []
        white_pts = []
        for (x, y) in visited:
            c = px[x, y]
            if c[0] > 235 and c[1] > 235 and c[2] > 235:
                white_pts.append((x, y, c))
            else:
                non_white.append((x, y, c))
            draw.rectangle([x * s, y * s, (x + 1) * s - 1, (y + 1) * s - 1], fill=skin_color)
        eye_layers.append((non_white, white_pts))

    for non_white, white_pts in eye_layers:
        for x, y, c in non_white:
            draw.rectangle([x * s + ox, y * s + oy, (x + 1) * s - 1 + ox, (y + 1) * s - 1 + oy], fill=c)
        for x, y, c in white_pts:
            draw.rectangle(
                [x * s + ox + hx, y * s + oy + hy, (x + 1) * s - 1 + ox + hx, (y + 1) * s - 1 + oy + hy],
                fill=c,
            )
    return scaled


def render_universal_eyes_cell(front_raw: Image.Image, scale: float, baseline_y: int, deg: float, dex: str = None) -> Image.Image:
    """Render stationary body with 16-direction animated eye/pupil tracking for any Pokémon."""
    if dex == "0007":
        return render_squirtle_eyes_cell(front_raw, scale=scale, baseline_y=baseline_y, deg=deg)

    cell = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    bbox = front_raw.getbbox()
    if bbox is None:
        return cell
    ft = front_raw.crop(bbox)
    s = max(1, round(scale))
    rad = math.radians(deg)
    dx = math.sin(rad)
    dy = -math.cos(rad)

    scaled = apply_eye_shift_to_scaled(ft, s, dx, dy)
    cx = CELL_WIDTH // 2
    py = max(2, baseline_y - scaled.height)
    cell.paste(scaled, (cx - scaled.width // 2, py), scaled)
    return cell


def render_universal_head_cell(
    front_raw: Image.Image,
    head_sheet: Image.Image,
    head_info: dict,
    scale: float,
    baseline_y: int,
    deg: float,
    dex: str = None,
) -> Image.Image:
    """Render stationary lower-body with continuous bottom-anchored head/upper-body lean & pitch + eye tracking."""
    if dex == "0007" and head_sheet is not None:
        return render_squirtle_head_cell(front_raw, head_sheet=head_sheet, scale=scale, baseline_y=baseline_y, deg=deg)

    cell = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    bbox = front_raw.getbbox()
    if bbox is None:
        return cell
    ft = front_raw.crop(bbox)
    s = max(1, round(scale))
    rad = math.radians(deg)
    dx = math.sin(rad)   # +1 screen-right, -1 screen-left
    dy = -math.cos(rad)  # -1 screen-up, +1 screen-down

    base_scaled = apply_eye_shift_to_scaled(ft, s, dx, dy)
    nw, nh = base_scaled.size

    # Continuous bottom-anchored upper-body/head lean & vertical pitch:
    # Lower 28% (feet/legs) stays 100% anchored on the ground;
    # Upper 72% smoothly leans horizontally and pitches vertically without ever severing the neck, ears, or tail.
    pad = 16
    comp = Image.new("RGBA", (nw + pad * 2, nh + pad * 2), (0, 0, 0, 0))
    anchor_y = int(nh * 0.72)

    for y in range(nh):
        if y >= anchor_y:
            shift_x = 0
            src_y = y
        else:
            t = (anchor_y - y) / max(1.0, float(anchor_y))
            shift_x = round(dx * (s * 0.85) * t)
            shift_y = round(dy * (s * 0.65) * t)
            src_y = max(0, min(anchor_y - 1, y - shift_y))
        row_strip = base_scaled.crop((0, src_y, nw, src_y + 1))
        comp.paste(row_strip, (pad + shift_x, pad + y), row_strip)

    cx = CELL_WIDTH // 2
    py = max(2, baseline_y - nh - pad)
    cell.paste(comp, (cx - nw // 2 - pad, py), comp)
    return cell


def render_squirtle_eyes_cell(front_raw: Image.Image, scale: float, baseline_y: int, deg: float) -> Image.Image:
    """Render Squirtle (#0007) with stationary body and 16-direction animated eye/pupil tracking."""
    cell = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    bbox = front_raw.getbbox()
    if bbox is None:
        return cell
    front_tight = front_raw.crop(bbox)
    tw, th = front_tight.size
    s = max(1, round(scale))
    nw, nh = tw * s, th * s
    scaled = front_tight.resize((nw, nh), Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(scaled)

    rad = math.radians(deg)
    dx = math.sin(rad)   # +1 screen-right, -1 screen-left
    dy = -math.cos(rad)  # -1 screen-up, +1 screen-down

    ox = round(dx * (s * 0.72))
    oy = round(dy * (s * 0.72))
    px_shift = round(dx * (s * 0.6))
    py_shift = round(dy * (s * 0.6))

    skin = (0x7F, 0xCF, 0xFF, 255)
    brow = (0x1F, 0x9F, 0xE7, 255)
    crimson = (0x9F, 0x00, 0x00, 255)
    coral = (0xFF, 0x87, 0x5F, 255)
    black = (0x00, 0x00, 0x00, 255)
    white = (0xFF, 0xFF, 0xFF, 255)

    # Clear original eyes (x=4..5, y=5..7 and x=11..12, y=5..7) and brow pixels (x=5,11, y=4)
    draw.rectangle([4 * s, 5 * s, 6 * s - 1, 8 * s - 1], fill=skin)
    draw.rectangle([11 * s, 5 * s, 13 * s - 1, 8 * s - 1], fill=skin)
    draw.rectangle([5 * s, 4 * s, 6 * s - 1, 5 * s - 1], fill=skin)
    draw.rectangle([11 * s, 4 * s, 12 * s - 1, 5 * s - 1], fill=skin)

    ew, eh = 2 * s, 3 * s
    pw, ph = max(4, round(1.15 * s)), max(6, round(1.55 * s))
    hw, hh = max(3, round(0.85 * s)), max(3, round(0.85 * s))

    for ex_base in (4 * s, 11 * s):
        ex = ex_base + ox
        ey = 5 * s + oy
        draw.rectangle([ex + 2, ey - 3, ex + ew - 3, ey - 1], fill=brow)
        draw.rectangle([ex, ey, ex + ew - 1, ey + eh - 1], fill=crimson)
        draw.rectangle([ex + 1, ey + eh - s + 1, ex + ew - 2, ey + eh - 1], fill=coral)

        pcx = ex + ew // 2 + px_shift
        pcy = ey + eh // 2 + py_shift
        p_left = max(ex + 1, min(ex + ew - pw - 1, pcx - pw // 2))
        p_top = max(ey + 1, min(ey + eh - ph - 1, pcy - ph // 2))
        draw.rectangle([p_left, p_top, p_left + pw - 1, p_top + ph - 1], fill=black)

        hl_left = max(ex + 1, min(ex + ew - hw - 1, p_left + (pw - hw if dx >= 0 else 0)))
        hl_top = max(ey + 1, min(ey + eh - hh - 1, p_top - 2 if dy <= 0 else p_top + ph - hh))
        draw.rectangle([hl_left, hl_top, hl_left + hw - 1, hl_top + hh - 1], fill=white)

    cx = CELL_WIDTH // 2
    py = max(2, baseline_y - nh)
    cell.paste(scaled, (cx - nw // 2, py), scaled)
    return cell


def render_squirtle_head_cell(front_raw: Image.Image, head_sheet: Image.Image, scale: float, baseline_y: int, deg: float) -> Image.Image:
    """Render Squirtle (#0007) with anchored front body and 16-direction 3D head turn/pitch/tilt."""
    cell = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    bbox = front_raw.getbbox()
    if bbox is None:
        return cell
    front_tight = front_raw.crop(bbox)
    tw, th = front_tight.size
    s = max(1, round(scale))
    nw, nh = tw * s, th * s

    # Extract headless body from front_tight (17x18)
    body_only = front_tight.copy()
    b_px = body_only.load()
    for y in range(min(11, th)):
        for x in range(tw):
            if y < 9:
                b_px[x, y] = (0, 0, 0, 0)
            elif y == 9 and 4 <= x <= 12:
                b_px[x, y] = (0, 0, 0, 0)
            elif y == 10 and 5 <= x <= 11:
                b_px[x, y] = (0x00, 0x67, 0xB7, 255) if x in (5, 11) else (0xDF, 0xAF, 0x67, 255)

    body_scaled = body_only.resize((nw, nh), Image.Resampling.NEAREST)

    rad = math.radians(deg)
    dx = math.sin(rad)   # +1 screen-right, -1 screen-left
    dy = -math.cos(rad)  # -1 screen-up, +1 screen-down

    if head_sheet is not None and dx >= 0.35:
        h_raw = head_sheet.crop((0, 1 * 32, 24, 2 * 32)).crop((6, 1, 19, 13))
        head_type = "right"
    elif head_sheet is not None and dx <= -0.35:
        h_raw = head_sheet.crop((0, 7 * 32, 24, 8 * 32)).crop((4, 1, 17, 13))
        head_type = "left"
    elif head_sheet is not None:
        h_raw = head_sheet.crop((0, 0 * 32, 24, 1 * 32)).crop((5, 1, 18, 13))
        head_type = "front"
    else:
        h_raw = front_tight.crop((2, 0, 15, 11))
        head_type = "front"

    hw_orig, hh_orig = h_raw.size
    head_scaled = h_raw.resize((hw_orig * s, hh_orig * s), Image.Resampling.NEAREST)
    draw_h = ImageDraw.Draw(head_scaled)

    skin = (0x7F, 0xCF, 0xFF, 255)
    brow = (0x1F, 0x9F, 0xE7, 255)
    crimson = (0x9F, 0x00, 0x00, 255)
    coral = (0xFF, 0x87, 0x5F, 255)
    black = (0x00, 0x00, 0x00, 255)
    white = (0xFF, 0xFF, 0xFF, 255)

    ew, eh = 2 * s, 3 * s
    pw, ph = max(4, round(1.15 * s)), max(6, round(1.55 * s))
    hw_hl, hh_hl = max(3, round(0.85 * s)), max(3, round(0.85 * s))

    if head_type == "front":
        draw_h.rectangle([2 * s, 4 * s, 4 * s - 1, 8 * s - 1], fill=skin)
        draw_h.rectangle([9 * s, 4 * s, 11 * s - 1, 8 * s - 1], fill=skin)
        draw_h.rectangle([5 * s, 8 * s, 8 * s - 1, 9 * s - 1], fill=skin)

        ox = round(dx * (s * 0.7))
        oy = round(dy * (s * 0.7))
        px_s = round(dx * (s * 0.55))
        py_s = round(dy * (s * 0.55))

        for ex_b in (2 * s, 9 * s):
            ex = ex_b + ox
            ey = 5 * s + oy
            draw_h.rectangle([ex + 2, ey - 3, ex + ew - 3, ey - 1], fill=brow)
            draw_h.rectangle([ex, ey, ex + ew - 1, ey + eh - 1], fill=crimson)
            draw_h.rectangle([ex + 1, ey + eh - s + 1, ex + ew - 2, ey + eh - 1], fill=coral)
            pcx, pcy = ex + ew // 2 + px_s, ey + eh // 2 + py_s
            pl = max(ex + 1, min(ex + ew - pw - 1, pcx - pw // 2))
            pt = max(ey + 1, min(ey + eh - ph - 1, pcy - ph // 2))
            draw_h.rectangle([pl, pt, pl + pw - 1, pt + ph - 1], fill=black)
            hl = max(ex + 1, min(ex + ew - hw_hl - 1, pl + (pw - hw_hl if dx >= 0 else 0)))
            ht = max(ey + 1, min(ey + eh - hh_hl - 1, pt - 2 if dy <= 0 else pt + ph - hh_hl))
            draw_h.rectangle([hl, ht, hl + hw_hl - 1, ht + hh_hl - 1], fill=white)

        ny = 8 * s + round(dy * (s * 0.55))
        nx1, nx2 = 5 * s + ox, 7 * s + ox
        draw_h.rectangle([nx1, ny, nx1 + s - 1, ny + s - 1], fill=brow)
        draw_h.rectangle([nx2, ny, nx2 + s - 1, ny + s - 1], fill=brow)

    elif head_type == "right":
        draw_h.rectangle([4 * s, 4 * s, 6 * s - 1, 8 * s - 1], fill=skin)
        draw_h.rectangle([9 * s, 4 * s, 11 * s - 1, 7 * s - 1], fill=skin)
        oy = round(dy * (s * 0.55))
        py_s = round(dy * (s * 0.55))
        ex, ey = 4 * s + round(dx * 2), 5 * s + oy
        draw_h.rectangle([ex + 2, ey - 3, ex + ew - 3, ey - 1], fill=brow)
        draw_h.rectangle([ex, ey, ex + ew - 1, ey + eh - 1], fill=crimson)
        draw_h.rectangle([ex + 1, ey + eh - s + 1, ex + ew - 2, ey + eh - 1], fill=coral)
        pl, pt = ex + ew - pw - 1, max(ey + 1, min(ey + eh - ph - 1, ey + (eh - ph) // 2 + py_s))
        draw_h.rectangle([pl, pt, pl + pw - 1, pt + ph - 1], fill=black)
        ht = max(ey + 1, min(ey + eh - hh_hl - 1, pt - 2 if dy <= 0 else pt + ph - hh_hl))
        draw_h.rectangle([pl + pw - hw_hl, ht, pl + pw - 1, ht + hh_hl - 1], fill=white)

        fx, fy, fw_e, fh_e = 10 * s, 4 * s + oy, s, 3 * s
        draw_h.rectangle([fx, fy, fx + fw_e - 1, fy + fh_e - 1], fill=crimson)
        pt_f = max(fy + 1, min(fy + fh_e - ph + 1, fy + (fh_e - ph) // 2 + py_s))
        draw_h.rectangle([fx + 1, pt_f, fx + fw_e - 1, pt_f + ph - 3], fill=black)
        ht_f = max(fy, min(fy + fh_e - hh_hl, pt_f - 2 if dy <= 0 else pt_f + 4))
        draw_h.rectangle([fx + 1, ht_f, fx + fw_e - 1, ht_f + hh_hl - 2], fill=white)

    elif head_type == "left":
        draw_h.rectangle([2 * s, 4 * s, 4 * s - 1, 7 * s - 1], fill=skin)
        draw_h.rectangle([7 * s, 4 * s, 9 * s - 1, 8 * s - 1], fill=skin)
        oy = round(dy * (s * 0.55))
        py_s = round(dy * (s * 0.55))
        ex, ey = 7 * s + round(dx * 2), 5 * s + oy
        draw_h.rectangle([ex + 2, ey - 3, ex + ew - 3, ey - 1], fill=brow)
        draw_h.rectangle([ex, ey, ex + ew - 1, ey + eh - 1], fill=crimson)
        draw_h.rectangle([ex + 1, ey + eh - s + 1, ex + ew - 2, ey + eh - 1], fill=coral)
        pl, pt = ex + 1, max(ey + 1, min(ey + eh - ph - 1, ey + (eh - ph) // 2 + py_s))
        draw_h.rectangle([pl, pt, pl + pw - 1, pt + ph - 1], fill=black)
        ht = max(ey + 1, min(ey + eh - hh_hl - 1, pt - 2 if dy <= 0 else pt + ph - hh_hl))
        draw_h.rectangle([pl, ht, pl + hw_hl - 1, ht + hh_hl - 1], fill=white)

        fx, fy, fw_e, fh_e = 2 * s, 4 * s + oy, s, 3 * s
        draw_h.rectangle([fx, fy, fx + fw_e - 1, fy + fh_e - 1], fill=crimson)
        pt_f = max(fy + 1, min(fy + fh_e - ph + 1, fy + (fh_e - ph) // 2 + py_s))
        draw_h.rectangle([fx, pt_f, fx + fw_e - 2, pt_f + ph - 3], fill=black)
        ht_f = max(fy, min(fy + fh_e - hh_hl, pt_f - 2 if dy <= 0 else pt_f + 4))
        draw_h.rectangle([fx, ht_f, fx + fw_e - 2, ht_f + hh_hl - 2], fill=white)

    tilt = -dx * 7.0
    if abs(tilt) > 1.0:
        head_scaled = head_scaled.rotate(tilt, resample=Image.Resampling.NEAREST, expand=False)

    hx = 2 * s + round(dx * (s * 1.15))
    hy = round(dy * (s * 1.0))

    ox_pad, oy_pad = 16, 16
    comp = Image.new("RGBA", (nw + ox_pad * 2, nh + oy_pad * 2), (0, 0, 0, 0))
    comp.paste(body_scaled, (ox_pad, oy_pad), body_scaled)
    comp.paste(head_scaled, (ox_pad + hx, oy_pad + hy), head_scaled)

    cx = CELL_WIDTH // 2
    py = max(2, baseline_y - nh - oy_pad)
    cell.paste(comp, (cx - nw // 2 - ox_pad, py), comp)
    return cell


def assemble_pokemon_atlas(pokemon: dict, src_dir: Path, anims: dict, user_scale_mult: float = 1.0, idle_style: str = "static", look_style: str = "head"):
    atlas = Image.new("RGBA", (ATLAS_WIDTH, ATLAS_HEIGHT), (0, 0, 0, 0))

    # Helper to load animation sheets
    def load_sheet(name):
        f = src_dir / f"{name}-Anim.png"
        return Image.open(f).convert("RGBA") if f.exists() else None

    walk_sheet = load_sheet("Walk")
    idle_sheet = load_sheet("Idle") or walk_sheet
    sleep_sheet = load_sheet("Sleep") or idle_sheet
    hop_sheet = load_sheet("Hop") or walk_sheet
    hurt_sheet = load_sheet("Hurt") or load_sheet("Pain") or load_sheet("Faint") or walk_sheet
    pose_sheet = load_sheet("Pose") or load_sheet("Nod") or hop_sheet
    rotate_sheet = load_sheet("Rotate") or walk_sheet
    attack_sheet = load_sheet("Attack") or load_sheet("Charge") or walk_sheet
    head_sheet = load_sheet("Head")
    head_info = anims.get("Head")

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
    # Row 0: Idle (6 frames in cols 0..5, plus EXTENDED_NEUTRAL_LOOK_FRAME in col 6!)
    # ----------------------------------------------------
    idle_info = anims.get("Idle", walk_info)
    idle_frames = max(1, idle_info["frames"])
    front_neutral_raw = get_frame(idle_sheet, "Idle", 0, 0)
    neutral_cell = build_cell(front_neutral_raw, scale=scale, baseline_y=baseline, lift_y=0)

    if idle_style == "sleep" and "Sleep" in anims and sleep_sheet is not None:
        sleep_frames = max(1, anims["Sleep"]["frames"])
        for c in range(6):
            raw = get_frame(sleep_sheet, "Sleep", (c // 3) % sleep_frames, 0)
            cell = build_cell(raw, scale=scale, baseline_y=baseline, lift_y=0)
            atlas.paste(cell, (c * CELL_WIDTH, 0 * CELL_HEIGHT), cell)
    elif idle_style == "breathe":
        breathe_lifts = [0, 0, 1, 1, 0, 0]
        for c in range(6):
            cell = build_cell(front_neutral_raw, scale=scale, baseline_y=baseline, lift_y=breathe_lifts[c])
            atlas.paste(cell, (c * CELL_WIDTH, 0 * CELL_HEIGHT), cell)
    else:
        for c in range(6):
            atlas.paste(neutral_cell, (c * CELL_WIDTH, 0 * CELL_HEIGHT), neutral_cell)

    # Codex V2 Contract: Row 0, Column 6 MUST be populated as EXTENDED_NEUTRAL_LOOK_FRAME = (0, 6)
    atlas.paste(neutral_cell, (6 * CELL_WIDTH, 0 * CELL_HEIGHT), neutral_cell)

    # ----------------------------------------------------
    # Row 1: Running-Right (8 frames, facing East / row 2)
    # ----------------------------------------------------
    walk_cols = walk_info["frames"]
    for c in range(8):
        raw = get_frame(walk_sheet, "Walk", c % walk_cols, 2)
        cell = build_cell(raw, scale=scale, baseline_y=baseline)
        atlas.paste(cell, (c * CELL_WIDTH, 1 * CELL_HEIGHT), cell)

    # ----------------------------------------------------
    # Row 2: Running-Left (8 frames, facing West / row 6)
    # ----------------------------------------------------
    for c in range(8):
        raw = get_frame(walk_sheet, "Walk", c % walk_cols, 6)
        cell = build_cell(raw, scale=scale, baseline_y=baseline)
        atlas.paste(cell, (c * CELL_WIDTH, 2 * CELL_HEIGHT), cell)

    # ----------------------------------------------------
    # Row 3: Waving (4 frames, mouse-click / greeting trigger using active Idle-Anim)
    # ----------------------------------------------------
    for c in range(4):
        frame_idx = int(c * idle_frames / 4) % idle_frames
        raw = get_frame(idle_sheet, "Idle", frame_idx, 0)
        b_lift = int(math.sin(c / 4.0 * math.pi * 2) * 2)
        acc = "sparkle" if c in [1, 2] else None
        cell = build_cell(raw, scale=scale, baseline_y=baseline, lift_y=b_lift, accessory=acc)
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
    # Note: In PMD Rotate-Anim.png, row 0 cols 0..7 are the 8 directions (0:S, 1:SE, 2:E, 3:NE, 4:N, 5:NW, 6:W, 7:SW)
    # ----------------------------------------------------
    wait_dirs = [0, 7, 6, 0, 1, 2]
    for c in range(6):
        if "Rotate" in anims and rotate_sheet is not None:
            raw = get_frame(rotate_sheet, "Rotate", wait_dirs[c], 0)
        else:
            raw = get_frame(walk_sheet, "Walk", 0, wait_dirs[c])
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
    # Row 9 & 10: 16 Gaze Directions (8 frames each, clockwise from 000=UP)
    # ----------------------------------------------------
    # PMD Rotate-Anim row 0 cols 0..7: 0:S(down), 1:SE(down-right), 2:E(right), 3:NE(up-right),
    #                                  4:N(up),   5:NW(up-left),    6:W(left),  7:SW(down-left)
    dir16_to_pmd = [
        (4, 0.0),    # 000: N (Up)
        (3, -4.0),   # 022.5: NNE
        (3, 0.0),    # 045: NE (Up-Right)
        (2, -4.0),   # 067.5: ENE
        (2, 0.0),    # 090: E (Right)
        (1, -4.0),   # 112.5: ESE
        (1, 0.0),    # 135: SE (Down-Right)
        (0, -4.0),   # 157.5: SSE
        (0, 0.0),    # 180: S (Down)
        (0, 4.0),    # 202.5: SSW
        (7, 0.0),    # 225: SW (Down-Left)
        (6, 4.0),    # 247.5: WSW
        (6, 0.0),    # 270: W (Left)
        (5, 4.0),    # 292.5: WNW
        (5, 0.0),    # 315: NW (Up-Left)
        (4, 4.0),    # 337.5: NNW
    ]

    for idx, (pmd_dir, tilt) in enumerate(dir16_to_pmd):
        target_row = 9 if idx < 8 else 10
        target_col = idx % 8
        deg = idx * 22.5

        if look_style == "eyes":
            cell = render_universal_eyes_cell(front_neutral_raw, scale=scale, baseline_y=baseline, deg=deg, dex=dex)
        elif look_style == "head":
            cell = render_universal_head_cell(
                front_neutral_raw,
                head_sheet=head_sheet,
                head_info=head_info,
                scale=scale,
                baseline_y=baseline,
                deg=deg,
                dex=dex,
            )
        else:
            if "Rotate" in anims and rotate_sheet is not None:
                raw = get_frame(rotate_sheet, "Rotate", pmd_dir, 0)
            else:
                raw = get_frame(walk_sheet, "Walk", 0, pmd_dir)
            cell = build_cell(raw, scale=scale, baseline_y=baseline, tilt_deg=tilt)

        atlas.paste(cell, (target_col * CELL_WIDTH, target_row * CELL_HEIGHT), cell)

    return atlas


def clean_alpha_residues(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    data = bytearray(rgba.tobytes())
    for i in range(0, len(data), 4):
        if data[i + 3] == 0:
            data[i] = 0
            data[i + 1] = 0
            data[i + 2] = 0
    return Image.frombytes("RGBA", rgba.size, bytes(data))


def generate_pet_json(pokemon: dict, custom_id: str = None, custom_name: str = None) -> dict:
    pet_id = custom_id or pokemon["en"].lower().replace(" ", "-")
    display_name = custom_name or f"{pokemon.get('zh_hans', pokemon['en'])} ({pokemon['en']})"
    desc = f"Official-quality animated AI companion pet based on {pokemon['en']} from Pokémon Mystery Dungeon (SpriteCollab)."

    return {
        "id": pet_id,
        "displayName": display_name,
        "description": desc,
        "spriteVersionNumber": 2,
        "spritesheetPath": "spritesheet.webp"
    }


def main():
    parser = argparse.ArgumentParser(description="Universal Pokémon Agent Pet Generator")
    parser.add_argument("--query", "-q", required=True, help="Pokémon name (Chinese/English) or Dex ID (e.g. 25, pikachu, 皮卡丘)")
    parser.add_argument("--check-only", action="store_true", help="Only check if available in SpriteCollab and inspect supported look styles")
    parser.add_argument("--dest", "-d", default=None, help="Destination directory for pet (defaults to ~/.codex/pets/<id>)")
    parser.add_argument("--scale-mult", type=float, default=1.0, help="Scale multiplier for character size (default: 1.0)")
    parser.add_argument(
        "--idle-style",
        choices=["static", "sleep", "breathe"],
        default="static",
        help="Idle animation style: static (standing still, default), sleep (Sleep-Anim), or breathe (subtle 1px lift)"
    )
    parser.add_argument(
        "--look-style",
        choices=["eyes", "head", "body", "all"],
        default="head",
        help="16-direction mouse tracking style: eyes (moving pupils), head (turning/tilting head + eyes, default), body (8-dir full body turn), or all (generate both eyes & head variants)"
    )
    parser.add_argument("--pet-id", default=None, help="Custom pet ID / folder slug")
    parser.add_argument("--display-name", default=None, help="Custom display name in pet.json")
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

    if args.check_only:
        has_head_sheet = "Head" in anims
        res = {
            "status": "AVAILABLE",
            "pokemon": pokemon,
            "hasDedicatedHeadSheet": has_head_sheet,
            "supportedLookStyles": ["eyes", "head", "body", "all"],
            "recommendedLookStyle": "head" if has_head_sheet else "eyes",
            "message": f"SpriteCollab 拥有【{name_zh}】(#{dex} {name_en}) 的完整官方级逐帧动作素材（{'含独立 8 向 Head-Anim 头部素材' if has_head_sheet else '支持智能眼部与头部拆分追踪'}），可以随时生成！"
        }
        print(json.dumps(res, ensure_ascii=False, indent=2))
        sys.exit(0)

    # 3. Download & Cache assets
    needed_sheets = ["Walk", "Idle", "Hop", "Hurt", "Pose", "Rotate", "Attack", "Charge", "Shock", "Shoot", "Strike", "Double", "Slam", "Float", "Head"]
    for s in needed_sheets:
        if s in anims or s in ["Walk", "Idle", "Hop", "Hurt", "Pose", "Rotate"]:
            fetch_file(dex, f"{s}-Anim.png", char_cache)
    if args.idle_style == "sleep" and "Sleep" in anims:
        fetch_file(dex, "Sleep-Anim.png", char_cache)

    # 4. Build & deploy one or multiple look styles
    base_slug = args.pet_id or name_en.lower().replace(" ", "-")
    if args.look_style == "all":
        variants = [
            ("eyes", f"{base_slug}-eyes", f"{name_zh}-眼球追踪 ({name_en} Eyes)"),
            ("head", f"{base_slug}-head", f"{name_zh}-头部追踪 ({name_en} Head)"),
        ]
    else:
        style_label_map = {
            "eyes": f"{name_zh}-眼球追踪 ({name_en} Eyes)",
            "head": f"{name_zh}-头部追踪 ({name_en} Head)",
            "body": f"{name_zh} ({name_en})",
        }
        default_name = args.display_name or (f"{name_zh} ({name_en})" if args.pet_id is None else style_label_map[args.look_style])
        variants = [(args.look_style, base_slug, default_name)]

    installed_packages = []
    for style, slug, disp_name in variants:
        atlas = assemble_pokemon_atlas(
            pokemon,
            char_cache,
            anims,
            user_scale_mult=args.scale_mult,
            idle_style=args.idle_style,
            look_style=style,
        )
        atlas = clean_alpha_residues(atlas)

        dest_dirs = []
        if args.dest and len(variants) == 1:
            dest_dirs.append(Path(args.dest))
        elif args.dest:
            dest_dirs.append(Path(args.dest) / slug)
        else:
            dest_dirs.append(DEFAULT_PETS_DIR / slug)
            copet_user = Path(os.path.expanduser("~/.copet/pets")) / slug
            dest_dirs.append(copet_user)
            copet_app = Path(os.path.expanduser("~/AppData/Local/CoPet/assets/pets")) / slug
            if copet_app.parent.exists():
                dest_dirs.append(copet_app)

        pet_metadata = generate_pet_json(pokemon, custom_id=slug, custom_name=disp_name)

        for target_dir in dest_dirs:
            target_dir.mkdir(parents=True, exist_ok=True)
            atlas.save(target_dir / "spritesheet.png", "PNG")
            atlas.save(target_dir / "spritesheet.webp", "WEBP", lossless=True, quality=100, exact=True)
            with open(target_dir / "pet.json", "w", encoding="utf-8") as f:
                json.dump(pet_metadata, f, ensure_ascii=False, indent=2)

        installed_packages.append({
            "petId": slug,
            "name": disp_name,
            "lookStyle": style,
            "installPaths": [str(d) for d in dest_dirs],
        })

    res = {
        "status": "SUCCESS",
        "pokemon": pokemon,
        "packages": installed_packages,
        "petId": installed_packages[0]["petId"],
        "name": installed_packages[0]["name"],
        "lookStyle": args.look_style,
        "installPaths": [p for pkg in installed_packages for p in pkg["installPaths"]],
        "files": ["pet.json", "spritesheet.png", "spritesheet.webp"],
        "message": f"🎉 成功为【{name_zh}】(#{dex} {name_en}) 生成 {len(installed_packages)} 款官方逐帧 AI Agent 桌宠（视线模式: {args.look_style}）！已自动部署至 CoPet 及 Codex 桌宠目录。"
    }
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


