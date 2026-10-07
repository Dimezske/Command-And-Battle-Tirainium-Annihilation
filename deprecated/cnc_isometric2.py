"""
TIBERIUM CLONE - Isometric Tileset Edition (Expanded)
=======================================================
A fan recreation of the Command & Conquer (1995) gameplay loop, built with
pygame.

Highlights of this expanded version:
  * Real flying projectiles for infantry, rocket soldiers, tanks, turrets
    and towers (instead of instant hit-scan damage)
  * Three resources: Tirainium (credits, 4 tiers - green/yellow/blue/red),
    Wood (from trees) and Metal (from ore rock)
  * Biomes: grassland, desert and snow maps, plus procedurally generated
    water
  * A Research Center that unlocks Harvester upgrades, Armor Plating and
    Improved Weapons
  * Unit veterancy: units rank up (Rookie -> Veteran -> Elite) as they
    score kills, gaining HP and damage
  * Buildable Fences (wood) and Stone Walls (metal), plus Rocket Towers
    and Machine-Gun Towers as wall-mounted defenses

Infantry, vehicles, and projectiles are simple flat top-down shapes;
terrain and buildings use the generated art in iso_assets.py.

Run:
    python3 cnc_isometric.py
"""

import os
import sys
import math
import random
import argparse

# This game does not use audio; avoid ALSA probing noise on headless systems.
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--selftest", type=int, default=0,
                     help="run N frames headlessly (no window) then exit")
args, _unknown = parser.parse_known_args()

if args.selftest:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.font.init()

import iso_assets
import net

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TILE = 32
SIDEBAR_W = 280
TOPBAR_H = 34
WINDOWED_W = 1280
WINDOWED_H = 800
SCREEN_W = WINDOWED_W
SCREEN_H = WINDOWED_H
VIEWPORT_X0 = 0
VIEWPORT_Y0 = TOPBAR_H
VIEWPORT_W = SCREEN_W - SIDEBAR_W
VIEWPORT_H = SCREEN_H - TOPBAR_H
IS_FULLSCREEN = False

FPS = 60
ADJ_RANGE = 6
MAX_QUEUE_LEN = 5
HARVEST_RATE = 150.0
TRAINIUM_PER_TILE = 2000.0
WOOD_PER_TREE = 900.0
METAL_PER_ORE = 1200.0
CAMERA_SPEED = 720
EDGE_SCROLL_MARGIN = 18

# ---------------------------------------------------------------------------
# Visual scale multipliers
# ---------------------------------------------------------------------------
# Adjust these to resize an entire category of sprites and their selection
# radii without touching any other rendering code.
VEHICLE_SCALE      = 1.8   # harvester, tank, APC — sprite & hit-radius
INFANTRY_SCALE     = 1.2   # rifleman, rocket soldier — sprite & hit-radius
BUILDING_SCALE     = 1.0   # building artwork (sprite images)
# Per-kind overrides — takes precedence over BUILDING_SCALE for that kind only.
BUILDING_SCALE_OVERRIDES = {
    "yard": 1.0,   # Construction Yard scale
}
# Pixels of breathing room around each sprite inside its rect.
BUILDING_RECT_PADDING = 4

TRAINIUM_TIER_MULT = [1.0, 1.6, 2.6, 4.0]
TRAINIUM_TIER_NAMES = ["Green", "Yellow", "Blue", "Red"]
TRAINIUM_TIER_WEIGHTS = [50, 27, 15, 8]

RANK_NAMES = ["Rookie", "Veteran", "Elite"]
RANK_HP_MULT = [1.0, 1.25, 1.6]
RANK_DMG_MULT = [1.0, 1.2, 1.45]
RANK_KILLS = [0, 3, 7]

PROJECTILE_SPEED = {"bullet": 900, "rocket": 420, "shell": 650}
PROJECTILE_COLOR = {"bullet": (255, 230, 120), "rocket": (230, 120, 60), "shell": (210, 210, 220)}
TRAINIUM_REGEN_SECONDS = 7 * 60
EXPLOSION_LIFETIME = 0.55
NUKE_BUILD_TIME = 8 * 60

screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
pygame.display.set_caption("Tiberium Clone - Isometric Tileset Edition")
clock = pygame.time.Clock()


def set_display_mode(fullscreen):
    """Toggle a borderless desktop-sized window without changing Linux's mode.

    NOFRAME is deliberately used instead of FULLSCREEN: SDL asks the desktop
    compositor for a borderless window at the current desktop resolution, so
    the monitor resolution and refresh rate are untouched. NOFRAME is
    available across the Pygame builds commonly shipped on Linux.
    The game renders directly at that size, which enlarges the visible map
    area rather than stretching a smaller framebuffer.
    """
    global SCREEN_W, SCREEN_H, VIEWPORT_W, VIEWPORT_H, IS_FULLSCREEN, screen
    IS_FULLSCREEN = fullscreen
    if fullscreen:
        # Use the desktop dimensions for the actual 2D surface. NOFRAME makes
        # this a borderless window rather than an exclusive mode switch.
        # There is intentionally no SCALED flag: tiles and sprites remain at
        # their native sizes, so the larger surface reveals more of the map.
        try:
            desktop_w, desktop_h = pygame.display.get_desktop_sizes()[0]
        except (AttributeError, IndexError):
            info = pygame.display.Info()
            desktop_w, desktop_h = info.current_w, info.current_h
        screen = pygame.display.set_mode((desktop_w, desktop_h), pygame.NOFRAME)
    else:
        SCREEN_W, SCREEN_H = WINDOWED_W, WINDOWED_H
        screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    # SDL may negotiate a slightly different borderless-window size than the
    # requested desktop dimensions. Always use the size that was actually
    # created, otherwise the sidebar/clip rectangle can leave unused edges.
    SCREEN_W, SCREEN_H = pygame.display.get_window_size()
    VIEWPORT_W = SCREEN_W - SIDEBAR_W
    VIEWPORT_H = SCREEN_H - TOPBAR_H


FONT = pygame.font.SysFont("consolas", 16)
FONT_SMALL = pygame.font.SysFont("consolas", 12)
FONT_TINY = pygame.font.SysFont("consolas", 11)
FONT_BIG = pygame.font.SysFont("consolas", 34, bold=True)
FONT_MED = pygame.font.SysFont("consolas", 20, bold=True)

COL_BG = (10, 10, 12)
COL_SIDEBAR = (24, 24, 28)
COL_TOPBAR = (18, 18, 22)
COL_TEXT = (225, 225, 225)
COL_TEXT_DIM = (140, 140, 145)
COL_GOOD = (110, 220, 110)
COL_BAD = (230, 90, 90)
COL_SELECT = (255, 255, 255)
COL_BTN = (40, 40, 48)
COL_BTN_HOVER = (58, 58, 70)
COL_BTN_DISABLED = (30, 30, 34)
COL_TAB = (34, 34, 40)
COL_TAB_ACTIVE = (60, 90, 70)
COL_BAR_BG = (40, 10, 10)
COL_BAR_FG = (60, 200, 80)
COL_WOOD = (190, 150, 90)
COL_METAL = (170, 175, 185)
COL_LIME = (170, 240, 40)

PLAYER_COLOR = (215, 180, 40)
AI_COLOR = (200, 50, 50)

# terrain tile type ids
TILE_GROUND = 0
TILE_ROCK = 1
TILE_WATER = 2
TILE_TREE = 3
TILE_ORE = 4
TILE_TRAINIUM = 5
TILE_RADIOACTIVE = 6
RESOURCE_TILE_TYPES = (TILE_TREE, TILE_ORE, TILE_TRAINIUM, TILE_RADIOACTIVE)

# Set by Game.__init__ so Unit.move_toward can do simple water collision
# without needing every unit to carry a back-reference to its Game/map.
# Only one Game is ever active per process (skirmish, or one side of a
# network match), so this is safe.
CURRENT_MAP = None

# ---------------------------------------------------------------------------
# Generated art (loaded once at startup)
# ---------------------------------------------------------------------------
TILES, BUILDING_SPRITES, ISO_SIZE, FLAG_OFFSET = iso_assets.generate_all(TILE)

# AI-generated additions for content that has no hand-authored tileset art.
AI_ASSET_DIR = os.path.join(os.path.dirname(__file__), "assets")

def _load_ai_sprite(filename, size):
    try:
        image = pygame.image.load(os.path.join(AI_ASSET_DIR, filename)).convert_alpha()
        return pygame.transform.smoothscale(image, size)
    except (pygame.error, OSError):
        return None

def _ss(base_w, base_h, factor):
    """Scale a base (w, h) by *factor*, rounding to the nearest pixel."""
    return (max(1, round(base_w * factor)), max(1, round(base_h * factor)))

def _unit_sprite_scale(kind):
    """Return the visual scale constant for *kind*."""
    return VEHICLE_SCALE if kind in ("harvester", "tank", "apc") else INFANTRY_SCALE

# ---------------------------------------------------------------------------
# Base sprite dimensions (pixels, before scale multipliers are applied).
# Edit these to change the reference artwork resolution; VEHICLE_SCALE,
# INFANTRY_SCALE, and BUILDING_SCALE are then multiplied on top.
# ---------------------------------------------------------------------------
_APC_BASE_SIZE       = (34, 34)
_NUKE_SILO_BASE_SIZE = (86, 86)
_UNIT_BASE_SIZES = {
    "harvester": (40, 40),
    "infantry":  (26, 26),
    "rocket":    (28, 28),
    "tank":      (38, 38),
}
_BUILDING_BASE_SIZES = {
    "yard":        (128, 116),
    "power":       ( 92, 108),
    "refinery":    (118, 110),
    "barracks":    ( 92,  94),
    "factory":     (122, 110),
    "research":    (110, 108),
    "turret":      ( 58,  64),
    "rockettower": ( 46,  56),
    "mgtower":     ( 46,  54),
}

AI_APC_SPRITE         = _load_ai_sprite("apc.png",       _ss(*_APC_BASE_SIZE,       VEHICLE_SCALE))
AI_NUKE_SILO_SPRITE   = _load_ai_sprite("nuke_silo.png", _ss(*_NUKE_SILO_BASE_SIZE, BUILDING_SCALE))
AI_RADIOACTIVE_SPRITE = _load_ai_sprite("radioactive_crystal.png", (30, 30))
AI_NUKE_EXPLOSION_SPRITE = _load_ai_sprite("nuke_explosion.png", (300, 300))
AI_PROJECTILE_SPRITE  = _load_ai_sprite("projectile_shell.png", (24, 24))
AI_UNIT_SPRITES = {
    k: _load_ai_sprite(f"{k}.png", _ss(*_UNIT_BASE_SIZES[k], _unit_sprite_scale(k)))
    for k in _UNIT_BASE_SIZES
}
AI_BUILDING_SPRITES = {
    kind: (f"{kind}.png", _ss(*base, BUILDING_SCALE_OVERRIDES.get(kind, BUILDING_SCALE)))
    for kind, base in _BUILDING_BASE_SIZES.items()
}
for _kind, (_filename, _size) in AI_BUILDING_SPRITES.items():
    _sprite = _load_ai_sprite(_filename, _size)
    if _sprite is not None:
        BUILDING_SPRITES[_kind] = _sprite
if AI_NUKE_SILO_SPRITE is not None:
    BUILDING_SPRITES["nuke_silo"] = AI_NUKE_SILO_SPRITE

# ---------------------------------------------------------------------------
# Data tables
# ---------------------------------------------------------------------------
def C(credits=0, wood=0, metal=0):
    return {"credits": credits, "wood": wood, "metal": metal}


BUILD_DATA = {
    "yard":     {"name": "Constr. Yard", "cost": C(0),    "hp": 1000, "power": 0,   "size": (3, 3), "time": 0},
    "power":    {"name": "Power Plant",  "cost": C(300),  "hp": 400,  "power": 100, "size": (2, 2), "time": 6},
    "refinery": {"name": "Refinery",     "cost": C(2000), "hp": 500,  "power": -30, "size": (3, 3), "time": 12},
    "barracks": {"name": "Barracks",     "cost": C(300),  "hp": 400,  "power": -20, "size": (2, 2), "time": 7},
    "factory":  {"name": "War Factory",  "cost": C(2000), "hp": 600,  "power": -30, "size": (3, 3), "time": 12},
    "research": {"name": "Research Ctr", "cost": C(1200), "hp": 400,  "power": -20, "size": (2, 2), "time": 10},
    "turret":   {"name": "Turret",       "cost": C(600),  "hp": 300,  "power": -10, "size": (1, 1), "time": 7,
                 "damage": 22, "range": 170, "cooldown": 0.9, "projectile": "bullet"},
    "fence":    {"name": "Fence",        "cost": C(0, wood=100),  "hp": 80,  "power": 0,   "size": (1, 1), "time": 3},
    "stonewall": {"name": "Stone Wall",  "cost": C(0, metal=150), "hp": 220, "power": 0,   "size": (1, 1), "time": 4},
    "rockettower": {"name": "Rocket Tower", "cost": C(400, metal=250), "hp": 260, "power": -10, "size": (1, 1), "time": 9,
                     "damage": 34, "range": 200, "cooldown": 1.3, "projectile": "rocket"},
    "mgtower":  {"name": "MG Tower",     "cost": C(300, metal=180), "hp": 230, "power": -10, "size": (1, 1), "time": 8,
                 "damage": 9, "range": 150, "cooldown": 0.28, "projectile": "bullet"},
    "nuke_silo": {"name": "Nuke Silo", "cost": C(5000, metal=1200), "hp": 800, "power": -40, "size": (3, 3), "time": 20,
                  "damage": 900, "range": 99999, "cooldown": NUKE_BUILD_TIME, "projectile": "nuke"},
}

DEFENSE_KINDS = {"turret", "rockettower", "mgtower", "nuke_silo"}
WALL_DRAG_KINDS = {"fence", "stonewall"}  # placed via click-and-drag, not the timed queue

UNIT_DATA = {
    "harvester": {"name": "Harvester",   "cost": C(1400), "hp": 250, "speed": 65, "damage": 0,  "range": 0,   "time": 10, "cooldown": 0,   "built_from": "factory"},
    "infantry":  {"name": "Rifleman",    "cost": C(100),  "hp": 50,  "speed": 85, "damage": 6,  "range": 110, "time": 3,  "cooldown": 0.5, "built_from": "barracks", "projectile": "bullet"},
    "rocket":    {"name": "Rocket Sldr", "cost": C(160),  "hp": 55,  "speed": 70, "damage": 20, "range": 150, "time": 4,  "cooldown": 1.1, "built_from": "barracks", "projectile": "rocket"},
    "tank":      {"name": "Medium Tank", "cost": C(800),  "hp": 300, "speed": 95, "damage": 26, "range": 140, "time": 8,  "cooldown": 0.9, "built_from": "factory",  "projectile": "shell"},
    "apc":       {"name": "APC", "cost": C(650), "hp": 240, "speed": 82, "damage": 12, "range": 120, "time": 7, "cooldown": 0.8, "built_from": "factory", "projectile": "bullet", "amphibious": True},
}

UPGRADE_DATA = {
    # --- Economy branch (row 0) ---
    "harvester_mk2": {"name": "Harvester Mk2", "cost": C(800), "time": 10, "tier": 0, "branch": 0,
                       "desc": "+300 cargo, +15% speed"},
    "harvester_mk3": {"name": "Harvester Mk3", "cost": C(1600), "time": 14, "tier": 1, "branch": 0,
                       "desc": "+300 cargo, +15% speed", "requires": "harvester_mk2"},
    "harvester_mk4": {"name": "Harvester Mk4", "cost": C(2400), "time": 18, "tier": 2, "branch": 0,
                       "desc": "+400 cargo, +15% speed", "requires": "harvester_mk3"},
    # --- Defense branch (row 1) ---
    "armor_plating":  {"name": "Armor Plating", "cost": C(1000), "time": 12, "tier": 0, "branch": 1,
                        "desc": "+20% unit HP"},
    "reinforced_armor": {"name": "Reinforced Armor", "cost": C(1800), "time": 14, "tier": 1, "branch": 1,
                          "desc": "+15% more unit HP", "requires": "armor_plating"},
    "siege_armor": {"name": "Siege Armor", "cost": C(2600), "time": 18, "tier": 2, "branch": 1,
                     "desc": "units slowly self-repair", "requires": "reinforced_armor"},
    # --- Offense branch (row 2) ---
    "improved_weapons": {"name": "Improved Weapons", "cost": C(1000), "time": 12, "tier": 0, "branch": 2,
                          "desc": "+20% unit/defense damage"},
    "advanced_ballistics": {"name": "Adv. Ballistics", "cost": C(1800), "time": 14, "tier": 1, "branch": 2,
                             "desc": "+15% more damage", "requires": "improved_weapons"},
    "veteran_training": {"name": "Veteran Training", "cost": C(2600), "time": 18, "tier": 2, "branch": 2,
                          "desc": "new units start as Veterans", "requires": "advanced_ballistics"},
    # --- Support branch (row 3) ---
    "fortified_walls": {"name": "Fortified Walls", "cost": C(900), "time": 10, "tier": 0, "branch": 3,
                         "desc": "+25% wall/turret HP"},
    "rapid_deployment": {"name": "Rapid Deployment", "cost": C(1700), "time": 13, "tier": 1, "branch": 3,
                          "desc": "-20% structure build time", "requires": "fortified_walls"},
    "auto_repair_bay": {"name": "Auto-Repair Bay", "cost": C(2500), "time": 16, "tier": 2, "branch": 3,
                         "desc": "buildings slowly self-repair", "requires": "rapid_deployment"},
    # --- Capstone: the Singularity, where every branch converges ---
    "singularity_core": {"name": "Singularity Core", "cost": C(5000), "time": 30, "tier": 3, "branch": None,
                          "desc": "+15% more to every bonus above",
                          "requires": ["harvester_mk4", "siege_armor", "veteran_training", "auto_repair_bay"]},
}
TECH_BRANCH_COLORS = [
    (215, 180, 60),   # economy - gold
    (90, 150, 220),   # defense - blue
    (210, 80, 70),    # offense - red
    (90, 190, 160),   # support - teal
]
TECH_CAPSTONE_COLOR = (200, 130, 240)  # singularity - violet

STRUCTURE_TABS = {
    "base": ["power", "refinery", "barracks", "factory"],
    "defense": ["turret", "fence", "stonewall", "rockettower", "mgtower", "nuke_silo"],
    "research": ["research"],
}
INFANTRY_ORDER = ["infantry", "rocket"]
VEHICLE_ORDER = ["harvester", "tank"]

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
_next_id = [1]


def next_id():
    _next_id[0] += 1
    return _next_id[0]


def dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def get_data(kind):
    if kind in BUILD_DATA:
        return BUILD_DATA[kind]
    if kind in UNIT_DATA:
        return UNIT_DATA[kind]
    return UPGRADE_DATA[kind]


def format_cost(cost):
    parts = []
    if cost.get("credits"):
        parts.append(f"${cost['credits']}")
    if cost.get("wood"):
        parts.append(f"{cost['wood']}w")
    if cost.get("metal"):
        parts.append(f"{cost['metal']}m")
    return " ".join(parts) if parts else "free"


def draw_health_bar(surf, x, y, w, h, hp, max_hp):
    pct = clamp(hp / max_hp if max_hp else 0, 0, 1)
    pygame.draw.rect(surf, COL_BAR_BG, (x, y, w, h))
    col = COL_BAR_FG if pct > 0.5 else ((220, 190, 40) if pct > 0.25 else COL_BAD)
    pygame.draw.rect(surf, col, (x, y, int(w * pct), h))


def get_center(entity):
    if isinstance(entity, Building):
        return entity.center
    return entity.x, entity.y


# effective (rank/upgrade adjusted) stat helpers ----------------------------
def armor_bonus_pct(owner):
    pct = 0.0
    if "armor_plating" in owner.upgrades:
        pct += 0.20
    if "reinforced_armor" in owner.upgrades:
        pct += 0.15
    if "singularity_core" in owner.upgrades:
        pct += 0.15
    return pct


def weapon_bonus_pct(owner):
    pct = 0.0
    if "improved_weapons" in owner.upgrades:
        pct += 0.20
    if "advanced_ballistics" in owner.upgrades:
        pct += 0.15
    if "singularity_core" in owner.upgrades:
        pct += 0.15
    return pct


def structure_hp_bonus_pct(owner):
    pct = 0.0
    if "fortified_walls" in owner.upgrades:
        pct += 0.25
    if "singularity_core" in owner.upgrades:
        pct += 0.15
    return pct


def build_time_mult(owner):
    mult = 1.0
    if "rapid_deployment" in owner.upgrades:
        mult *= 0.80
    if "singularity_core" in owner.upgrades:
        mult *= 0.85
    return mult


def effective_max_hp(unit):
    base = UNIT_DATA[unit.kind]["hp"] * RANK_HP_MULT[unit.rank]
    return base * (1 + armor_bonus_pct(unit.owner))


def effective_damage(unit):
    base = UNIT_DATA[unit.kind]["damage"] * RANK_DMG_MULT[unit.rank]
    return base * (1 + weapon_bonus_pct(unit.owner))


def effective_speed(unit):
    base = UNIT_DATA[unit.kind]["speed"]
    if unit.kind == "harvester":
        if "harvester_mk4" in unit.owner.upgrades:
            base *= 1.52
        elif "harvester_mk3" in unit.owner.upgrades:
            base *= 1.32
        elif "harvester_mk2" in unit.owner.upgrades:
            base *= 1.15
        if "singularity_core" in unit.owner.upgrades:
            base *= 1.10
    return base


def harvester_capacity(owner):
    if "harvester_mk4" in owner.upgrades:
        cap = 1700
    elif "harvester_mk3" in owner.upgrades:
        cap = 1300
    elif "harvester_mk2" in owner.upgrades:
        cap = 1000
    else:
        cap = 700
    if "singularity_core" in owner.upgrades:
        cap += 200
    return cap


def structure_damage(building):
    base = BUILD_DATA[building.kind]["damage"]
    return base * (1 + weapon_bonus_pct(building.owner))


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------
class Camera:
    def __init__(self, map_px_w, map_px_h):
        self.x = 0.0
        self.y = 0.0
        self.map_px_w = map_px_w
        self.map_px_h = map_px_h

    def clamp(self):
        self.x = clamp(self.x, 0, max(0, self.map_px_w - VIEWPORT_W))
        self.y = clamp(self.y, 0, max(0, self.map_px_h - VIEWPORT_H))

    def move(self, dx, dy):
        self.x += dx
        self.y += dy
        self.clamp()

    def center_on(self, wx, wy):
        self.x = wx - VIEWPORT_W / 2
        self.y = wy - VIEWPORT_H / 2
        self.clamp()

    def to_screen(self, wx, wy):
        return wx - self.x + VIEWPORT_X0, wy - self.y + VIEWPORT_Y0

    def to_world(self, sx, sy):
        return sx - VIEWPORT_X0 + self.x, sy - VIEWPORT_Y0 + self.y

    def in_viewport(self, sx, sy):
        return VIEWPORT_X0 <= sx < VIEWPORT_X0 + VIEWPORT_W and VIEWPORT_Y0 <= sy < VIEWPORT_Y0 + VIEWPORT_H


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------
class GameMap:
    def __init__(self, cols, rows, seed=None, biome="grass"):
        self.cols = cols
        self.rows = rows
        self.seed = seed
        self.biome = biome
        self.rng = random.Random(seed)
        self.tiles = [[TILE_GROUND] * cols for _ in range(rows)]
        self.resource_amount = [[0.0] * cols for _ in range(rows)]
        self.trainium_tier = [[0] * cols for _ in range(rows)]
        self.variant = [[0] * cols for _ in range(rows)]
        self.depleted_at = [[0.0] * cols for _ in range(rows)]
        self._generate()

    def _generate(self):
        rng = self.rng
        cols, rows = self.cols, self.rows
        for y in range(rows):
            for x in range(cols):
                self.variant[y][x] = rng.randrange(1000)

        def blob(n, min_r, max_r, tile_type, resource=0.0, tier_choice=None, pad=6):
            for _ in range(n):
                pcx = rng.randint(pad, cols - pad - 1)
                pcy = rng.randint(pad, rows - pad - 1)
                rad = rng.uniform(min_r, max_r)
                tier = tier_choice() if tier_choice else 0
                span = int(rad) + 2
                for y in range(max(0, pcy - span), min(rows, pcy + span)):
                    for x in range(max(0, pcx - span), min(cols, pcx + span)):
                        if self.tiles[y][x] != TILE_GROUND:
                            continue
                        if dist(x, y, pcx, pcy) <= rad + rng.uniform(-0.6, 0.6):
                            self.tiles[y][x] = tile_type
                            self.resource_amount[y][x] = resource
                            if tile_type == TILE_TRAINIUM:
                                self.trainium_tier[y][x] = tier

        # --- water: pools plus short & long winding rivers ---
        area = cols * rows

        def carve_river(length, width):
            x = rng.uniform(cols * 0.15, cols * 0.85)
            y = rng.uniform(rows * 0.15, rows * 0.85)
            angle = rng.uniform(0, 2 * math.pi)
            for _ in range(length):
                angle += rng.uniform(-0.4, 0.4)
                x += math.cos(angle) * 1.4
                y += math.sin(angle) * 1.4
                if not (1 <= x < cols - 1 and 1 <= y < rows - 1):
                    break
                cx_, cy_ = int(x), int(y)
                w = width if rng.random() > 0.15 else max(0, width - 1)
                for wx in range(-w, w + 1):
                    for wy in range(-w, w + 1):
                        if wx * wx + wy * wy <= w * w + 1:
                            tx, ty = cx_ + wx, cy_ + wy
                            if self.in_bounds(tx, ty) and self.tiles[ty][tx] == TILE_GROUND:
                                self.tiles[ty][tx] = TILE_WATER

        n_pools = max(2, area // 2600)
        blob(n_pools, 3, 6, TILE_WATER)
        n_short = max(1, area // 9000)
        for _ in range(n_short):
            carve_river(rng.randint(14, 24), 1)
        n_long = max(1, area // 15000)
        for _ in range(n_long):
            carve_river(rng.randint(45, 85), rng.choice([1, 1, 2]))

        # rock cliffs
        n_rock = max(6, (cols * rows) // 450)
        for _ in range(n_rock):
            cx = rng.randint(2, cols - 3)
            cy = rng.randint(2, rows - 3)
            for _ in range(rng.randint(3, 7)):
                x = clamp(cx + rng.randint(-2, 2), 0, cols - 1)
                y = clamp(cy + rng.randint(-2, 2), 0, rows - 1)
                if self.tiles[y][x] == TILE_GROUND:
                    self.tiles[y][x] = TILE_ROCK
        # forests (wood)
        blob(max(4, (cols * rows) // 700), 2, 4, TILE_TREE, resource=WOOD_PER_TREE)
        # ore deposits (metal)
        blob(max(4, (cols * rows) // 900), 1.6, 3, TILE_ORE, resource=METAL_PER_ORE)

        # trainium fields, weighted tier
        def pick_tier():
            return rng.choices(range(4), weights=TRAINIUM_TIER_WEIGHTS, k=1)[0]

        blob(max(5, (cols * rows) // 480), 2.5, 5.5, TILE_TRAINIUM,
             resource=TRAINIUM_PER_TILE, tier_choice=pick_tier)
        blob(max(2, (cols * rows) // 1800), 2, 4, TILE_RADIOACTIVE, resource=TRAINIUM_PER_TILE * 0.65)

        # keep the two base corners clear
        for (cx, cy) in [(5, rows - 6), (cols - 6, 5)]:
            for y in range(cy - 4, cy + 6):
                for x in range(cx - 4, cx + 6):
                    if 0 <= x < cols and 0 <= y < rows:
                        self.tiles[y][x] = TILE_GROUND
                        self.resource_amount[y][x] = 0
                        self.trainium_tier[y][x] = 0

    def in_bounds(self, col, row):
        return 0 <= col < self.cols and 0 <= row < self.rows

    def blocked_for_building(self, col, row):
        if not self.in_bounds(col, row):
            return True
        return self.tiles[row][col] != TILE_GROUND

    def draw_visible(self, surf, camera):
        col0 = max(0, int(camera.x // TILE))
        row0 = max(0, int(camera.y // TILE))
        col1 = min(self.cols, int((camera.x + VIEWPORT_W) // TILE) + 2)
        row1 = min(self.rows, int((camera.y + VIEWPORT_H) // TILE) + 2)
        ground_set = TILES["biomes"].get(self.biome, TILES["biomes"]["grass"])
        for row in range(row0, row1):
            for col in range(col0, col1):
                wx, wy = col * TILE, row * TILE
                sx, sy = camera.to_screen(wx, wy)
                t = self.tiles[row][col]
                v = self.variant[row][col]
                if t == TILE_ROCK:
                    img = TILES["rock"][v % len(TILES["rock"])]
                elif t == TILE_WATER:
                    img = TILES["water"][v % len(TILES["water"])]
                elif t == TILE_TREE:
                    img = TILES["tree"][v % len(TILES["tree"])]
                elif t == TILE_ORE:
                    img = TILES["ore"][v % len(TILES["ore"])]
                elif t == TILE_TRAINIUM:
                    tier = self.trainium_tier[row][col]
                    variants = TILES["trainium"][tier]
                    img = variants[v % len(variants)]
                elif t == TILE_RADIOACTIVE:
                    img = ground_set[v % len(ground_set)]
                else:
                    img = ground_set[v % len(ground_set)]
                surf.blit(img, (sx, sy))
                if t == TILE_RADIOACTIVE and AI_RADIOACTIVE_SPRITE is not None:
                    surf.blit(AI_RADIOACTIVE_SPRITE, (sx + 1, sy + 1))


def map_overview_surface(gmap, w, h):
    small = pygame.Surface((gmap.cols, gmap.rows))
    tier_colors = [(70, 200, 100), (215, 195, 60), (70, 140, 220), (210, 70, 70)]
    for y in range(gmap.rows):
        row_tiles = gmap.tiles[y]
        for x in range(gmap.cols):
            t = row_tiles[x]
            if t == TILE_ROCK:
                c = (70, 68, 64)
            elif t == TILE_WATER:
                c = (40, 90, 150)
            elif t == TILE_TREE:
                c = (30, 90, 40)
            elif t == TILE_ORE:
                c = (150, 130, 60)
            elif t == TILE_TRAINIUM:
                c = tier_colors[gmap.trainium_tier[y][x]]
            elif t == TILE_RADIOACTIVE:
                c = (100, 220, 70)
            else:
                c = {"grass": (28, 56, 30), "desert": (176, 148, 100), "snow": (215, 222, 230),
                     "radioactive": (46, 82, 48)}.get(gmap.biome, (28, 56, 30))
            small.set_at((x, y), c)
    return pygame.transform.scale(small, (w, h))


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
class Building:
    def __init__(self, kind, owner, col, row):
        data = BUILD_DATA[kind]
        self.id = next_id()
        self.kind = kind
        self.owner = owner
        self.col = col
        self.row = row
        self.w, self.h = data["size"]
        base_hp = data["hp"]
        if kind in DEFENSE_KINDS or kind in WALL_DRAG_KINDS:
            base_hp *= (1 + structure_hp_bonus_pct(owner))
        self.hp = base_hp
        self.max_hp = base_hp
        self.attack_cd = NUKE_BUILD_TIME if kind == "nuke_silo" else 0.0
        self.turret_angle = 0.0
        self.alive = True
        self.sprite = BUILDING_SPRITES.get(kind)
        # Demolish state (set by Game.start_demolish)
        self.demolish_timer    = 0.0   # seconds elapsed; 0 = not being demolished
        self.demolish_duration = 5.0   # seconds for a full demolish
        self.demolish_harvester = None  # Unit assigned to carry out the demolish

    @property
    def rect(self):
        return pygame.Rect(self.col * TILE, self.row * TILE, self.w * TILE, self.h * TILE)

    @property
    def center(self):
        r = self.rect
        return r.centerx, r.centery

    def footprint(self):
        return [(self.col + dx, self.row + dy) for dx in range(self.w) for dy in range(self.h)]

    def _wall_connections(self):
        """Return aligned wall/tower neighbors so walls visually terminate at towers."""
        if self.kind not in WALL_DRAG_KINDS:
            return set()
        neighbors = set()
        for other in self.owner.buildings:
            if other is self or not other.alive:
                continue
            if other.kind not in WALL_DRAG_KINDS and other.kind not in DEFENSE_KINDS:
                continue
            if other.col == self.col - 1 and other.row == self.row:
                neighbors.add("left")
            if other.col == self.col + 1 and other.row == self.row:
                neighbors.add("right")
            if other.col == self.col and other.row == self.row - 1:
                neighbors.add("up")
            if other.col == self.col and other.row == self.row + 1:
                neighbors.add("down")
        return neighbors

    def visual_screen_rect(self, camera):
        """Screen-space rect = tile footprint. Matches pad_rect in draw()."""
        r = self.rect
        sx0, sy0 = camera.to_screen(r.x, r.y)
        return pygame.Rect(sx0, sy0, r.w, r.h)

    def take_damage(self, dmg):
        self.hp -= dmg
        if self.hp <= 0:
            self.hp = 0
            self.alive = False

    def draw(self, surf, camera, selected=False):
        r = self.rect
        _CM = 320
        if r.right < camera.x - _CM or r.left > camera.x + VIEWPORT_W + _CM or \
           r.bottom < camera.y - _CM or r.top > camera.y + VIEWPORT_H + _CM:
            return
        sx0, sy0 = camera.to_screen(r.x, r.y)
        sprite = self.sprite

        # pad_rect = tile footprint in screen space.
        # This is the "invisible build space" made visible — exact grid cells,
        # never overlaps, always aligned to the 32 px tile grid.
        pad_rect = pygame.Rect(sx0, sy0, r.w, r.h)

        if sprite is not None:
            sp_w, sp_h = sprite.get_size()
        else:
            sp_w, sp_h = r.w, r.h
        pad = pygame.Surface((pad_rect.w, pad_rect.h), pygame.SRCALPHA)
        pad.fill((*self.owner.color, 40))
        surf.blit(pad, pad_rect.topleft)
        pygame.draw.rect(surf, self.owner.color, pad_rect, 2)
        # Sprite anchored midbottom at the tile footprint bottom-centre.
        iso_rect = (sprite or pygame.Surface((sp_w, sp_h), pygame.SRCALPHA)).get_rect(
            midbottom=(pad_rect.centerx, pad_rect.bottom))
        if sprite is not None:
            surf.blit(sprite, iso_rect)
        else:
            col = (80, 170, 70) if self.kind == "nuke_silo" else self.owner.color
            pygame.draw.rect(surf, col, iso_rect, border_radius=4)
            pygame.draw.rect(surf, (20, 20, 20), iso_rect, 2, border_radius=4)
            if self.kind == "nuke_silo":
                pygame.draw.circle(surf, (220, 240, 80), iso_rect.center, max(4, iso_rect.w // 5))
        if self.kind in WALL_DRAG_KINDS:
            connections = self._wall_connections()
            left, right = "left" in connections, "right" in connections
            up, down = "up" in connections, "down" in connections
            cx, cy = pad_rect.center
            wall_col = (205, 185, 120) if self.kind == "fence" else (145, 150, 160)
            arm = max(10, min(pad_rect.w, pad_rect.h) // 2 - 2)
            endpoints = []
            if left: endpoints.append((cx - arm, cy))
            if right: endpoints.append((cx + arm, cy))
            if up: endpoints.append((cx, cy - arm))
            if down: endpoints.append((cx, cy + arm))
            # Isolated pieces retain a clear vertical orientation; connected
            # pieces use only their actual cardinal neighbors, producing clean
            # straight, L-corner, T, and cross junctions.
            if not endpoints:
                endpoints = [(cx, cy - arm), (cx, cy + arm)]
            for ex, ey in endpoints:
                pygame.draw.line(surf, wall_col, (cx, cy), (ex, ey), 6)
            pygame.draw.circle(surf, (245, 220, 150), (cx, cy), 4)
        elif self.kind in DEFENSE_KINDS:
            # Keep the generated tower/base artwork fixed while the weapon on
            # top tracks the current target independently.
            cx, cy = iso_rect.center
            gun_len = 22 if self.kind != "rockettower" else 18
            gx = int(cx + math.cos(self.turret_angle) * gun_len)
            gy = int(cy + math.sin(self.turret_angle) * gun_len)
            if self.kind == "rockettower":
                pygame.draw.line(surf, (52, 56, 48), (cx, cy), (gx, gy), 7)
                pygame.draw.line(surf, (170, 70, 45), (cx, cy), (gx, gy), 3)
                pygame.draw.circle(surf, (210, 80, 45), (gx, gy), 4)
            else:
                pygame.draw.line(surf, (35, 38, 38), (cx, cy), (gx, gy), 7)
                pygame.draw.line(surf, (150, 155, 125), (cx, cy), (gx, gy), 3)
                pygame.draw.circle(surf, (30, 32, 30), (cx, cy), 8, 2)
        fx, fy = FLAG_OFFSET.get(self.kind, (6, 6))
        flag_rect = pygame.Rect(iso_rect.x + fx, iso_rect.y + fy, 9, 9)
        pygame.draw.rect(surf, self.owner.color, flag_rect)
        pygame.draw.rect(surf, (10, 10, 10), flag_rect, 1)
        if selected:
            pygame.draw.rect(surf, COL_SELECT, pad_rect, 2)
        top_y = min(pad_rect.y, iso_rect.y)
        if self.kind not in WALL_DRAG_KINDS:
            label = FONT_SMALL.render(BUILD_DATA[self.kind]["name"][:12], True, COL_TEXT)
            label_bg = pygame.Surface((label.get_width() + 4, label.get_height() + 2), pygame.SRCALPHA)
            label_bg.fill((0, 0, 0, 120))
            surf.blit(label_bg, (pad_rect.x - 2, top_y - 17))
            surf.blit(label, (pad_rect.x, top_y - 16))
        draw_health_bar(surf, pad_rect.x, top_y - 4, pad_rect.w, 5, self.hp, self.max_hp)
        if self.demolish_timer > 0 and self.demolish_duration > 0:
            pct_left = 1.0 - min(self.demolish_timer / self.demolish_duration, 1.0)
            bar_x, bar_y = pad_rect.x, top_y + 4
            bar_w, bar_h = max(pad_rect.w, 20), 6
            pygame.draw.rect(surf, (50, 15, 15),   (bar_x, bar_y, bar_w, bar_h))
            fill_w = max(0, round(bar_w * pct_left))
            if fill_w > 0:
                pygame.draw.rect(surf, (210, 35, 35), (bar_x, bar_y, fill_w, bar_h))
            pygame.draw.rect(surf, (160, 20, 20),  (bar_x, bar_y, bar_w, bar_h), 1)


class Unit:
    def __init__(self, kind, owner, x, y):
        data = UNIT_DATA[kind]
        self.id = next_id()
        self.kind = kind
        self.owner = owner
        self.x = float(x)
        self.y = float(y)
        self.hp = data["hp"]
        self.selected = False
        self.target_pos = None
        self.target_entity = None
        self.attack_cd = 0.0
        self.alive = True
        self.state = "idle"
        self.cargo = 0.0
        self.cargo_kind = None
        self.cargo_tier = 0
        self.harvest_tile = None
        self.manual_harvest_tile = None  # set when the player right-clicks a specific resource tile
        self.rank = 0
        self.kills = 0
        self.heading = 0.0
        self.gun_angle = 0.0

    @property
    def radius(self):
        if self.kind in ("tank", "harvester", "apc"):
            return round(14 * VEHICLE_SCALE)
        return round(9 * INFANTRY_SCALE)

    def take_damage(self, dmg):
        self.hp -= dmg
        if self.hp <= 0:
            self.hp = 0
            self.alive = False

    def move_toward(self, tx, ty, dt):
        dx, dy = tx - self.x, ty - self.y
        d = math.hypot(dx, dy)
        if d < 2:
            return True
        self.heading = math.atan2(dy, dx)
        step = effective_speed(self) * dt
        reached = step >= d
        nx, ny = (tx, ty) if reached else (self.x + dx / d * step, self.y + dy / d * step)
        if CURRENT_MAP is not None:
            col, row = int(nx // TILE), int(ny // TILE)
            if CURRENT_MAP.in_bounds(col, row):
                tile = CURRENT_MAP.tiles[row][col]
                if tile == TILE_WATER and not UNIT_DATA[self.kind].get("amphibious"):
                    sx, sy = -dy / (d or 1), dx / (d or 1)
                    for side in (1, -1):
                        ax, ay = self.x + sx * side * TILE, self.y + sy * side * TILE
                        ac, ar = int(ax // TILE), int(ay // TILE)
                        if CURRENT_MAP.in_bounds(ac, ar) and CURRENT_MAP.tiles[ar][ac] != TILE_WATER:
                            self.x, self.y = ax, ay
                            break
                    return False
                for b in getattr(CURRENT_MAP, "game_buildings", []):
                    if b.alive and b.kind in WALL_DRAG_KINDS and b.owner is not self.owner and b.rect.collidepoint(nx, ny):
                        return False
        self.x, self.y = nx, ny
        return reached

    def draw(self, surf, camera):
        if not (camera.x - 30 <= self.x <= camera.x + VIEWPORT_W + 30 and
                camera.y - 30 <= self.y <= camera.y + VIEWPORT_H + 30):
            return
        px, py = camera.to_screen(self.x, self.y)
        px, py = int(px), int(py)
        color = self.owner.color
        ai_sprite = AI_APC_SPRITE if self.kind == "apc" else AI_UNIT_SPRITES.get(self.kind)
        if ai_sprite is not None:
            # Vehicles and infantry face their travel direction. The tank hull
            # rotates with movement while its gun is aimed independently.
            rotated = pygame.transform.rotate(ai_sprite, -math.degrees(self.heading))
            sprite_rect = rotated.get_rect(center=(px, py))
            surf.blit(rotated, sprite_rect)
            if self.kind == "tank":
                if self.target_entity is not None:
                    tcx, tcy = get_center(self.target_entity)
                    tsx, tsy = camera.to_screen(tcx, tcy)
                    self.gun_angle = math.atan2(tsy - py, tsx - px)
                _gun_len = round(23 * VEHICLE_SCALE)
                gx = px + math.cos(self.gun_angle) * _gun_len
                gy = py + math.sin(self.gun_angle) * _gun_len
                pygame.draw.line(surf, (40, 42, 42), (px, py), (gx, gy), 5)
                pygame.draw.line(surf, (120, 125, 110), (px, py), (gx, gy), 2)
            txt = ""
        elif self.kind == "harvester":
            _sz = round(22 * VEHICLE_SCALE)
            rect = pygame.Rect(0, 0, _sz, _sz)
            rect.center = (px, py)
            pygame.draw.rect(surf, (210, 200, 60), rect)
            pygame.draw.rect(surf, color, rect, 2)
            txt = "H"
        elif self.kind == "tank":
            _sz = round(24 * VEHICLE_SCALE)
            rect = pygame.Rect(0, 0, _sz, _sz)
            rect.center = (px, py)
            pygame.draw.rect(surf, color, rect)
            pygame.draw.rect(surf, (10, 10, 10), rect, 2)
            angle = 0
            if self.target_entity is not None:
                tcx, tcy = get_center(self.target_entity)
                tsx, tsy = camera.to_screen(tcx, tcy)
                angle = math.atan2(tsy - py, tsx - px)
            _blen = round(16 * VEHICLE_SCALE)
            bx = px + math.cos(angle) * _blen
            by = py + math.sin(angle) * _blen
            pygame.draw.line(surf, (10, 10, 10), (px, py), (bx, by), 4)
            txt = "T"
        elif self.kind == "rocket":
            _r = round(10 * INFANTRY_SCALE)
            pygame.draw.circle(surf, color, (px, py), _r)
            pygame.draw.circle(surf, (10, 10, 10), (px, py), _r, 2)
            txt = "R"
        else:
            _r = round(8 * INFANTRY_SCALE)
            pygame.draw.circle(surf, color, (px, py), _r)
            pygame.draw.circle(surf, (10, 10, 10), (px, py), _r, 2)
            txt = "I"

        if self.selected:
            pygame.draw.circle(surf, COL_SELECT, (px, py), self.radius + 6, 1)

        if txt:
            label = FONT_SMALL.render(txt, True, (15, 15, 15))
            surf.blit(label, (px - 4, py - 6))
        top = py - self.radius - 10
        if self.rank > 0:
            for i in range(self.rank):
                cx2 = px - 6 + i * 7
                pygame.draw.polygon(surf, (255, 215, 80),
                                     [(cx2 - 3, top - 2), (cx2, top - 6), (cx2 + 3, top - 2)])
        draw_health_bar(surf, px - 14, top, 28, 4, self.hp, effective_max_hp(self))


class Projectile:
    def __init__(self, shooter, owner, target, damage, kind, x, y):
        self.shooter = shooter
        self.owner = owner
        self.target = target
        self.damage = damage
        self.kind = kind
        self.x = x
        self.y = y
        self.speed = PROJECTILE_SPEED.get(kind, 700)
        self.alive = True
        self.age = 0.0

    def update(self, dt, game):
        self.age += dt
        if not getattr(self.target, "alive", False):
            self.alive = False
            return
        tx, ty = get_center(self.target)
        dx, dy = tx - self.x, ty - self.y
        d = math.hypot(dx, dy)
        hit_radius = 14 if self.kind == "rocket" else 10
        if d <= hit_radius or self.age > 4.0:
            was_alive = self.target.alive
            self.target.take_damage(self.damage)
            if self.kind in ("rocket", "nuke"):
                radius = 150 if self.kind == "nuke" else 34
                game.explosions.append({"x": tx, "y": ty, "radius": radius, "age": 0.0,
                                        "max_age": EXPLOSION_LIFETIME,
                                        "color": (180, 255, 80) if self.kind == "nuke" else (255, 150, 50)})
                if self.kind == "nuke":
                    for p in game.players:
                        for e in p.units + p.buildings:
                            if e is not self.target and getattr(e, "alive", False):
                                ex, ey = get_center(e)
                                if dist(tx, ty, ex, ey) <= radius:
                                    e.take_damage(self.damage * 0.55)
            if was_alive and not self.target.alive and self.shooter is not None:
                game.register_kill(self.shooter)
            self.alive = False
            return
        step = self.speed * dt
        if step >= d:
            self.x, self.y = tx, ty
        else:
            self.x += dx / d * step
            self.y += dy / d * step

    def draw(self, surf, camera):
        sx, sy = camera.to_screen(self.x, self.y)
        sx, sy = int(sx), int(sy)
        color = PROJECTILE_COLOR.get(self.kind, (255, 255, 255))
        if self.kind == "shell" and AI_PROJECTILE_SPRITE is not None:
            surf.blit(AI_PROJECTILE_SPRITE, AI_PROJECTILE_SPRITE.get_rect(center=(sx, sy)))
        elif self.kind == "bullet":
            pygame.draw.circle(surf, color, (sx, sy), 2)
        elif self.kind == "rocket":
            pygame.draw.circle(surf, color, (sx, sy), 4)
            pygame.draw.circle(surf, (255, 230, 190), (sx, sy), 2)
        else:
            pygame.draw.circle(surf, color, (sx, sy), 3)
            pygame.draw.circle(surf, (255, 220, 140), (sx, sy), 1)


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------
class Player:
    def __init__(self, name, color, is_ai, corner, is_remote=False):
        self.name = name
        self.color = color
        self.is_ai = is_ai
        self.is_remote = is_remote   # True only for the host's copy of a connected human client
        self.credits = 4000
        self.wood = 400
        self.metal = 400
        self.buildings = []
        self.units = []
        self.upgrades = set()
        self.queues = {"building": [], "infantry": [], "vehicle": [], "research": []}
        self.pending_placement = None
        self.pending_cost = None
        self.corner = corner
        self.ai_decision_timer = 0.0
        self.ui_tab = "base"

    def power_produced(self):
        return sum(BUILD_DATA[b.kind]["power"] for b in self.buildings if b.alive and BUILD_DATA[b.kind]["power"] > 0)

    def power_used(self):
        return sum(-BUILD_DATA[b.kind]["power"] for b in self.buildings if b.alive and BUILD_DATA[b.kind]["power"] < 0)

    def low_power(self):
        return self.power_used() > self.power_produced()

    def has_building(self, kind):
        return any(b.kind == kind and b.alive for b in self.buildings)

    def buildings_of(self, kind):
        return [b for b in self.buildings if b.kind == kind and b.alive]

    def is_defeated(self):
        return not self.has_building("yard")

    def category_of(self, kind):
        if kind in BUILD_DATA:
            return "building"
        if kind in UPGRADE_DATA:
            return "research"
        if UNIT_DATA[kind]["built_from"] == "barracks":
            return "infantry"
        return "vehicle"

    def can_afford(self, cost):
        return (self.credits >= cost.get("credits", 0) and
                self.wood >= cost.get("wood", 0) and
                self.metal >= cost.get("metal", 0))

    def can_start(self, kind):
        cat = self.category_of(kind)
        if len(self.queues[cat]) >= MAX_QUEUE_LEN:
            return False
        if kind in UPGRADE_DATA:
            if kind in self.upgrades:
                return False
            if any(item["kind"] == kind for item in self.queues[cat]):
                return False
            if not self.has_building("research"):
                return False
            req = UPGRADE_DATA[kind].get("requires")
            if req:
                req_list = [req] if isinstance(req, str) else req
                if not all(r in self.upgrades for r in req_list):
                    return False
        if kind in UNIT_DATA and not self.has_building(UNIT_DATA[kind]["built_from"]):
            return False
        if not self.can_afford(get_data(kind)["cost"]):
            return False
        return True

    def start_production(self, kind):
        if not self.can_start(kind):
            return False
        cat = self.category_of(kind)
        data = get_data(kind)
        cost = data["cost"]
        self.credits -= cost.get("credits", 0)
        self.wood -= cost.get("wood", 0)
        self.metal -= cost.get("metal", 0)
        time_ = data["time"]
        if cat == "building":
            time_ *= build_time_mult(self)
        self.queues[cat].append({"kind": kind, "timer": 0.0, "total": max(time_, 0.4)})
        return True

    def update_queues(self, dt, game):
        slow = 2.0 if self.low_power() else 1.0
        for cat, items in self.queues.items():
            if not items:
                continue
            if cat == "building" and self.pending_placement is not None:
                continue  # a building is already finished and awaiting placement
            item = items[0]
            item["timer"] += dt / slow
            if item["timer"] >= item["total"]:
                items.pop(0)
                kind = item["kind"]
                if cat == "building":
                    if self.is_ai:
                        game.ai_auto_place(self, kind)
                    else:
                        self.pending_placement = kind
                        self.pending_cost = BUILD_DATA[kind]["cost"]
                        if self.is_remote:
                            game.notify_remote_ready_to_place(self, kind)
                elif cat == "research":
                    game.apply_upgrade(self, kind)
                else:
                    game.spawn_unit(self, kind)


# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------
class Game:
    def __init__(self, cols, rows, seed=None, biome="grass", net_role=None, net=None):
        self.net_role = net_role      # None (skirmish), "host", or "client"
        self.net = net
        self.net_send_timer = 0.0
        self.dirty_tiles = []         # (col,row,tile_type,tier) - depleted resource tiles to sync
        self.local_is_p1 = (net_role != "client")
        self.map = GameMap(cols, rows, seed=seed, biome=biome)
        global CURRENT_MAP
        CURRENT_MAP = self.map
        map_px_w, map_px_h = cols * TILE, rows * TILE
        self.camera = Camera(map_px_w, map_px_h)
        self._p1 = Player("Player 1", PLAYER_COLOR, False, (5, rows - 6))
        self._p2 = Player("Player 2", AI_COLOR, net_role is None, (cols - 6, 5),
                           is_remote=(net_role == "host"))
        self.players = [self._p1, self._p2]
        self.selected_units = []
        self.selected_entity = None
        self.drag_start = None
        self.drag_rect = None
        self.wall_drag_tile = None
        self.game_over = None
        self.projectiles = []
        self.explosions = []
        self.elapsed = 0.0
        self._setup_base(self._p1)
        self._setup_base(self._p2)
        self.map.game_buildings = self._p1.buildings + self._p2.buildings
        self.camera.center_on(*[c * TILE for c in self.player.corner])
        self.overview_surface = None
        self.overview_timer = 0.0
        self.sidebar_buttons = []
        self.tab_buttons = []
        self.minimap_rect = None
        self.sidebar_scroll = 0
        self.sidebar_max_scroll = 0
        self.move_marker = None  # {"x","y","age","attack"} - fading ping shown at right-click orders
        self.open_tree_button = None
        self.show_tech_tree = False
        self.tech_tree_nodes = None  # lazily built: kind -> pygame.Rect
        self.tech_tree_close_button = None

    # "player"/"ai" are perspective-relative views onto the two absolute
    # sides (_p1/_p2) so all the existing rendering/input/sidebar code can
    # keep saying "my side" / "their side" regardless of whether this
    # instance is a skirmish, a network host (always p1), or a network
    # client (always p2).
    @property
    def player(self):
        return self._p1 if self.local_is_p1 else self._p2

    @property
    def ai(self):
        return self._p2 if self.local_is_p1 else self._p1

    def _setup_base(self, p):
        cx, cy = p.corner
        cols, rows = self.map.cols, self.map.rows
        yard = Building("yard", p, cx, cy)
        power = Building("power", p, cx + 5, cy)
        ref_row = cy + 6 if cy + 6 + 2 <= rows else max(cy - 5, 0)
        refinery = Building("refinery", p, cx, ref_row)
        for b in (yard, power, refinery):
            b.col = clamp(b.col, 0, cols - b.w)
            b.row = clamp(b.row, 0, rows - b.h)
            for (fx, fy) in b.footprint():
                self.map.tiles[fy][fx] = TILE_GROUND
                self.map.resource_amount[fy][fx] = 0
        p.buildings += [yard, power, refinery]
        rx, ry = refinery.center
        h = Unit("harvester", p, rx, ry + 55)
        p.units.append(h)
        for i in range(2):
            u = Unit("infantry", p, rx + 30 + i * 26, ry + 55)
            p.units.append(u)

    def enemy_of(self, p):
        return self._p2 if p is self._p1 else self._p1

    def spawn_unit(self, p, kind):
        src_kind = UNIT_DATA[kind]["built_from"]
        sources = p.buildings_of(src_kind)
        if not sources:
            p.credits += UNIT_DATA[kind]["cost"].get("credits", 0)
            return
        b = self.selected_entity if self.selected_entity in sources else sources[0]
        bx, by = b.center
        ox = random.uniform(-1, 1) * (b.w * TILE / 2 + 20)
        oy = b.h * TILE / 2 + 24
        u = Unit(kind, p, bx + ox, by + oy)
        u.x = clamp(u.x, 10, self.map.cols * TILE - 10)
        u.y = clamp(u.y, 10, self.map.rows * TILE - 10)
        if kind != "harvester" and "veteran_training" in p.upgrades:
            u.rank = 1
            u.hp = effective_max_hp(u)
        p.units.append(u)

    def apply_upgrade(self, player, kind):
        UNIT_HP_UPGRADES = {"armor_plating", "reinforced_armor", "singularity_core"}
        STRUCT_HP_UPGRADES = {"fortified_walls", "singularity_core"}
        old_unit_max = {u.id: effective_max_hp(u) for u in player.units} if kind in UNIT_HP_UPGRADES else None
        structs = [b for b in player.buildings if b.kind in DEFENSE_KINDS or b.kind in WALL_DRAG_KINDS]
        old_struct_max = {b.id: b.max_hp for b in structs} if kind in STRUCT_HP_UPGRADES else None

        player.upgrades.add(kind)

        if old_unit_max is not None:
            for u in player.units:
                new_max = effective_max_hp(u)
                old_max = old_unit_max.get(u.id, new_max)
                if old_max > 0:
                    u.hp = u.hp * new_max / old_max
        if old_struct_max is not None:
            for b in structs:
                new_max = BUILD_DATA[b.kind]["hp"] * (1 + structure_hp_bonus_pct(player))
                old_max = old_struct_max.get(b.id, new_max)
                if old_max > 0:
                    b.hp = b.hp * new_max / old_max
                b.max_hp = new_max

    def register_kill(self, shooter):
        if not isinstance(shooter, Unit) or not shooter.alive:
            return
        shooter.kills += 1
        new_rank = 0
        if shooter.kills >= RANK_KILLS[2]:
            new_rank = 2
        elif shooter.kills >= RANK_KILLS[1]:
            new_rank = 1
        if new_rank > shooter.rank:
            shooter.rank = new_rank
            shooter.hp = effective_max_hp(shooter)

    def spawn_projectile(self, shooter, owner, target, damage, kind):
        x, y = get_center(shooter)
        self.projectiles.append(Projectile(shooter, owner, target, damage, kind, x, y))

    # ---- networking -----------------------------------------------------
    def notify_remote_ready_to_place(self, player, kind):
        # host telling the connected client "your building is done, place it"
        if self.net_role == "host":
            self.net.send({"type": "ready_to_place", "kind": kind})

    def find_entity_by_id(self, entity_id):
        for p in self.players:
            for u in p.units:
                if u.id == entity_id:
                    return u
            for b in p.buildings:
                if b.id == entity_id:
                    return b
        return None

    def poll_network(self):
        if not self.net:
            return
        if self.net_role == "host":
            for msg in self.net.poll():
                self.handle_client_command(msg)
            if not self.net.connected and self.game_over is None:
                self.game_over = "disconnected"
        elif self.net_role == "client":
            for msg in self.net.poll():
                t = msg.get("type")
                if t == "state":
                    self.apply_snapshot(msg)
                elif t == "ready_to_place":
                    kind = msg["kind"]
                    self.player.pending_placement = kind
                    self.player.pending_cost = BUILD_DATA[kind]["cost"]
            if not self.net.connected and self.game_over is None:
                self.game_over = "disconnected"

    def handle_client_command(self, msg):
        # Host-side: apply a command sent by the connected human client.
        p2 = self._p2
        t = msg.get("type")
        if t == "produce":
            p2.start_production(msg["kind"])
        elif t == "place":
            kind, col, row = msg["kind"], msg["col"], msg["row"]
            if kind in BUILD_DATA and self.can_place(p2, kind, col, row):
                if kind in WALL_DRAG_KINDS:
                    cost = BUILD_DATA[kind]["cost"]
                    if not p2.can_afford(cost):
                        return
                    p2.credits -= cost.get("credits", 0)
                    p2.wood -= cost.get("wood", 0)
                    p2.metal -= cost.get("metal", 0)
                self.place_building(p2, kind, col, row)
        elif t == "cancel_placement":
            cost = msg.get("cost") or {}
            p2.credits += cost.get("credits", 0)
            p2.wood += cost.get("wood", 0)
            p2.metal += cost.get("metal", 0)
            p2.pending_placement = None
            p2.pending_cost = None
        elif t == "move":
            ids = set(msg.get("unit_ids", []))
            units = [u for u in p2.units if u.id in ids]
            self._apply_move_order(units, msg["x"], msg["y"])
        elif t == "attack":
            target = self.find_entity_by_id(msg.get("target_id"))
            ids = set(msg.get("unit_ids", []))
            if target is not None:
                for u in p2.units:
                    if u.id in ids:
                        u.target_entity = target
                        u.target_pos = None
                        u.manual_harvest_tile = None

    def build_snapshot(self):
        def uinfo(u):
            return {"id": u.id, "kind": u.kind, "owner": "p1" if u.owner is self._p1 else "p2",
                    "x": u.x, "y": u.y, "hp": u.hp, "rank": u.rank}

        def binfo(b):
            return {"id": b.id, "kind": b.kind, "owner": "p1" if b.owner is self._p1 else "p2",
                    "col": b.col, "row": b.row, "hp": b.hp, "max_hp": b.max_hp}

        def pinfo(p):
            return {"credits": p.credits, "wood": p.wood, "metal": p.metal,
                    "upgrades": list(p.upgrades), "queues": p.queues}

        msg = {
            "type": "state",
            "p1": pinfo(self._p1), "p2": pinfo(self._p2),
            "units": [uinfo(u) for p in self.players for u in p.units],
            "buildings": [binfo(b) for p in self.players for b in p.buildings],
            "projectiles": [{"x": pr.x, "y": pr.y, "kind": pr.kind} for pr in self.projectiles],
            "dirty_tiles": self.dirty_tiles,
            "game_over": self.game_over,
        }
        self.dirty_tiles = []
        return msg

    def apply_snapshot(self, msg):
        def apply_pinfo(player, data):
            player.credits = data["credits"]
            player.wood = data["wood"]
            player.metal = data["metal"]
            player.upgrades = set(data["upgrades"])
            for k, v in data["queues"].items():
                player.queues[k] = v

        apply_pinfo(self._p1, msg["p1"])
        apply_pinfo(self._p2, msg["p2"])

        selected_ids = {u.id for u in self.selected_units}
        existing_units = {u.id: u for p in self.players for u in p.units}
        new_p1_units, new_p2_units = [], []
        for ud in msg["units"]:
            owner = self._p1 if ud["owner"] == "p1" else self._p2
            u = existing_units.get(ud["id"])
            if u is None:
                u = Unit(ud["kind"], owner, ud["x"], ud["y"])
                u.id = ud["id"]
            else:
                u.x, u.y = ud["x"], ud["y"]
                u.owner = owner
            u.hp = ud["hp"]
            u.rank = ud["rank"]
            u.selected = u.id in selected_ids
            (new_p1_units if owner is self._p1 else new_p2_units).append(u)
        self._p1.units = new_p1_units
        self._p2.units = new_p2_units
        self.selected_units = [u for u in self.player.units if u.selected]

        existing_b = {b.id: b for p in self.players for b in p.buildings}
        new_p1_b, new_p2_b = [], []
        for bd in msg["buildings"]:
            owner = self._p1 if bd["owner"] == "p1" else self._p2
            b = existing_b.get(bd["id"])
            if b is None:
                b = Building(bd["kind"], owner, bd["col"], bd["row"])
                b.id = bd["id"]
            b.hp = bd["hp"]
            b.max_hp = bd["max_hp"]
            (new_p1_b if owner is self._p1 else new_p2_b).append(b)
        self._p1.buildings = new_p1_b
        self._p2.buildings = new_p2_b

        self.projectiles = [Projectile(None, None, None, 0, pd["kind"], pd["x"], pd["y"])
                             for pd in msg["projectiles"]]

        for (col, row, ttype, tier) in msg.get("dirty_tiles", []):
            if self.map.in_bounds(col, row):
                self.map.tiles[row][col] = ttype
                self.map.trainium_tier[row][col] = tier

        self.game_over = msg.get("game_over")

    # ---- building placement --------------------------------------------
    def can_place(self, p, kind, col, row):
        data = BUILD_DATA[kind]
        w, h = data["size"]
        cols, rows = self.map.cols, self.map.rows
        if col < 0 or row < 0 or col + w > cols or row + h > rows:
            return False
        for x in range(col, col + w):
            for y in range(row, row + h):
                if self.map.tiles[y][x] != TILE_GROUND:
                    return False
        for other in p.buildings + self.enemy_of(p).buildings:
            if not other.alive:
                continue
            orect = pygame.Rect(other.col, other.row, other.w, other.h)
            nrect = pygame.Rect(col, row, w, h)
            if orect.colliderect(nrect):
                return False
        near = False
        for b in p.buildings:
            if not b.alive:
                continue
            bd = max(abs((col + w / 2) - (b.col + b.w / 2)), abs((row + h / 2) - (b.row + b.h / 2)))
            if bd <= ADJ_RANGE:
                near = True
                break
        return near

    def place_building(self, p, kind, col, row):
        b = Building(kind, p, col, row)
        p.buildings.append(b)
        p.pending_placement = None
        p.pending_cost = None

    def ai_auto_place(self, p, kind):
        w, h = BUILD_DATA[kind]["size"]
        cx, cy = p.corner
        for radius in range(0, 18):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    col, row = cx + dx, cy + dy
                    if self.can_place(p, kind, col, row):
                        self.place_building(p, kind, col, row)
                        return
        cost = BUILD_DATA[kind]["cost"]
        p.credits += cost.get("credits", 0)
        p.wood += cost.get("wood", 0)
        p.metal += cost.get("metal", 0)

    def nearest_enemy(self, p, x, y, max_range=None):
        best, best_d = None, None
        for target in self.enemy_of(p).units:
            if not target.alive:
                continue
            d = dist(x, y, target.x, target.y)
            if max_range is not None and d > max_range:
                continue
            if best_d is None or d < best_d:
                best, best_d = target, d
        for target in self.enemy_of(p).buildings:
            if not target.alive:
                continue
            tx, ty = target.center
            d = dist(x, y, tx, ty)
            if max_range is not None and d > max_range:
                continue
            if best_d is None or d < best_d:
                best, best_d = target, d
        return best

    # ---- update ---------------------------------------------------------
    def update(self, dt):
        self.elapsed += dt
        self.map.game_buildings = self._p1.buildings + self._p2.buildings
        self.update_camera(dt)
        self._update_overview(dt)
        if self.move_marker is not None:
            self.move_marker["age"] += dt
            if self.move_marker["age"] > 0.7:
                self.move_marker = None

        if self.net_role == "client":
            self.poll_network()
            return
        if self.net_role == "host":
            self.poll_network()

        if self.game_over:
            if self.net_role == "host":
                self.net_send_timer -= dt
                if self.net_send_timer <= 0:
                    self.net_send_timer = 0.08
                    self.net.send(self.build_snapshot())
            return

        self.update_resource_regeneration()
        self.update_demolish(dt)
        for p in self.players:
            p.update_queues(dt, self)
        self.update_units(self._p1, dt)
        self.update_units(self._p2, dt)
        self.update_defenses(self._p1, dt)
        self.update_defenses(self._p2, dt)
        if self.net_role is None:
            self.update_ai(dt)

        for pr in self.projectiles:
            pr.update(dt, self)
        self.projectiles = [pr for pr in self.projectiles if pr.alive]
        for fx in self.explosions:
            fx["age"] += dt
        self.explosions = [fx for fx in self.explosions if fx["age"] < fx["max_age"]]

        for p in self.players:
            p.units = [u for u in p.units if u.alive]
            p.buildings = [b for b in p.buildings if b.alive]
        self.selected_units = [u for u in self.selected_units if u.alive]

        if self._p1.is_defeated():
            self.game_over = "p2_win"
        elif self._p2.is_defeated():
            self.game_over = "p1_win"

        if self.net_role == "host":
            self.net_send_timer -= dt
            if self.net_send_timer <= 0:
                self.net_send_timer = 0.08
                self.net.send(self.build_snapshot())

    def start_demolish(self):
        """Called when player presses Del with a friendly building selected.
        Finds the nearest harvester and sends it to demolish the building."""
        b = self.selected_entity
        if not isinstance(b, Building):
            return
        if b.owner is not self.player or not b.alive:
            return
        if b.kind == "yard":
            return
        harvesters = [u for u in self.player.units
                      if u.kind == "harvester" and u.alive]
        if not harvesters:
            return
        bx, by = b.center
        h = min(harvesters, key=lambda u: dist(u.x, u.y, bx, by))
        # Interrupt whatever the harvester was doing
        h.target_pos = (bx, by)
        h.target_entity = None
        h.state = "idle"
        h.cargo = 0.0
        # Arm the building
        b.demolish_timer    = 0.001   # non-zero activates the bar immediately
        b.demolish_duration = 5.0
        b.demolish_harvester = h

    def update_demolish(self, dt):
        """Tick demolish progress on every building that is being demolished."""
        for p in self.players:
            for b in p.buildings:
                if b.demolish_timer <= 0 or b.demolish_harvester is None:
                    continue
                h = b.demolish_harvester
                if not h.alive:
                    b.demolish_timer = 0.0
                    b.demolish_harvester = None
                    continue
                bx, by = b.center
                # Keep the harvester pinned to the building centre
                h.target_pos = (bx, by)
                # Only progress once the harvester is close enough
                arrive_dist = h.radius + max(b.w, b.h) * TILE * 0.55
                if dist(h.x, h.y, bx, by) <= arrive_dist:
                    b.demolish_timer += dt
                    if b.demolish_timer >= b.demolish_duration:
                        # Refund 80 % of build cost in every resource
                        cost = BUILD_DATA[b.kind]["cost"]
                        p.credits += int(cost.get("credits", 0) * 0.8)
                        p.wood    += int(cost.get("wood",    0) * 0.8)
                        p.metal   += int(cost.get("metal",   0) * 0.8)
                        h.target_pos       = None
                        b.demolish_harvester = None
                        b.alive            = False
                        if self.selected_entity is b:
                            self.selected_entity = None

    def _update_overview(self, dt):
        # runs for host, client, and skirmish alike since each side has its
        # own local copy of the map (kept in sync via dirty_tiles)
        self.overview_timer -= dt
        if self.overview_timer <= 0:
            self.overview_timer = 3.0
            self.overview_surface = map_overview_surface(self.map, 250, int(250 * self.map.rows / self.map.cols))

    def update_camera(self, dt):
        keys = pygame.key.get_pressed()
        dx = dy = 0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            dx -= 1
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            dx += 1
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            dy -= 1
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            dy += 1
        mx, my = pygame.mouse.get_pos()
        if self.camera.in_viewport(mx, my):
            if mx - VIEWPORT_X0 < EDGE_SCROLL_MARGIN:
                dx -= 1
            elif VIEWPORT_X0 + VIEWPORT_W - mx < EDGE_SCROLL_MARGIN:
                dx += 1
            if my - VIEWPORT_Y0 < EDGE_SCROLL_MARGIN:
                dy -= 1
            elif VIEWPORT_Y0 + VIEWPORT_H - my < EDGE_SCROLL_MARGIN:
                dy += 1
        if dx or dy:
            norm = math.hypot(dx, dy) or 1
            self.camera.move(dx / norm * CAMERA_SPEED * dt, dy / norm * CAMERA_SPEED * dt)

    def update_defenses(self, p, dt):
        struct_regen = "auto_repair_bay" in p.upgrades or "singularity_core" in p.upgrades
        for b in p.buildings:
            if not b.alive:
                continue
            is_defensive = b.kind in DEFENSE_KINDS or b.kind in WALL_DRAG_KINDS
            if struct_regen and is_defensive and b.hp < b.max_hp:
                b.hp = min(b.max_hp, b.hp + b.max_hp * 0.015 * dt)
            if b.kind not in DEFENSE_KINDS:
                continue
            data = BUILD_DATA[b.kind]
            b.attack_cd -= dt
            if b.attack_cd <= 0:
                cx, cy = b.center
                target = self.nearest_enemy(p, cx, cy, data["range"])
                if target is not None:
                    tx, ty = get_center(target)
                    b.turret_angle = math.atan2(ty - cy, tx - cx)
                    dmg = structure_damage(b)
                    self.spawn_projectile(b, p, target, dmg, data.get("projectile", "bullet"))
                    b.attack_cd = data["cooldown"] * (2.0 if p.low_power() else 1.0)

    def update_units(self, p, dt):
        regen = "siege_armor" in p.upgrades or "singularity_core" in p.upgrades
        for u in p.units:
            if not u.alive:
                continue
            if regen and u.hp > 0:
                maxhp = effective_max_hp(u)
                if u.hp < maxhp:
                    u.hp = min(maxhp, u.hp + maxhp * 0.02 * dt)
            if u.kind == "harvester":
                self.update_harvester(p, u, dt)
                continue
            u.attack_cd -= dt
            if u.target_entity is not None and not getattr(u.target_entity, "alive", False):
                u.target_entity = None
            data = UNIT_DATA[u.kind]
            proj_kind = data.get("projectile", "bullet")

            def try_fire(target):
                if u.attack_cd <= 0:
                    self.spawn_projectile(u, p, target, effective_damage(u), proj_kind)
                    u.attack_cd = data["cooldown"]

            if u.target_entity is not None:
                tx, ty = get_center(u.target_entity)
                u.gun_angle = math.atan2(ty - u.y, tx - u.x)
                d = dist(u.x, u.y, tx, ty)
                if d <= data["range"]:
                    try_fire(u.target_entity)
                else:
                    u.move_toward(tx, ty, dt)
            elif u.target_pos is not None:
                reached = u.move_toward(u.target_pos[0], u.target_pos[1], dt)
                target = self.nearest_enemy(p, u.x, u.y, data["range"])
                if target is not None:
                    tx, ty = get_center(target)
                    u.gun_angle = math.atan2(ty - u.y, tx - u.x)
                    try_fire(target)
                if reached:
                    u.target_pos = None
            else:
                target = self.nearest_enemy(p, u.x, u.y, data["range"])
                if target is not None:
                    tx, ty = get_center(target)
                    u.gun_angle = math.atan2(ty - u.y, tx - u.x)
                    try_fire(target)

    def update_harvester(self, p, u, dt):
        m = self.map
        cap = harvester_capacity(p)
        # manual override: the player explicitly right-clicked this harvester
        # somewhere, so pause auto-mining and go there instead
        if u.target_entity is not None:
            u.target_entity = None  # harvesters can't fight; drop attack-move orders
        if u.target_pos is not None:
            reached = u.move_toward(u.target_pos[0], u.target_pos[1], dt)
            if reached:
                u.target_pos = None
                u.state = "idle"  # resume auto-harvesting from the new spot
            return
        if u.state == "idle":
            target_tile = None
            if u.manual_harvest_tile is not None:
                col, row = u.manual_harvest_tile
                if (m.in_bounds(col, row) and m.tiles[row][col] in RESOURCE_TILE_TYPES
                        and m.resource_amount[row][col] > 0):
                    tier = m.trainium_tier[row][col] if m.tiles[row][col] == TILE_TRAINIUM else 0
                    target_tile = (col, row, m.tiles[row][col], tier)
                else:
                    u.manual_harvest_tile = None  # depleted/invalid - drop the manual pin
            if target_tile is None and u.manual_harvest_tile is None:
                target_tile = self.find_resource(u.x, u.y)
            if target_tile:
                col, row, tile_type, tier = target_tile
                u.harvest_tile = (col, row)
                u.cargo_kind = tile_type
                u.cargo_tier = tier
                u.state = "seeking"
            else:
                return
        if u.state == "seeking":
            tcol, trow = u.harvest_tile
            tx, ty = tcol * TILE + TILE / 2, trow * TILE + TILE / 2
            if not m.in_bounds(tcol, trow) or m.tiles[trow][tcol] not in RESOURCE_TILE_TYPES or m.resource_amount[trow][tcol] <= 0:
                u.state, u.harvest_tile = "idle", None
                return
            if u.move_toward(tx, ty, dt):
                u.state = "harvesting"
        elif u.state == "harvesting":
            tcol, trow = u.harvest_tile
            if not m.in_bounds(tcol, trow) or m.tiles[trow][tcol] not in RESOURCE_TILE_TYPES or m.resource_amount[trow][tcol] <= 0:
                u.state = "idle" if u.cargo <= 0 else "returning"
                return
            take = min(HARVEST_RATE * dt, m.resource_amount[trow][tcol], cap - u.cargo)
            m.resource_amount[trow][tcol] -= take
            u.cargo += take
            if m.resource_amount[trow][tcol] <= 0:
                m.tiles[trow][tcol] = TILE_GROUND
                m.depleted_at[trow][tcol] = self.elapsed
                self.dirty_tiles.append((tcol, trow, TILE_GROUND, 0))
            if u.cargo >= cap:
                u.state = "returning"
        elif u.state == "returning":
            refs = p.buildings_of("refinery")
            if not refs:
                return
            ref = min(refs, key=lambda b: dist(u.x, u.y, *b.center))
            rx, ry = ref.center
            if u.move_toward(rx, ry, dt):
                self.deposit_cargo(p, u)
                u.cargo = 0
                u.cargo_kind = None
                u.state = "idle"

    def deposit_cargo(self, p, u):
        if u.cargo_kind in (TILE_TRAINIUM, TILE_RADIOACTIVE):
            p.credits += u.cargo * TRAINIUM_TIER_MULT[u.cargo_tier]
        elif u.cargo_kind == TILE_TREE:
            p.wood += u.cargo
        elif u.cargo_kind == TILE_ORE:
            p.metal += u.cargo

    def find_resource(self, x, y):
        # Trainium (credits) is the priority resource: if any is within range,
        # a harvester will always prefer it over wood/ore, even if a tree or
        # ore deposit happens to be a little closer.
        col0 = int(x // TILE)
        row0 = int(y // TILE)
        search = 24
        m = self.map
        best_trainium, best_trainium_d = None, None
        best_any, best_any_d = None, None
        for row in range(max(0, row0 - search), min(m.rows, row0 + search)):
            for col in range(max(0, col0 - search), min(m.cols, col0 + search)):
                t = m.tiles[row][col]
                if t in RESOURCE_TILE_TYPES and m.resource_amount[row][col] > 0:
                    d = abs(col - col0) + abs(row - row0)
                    tier = m.trainium_tier[row][col] if t == TILE_TRAINIUM else 0
                    if t == TILE_TRAINIUM and (best_trainium_d is None or d < best_trainium_d):
                        best_trainium, best_trainium_d = (col, row, t, tier), d
                    if best_any_d is None or d < best_any_d:
                        best_any, best_any_d = (col, row, t, tier), d
        return best_trainium if best_trainium is not None else best_any

    def update_resource_regeneration(self):
        for row in range(self.map.rows):
            for col in range(self.map.cols):
                if self.map.tiles[row][col] == TILE_GROUND and self.map.depleted_at[row][col] > 0:
                    if self.elapsed - self.map.depleted_at[row][col] >= TRAINIUM_REGEN_SECONDS:
                        self.map.tiles[row][col] = TILE_TRAINIUM
                        self.map.resource_amount[row][col] = TRAINIUM_PER_TILE
                        self.map.trainium_tier[row][col] = random.randrange(4)
                        self.map.depleted_at[row][col] = 0
                        self.dirty_tiles.append((col, row, TILE_TRAINIUM, self.map.trainium_tier[row][col]))

    # ---- AI ---------------------------------------------------------------
    def update_ai(self, dt):
        ai = self.ai
        ai.ai_decision_timer -= dt
        if ai.ai_decision_timer > 0:
            return
        ai.ai_decision_timer = 1.2

        if ai.low_power() and ai.can_start("power"):
            ai.start_production("power")
        elif len(ai.buildings_of("refinery")) < 2 and ai.can_start("refinery"):
            ai.start_production("refinery")
        elif not ai.has_building("barracks") and ai.can_start("barracks"):
            ai.start_production("barracks")
        elif not ai.has_building("factory") and ai.can_start("factory"):
            ai.start_production("factory")
        elif not ai.has_building("research") and ai.can_start("research"):
            ai.start_production("research")
        else:
            defense_count = sum(len(ai.buildings_of(k)) for k in DEFENSE_KINDS)
            if defense_count < 4:
                candidates = [k for k in DEFENSE_KINDS if ai.can_start(k)]
                if candidates:
                    ai.start_production(random.choice(candidates))
            elif len(ai.buildings_of("refinery")) < 3 and ai.can_start("refinery") and random.random() < 0.15:
                ai.start_production("refinery")

        if ai.has_building("research") and ai.queues["research"] is None:
            candidates = [k for k in UPGRADE_DATA if ai.can_start(k)]
            if candidates and random.random() < 0.5:
                ai.start_production(random.choice(candidates))

        harvesters = [u for u in ai.units if u.kind == "harvester" and u.alive]
        if len(harvesters) < 3 and ai.can_start("harvester"):
            ai.start_production("harvester")
        elif ai.has_building("factory") and ai.queues["vehicle"] is None and ai.can_start("tank"):
            ai.start_production("tank")
        if ai.has_building("barracks") and ai.queues["infantry"] is None:
            kind = random.choice(["infantry", "infantry", "rocket"])
            if ai.can_start(kind):
                ai.start_production(kind)

        combat_units = [u for u in ai.units if u.alive and u.kind in ("infantry", "rocket", "tank")]
        idle_army = [u for u in combat_units if u.target_entity is None and u.target_pos is None]
        if len(combat_units) >= 6 and len(idle_army) >= max(4, len(combat_units) // 2):
            targets = [b for b in self.player.buildings if b.alive]
            if targets:
                target = random.choice(targets)
                for u in idle_army:
                    u.target_entity = target
                    u.target_pos = None

    # ---- input --------------------------------------------------------
    def handle_left_down(self, pos):
        x, y = pos
        if x >= VIEWPORT_W:
            self.handle_sidebar_click(pos)
            return
        if y < TOPBAR_H:
            return
        if not self.camera.in_viewport(x, y):
            return

        if self.player.pending_placement:
            wx, wy = self.camera.to_world(x, y)
            col, row = int(wx // TILE), int(wy // TILE)
            kind = self.player.pending_placement
            if kind in WALL_DRAG_KINDS:
                self.wall_drag_tile = (col, row)
                return
            ok = self.can_place(self.player, kind, col, row)
            if self.net_role == "client":
                if ok:
                    self.net.send({"type": "place", "kind": kind, "col": col, "row": row})
                self.player.pending_placement = None
                self.player.pending_cost = None
            elif ok:
                self.place_building(self.player, kind, col, row)
            return

        self.drag_start = pos
        self.drag_rect = pygame.Rect(x, y, 0, 0)

    def _wall_line_tiles(self, c0, r0, c1, r1):
        """A straight (AoE-style) run of tiles from the drag anchor to the
        current tile, snapped to whichever axis moved further."""
        dx, dy = c1 - c0, r1 - r0
        if abs(dx) >= abs(dy):
            step = 1 if dx >= 0 else -1
            return [(c, r0) for c in range(c0, c1 + step, step)]
        step = 1 if dy >= 0 else -1
        return [(c0, r) for r in range(r0, r1 + step, step)]

    def _place_wall_line(self, kind, tiles):
        cost = BUILD_DATA[kind]["cost"]
        p = self.player
        if self.net_role == "client":
            for (col, row) in tiles:
                if self.can_place(p, kind, col, row):
                    self.net.send({"type": "place", "kind": kind, "col": col, "row": row})
            return
        for (col, row) in tiles:
            if not self.can_place(p, kind, col, row):
                continue
            if not p.can_afford(cost):
                break
            p.credits -= cost.get("credits", 0)
            p.wood -= cost.get("wood", 0)
            p.metal -= cost.get("metal", 0)
            self.place_building(p, kind, col, row)

    def handle_left_up(self, pos):
        if self.wall_drag_tile is not None:
            kind = self.player.pending_placement
            wx, wy = self.camera.to_world(*pos)
            col1, row1 = int(wx // TILE), int(wy // TILE)
            col0, row0 = self.wall_drag_tile
            tiles = self._wall_line_tiles(col0, row0, col1, row1)
            if kind:
                self._place_wall_line(kind, tiles)
            self.wall_drag_tile = None
            self.player.pending_placement = None
            self.player.pending_cost = None
            return
        if self.drag_start is None:
            return
        x0, y0 = self.drag_start
        x1, y1 = pos
        rect = pygame.Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        for u in self.selected_units:
            u.selected = False
        self.selected_units = []
        self.selected_entity = None
        wrx0, wry0 = self.camera.to_world(rect.x, rect.y)
        world_rect = pygame.Rect(wrx0, wry0, rect.w, rect.h)
        if rect.w < 4 and rect.h < 4:
            wx, wy = self.camera.to_world(x0, y0)
            best, best_d = None, None
            for u in self.player.units:
                d = dist(u.x, u.y, wx, wy)
                if d <= u.radius + 4 and (best_d is None or d < best_d):
                    best, best_d = u, d
            if best:
                best.selected = True
                self.selected_units = [best]
            else:
                for b in self.player.buildings:
                    if b.alive and b.visual_screen_rect(self.camera).collidepoint(x0, y0):
                        self.selected_entity = b
                        break
        else:
            for u in self.player.units:
                if world_rect.collidepoint(u.x, u.y):
                    u.selected = True
                    self.selected_units.append(u)
        self.drag_start = None
        self.drag_rect = None

    def _apply_move_order(self, units, wx, wy):
        """Shared by local right-click and the networked 'move' command.
        If the destination is a resource tile, any harvesters in the group
        are pinned to mine that specific tile instead of just walking
        there and resuming their own (Trainium-priority) auto-search."""
        col, row = int(wx // TILE), int(wy // TILE)
        is_resource = self.map.in_bounds(col, row) and self.map.tiles[row][col] in RESOURCE_TILE_TYPES
        for u in units:
            u.target_entity = None
            if is_resource and u.kind == "harvester":
                u.manual_harvest_tile = (col, row)
                u.target_pos = None
                u.state = "idle"
            else:
                u.manual_harvest_tile = None
                u.target_pos = (wx, wy)

    def _marker_kind(self, target, wx, wy):
        if target is not None:
            return "attack"
        col, row = int(wx // TILE), int(wy // TILE)
        is_resource = self.map.in_bounds(col, row) and self.map.tiles[row][col] in RESOURCE_TILE_TYPES
        has_harvester = any(u.kind == "harvester" for u in self.selected_units)
        return "harvest" if (is_resource and has_harvester) else "move"

    def handle_right_click(self, pos):
        x, y = pos
        if self.player.pending_placement:
            self.wall_drag_tile = None
            cost = self.player.pending_cost or {}
            if self.net_role == "client":
                self.net.send({"type": "cancel_placement", "cost": cost})
            else:
                self.player.credits += cost.get("credits", 0)
                self.player.wood += cost.get("wood", 0)
                self.player.metal += cost.get("metal", 0)
            self.player.pending_placement = None
            self.player.pending_cost = None
            return
        if x >= VIEWPORT_W or y < TOPBAR_H or not self.selected_units:
            return
        if not self.camera.in_viewport(x, y):
            return
        wx, wy = self.camera.to_world(x, y)
        target = None
        for u in self.ai.units:
            if u.alive and dist(u.x, u.y, wx, wy) <= u.radius + 4:
                target = u
                break
        if target is None:
            for b in self.ai.buildings:
                if b.alive and b.visual_screen_rect(self.camera).collidepoint(x, y):
                    target = b
                    break
        self.move_marker = {"x": wx, "y": wy, "age": 0.0, "kind": self._marker_kind(target, wx, wy)}
        if self.net_role == "client":
            ids = [u.id for u in self.selected_units]
            if target is not None:
                self.net.send({"type": "attack", "unit_ids": ids, "target_id": target.id})
            else:
                self.net.send({"type": "move", "unit_ids": ids, "x": wx, "y": wy})
            return
        if target is not None:
            for u in self.selected_units:
                u.target_entity = target
                u.target_pos = None
                u.manual_harvest_tile = None
        else:
            self._apply_move_order(self.selected_units, wx, wy)

    def handle_sidebar_click(self, pos):
        if self.open_tree_button and self.open_tree_button.collidepoint(pos):
            self.show_tech_tree = True
            return
        if self.minimap_rect and self.minimap_rect.collidepoint(pos):
            fx = (pos[0] - self.minimap_rect.x) / self.minimap_rect.w
            fy = (pos[1] - self.minimap_rect.y) / self.minimap_rect.h
            wx = fx * self.map.cols * TILE
            wy = fy * self.map.rows * TILE
            self.camera.center_on(wx, wy)
            return
        for rect, tab in self.tab_buttons:
            if rect.collidepoint(pos):
                self.player.ui_tab = tab
                return
        for rect, kind in self.sidebar_buttons:
            if rect.collidepoint(pos):
                if kind in WALL_DRAG_KINDS:
                    placing_other = self.player.pending_placement is not None and self.player.pending_placement != kind
                    if self.player.can_afford(BUILD_DATA[kind]["cost"]) and not placing_other:
                        self.player.pending_placement = kind
                        self.player.pending_cost = None
                elif self.net_role == "client":
                    if self.player.can_start(kind):
                        self.net.send({"type": "produce", "kind": kind})
                else:
                    self.player.start_production(kind)
                return

    def handle_mouse_motion(self, pos):
        if self.drag_start is not None:
            x0, y0 = self.drag_start
            x1, y1 = pos
            self.drag_rect = pygame.Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))

    # ---- rendering -----------------------------------------------------
    def render(self):
        screen.fill(COL_BG)
        clip = pygame.Rect(VIEWPORT_X0, VIEWPORT_Y0, VIEWPORT_W, VIEWPORT_H)
        screen.set_clip(clip)

        self.map.draw_visible(screen, self.camera)

        # ------------------------------------------------------------------
        # Isometric depth sort
        # Depth key = world_x + world_y so objects further from the camera
        # origin (top-left of the map) are painted last (on top).
        # Walls are flat ground objects — always drawn before everything else.
        # Objects outside the viewport are culled before the sort.
        # ------------------------------------------------------------------
        cx, cy, cw, ch = (self.camera.x, self.camera.y, VIEWPORT_W, VIEWPORT_H)
        _CM = 320
        wall_draw   = []
        depth_items = []   # (depth_key, entity, is_building)

        for p in self.players:
            for b in p.buildings:
                r = b.rect
                if r.right < cx - _CM or r.left > cx + cw + _CM or \
                   r.bottom < cy - _CM or r.top > cy + ch + _CM:
                    continue
                if b.kind in WALL_DRAG_KINDS:
                    wall_draw.append(b)
                else:
                    # Ground contact = tile footprint bottom-centre (world space).
                    # Subtracting half the world-X gives the isometric left-in-front
                    # ordering: buildings further right draw first (behind), buildings
                    # further left draw last (in front).  Units use the same formula
                    # with u.y / u.x so they layer correctly against buildings at
                    # every point — in front when below, behind when above.
                    depth_items.append((float(r.bottom) - r.centerx * 0.5, b, True))
            for u in p.units:
                if u.x < cx - _CM or u.x > cx + cw + _CM or \
                   u.y < cy - _CM or u.y > cy + ch + _CM:
                    continue
                depth_items.append((u.y - u.x * 0.5, u, False))

        for b in wall_draw:
            b.draw(screen, self.camera, selected=(b is self.selected_entity))

        depth_items.sort(key=lambda t: t[0])
        for _, entity, is_building in depth_items:
            if is_building:
                entity.draw(screen, self.camera, selected=(entity is self.selected_entity))
            else:
                entity.draw(screen, self.camera)
        for pr in self.projectiles:
            pr.draw(screen, self.camera)
        for fx in self.explosions:
            sx, sy = self.camera.to_screen(fx["x"], fx["y"])
            pct = fx["age"] / fx["max_age"]
            r = max(4, int(fx["radius"] * (0.35 + 0.65 * pct)))
            if fx["color"] == (180, 255, 80) and AI_NUKE_EXPLOSION_SPRITE is not None:
                sprite = pygame.transform.smoothscale(AI_NUKE_EXPLOSION_SPRITE, (r * 2 + 8, r * 2 + 8))
                sprite.set_alpha(int(255 * (1 - pct)))
                screen.blit(sprite, (int(sx - r - 4), int(sy - r - 4)))
            else:
                layer = pygame.Surface((r * 2 + 8, r * 2 + 8), pygame.SRCALPHA)
                alpha = int(210 * (1 - pct))
                pygame.draw.circle(layer, (*fx["color"], alpha), (r + 4, r + 4), r)
                pygame.draw.circle(layer, (255, 235, 160, alpha), (r + 4, r + 4), max(2, r // 2), 3)
                screen.blit(layer, (int(sx - r - 4), int(sy - r - 4)))
        self.render_move_marker()

        if self.drag_rect and self.drag_rect.w > 2 and self.drag_rect.h > 2:
            s = pygame.Surface((self.drag_rect.w, self.drag_rect.h), pygame.SRCALPHA)
            s.fill((255, 255, 255, 40))
            screen.blit(s, self.drag_rect.topleft)
            pygame.draw.rect(screen, COL_SELECT, self.drag_rect, 1)

        if self.player.pending_placement:
            mx, my = pygame.mouse.get_pos()
            kind = self.player.pending_placement
            w, h = BUILD_DATA[kind]["size"]
            wx, wy = self.camera.to_world(mx, my)
            col, row = int(wx // TILE), int(wy // TILE)
            if kind in WALL_DRAG_KINDS and self.wall_drag_tile is not None:
                tiles = self._wall_line_tiles(self.wall_drag_tile[0], self.wall_drag_tile[1], col, row)
                for (tc, tr) in tiles:
                    ok = self.can_place(self.player, kind, tc, tr)
                    sx, sy = self.camera.to_screen(tc * TILE, tr * TILE)
                    rect = pygame.Rect(sx, sy, w * TILE, h * TILE)
                    ghost = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
                    ghost.fill((60, 220, 90, 110) if ok else (220, 60, 60, 110))
                    screen.blit(ghost, rect.topleft)
                    pygame.draw.rect(screen, (255, 255, 255), rect, 1)
            else:
                ok = self.can_place(self.player, kind, col, row)
                sx, sy = self.camera.to_screen(col * TILE, row * TILE)
                rect = pygame.Rect(sx, sy, w * TILE, h * TILE)
                ghost = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
                ghost.fill((60, 220, 90, 100) if ok else (220, 60, 60, 100))
                screen.blit(ghost, rect.topleft)
                pygame.draw.rect(screen, (255, 255, 255), rect, 2)

        screen.set_clip(None)
        self.render_topbar()
        self.render_sidebar()
        if self.show_tech_tree:
            self.render_tech_tree()
        if self.game_over:
            self.render_gameover()

    def render_move_marker(self):
        mk = self.move_marker
        if mk is None:
            return
        t = clamp(mk["age"] / 0.7, 0, 1)
        sx, sy = self.camera.to_screen(mk["x"], mk["y"])
        if not (VIEWPORT_X0 - 40 <= sx <= VIEWPORT_X0 + VIEWPORT_W + 40 and
                VIEWPORT_Y0 - 40 <= sy <= VIEWPORT_Y0 + VIEWPORT_H + 40):
            return
        kind = mk.get("kind", "move")
        color = (235, 80, 65) if kind == "attack" else (95, 225, 120)
        ease = 1 - (1 - t) * (1 - t)  # ease-out: fast start, gentle settle
        alpha = int(255 * (1 - t) ** 1.4)
        if alpha <= 2:
            return

        size = 76
        s = pygame.Surface((size, size), pygame.SRCALPHA)
        c = (size // 2, size // 2)
        rgba = (*color, alpha)

        # central ring, contracting in from a wide "impact" toward its resting size
        ring_r = 24 - 13 * ease
        pygame.draw.circle(s, rgba, c, max(2, int(ring_r)), 2)

        # four corner brackets closing in like a targeting reticle
        bracket_r = 34 - 18 * ease
        leg = 7
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            bx, by = c[0] + dx * bracket_r, c[1] + dy * bracket_r
            pygame.draw.line(s, rgba, (bx, by), (bx - dx * leg, by), 2)
            pygame.draw.line(s, rgba, (bx, by), (bx, by - dy * leg), 2)

        # center glyph, distinguishing harvest from a plain move even though
        # both read as "green"
        if kind == "attack":
            pygame.draw.line(s, rgba, (c[0] - 5, c[1] - 5), (c[0] + 5, c[1] + 5), 2)
            pygame.draw.line(s, rgba, (c[0] - 5, c[1] + 5), (c[0] + 5, c[1] - 5), 2)
        elif kind == "harvest":
            pts = [(c[0], c[1] - 6), (c[0] + 6, c[1]), (c[0], c[1] + 6), (c[0] - 6, c[1])]
            pygame.draw.polygon(s, rgba, pts, 2)
        else:
            pygame.draw.circle(s, rgba, c, 3)

        screen.blit(s, (sx - c[0], sy - c[1]))

    def render_topbar(self):
        pygame.draw.rect(screen, COL_TOPBAR, (0, 0, SCREEN_W, TOPBAR_H))
        p = self.player
        screen.blit(FONT.render(f"${int(p.credits)}", True, COL_GOOD), (10, 8))
        screen.blit(FONT.render(f"Wood: {int(p.wood)}", True, COL_WOOD), (110, 8))
        screen.blit(FONT.render(f"Metal: {int(p.metal)}", True, COL_METAL), (230, 8))
        used, prod = p.power_used(), p.power_produced()
        pc = COL_BAD if used > prod else COL_LIME
        screen.blit(FONT.render(f"Pwr {used}/{prod}", True, pc), (350, 8))
        screen.blit(FONT.render(f"Units {len(p.units)}  Bldgs {len(p.buildings)}", True, COL_TEXT_DIM), (470, 8))
        screen.blit(FONT.render(f"NOD units {len(self.ai.units)}  bldgs {len(self.ai.buildings)}", True, (150, 90, 90)), (700, 8))
        screen.blit(FONT_SMALL.render("F11: fullscreen   ESC: pause", True, COL_TEXT_DIM), (SCREEN_W - 210, 10))

    def render_sidebar(self):
        x0 = VIEWPORT_W
        pygame.draw.rect(screen, COL_SIDEBAR, (x0, TOPBAR_H, SIDEBAR_W, SCREEN_H - TOPBAR_H))
        y = TOPBAR_H + 8
        self.sidebar_buttons = []
        self.tab_buttons = []
        self.open_tree_button = None
        mx, my = pygame.mouse.get_pos()
        p = self.player

        # tab bar (fixed, not part of the scrollable content below)
        tabs = [("base", "Base"), ("defense", "Defense"), ("research", "Research")]
        tab_w = (SIDEBAR_W - 20) / 3
        for i, (key, label) in enumerate(tabs):
            rect = pygame.Rect(x0 + 10 + i * tab_w, y, tab_w - 4, 26)
            active = p.ui_tab == key
            color = COL_TAB_ACTIVE if active else (COL_BTN_HOVER if rect.collidepoint(mx, my) else COL_TAB)
            pygame.draw.rect(screen, color, rect, border_radius=4)
            t = FONT_SMALL.render(label, True, COL_TEXT if active else COL_TEXT_DIM)
            screen.blit(t, t.get_rect(center=rect.center))
            self.tab_buttons.append((rect, key))
        content_top = y + 34

        # minimap geometry (fixed at the bottom - the scrollable area above
        # is clipped to leave room for it)
        mm_w = SIDEBAR_W - 24
        mm_h = int(mm_w * self.map.rows / self.map.cols)
        mm_x = x0 + 12
        mm_y = SCREEN_H - mm_h - 14
        content_bottom = mm_y - 12
        content_h = max(40, content_bottom - content_top)

        # render all scrollable content onto an off-screen surface first,
        # in LOCAL coordinates, so we can clip+scroll it as a unit
        CONTENT_CANVAS_H = 1400
        content_surf = pygame.Surface((SIDEBAR_W, CONTENT_CANVAS_H), pygame.SRCALPHA)
        cy = 8
        local_buttons = []

        selected = self.selected_entity or (self.selected_units[0] if self.selected_units else None)
        pygame.draw.rect(content_surf, (35, 48, 40) if selected else (32, 32, 38),
                         (10, cy, SIDEBAR_W - 20, 62), border_radius=5)
        pygame.draw.rect(content_surf, COL_GOOD if selected else (70, 70, 80),
                         (10, cy, SIDEBAR_W - 20, 62), 2, border_radius=5)
        if selected:
            if isinstance(selected, Building):
                label, hp, maxhp = BUILD_DATA[selected.kind]["name"], selected.hp, selected.max_hp
                detail = "Building selected"
            else:
                label, hp, maxhp = UNIT_DATA[selected.kind]["name"], selected.hp, effective_max_hp(selected)
                detail = f"Unit selected  |  {RANK_NAMES[selected.rank]}"
            content_surf.blit(FONT_MED.render(label, True, COL_TEXT), (18, cy + 5))
            content_surf.blit(FONT_TINY.render(detail, True, COL_TEXT_DIM), (18, cy + 29))
            draw_health_bar(content_surf, 18, cy + 46, SIDEBAR_W - 36, 7, hp, maxhp)
        else:
            content_surf.blit(FONT.render("No selection", True, COL_TEXT_DIM), (18, cy + 20))
        cy += 72

        def button(kind, category, extra_note=None):
            nonlocal cy
            data = get_data(kind)
            rect_h = 46
            rect = pygame.Rect(10, cy, SIDEBAR_W - 20, rect_h)
            is_wall = kind in WALL_DRAG_KINDS
            afford = p.can_afford(data["cost"])
            prereq = True
            if kind in UNIT_DATA:
                prereq = p.has_building(UNIT_DATA[kind]["built_from"])
            already = kind in UPGRADE_DATA and kind in p.upgrades
            full = False
            if is_wall:
                placing_other = p.pending_placement is not None and p.pending_placement != kind
                enabled = afford and prereq and not placing_other
            else:
                full = len(p.queues[category]) >= MAX_QUEUE_LEN
                enabled = afford and prereq and not full and not already
            screen_rect = pygame.Rect(x0 + rect.x, content_top - self.sidebar_scroll + rect.y, rect.w, rect.h)
            hover = screen_rect.collidepoint(mx, my)
            color = COL_BTN_DISABLED if not enabled else (COL_BTN_HOVER if hover else COL_BTN)
            pygame.draw.rect(content_surf, color, rect, border_radius=4)
            pygame.draw.rect(content_surf, (70, 70, 80), rect, 1, border_radius=4)
            name = data["name"] + (" \u2713" if already else "")
            content_surf.blit(FONT.render(name, True, COL_TEXT if enabled else COL_TEXT_DIM), (rect.x + 8, rect.y + 4))
            content_surf.blit(FONT_SMALL.render(format_cost(data["cost"]), True, COL_TEXT_DIM), (rect.x + 8, rect.y + 21))
            note_y = rect.y + 34
            if is_wall:
                if p.pending_placement == kind:
                    content_surf.blit(FONT_TINY.render("click + drag on the map", True, COL_GOOD), (rect.x + 8, note_y))
                else:
                    content_surf.blit(FONT_TINY.render("click, then drag to place a line", True, COL_TEXT_DIM), (rect.x + 8, note_y))
            else:
                items = p.queues[category]
                count = sum(1 for it in items if it["kind"] == kind)
                if items and items[0]["kind"] == kind:
                    pct = clamp(items[0]["timer"] / items[0]["total"], 0, 1)
                    bar_w = rect.w - 16 - (36 if count > 1 else 0)
                    bar = pygame.Rect(rect.x + 8, note_y, bar_w, 8)
                    pygame.draw.rect(content_surf, COL_BAR_BG, bar)
                    pygame.draw.rect(content_surf, COL_BAR_FG, (bar.x, bar.y, int(bar.w * pct), bar.h))
                    if count > 1:
                        content_surf.blit(FONT_TINY.render(f"+{count - 1}", True, COL_TEXT_DIM), (bar.right + 6, note_y - 2))
                elif count > 0:
                    content_surf.blit(FONT_TINY.render(f"banked x{count}", True, COL_TEXT_DIM), (rect.x + 8, note_y))
                elif full:
                    content_surf.blit(FONT_TINY.render("(queue full)", True, COL_TEXT_DIM), (rect.x + 8, note_y))
                elif kind in UNIT_DATA and not prereq:
                    content_surf.blit(FONT_TINY.render(f"needs {UNIT_DATA[kind]['built_from']}", True, (150, 90, 90)), (rect.x + 8, note_y))
                elif extra_note:
                    content_surf.blit(FONT_TINY.render(extra_note, True, COL_TEXT_DIM), (rect.x + 8, note_y))
            if not already:
                local_buttons.append((rect, kind))
            cy += rect_h + 6

        content_surf.blit(FONT.render("STRUCTURES", True, (170, 170, 180)), (12, cy))
        cy += 20
        if p.ui_tab == "research":
            button("research", "building")
            if p.has_building("research"):
                cy += 6
                tree_rect = pygame.Rect(10, cy, SIDEBAR_W - 20, 48)
                tree_screen_rect = pygame.Rect(x0 + tree_rect.x, content_top - self.sidebar_scroll + tree_rect.y,
                                                tree_rect.w, tree_rect.h)
                hover = tree_screen_rect.collidepoint(mx, my)
                pygame.draw.rect(content_surf, COL_BTN_HOVER if hover else COL_BTN, tree_rect, border_radius=6)
                pygame.draw.rect(content_surf, TECH_CAPSTONE_COLOR, tree_rect, 2, border_radius=6)
                label = FONT.render("Open Research Tree", True, COL_TEXT)
                content_surf.blit(label, label.get_rect(center=(tree_rect.centerx, tree_rect.centery - 8)))
                n_done = len(p.upgrades)
                sub = FONT_TINY.render(f"{n_done}/{len(UPGRADE_DATA)} researched", True, COL_TEXT_DIM)
                content_surf.blit(sub, sub.get_rect(center=(tree_rect.centerx, tree_rect.centery + 12)))
                self._pending_tree_rect = tree_rect  # transformed to screen coords after we know final scroll clamp
                cy += 56
                active = p.queues["research"]
                if active:
                    kind = active[0]["kind"]
                    pct = clamp(active[0]["timer"] / active[0]["total"], 0, 1)
                    content_surf.blit(FONT_TINY.render(f"Researching: {UPGRADE_DATA[kind]['name']}", True, COL_GOOD), (12, cy))
                    cy += 16
                    bar = pygame.Rect(12, cy, SIDEBAR_W - 44, 8)
                    pygame.draw.rect(content_surf, COL_BAR_BG, bar)
                    pygame.draw.rect(content_surf, COL_BAR_FG, (bar.x, bar.y, int(bar.w * pct), bar.h))
                    cy += 18
                    if len(active) > 1:
                        content_surf.blit(FONT_TINY.render(f"+{len(active) - 1} banked", True, COL_TEXT_DIM), (12, cy))
                        cy += 16
            else:
                content_surf.blit(FONT_SMALL.render("(build Research Ctr for upgrades)", True, COL_TEXT_DIM), (12, cy))
                cy += 22
        else:
            self._pending_tree_rect = None
            for kind in STRUCTURE_TABS[p.ui_tab]:
                button(kind, "building")

        cy += 4
        content_surf.blit(FONT.render("INFANTRY", True, (170, 170, 180)), (12, cy))
        cy += 20
        if p.has_building("barracks"):
            for kind in INFANTRY_ORDER:
                button(kind, "infantry")
        else:
            content_surf.blit(FONT_SMALL.render("(build a Barracks)", True, COL_TEXT_DIM), (12, cy))
            cy += 22

        cy += 4
        content_surf.blit(FONT.render("VEHICLES", True, (170, 170, 180)), (12, cy))
        cy += 20
        if p.has_building("factory"):
            for kind in VEHICLE_ORDER:
                button(kind, "vehicle")
        else:
            content_surf.blit(FONT_SMALL.render("(build a War Factory)", True, COL_TEXT_DIM), (12, cy))
            cy += 22

        if self.selected_units:
            cy += 4
            content_surf.blit(FONT.render(f"SELECTED: {len(self.selected_units)}", True, (170, 170, 180)), (12, cy))
            cy += 18
            counts = {}
            ranks = {}
            for u in self.selected_units:
                counts[u.kind] = counts.get(u.kind, 0) + 1
                ranks[u.kind] = max(ranks.get(u.kind, 0), u.rank)
            for kind, n in counts.items():
                rank_txt = f" [{RANK_NAMES[ranks[kind]]}]" if ranks[kind] > 0 else ""
                content_surf.blit(FONT_TINY.render(f"  {UNIT_DATA[kind]['name']} x{n}{rank_txt}", True, COL_TEXT_DIM), (12, cy))
                cy += 15

        used_height = cy + 8
        self.sidebar_max_scroll = max(0, used_height - content_h)
        self.sidebar_scroll = clamp(self.sidebar_scroll, 0, self.sidebar_max_scroll)

        visible = pygame.Rect(0, self.sidebar_scroll, SIDEBAR_W, content_h)
        screen.blit(content_surf, (x0, content_top), area=visible)

        # now that scroll is finalized, convert this frame's local button
        # rects (and the tech-tree button, if any) into real screen rects
        for local_rect, kind in local_buttons:
            screen_rect = pygame.Rect(x0 + local_rect.x, content_top - self.sidebar_scroll + local_rect.y,
                                       local_rect.w, local_rect.h)
            self.sidebar_buttons.append((screen_rect, kind))
        if getattr(self, "_pending_tree_rect", None) is not None:
            r = self._pending_tree_rect
            self.open_tree_button = pygame.Rect(x0 + r.x, content_top - self.sidebar_scroll + r.y, r.w, r.h)

        # scrollbar, only shown if content overflows
        if self.sidebar_max_scroll > 0:
            track = pygame.Rect(x0 + SIDEBAR_W - 8, content_top, 5, content_h)
            pygame.draw.rect(screen, (40, 40, 46), track, border_radius=2)
            thumb_h = max(24, int(content_h * content_h / used_height))
            thumb_y = content_top + int((content_h - thumb_h) * (self.sidebar_scroll / self.sidebar_max_scroll))
            pygame.draw.rect(screen, (110, 110, 120), (track.x, thumb_y, track.w, thumb_h), border_radius=2)

        self.minimap_rect = pygame.Rect(mm_x, mm_y, mm_w, mm_h)
        if self.overview_surface is not None:
            ov = pygame.transform.scale(self.overview_surface, (mm_w, mm_h))
            screen.blit(ov, (mm_x, mm_y))
        else:
            pygame.draw.rect(screen, (20, 30, 20), self.minimap_rect)
        for pl in self.players:
            for b in pl.buildings:
                fx = b.col / self.map.cols
                fy = b.row / self.map.rows
                dot = pygame.Rect(0, 0, 4, 4)
                dot.center = (mm_x + fx * mm_w, mm_y + fy * mm_h)
                pygame.draw.rect(screen, pl.color, dot)
        view_rect = pygame.Rect(
            mm_x + (self.camera.x / (self.map.cols * TILE)) * mm_w,
            mm_y + (self.camera.y / (self.map.rows * TILE)) * mm_h,
            (VIEWPORT_W / (self.map.cols * TILE)) * mm_w,
            (VIEWPORT_H / (self.map.rows * TILE)) * mm_h,
        )
        pygame.draw.rect(screen, COL_SELECT, view_rect, 1)
        pygame.draw.rect(screen, (90, 90, 100), self.minimap_rect, 1)

    def handle_sidebar_scroll(self, mx, my, wheel_y):
        if mx >= VIEWPORT_W:
            self.sidebar_scroll = clamp(self.sidebar_scroll - wheel_y * 40, 0, self.sidebar_max_scroll)

    # ---- research tree ---------------------------------------------------
    def _build_tech_tree_layout(self):
        margin_x = 90
        top_y = 190
        col_w = (SCREEN_W - 2 * margin_x) / 4
        row_h = 140
        node_w, node_h = 210, 100
        tier_x = [margin_x + col_w * i + col_w / 2 for i in range(4)]
        row_y = [top_y + row_h * i for i in range(4)]
        nodes = {}
        for kind, data in UPGRADE_DATA.items():
            tier = data["tier"]
            branch = data.get("branch")
            x = tier_x[tier]
            y = row_y[branch] if branch is not None else sum(row_y) / len(row_y)
            rect = pygame.Rect(0, 0, node_w, node_h)
            rect.center = (int(x), int(y))
            nodes[kind] = rect
        return nodes

    def _tech_node_state(self, p, kind):
        if kind in p.upgrades:
            return "done"
        for i, item in enumerate(p.queues["research"]):
            if item["kind"] == kind:
                return "active" if i == 0 else "banked"
        req = UPGRADE_DATA[kind].get("requires")
        if req:
            req_list = [req] if isinstance(req, str) else req
            if not all(r in p.upgrades for r in req_list):
                return "locked"
        if not p.has_building("research"):
            return "locked"
        if not p.can_afford(UPGRADE_DATA[kind]["cost"]):
            return "unaffordable"
        return "available"

    def handle_tech_tree_click(self, pos):
        if self.tech_tree_close_button and self.tech_tree_close_button.collidepoint(pos):
            self.show_tech_tree = False
            return
        if not self.tech_tree_nodes:
            return
        for kind, rect in self.tech_tree_nodes.items():
            if rect.collidepoint(pos):
                if self._tech_node_state(self.player, kind) == "available":
                    if self.net_role == "client":
                        if self.player.can_start(kind):
                            self.net.send({"type": "produce", "kind": kind})
                    else:
                        self.player.start_production(kind)
                return

    def render_tech_tree(self):
        if self.tech_tree_nodes is None:
            self.tech_tree_nodes = self._build_tech_tree_layout()
        nodes = self.tech_tree_nodes
        p = self.player

        dim = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        dim.fill((8, 8, 14, 235))
        screen.blit(dim, (0, 0))

        title = FONT_BIG.render("RESEARCH TREE", True, (215, 180, 40))
        screen.blit(title, title.get_rect(center=(SCREEN_W // 2, 55)))
        sub = FONT_SMALL.render("click an unlocked node to research it - every branch converges at the Singularity",
                                 True, COL_TEXT_DIM)
        screen.blit(sub, sub.get_rect(center=(SCREEN_W // 2, 90)))

        branch_labels = ["ECONOMY", "DEFENSE", "OFFENSE", "SUPPORT"]
        for i, label in enumerate(branch_labels):
            tier0_kind = next(k for k, d in UPGRADE_DATA.items() if d.get("branch") == i and d["tier"] == 0)
            t = FONT_TINY.render(label, True, TECH_BRANCH_COLORS[i])
            screen.blit(t, (30, nodes[tier0_kind].y + 40))

        # connecting lines (under the nodes)
        for kind, data in UPGRADE_DATA.items():
            req = data.get("requires")
            if not req:
                continue
            req_list = [req] if isinstance(req, str) else req
            branch = data.get("branch")
            color = TECH_BRANCH_COLORS[branch] if branch is not None else TECH_CAPSTONE_COLOR
            child_rect = nodes[kind]
            for r in req_list:
                parent_rect = nodes[r]
                done = r in p.upgrades
                line_col = color if done else (64, 64, 72)
                width = 3 if done else 2
                pygame.draw.line(screen, line_col, parent_rect.midright, child_rect.midleft, width)

        mx, my = pygame.mouse.get_pos()
        for kind, rect in nodes.items():
            data = UPGRADE_DATA[kind]
            branch = data.get("branch")
            color = TECH_BRANCH_COLORS[branch] if branch is not None else TECH_CAPSTONE_COLOR
            state = self._tech_node_state(p, kind)
            hover = rect.collidepoint(mx, my)

            if branch is None and state != "locked":
                pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 300.0)
                glow = pygame.Surface((rect.w + 24, rect.h + 24), pygame.SRCALPHA)
                alpha = int(50 + 60 * pulse)
                pygame.draw.rect(glow, (*TECH_CAPSTONE_COLOR, alpha), glow.get_rect(), border_radius=18)
                screen.blit(glow, (rect.x - 12, rect.y - 12), special_flags=pygame.BLEND_RGBA_ADD)

            if state == "done":
                fill = tuple(int(c * 0.32) for c in color)
                border = color
            elif state == "locked":
                fill = (24, 24, 28)
                border = (52, 52, 58)
            elif state in ("active", "banked"):
                fill = (36, 44, 36)
                border = COL_GOOD
            else:
                fill = COL_BTN_HOVER if hover else COL_BTN
                border = color if state == "available" else (90, 90, 96)

            pygame.draw.rect(screen, fill, rect, border_radius=10)
            pygame.draw.rect(screen, border, rect, 3 if (hover and state in ("available", "unaffordable")) else 2,
                              border_radius=10)

            name_col = COL_TEXT if state != "locked" else COL_TEXT_DIM
            name = FONT_SMALL.render(data["name"], True, name_col)
            screen.blit(name, (rect.x + 10, rect.y + 8))

            if state == "done":
                tick = FONT.render("\u2713", True, color)
                screen.blit(tick, (rect.right - 28, rect.y + 6))
                desc = FONT_TINY.render(data["desc"], True, COL_TEXT_DIM)
                screen.blit(desc, (rect.x + 10, rect.y + 30))
            elif state == "locked":
                lock = FONT_TINY.render("requires prior research", True, (110, 110, 115))
                screen.blit(lock, (rect.x + 10, rect.y + 30))
            elif state in ("active", "banked"):
                queue_items = p.queues["research"]
                idx = next(i for i, it in enumerate(queue_items) if it["kind"] == kind)
                if idx == 0:
                    pct = clamp(queue_items[0]["timer"] / queue_items[0]["total"], 0, 1)
                    bar = pygame.Rect(rect.x + 10, rect.y + 34, rect.w - 20, 8)
                    pygame.draw.rect(screen, COL_BAR_BG, bar)
                    pygame.draw.rect(screen, COL_BAR_FG, (bar.x, bar.y, int(bar.w * pct), bar.h))
                else:
                    txt = FONT_TINY.render(f"banked (#{idx + 1})", True, COL_TEXT_DIM)
                    screen.blit(txt, (rect.x + 10, rect.y + 34))
            else:
                desc = FONT_TINY.render(data["desc"], True, COL_TEXT_DIM)
                screen.blit(desc, (rect.x + 10, rect.y + 30))
                cost_col = COL_TEXT_DIM if state == "available" else COL_BAD
                cost = FONT_TINY.render(format_cost(data["cost"]), True, cost_col)
                screen.blit(cost, (rect.x + 10, rect.y + 46))

        close_rect = pygame.Rect(0, 0, 160, 44)
        close_rect.center = (SCREEN_W // 2, SCREEN_H - 40)
        hover_close = close_rect.collidepoint(mx, my)
        pygame.draw.rect(screen, COL_BTN_HOVER if hover_close else COL_BTN, close_rect, border_radius=8)
        pygame.draw.rect(screen, (120, 120, 130), close_rect, 2, border_radius=8)
        t = FONT.render("Close", True, COL_TEXT)
        screen.blit(t, t.get_rect(center=close_rect.center))
        self.tech_tree_close_button = close_rect

    def render_gameover(self):
        s = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        s.fill((0, 0, 0, 170))
        screen.blit(s, (0, 0))
        my_side = "p1" if self.local_is_p1 else "p2"
        if self.game_over == "disconnected":
            msg, col = "CONNECTION LOST", COL_BAD
        elif self.game_over == f"{my_side}_win":
            msg, col = "VICTORY", COL_GOOD
        else:
            msg, col = "DEFEAT", COL_BAD
        t = FONT_BIG.render(msg, True, col)
        screen.blit(t, t.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2 - 30)))
        btn = pygame.Rect(0, 0, 220, 44)
        btn.center = (SCREEN_W // 2, SCREEN_H // 2 + 30)
        pygame.draw.rect(screen, COL_BTN_HOVER, btn, border_radius=6)
        pygame.draw.rect(screen, (120, 120, 130), btn, 2, border_radius=6)
        t2 = FONT.render("Main Menu", True, COL_TEXT)
        screen.blit(t2, t2.get_rect(center=btn.center))
        self.gameover_button = btn


# ---------------------------------------------------------------------------
# Menu / App layer
# ---------------------------------------------------------------------------
def make_button(rect, label, font=FONT_MED):
    return {"rect": rect, "label": label, "font": font}


def draw_button(surf, btn, hover=False, enabled=True):
    color = COL_BTN_DISABLED if not enabled else (COL_BTN_HOVER if hover else COL_BTN)
    pygame.draw.rect(surf, color, btn["rect"], border_radius=8)
    pygame.draw.rect(surf, (110, 110, 120), btn["rect"], 2, border_radius=8)
    label = btn["font"].render(btn["label"], True, COL_TEXT if enabled else COL_TEXT_DIM)
    surf.blit(label, label.get_rect(center=btn["rect"].center))


class TextInput:
    def __init__(self, rect, placeholder="", max_len=32):
        self.rect = rect
        self.text = ""
        self.placeholder = placeholder
        self.active = False
        self.max_len = max_len

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(event.pos)
        elif event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif len(self.text) < self.max_len and event.unicode and event.unicode.isprintable():
                self.text += event.unicode

    def draw(self, surf):
        color = (46, 66, 46) if self.active else COL_BTN
        pygame.draw.rect(surf, color, self.rect, border_radius=6)
        pygame.draw.rect(surf, (120, 150, 120) if self.active else (90, 90, 100), self.rect, 2, border_radius=6)
        disp = self.text if self.text else self.placeholder
        col = COL_TEXT if self.text else COL_TEXT_DIM
        t = FONT.render(disp, True, col)
        surf.blit(t, (self.rect.x + 10, self.rect.y + (self.rect.h - t.get_height()) // 2))
        if self.active and (pygame.time.get_ticks() // 500) % 2 == 0:
            cx = self.rect.x + 10 + FONT.size(self.text)[0] + 2
            pygame.draw.line(surf, (255, 255, 255), (cx, self.rect.y + 8), (cx, self.rect.bottom - 8), 2)


def _map_size(cols0, rows0, factor):
    """Scale a base (small) map size so the total tile AREA is `factor`
    times bigger, keeping the aspect ratio (so 'medium'/'large' aren't
    just stretched versions of 'small')."""
    scale = math.sqrt(factor)
    return (int(round(cols0 * scale)), int(round(rows0 * scale)))


_GRASS_BASE = (90, 60)
_DESERT_BASE = (84, 70)
_SNOW_BASE = (92, 62)
_RAD_BASE = (88, 66)

MAP_PRESETS = [
    # --- grassland ---
    {"name": "Wasteland Ridge", "seed": 1101, "size": "Small", "biome": "grass",
     "cols": _GRASS_BASE[0], "rows": _GRASS_BASE[1]},
    {"name": "Twin Rivers", "seed": 4242, "size": "Medium", "biome": "grass",
     "cols": _map_size(*_GRASS_BASE, 3)[0], "rows": _map_size(*_GRASS_BASE, 3)[1]},
    {"name": "Emerald Expanse", "seed": 4243, "size": "Large", "biome": "grass",
     "cols": _map_size(*_GRASS_BASE, 5)[0], "rows": _map_size(*_GRASS_BASE, 5)[1]},
    # --- desert ---
    {"name": "Crimson Fields", "seed": 777, "size": "Small", "biome": "desert",
     "cols": _DESERT_BASE[0], "rows": _DESERT_BASE[1]},
    {"name": "Death Valley", "seed": 505, "size": "Medium", "biome": "desert",
     "cols": _map_size(*_DESERT_BASE, 3)[0], "rows": _map_size(*_DESERT_BASE, 3)[1]},
    {"name": "Scorched Dunes", "seed": 506, "size": "Large", "biome": "desert",
     "cols": _map_size(*_DESERT_BASE, 5)[0], "rows": _map_size(*_DESERT_BASE, 5)[1]},
    # --- snow ---
    {"name": "Frozen Wastes", "seed": 909, "size": "Small", "biome": "snow",
     "cols": _SNOW_BASE[0], "rows": _SNOW_BASE[1]},
    {"name": "Glacial Reach", "seed": 910, "size": "Medium", "biome": "snow",
     "cols": _map_size(*_SNOW_BASE, 3)[0], "rows": _map_size(*_SNOW_BASE, 3)[1]},
    {"name": "Arctic Expanse", "seed": 911, "size": "Large", "biome": "snow",
     "cols": _map_size(*_SNOW_BASE, 5)[0], "rows": _map_size(*_SNOW_BASE, 5)[1]},
    {"name": "Irradiated Basin", "seed": 1212, "size": "Small", "biome": "radioactive",
     "cols": _RAD_BASE[0], "rows": _RAD_BASE[1]},
    {"name": "Greenfire Frontier", "seed": 1213, "size": "Extreme", "biome": "radioactive",
     "cols": _map_size(*_RAD_BASE, 10)[0], "rows": _map_size(*_RAD_BASE, 10)[1]},
]


class App:
    def __init__(self):
        self.state = "MENU"
        self.game = None
        self.paused = False
        self.net = None
        self.mp_preset = None
        self.join_error = None
        self.map_cards = []
        self._build_map_cards()
        self.ip_input = TextInput(pygame.Rect(0, 0, 320, 46),
                                   placeholder=f"host IP (default port {net.DEFAULT_PORT})")
        self._build_layout()

    def _build_layout(self):
        """(Re)computes every screen-size-dependent rect. Called once at
        startup and again whenever the window is resized (F11 fullscreen)."""
        self.menu_buttons = {
            "new_game": make_button(pygame.Rect(SCREEN_W // 2 - 130, 330, 260, 54), "New Game (vs AI)"),
            "multiplayer": make_button(pygame.Rect(SCREEN_W // 2 - 130, 400, 260, 54), "Multiplayer"),
            "quit": make_button(pygame.Rect(SCREEN_W // 2 - 130, 470, 260, 54), "Quit"),
        }
        self.mp_menu_buttons = {
            "host": make_button(pygame.Rect(SCREEN_W // 2 - 130, 340, 260, 54), "Host Game"),
            "join": make_button(pygame.Rect(SCREEN_W // 2 - 130, 410, 260, 54), "Join Game"),
        }
        self.pause_buttons = {
            "resume": make_button(pygame.Rect(SCREEN_W // 2 - 130, SCREEN_H // 2 - 40, 260, 50), "Resume"),
            "menu": make_button(pygame.Rect(SCREEN_W // 2 - 130, SCREEN_H // 2 + 25, 260, 50), "Main Menu"),
        }
        self.back_button = make_button(pygame.Rect(30, SCREEN_H - 70, 160, 44), "Back", FONT)
        self.start_button = make_button(pygame.Rect(SCREEN_W // 2 - 110, 560, 220, 50), "Start Game")
        self.connect_button = make_button(pygame.Rect(SCREEN_W // 2 - 110, 380, 220, 50), "Connect")
        self.ip_input.rect = pygame.Rect(SCREEN_W // 2 - 160, 310, 320, 46)
        self._reposition_map_cards()
        if self.game:
            # force the tech tree (and any other cached, size-dependent
            # layout) to rebuild next time it's drawn
            self.game.tech_tree_nodes = None

    def toggle_fullscreen(self):
        set_display_mode(not IS_FULLSCREEN)
        # The playable area changes when F11 changes the window size. Clamp
        # immediately so the map fills the new viewport instead of retaining
        # the old window's camera limits until the next camera movement.
        if self.game:
            self.game.camera.clamp()
        self._build_layout()

    def _build_map_cards(self):
        card_w, card_h = 210, 168
        for preset in MAP_PRESETS:
            gmap = GameMap(preset["cols"], preset["rows"], seed=preset["seed"], biome=preset["biome"])
            thumb = map_overview_surface(gmap, card_w - 16, card_h - 56)
            self.map_cards.append({"preset": preset, "thumb": thumb, "rect": pygame.Rect(0, 0, card_w, card_h)})

    def _reposition_map_cards(self):
        card_w, card_h = 210, 168
        gap_x, gap_y = 20, 16
        cols_per_row = 3
        total_w = card_w * cols_per_row + gap_x * (cols_per_row - 1)
        start_x = (SCREEN_W - total_w) // 2
        start_y = 150
        for i, card in enumerate(self.map_cards):
            row, col = divmod(i, cols_per_row)
            card["rect"] = pygame.Rect(start_x + col * (card_w + gap_x), start_y + row * (card_h + gap_y), card_w, card_h)

    # ---- lifecycle helpers ----------------------------------------------
    def start_new_game(self, preset):
        seed = preset["seed"] if preset["seed"] is not None else random.randint(0, 999999)
        self.game = Game(preset["cols"], preset["rows"], seed=seed, biome=preset["biome"])
        self.state = "PLAYING"
        self.paused = False

    def close_network(self):
        if self.net:
            self.net.close()
        self.net = None

    def return_to_menu(self):
        self.close_network()
        self.game = None
        self.paused = False
        self.join_error = None
        self.state = "MENU"

    # ---- multiplayer: hosting --------------------------------------------
    def start_hosting(self, preset):
        self.mp_preset = preset
        self.net = net.Host(net.DEFAULT_PORT)
        self.state = "MP_HOST_WAIT"

    def host_start_game(self):
        preset = self.mp_preset
        seed = preset["seed"] if preset["seed"] is not None else random.randint(0, 999999)
        self.net.send({"type": "start", "seed": seed, "cols": preset["cols"],
                        "rows": preset["rows"], "biome": preset["biome"]})
        self.game = Game(preset["cols"], preset["rows"], seed=seed, biome=preset["biome"],
                          net_role="host", net=self.net)
        self.state = "PLAYING"
        self.paused = False

    # ---- multiplayer: joining ---------------------------------------------
    def start_joining(self):
        ip, port = net.parse_address(self.ip_input.text)
        if not ip:
            self.join_error = "Enter the host's IP address"
            return
        self.join_error = None
        self.net = net.Client(ip, port)
        self.state = "MP_JOIN_WAIT"

    def check_join_start(self):
        if not self.net:
            return
        for msg in self.net.poll():
            if msg.get("type") == "start":
                self.game = Game(msg["cols"], msg["rows"], seed=msg["seed"], biome=msg["biome"],
                                  net_role="client", net=self.net)
                self.state = "PLAYING"
                self.paused = False
                return

    # ---- event handling ---------------------------------------------------
    def handle_event(self, event):
        if self.state == "MENU":
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.menu_buttons["new_game"]["rect"].collidepoint(event.pos):
                    self.state = "MAP_SELECT"
                elif self.menu_buttons["multiplayer"]["rect"].collidepoint(event.pos):
                    self.state = "MP_MENU"
                elif self.menu_buttons["quit"]["rect"].collidepoint(event.pos):
                    pygame.quit()
                    sys.exit(0)

        elif self.state == "MAP_SELECT":
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.back_button["rect"].collidepoint(event.pos):
                    self.state = "MENU"
                    return
                for card in self.map_cards:
                    if card["rect"].collidepoint(event.pos):
                        self.start_new_game(card["preset"])
                        return

        elif self.state == "MP_MENU":
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.mp_menu_buttons["host"]["rect"].collidepoint(event.pos):
                    self.state = "MP_HOST_MAPSELECT"
                elif self.mp_menu_buttons["join"]["rect"].collidepoint(event.pos):
                    self.ip_input.text = ""
                    self.join_error = None
                    self.state = "MP_JOIN_ENTER"
                elif self.back_button["rect"].collidepoint(event.pos):
                    self.state = "MENU"

        elif self.state == "MP_HOST_MAPSELECT":
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.back_button["rect"].collidepoint(event.pos):
                    self.state = "MP_MENU"
                    return
                for card in self.map_cards:
                    if card["rect"].collidepoint(event.pos):
                        self.start_hosting(card["preset"])
                        return

        elif self.state == "MP_HOST_WAIT":
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.back_button["rect"].collidepoint(event.pos):
                    self.close_network()
                    self.state = "MP_MENU"
                elif self.net and self.net.connected and self.start_button["rect"].collidepoint(event.pos):
                    self.host_start_game()

        elif self.state == "MP_JOIN_ENTER":
            self.ip_input.handle_event(event)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.back_button["rect"].collidepoint(event.pos):
                    self.state = "MP_MENU"
                elif self.connect_button["rect"].collidepoint(event.pos):
                    self.start_joining()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                self.start_joining()

        elif self.state == "MP_JOIN_WAIT":
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.back_button["rect"].collidepoint(event.pos):
                    self.close_network()
                    self.state = "MP_JOIN_ENTER"

        elif self.state == "PLAYING":
            if self.paused:
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.pause_buttons["resume"]["rect"].collidepoint(event.pos):
                        self.paused = False
                    elif self.pause_buttons["menu"]["rect"].collidepoint(event.pos):
                        self.return_to_menu()
                return
            if self.game.show_tech_tree:
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.game.handle_tech_tree_click(event.pos)
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self.game.show_tech_tree = False
                return
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.paused = True
                return
            if self.game.game_over:
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if getattr(self.game, "gameover_button", None) and self.game.gameover_button.collidepoint(event.pos):
                        self.return_to_menu()
                return
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    self.game.handle_left_down(event.pos)
                elif event.button == 3:
                    self.game.handle_right_click(event.pos)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.game.handle_left_up(event.pos)
            elif event.type == pygame.MOUSEMOTION:
                self.game.handle_mouse_motion(event.pos)
            elif event.type == pygame.MOUSEWHEEL:
                self.game.handle_sidebar_scroll(*pygame.mouse.get_pos(), event.y)
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_DELETE:
                self.game.start_demolish()

    def update(self, dt):
        if self.state == "MP_JOIN_WAIT":
            self.check_join_start()
        if self.state == "PLAYING" and not self.paused and self.game:
            self.game.update(dt)

    def render(self):
        if self.state == "MENU":
            self.render_menu()
        elif self.state == "MAP_SELECT":
            self.render_map_select("SELECT MAP", self.start_new_game)
        elif self.state == "MP_MENU":
            self.render_mp_menu()
        elif self.state == "MP_HOST_MAPSELECT":
            self.render_map_select("HOST - SELECT MAP", self.start_hosting)
        elif self.state == "MP_HOST_WAIT":
            self.render_host_wait()
        elif self.state == "MP_JOIN_ENTER":
            self.render_join_enter()
        elif self.state == "MP_JOIN_WAIT":
            self.render_join_wait()
        elif self.state == "PLAYING":
            self.game.render()
            if self.paused:
                self.render_pause()

    def render_menu(self):
        screen.fill((14, 16, 14))
        for i in range(0, SCREEN_H, 4):
            shade = 14 + int(10 * (i / SCREEN_H))
            pygame.draw.line(screen, (shade, shade + 4, shade), (0, i), (SCREEN_W, i))
        title = FONT_BIG.render("TIBERIUM CLONE", True, (215, 180, 40))
        screen.blit(title, title.get_rect(center=(SCREEN_W // 2, 200)))
        sub = FONT.render("an isometric fan recreation - Command & Conquer (1995) inspired", True, COL_TEXT_DIM)
        screen.blit(sub, sub.get_rect(center=(SCREEN_W // 2, 250)))
        hint = FONT_SMALL.render("F11: toggle fullscreen", True, COL_TEXT_DIM)
        screen.blit(hint, hint.get_rect(center=(SCREEN_W // 2, SCREEN_H - 30)))
        mx, my = pygame.mouse.get_pos()
        for btn in self.menu_buttons.values():
            draw_button(screen, btn, hover=btn["rect"].collidepoint(mx, my))

    def render_mp_menu(self):
        screen.fill((14, 16, 14))
        title = FONT_BIG.render("MULTIPLAYER", True, (215, 180, 40))
        screen.blit(title, title.get_rect(center=(SCREEN_W // 2, 220)))
        sub = FONT.render("Play head-to-head against another player over LAN or the internet", True, COL_TEXT_DIM)
        screen.blit(sub, sub.get_rect(center=(SCREEN_W // 2, 270)))
        mx, my = pygame.mouse.get_pos()
        for btn in self.mp_menu_buttons.values():
            draw_button(screen, btn, hover=btn["rect"].collidepoint(mx, my))
        draw_button(screen, self.back_button, hover=self.back_button["rect"].collidepoint(mx, my))

    def render_map_select(self, title_text, on_pick):
        screen.fill((14, 16, 14))
        title = FONT_MED.render(title_text, True, COL_TEXT)
        screen.blit(title, title.get_rect(center=(SCREEN_W // 2, 110)))
        mx, my = pygame.mouse.get_pos()
        for card in self.map_cards:
            rect = card["rect"]
            hover = rect.collidepoint(mx, my)
            pygame.draw.rect(screen, COL_BTN_HOVER if hover else COL_BTN, rect, border_radius=8)
            pygame.draw.rect(screen, (110, 110, 120), rect, 2, border_radius=8)
            screen.blit(card["thumb"], (rect.x + 8, rect.y + 8))
            name = FONT_TINY.render(f'{card["preset"]["name"]}  ({card["preset"]["size"]})', True, COL_TEXT)
            screen.blit(name, (rect.x + 10, rect.bottom - 40))
            size = FONT_TINY.render(f'{card["preset"]["cols"]}x{card["preset"]["rows"]} - {card["preset"]["biome"]}', True, COL_TEXT_DIM)
            screen.blit(size, (rect.x + 10, rect.bottom - 22))
        draw_button(screen, self.back_button, hover=self.back_button["rect"].collidepoint(mx, my))

    def render_host_wait(self):
        screen.fill((14, 16, 14))
        title = FONT_MED.render("HOSTING", True, COL_TEXT)
        screen.blit(title, title.get_rect(center=(SCREEN_W // 2, 140)))
        ip = net.get_local_ip()
        if self.net and self.net.error:
            lines = [f"Could not start hosting: {self.net.error}"]
        else:
            addr_txt = f"Share this address:  {ip}:{net.DEFAULT_PORT}"
            status = "Waiting for opponent to connect..." if not (self.net and self.net.connected) else "Opponent connected! Click Start when ready."
            lines = [addr_txt, "", status]
        y = 220
        for line in lines:
            col = COL_TEXT if line else COL_TEXT_DIM
            t = FONT.render(line, True, col)
            screen.blit(t, t.get_rect(center=(SCREEN_W // 2, y)))
            y += 32
        if self.mp_preset:
            m = FONT_SMALL.render(f'Map: {self.mp_preset["name"]} ({self.mp_preset["biome"]})', True, COL_TEXT_DIM)
            screen.blit(m, m.get_rect(center=(SCREEN_W // 2, y + 10)))
        mx, my = pygame.mouse.get_pos()
        connected = bool(self.net and self.net.connected)
        draw_button(screen, self.start_button, hover=self.start_button["rect"].collidepoint(mx, my), enabled=connected)
        draw_button(screen, self.back_button, hover=self.back_button["rect"].collidepoint(mx, my))

    def render_join_enter(self):
        screen.fill((14, 16, 14))
        title = FONT_MED.render("JOIN GAME", True, COL_TEXT)
        screen.blit(title, title.get_rect(center=(SCREEN_W // 2, 220)))
        sub = FONT_SMALL.render("Ask the host for their IP address (shown on their Hosting screen)", True, COL_TEXT_DIM)
        screen.blit(sub, sub.get_rect(center=(SCREEN_W // 2, 260)))
        self.ip_input.draw(screen)
        mx, my = pygame.mouse.get_pos()
        draw_button(screen, self.connect_button, hover=self.connect_button["rect"].collidepoint(mx, my))
        if self.join_error:
            e = FONT_SMALL.render(self.join_error, True, COL_BAD)
            screen.blit(e, e.get_rect(center=(SCREEN_W // 2, 450)))
        draw_button(screen, self.back_button, hover=self.back_button["rect"].collidepoint(mx, my))

    def render_join_wait(self):
        screen.fill((14, 16, 14))
        title = FONT_MED.render("JOINING...", True, COL_TEXT)
        screen.blit(title, title.get_rect(center=(SCREEN_W // 2, 220)))
        if not self.net:
            text, col = "No connection attempt in progress", COL_BAD
        elif self.net.connecting:
            text, col = "Connecting...", COL_TEXT_DIM
        elif self.net.error:
            text, col = f"Connection failed: {self.net.error}", COL_BAD
        elif self.net.connected:
            text, col = "Connected! Waiting for host to start the game...", COL_GOOD
        else:
            text, col = "Disconnected", COL_BAD
        t = FONT.render(text, True, col)
        screen.blit(t, t.get_rect(center=(SCREEN_W // 2, 280)))
        mx, my = pygame.mouse.get_pos()
        draw_button(screen, self.back_button, hover=self.back_button["rect"].collidepoint(mx, my))

    def render_pause(self):
        s = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        s.fill((0, 0, 0, 170))
        screen.blit(s, (0, 0))
        title = FONT_BIG.render("PAUSED", True, COL_TEXT)
        screen.blit(title, title.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2 - 110)))
        mx, my = pygame.mouse.get_pos()
        for btn in self.pause_buttons.values():
            draw_button(screen, btn, hover=btn["rect"].collidepoint(mx, my))


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main():
    app = App()

    if args.selftest:
        app.render()
        app.state = "MAP_SELECT"
        app.render()
        app.start_new_game(MAP_PRESETS[0])

    running = True
    frame = 0
    while running:
        dt = (clock.tick(FPS) / 1000.0) if not args.selftest else (1.0 / 30.0)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                app.toggle_fullscreen()
            else:
                app.handle_event(event)

        if args.selftest and app.state == "PLAYING" and app.game:
            if frame == 10 and app.game.player.units:
                u = app.game.player.units[0]
                u.selected = True
                app.game.selected_units = [u]
            if frame == 20:
                app.game.handle_right_click((VIEWPORT_W // 2, VIEWPORT_H // 2))
            if 30 <= frame <= 60:
                app.game.camera.move(20, 0)
            if frame == 70:
                app.game.camera.center_on(*[c * TILE for c in app.game.player.corner])
                app.game.player.pending_placement = "fence"
                app.game.player.pending_cost = None
            if frame == 90:
                cx, cy = app.game.player.corner
                sx, sy = app.game.camera.to_screen((cx - 2) * TILE, cy * TILE)
                app.game.handle_left_down((int(sx), int(sy)))
            if frame == 100:
                cx, cy = app.game.player.corner
                sx, sy = app.game.camera.to_screen((cx - 2) * TILE, (cy + 4) * TILE)
                app.game.handle_left_up((int(sx), int(sy)))

        app.update(dt)
        app.render()
        pygame.display.flip()

        frame += 1
        if args.selftest and frame >= args.selftest:
            g = app.game
            print(f"SELFTEST OK frames={frame} state={app.state} "
                  f"player(credits={int(g.player.credits)}, wood={int(g.player.wood)}, metal={int(g.player.metal)}, "
                  f"buildings={len(g.player.buildings)}, units={len(g.player.units)}) "
                  f"ai(credits={int(g.ai.credits)}, buildings={len(g.ai.buildings)}, units={len(g.ai.units)}) "
                  f"projectiles={len(g.projectiles)} camera=({g.camera.x:.0f},{g.camera.y:.0f}) game_over={g.game_over}")
            running = False

    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
