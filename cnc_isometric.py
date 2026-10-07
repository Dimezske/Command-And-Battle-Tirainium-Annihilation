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
import heapq
from array import array

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

try:
    if not pygame.mixer.get_init():
        pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=256)
except pygame.error:
    # Audio is optional so the game and self-tests still work in headless VMs.
    pass

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
# Combat and construction tuning knobs. Adjust these values to rebalance the
# whole game without changing individual building or unit data entries.
BUILDING_RANGE_MULT           = 3.0  # defensive building attack range
UNIT_FIRE_RANGE_MULT          = 1.5  # infantry/vehicle offensive fire range
BUILDING_PLACEMENT_RANGE_MULT = 3.5  # reach from an existing friendly building
ADJ_RANGE = 6                    # base placement reach before the multiplier
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
UNIT_FACING_DIRECTIONS = 8  # cardinal + diagonal sprite facings
BUILDING_SCALE     = 2.0   # master multiplier — scales sprite, tile footprint AND visual rect together
# Optional per-kind overrides.  A value here replaces BUILDING_SCALE for that building only.
# Example: set "yard": 1.5 to make the Construction Yard 50 % bigger than everything else.
BUILDING_SCALE_OVERRIDES = {
    # "yard": 1.5,
}
BUILDING_RECT_PADDING = 4  # pixels of clear space around sprite inside the rect
BUILDING_PERIMETER    = 1  # tile-wide sand gap around every building (visual + placement exclusion)
WALL_HP_BAR_MS = 5000  # walls only show their HP bar this long after taking damage
BUILDING_OVERLAY_ALPHA = 77  # 30% opacity for owner-colored footprint squares
LIME_UNIT_COLOR       = (174, 255, 48)

TRAINIUM_TIER_MULT = [1.0, 1.6, 2.6, 4.0]
TRAINIUM_TIER_NAMES = ["Green", "Yellow", "Blue", "Red"]
TRAINIUM_TIER_WEIGHTS = [50, 27, 15, 8]

RANK_NAMES = ["Rookie", "Veteran", "Elite"]
RANK_COLORS = [(255, 220, 60), (174, 255, 48), (255, 150, 40)]   # Rookie yellow, Veteran lime green, Elite orange
SELECTED_HEADER_COLOR = (160, 240, 160)   # light green
SELECTED_TEXT_COLOR = (70, 190, 70)       # green
RANK_HP_MULT = [1.0, 1.25, 1.6]
RANK_DMG_MULT = [1.0, 1.2, 1.45]
RANK_KILLS = [0, 3, 7]

PROJECTILE_SPEED = {"bullet": 900, "rocket": 420, "shell": 650, "nuke": 520}
PROJECTILE_COLOR = {"bullet": (255, 230, 120), "rocket": (230, 120, 60), "shell": (210, 210, 220)}
TRAINIUM_REGEN_SECONDS = 7 * 60
EXPLOSION_LIFETIME = 0.55
MUZZLE_FLASH_LIFETIME = 0.12
ATTACK_MOVE_SCAN_RANGE = 220.0
# Fog reveal radii in tiles. The yard gets the broadest radius so the player
# can see open ground around the base before placing another structure.
FOG_VISION_RADIUS_TILES = 7
FOG_BUILDING_VISION_TILES = 6
FOG_YARD_VISION_TILES = 12
RADAR_PING_LIFETIME = 2.4
RADAR_PING_COOLDOWN = 1.6
RADAR_PING_RING_SPEED = 78.0
NUKE_BUILD_TIME = 5 * 60      # seconds to assemble one nuke
NUKE_CREDIT_COST = 20000      # Tirainium credits required per assembled warhead
NUKE_BLAST_RADIUS = 450        # three times the original 150 px blast radius
NUKE_FALLOUT_RADIUS = int(NUKE_BLAST_RADIUS * 0.78)
NUKE_FALLOUT_DURATION = 40.0
NUKE_FALLOUT_TICK = 1.0
NUKE_FALLOUT_DAMAGE = 9.0
NUKE_CLOUD_DURATION = 3.0
NUKE_LAUNCH_ALTITUDE = 170.0
NUKE_ASCENT_TIME = 0.65
NUKE_DESCENT_TIME = 0.60
HACK_DURATION = 5 * 60      # seconds the enemy-intel hack stays online
HACK_COOLDOWN = 2 * 60      # seconds before it can be used again
WALL_LOS_THICKNESS = 14       # px: the part of a wall tile that actually blocks fire

screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
pygame.display.set_caption("Command and Battle: Tirainium Anihilation")
clock = pygame.time.Clock()


def _make_sfx(kind, duration, start_hz, end_hz=None, noise=0.0):
    """Create a small procedural 16-bit mono effect without external assets."""
    if not pygame.mixer.get_init():
        return None
    rate = 22050
    count = max(1, round(duration * rate))
    end_hz = start_hz if end_hz is None else end_hz
    samples = array("h")
    for i in range(count):
        t = i / rate
        p = i / max(1, count - 1)
        hz = start_hz + (end_hz - start_hz) * p
        env = (1.0 - p) ** (1.6 if kind != "engine" else 0.7)
        if kind == "engine":
            wave = 0.58 * math.sin(2 * math.pi * hz * t) + 0.22 * math.sin(2 * math.pi * hz * 2 * t)
        else:
            wave = math.sin(2 * math.pi * hz * t)
        if noise:
            wave += random.uniform(-noise, noise)
        samples.append(int(max(-32767, min(32767, wave * env * 27000))))
    return pygame.mixer.Sound(buffer=samples.tobytes())


SOUNDS = {}
if pygame.mixer.get_init():
    SOUNDS = {
        "tank_fire": _make_sfx("fire", 0.22, 105, 48, noise=0.32),
        "turret_rotate": _make_sfx("servo", 0.10, 145, 72, noise=0.08),
        "vehicle_move": _make_sfx("engine", 0.20, 72, 98, noise=0.035),
        "harvester_move": _make_sfx("engine", 0.20, 62, 78, noise=0.035),
        "tank_move": _make_sfx("engine", 0.20, 68, 90, noise=0.045),
        "apc_move": _make_sfx("engine", 0.20, 78, 105, noise=0.035),
        "resource_gather": _make_sfx("harvest", 0.16, 320, 540, noise=0.025),
    }
    _sound_dir = os.path.join(os.path.dirname(__file__), "assets", "sounds")
    for _name, _filename in {
        "harvester_move": "harvester_move.mp3",
        "tank_move": "medium_tank_move.mp3",
        "apc_move": "apc_move.mp3",
        "affirmative": "affirmative.wav",
        "negative": "negative.wav",
        "harvest_ack": "harvest_ack.wav",
    }.items():
        _path = os.path.join(_sound_dir, _filename)
        if os.path.isfile(_path):
            try:
                SOUNDS[_name] = pygame.mixer.Sound(_path)
            except pygame.error:
                pass


def play_sfx(name, volume=1.0):
    sound = SOUNDS.get(name)
    if sound is not None:
        sound.set_volume(clamp(volume, 0.0, 1.0))
        sound.play()


def _make_nuke_warhead_sprite():
    """Create a compact, high-contrast warhead icon without an external art dependency."""
    if not pygame.display.get_surface():
        return None
    image = pygame.Surface((36, 58), pygame.SRCALPHA)
    pygame.draw.polygon(image, (52, 65, 57), [(18, 2), (28, 20), (28, 42), (8, 42), (8, 20)])
    pygame.draw.polygon(image, (175, 190, 150), [(18, 2), (25, 19), (11, 19)])
    pygame.draw.rect(image, (115, 133, 102), (9, 19, 18, 25), border_radius=4)
    pygame.draw.rect(image, (35, 46, 39), (9, 19, 18, 25), 2, border_radius=4)
    pygame.draw.line(image, (219, 188, 82), (11, 29), (25, 29), 3)
    pygame.draw.polygon(image, (190, 70, 39), [(9, 40), (2, 53), (13, 46)])
    pygame.draw.polygon(image, (190, 70, 39), [(27, 40), (34, 53), (23, 46)])
    pygame.draw.polygon(image, (255, 165, 55), [(15, 44), (21, 44), (18, 57)])
    return image


NUKE_WARHEAD_SPRITE = _make_nuke_warhead_sprite()


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

# ---------------------------------------------------------------------------
# Match setup: teams, colours, start positions
# ---------------------------------------------------------------------------
MAX_SLOTS = 8
MAX_TEAM_SIZE = 4
TEAM_LETTERS = ["A", "B", "C", "D"]
COLOR_PALETTE = [
    ("Gold", (215, 180, 40)),
    ("Red", (200, 50, 50)),
    ("Blue", (60, 120, 220)),
    ("Green", (70, 190, 80)),
    ("Orange", (235, 130, 40)),
    ("Purple", (150, 80, 200)),
    ("Cyan", (50, 200, 210)),
    ("Pink", (230, 110, 170)),
]


def start_positions(cols, rows, n):
    """n base positions spread round the map edge (corners + edge midpoints).

    The ring runs BL, L, TL, T, TR, R, BR, B. Players are handed out in
    (team, slot) order, so allies end up next to each other and enemies
    opposite: 1v1 = opposite corners, 2v2 = left side vs right side."""
    ring = [(5, rows - 6), (5, rows // 2 - 2), (5, 5), (cols // 2 - 3, 5),
            (cols - 6, 5), (cols - 6, rows // 2 - 2), (cols - 6, rows - 6),
            (cols // 2 - 3, rows - 6)]
    if n <= 1:
        return [ring[0]]
    idx = [int(round(i * 8.0 / n)) % 8 for i in range(n)]
    return [ring[i] for i in idx]


def make_slots(per_team, teams):
    """Standard layouts: `teams` teams of `per_team` players each."""
    slots = []
    for t in range(teams):
        for _ in range(per_team):
            i = len(slots)
            slots.append({"kind": "ai", "name": "", "team": t, "color": i % len(COLOR_PALETTE),
                          "cid": None, "prev": "ai"})
    return slots


def default_match(local_kind="skirmish"):
    slots = make_slots(1, 2)
    slots[0]["kind"] = "human"
    return {"slots": slots}

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
_WALL_VARIANT_CACHE = {}

# ---------------------------------------------------------------------------
# Generated art (loaded once at startup)
# ---------------------------------------------------------------------------
TILES, BUILDING_SPRITES, ISO_SIZE, FLAG_OFFSET = iso_assets.generate_all(TILE)
BUILDING_SAND_TEXTURE = iso_assets.make_building_sand_texture(TILE)
_ENEMY_BUILDING_SPRITE_CACHE = {}


def _enemy_building_sprite(kind, sprite):
    """Return *sprite* with yellow/gold accents converted to enemy red."""
    cached = _ENEMY_BUILDING_SPRITE_CACHE.get(kind)
    if cached is not None:
        return cached
    recolored = pygame.Surface(sprite.get_size(), pygame.SRCALPHA)
    for x in range(sprite.get_width()):
        for y in range(sprite.get_height()):
            r, g, b, a = sprite.get_at((x, y))
            if a == 0:
                continue
            # Target the full yellow/gold accent hue, including anti-aliased
            # edge pixels, so no isolated yellow speckles remain.
            yellow_accent = (r >= 82 and g >= 62 and r > b * 1.18 and
                             g > b * 1.10 and r >= g * 0.68)
            if yellow_accent:
                strength = max(r, g)
                recolored.set_at((x, y), (min(255, strength), max(22, int(g * 0.24)),
                                           max(18, int(b * 0.28)), a))
            else:
                recolored.set_at((x, y), (r, g, b, a))
    _ENEMY_BUILDING_SPRITE_CACHE[kind] = recolored
    return recolored


_OWNER_BUILDING_SPRITE_CACHE = {}


def _soft_tint(color):
    """Light multiply-tint for walls: keeps the stone/wood readable but coloured."""
    return tuple(255 - int((255 - c) * 0.65) for c in color)


def _owner_building_sprite(kind, sprite, color):
    """Building art recoloured to a player's chosen colour (yellow accents -> colour)."""
    if color == AI_COLOR:
        return _enemy_building_sprite(kind, sprite)
    key = (kind, color)
    cached = _OWNER_BUILDING_SPRITE_CACHE.get(key)
    if cached is not None:
        return cached
    tr, tg, tb = color
    recolored = pygame.Surface(sprite.get_size(), pygame.SRCALPHA)
    for x in range(sprite.get_width()):
        for y in range(sprite.get_height()):
            r, g, b, a = sprite.get_at((x, y))
            if a == 0:
                continue
            yellow_accent = (r >= 82 and g >= 62 and r > b * 1.18 and
                             g > b * 1.10 and r >= g * 0.68)
            if yellow_accent:
                k = max(r, g) / 255.0
                recolored.set_at((x, y), (min(255, int(tr * k * 1.15)), min(255, int(tg * k * 1.15)),
                                           min(255, int(tb * k * 1.15)), a))
            else:
                recolored.set_at((x, y), (r, g, b, a))
    _OWNER_BUILDING_SPRITE_CACHE[key] = recolored
    return recolored


def _tile_texture(surface, texture, rect):
    """Fill *rect* with a small repeating texture without a large allocation."""
    for y in range(rect.top, rect.bottom, texture.get_height()):
        for x in range(rect.left, rect.right, texture.get_width()):
            area = pygame.Rect(0, 0, min(texture.get_width(), rect.right - x),
                               min(texture.get_height(), rect.bottom - y))
            surface.blit(texture, (x, y), area=area)


def _tile_texture_alpha(surface, texture, rect, alpha):
    """Tile a texture through a temporary layer with controlled opacity."""
    layer = pygame.Surface(rect.size, pygame.SRCALPHA)
    _tile_texture(layer, texture, layer.get_rect())
    layer.set_alpha(max(0, min(255, int(alpha))))
    surface.blit(layer, rect.topleft)


def _wall_variant(kind, connections, size, enemy=False):
    key = (kind, tuple(sorted(connections)), tuple(size), enemy)
    if key not in _WALL_VARIANT_CACHE:
        _WALL_VARIANT_CACHE[key] = iso_assets.make_wall_variant(kind, connections, size, enemy=enemy)
    return _WALL_VARIANT_CACHE[key]

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
def _load_nuke_cloud_frames():
    cloud_dir = os.path.join(os.path.dirname(__file__), "assets", "nuke_cloud")
    try:
        names = sorted(name for name in os.listdir(cloud_dir)
                       if name.startswith("cloud_") and name.endswith(".png"))
        return [pygame.image.load(os.path.join(cloud_dir, name)).convert_alpha()
                for name in names]
    except (OSError, pygame.error):
        return []


NUKE_CLOUD_FRAMES = _load_nuke_cloud_frames()
AI_PROJECTILE_SPRITE  = _load_ai_sprite("projectile_shell.png", (24, 24))
AI_UNIT_SPRITES = {
    k: _load_ai_sprite(f"{k}.png", _ss(*_UNIT_BASE_SIZES[k], _unit_sprite_scale(k)))
    for k in _UNIT_BASE_SIZES
}


def _split_tank_sprite(source):
    """Separate the original tank image into hull, turret, and cannon layers.

    Only the circular turret and the narrow cannon are copied out of the
    source. Keeping the cannon mask narrow prevents nearby hull pixels from
    being dragged around when the gun aims at a new target.
    """
    if source is None:
        return None, None, None, (0, 0)
    w, h = source.get_size()
    pivot = (round(w * 0.46), round(h * 0.34))
    radius = max(7, round(min(w, h) * 0.18))
    turret_mask_surface = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.circle(turret_mask_surface, (255, 255, 255, 255), pivot, radius)
    turret_mask = pygame.mask.from_surface(turret_mask_surface)

    # The original cannon points down/right from the source artwork's pivot.
    # Use a narrow capsule-like polygon so the gun layer contains no deck.
    vx, vy = float(w - 2 - pivot[0]), float(h - 3 - pivot[1])
    length = math.hypot(vx, vy) or 1.0
    vx, vy = vx / length, vy / length
    nx, ny = -vy, vx
    start = (pivot[0] + vx * 3, pivot[1] + vy * 3)
    end = (pivot[0] + vx * (length + 1), pivot[1] + vy * (length + 1))
    gun_width = max(2.5, min(w, h) * 0.075)
    gun_mask_surface = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.polygon(gun_mask_surface, (255, 255, 255, 255), [
        (start[0] + nx * gun_width, start[1] + ny * gun_width),
        (end[0] + nx * gun_width * 0.72, end[1] + ny * gun_width * 0.72),
        (end[0] - nx * gun_width * 0.72, end[1] - ny * gun_width * 0.72),
        (start[0] - nx * gun_width, start[1] - ny * gun_width),
    ])
    gun_mask = pygame.mask.from_surface(gun_mask_surface)
    combined_mask = turret_mask.copy()
    combined_mask.draw(gun_mask, (0, 0))
    hull = source.copy()
    turret = pygame.Surface((w, h), pygame.SRCALPHA)
    gun = pygame.Surface((w, h), pygame.SRCALPHA)
    for y in range(h):
        for x in range(w):
            if turret_mask.get_at((x, y)):
                turret.set_at((x, y), source.get_at((x, y)))
            if gun_mask.get_at((x, y)):
                gun.set_at((x, y), source.get_at((x, y)))
            if combined_mask.get_at((x, y)):
                hull.set_at((x, y), (67, 79, 46, 255))
    # Build a flat armored deck over the removed turret footprint. This is
    # intentionally not circular: the hull must not retain a baked-in turret
    # silhouette underneath the independently rotating turret layer.
    deck = [
        (max(2, pivot[0] - radius - 5), max(4, pivot[1] - radius // 2)),
        (min(w - 3, pivot[0] + radius + 7), max(5, pivot[1] - radius // 2 + 3)),
        (min(w - 3, pivot[0] + radius + 4), min(h - 4, pivot[1] + radius // 2 + 8)),
        (max(2, pivot[0] - radius - 6), min(h - 5, pivot[1] + radius // 2 + 6)),
    ]
    pygame.draw.polygon(hull, (69, 82, 48, 255), deck)
    pygame.draw.line(hull, (101, 113, 65, 255), deck[0], deck[1], 1)
    pygame.draw.line(hull, (38, 48, 32, 255), deck[2], deck[3], 1)
    return hull, turret, gun, pivot


_TANK_SOURCE_SPRITE = AI_UNIT_SPRITES.get("tank")
_TANK_HULL_ART = _load_ai_sprite("tank_hull.png", _ss(*_UNIT_BASE_SIZES["tank"], VEHICLE_SCALE))
_TANK_SPLIT_HULL, TANK_TURRET_SPRITE, TANK_GUN_SPRITE, TANK_TURRET_PIVOT = _split_tank_sprite(_TANK_SOURCE_SPRITE)
# Prefer the freshly reworked hull artwork. The split result remains a safe
# fallback if the optional generated asset is unavailable.
TANK_HULL_SPRITE = _TANK_HULL_ART or _TANK_SPLIT_HULL
TANK_TURRET_ART_ANGLE = math.atan2(34, 35)
if TANK_HULL_SPRITE is not None:
    AI_UNIT_SPRITES["tank"] = TANK_HULL_SPRITE


def _make_eight_direction_sprites(source, native_forward_angle=0.0):
    """Build upright eight-way facings from a sprite's native forward angle.

    Backward-facing directions use a horizontal mirror and only rotate within
    a 90-degree upright range. This avoids the old upside-down 180-degree
    rotations while keeping the original artwork and silhouette intact.
    """
    if source is None:
        return {}
    step = (2.0 * math.pi) / UNIT_FACING_DIRECTIONS
    variants = {}
    for index in range(UNIT_FACING_DIRECTIONS):
        desired_angle = index * step
        relative = desired_angle - native_forward_angle
        signed_angle = (relative + math.pi) % (2.0 * math.pi) - math.pi
        if signed_angle > math.pi / 2.0:
            image = pygame.transform.flip(source, True, False)
            delta = signed_angle - math.pi
        elif signed_angle < -math.pi / 2.0:
            image = pygame.transform.flip(source, True, False)
            delta = signed_angle + math.pi
        else:
            image = source
            delta = signed_angle
        variants[index] = pygame.transform.rotate(image, -math.degrees(delta))
    return variants


UNIT_ART_FORWARD_ANGLES = {
    # The source illustrations are three-quarter views, not screen-right
    # orthographic sprites. These are their visible front/bucket directions.
    "infantry": math.radians(35),
    "rocket": math.radians(35),
    "tank": TANK_TURRET_ART_ANGLE,
    "harvester": math.radians(135),
    "apc": math.radians(135),
}
UNIT_DIRECTION_SPRITES = {
    kind: _make_eight_direction_sprites(
        sprite, UNIT_ART_FORWARD_ANGLES.get(kind, 0.0))
    for kind, sprite in AI_UNIT_SPRITES.items()
}
UNIT_DIRECTION_SPRITES["apc"] = _make_eight_direction_sprites(
    AI_APC_SPRITE, UNIT_ART_FORWARD_ANGLES["apc"])


def _heading_direction_index(angle):
    step = (2.0 * math.pi) / UNIT_FACING_DIRECTIONS
    return int(round(angle / step)) % UNIT_FACING_DIRECTIONS


def _directional_pivot_offset(index, pivot, size):
    """Return the tank-ring offset in the selected hull's rotated canvas."""
    step = (2.0 * math.pi) / UNIT_FACING_DIRECTIONS
    angle = index * step
    signed_angle = angle if angle <= math.pi else angle - 2.0 * math.pi
    mirror = signed_angle > math.pi / 2.0 or signed_angle < -math.pi / 2.0
    if signed_angle > math.pi / 2.0:
        delta = signed_angle - math.pi
    elif signed_angle < -math.pi / 2.0:
        delta = signed_angle + math.pi
    else:
        delta = signed_angle
    offset = pygame.Vector2(pivot[0] - size[0] / 2, pivot[1] - size[1] / 2)
    if mirror:
        offset.x = -offset.x
    return offset.rotate(-math.degrees(delta))


def _solid_sprite(sprite, color):
    return pygame.mask.from_surface(sprite).to_surface(
        setcolor=(*color, 255), unsetcolor=(0, 0, 0, 0))


def _rotate_tank_turret(sprite, angle, pivot):
    """Rotate a turret around its real image pivot, not its canvas center."""
    if sprite is None:
        return None
    w, h = sprite.get_size()
    pad = max(w, h) * 2 + 8
    layer = pygame.Surface((pad, pad), pygame.SRCALPHA)
    center = (pad // 2, pad // 2)
    layer.blit(sprite, (center[0] - pivot[0], center[1] - pivot[1]))
    return pygame.transform.rotate(layer, -math.degrees(angle))


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

def _building_tile_size(kind):
    """Return (w_tiles, h_tiles) for *kind* after applying the scale multiplier.
    BUILDING_SCALE is the global knob; BUILDING_SCALE_OVERRIDES lets individual
    buildings diverge.  Everything — sprite, footprint, and visual rect — uses
    this one function so a single number change scales the whole building.
    """
    bw, bh = BUILD_DATA[kind]["size"]
    s = BUILDING_SCALE_OVERRIDES.get(kind, BUILDING_SCALE)
    return max(1, round(bw * s)), max(1, round(bh * s))


UNIT_DATA = {
    "harvester": {"name": "Harvester",   "cost": C(1400), "hp": 250, "speed": 65, "damage": 0,  "range": 0,   "time": 10, "cooldown": 0,   "built_from": "factory"},
    "infantry":  {"name": "Rifleman",    "cost": C(100),  "hp": 50,  "speed": 85, "damage": 6,  "range": 110, "time": 3,  "cooldown": 0.5, "built_from": "barracks", "projectile": "bullet"},
    "rocket":    {"name": "Rocket Sldr", "cost": C(160),  "hp": 55,  "speed": 70, "damage": 20, "range": 150, "time": 4,  "cooldown": 1.1, "built_from": "barracks", "projectile": "rocket"},
    "tank":      {"name": "Medium Tank", "cost": C(800),  "hp": 300, "speed": 95, "damage": 26, "range": 140, "time": 8,  "cooldown": 0.9, "built_from": "factory",  "projectile": "shell"},
    "apc":       {"name": "APC", "cost": C(650), "hp": 240, "speed": 82, "damage": 12, "range": 120, "time": 7, "cooldown": 0.8, "built_from": "factory", "projectile": "bullet", "amphibious": True, "transport_capacity": 5},
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
VEHICLE_ORDER = ["harvester", "tank", "apc"]

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


def quantize_heading(angle):
    """Snap a movement angle to the nearest configured facing direction."""
    step = (2.0 * math.pi) / UNIT_FACING_DIRECTIONS
    return round(angle / step) * step


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
    def __init__(self, cols, rows, seed=None, biome="grass", starts=None):
        self.cols = cols
        self.rows = rows
        self.seed = seed
        self.biome = biome
        self.starts = list(starts) if starts else [(5, rows - 6), (cols - 6, 5)]
        self.rng = random.Random(seed)
        self.tiles = [[TILE_GROUND] * cols for _ in range(rows)]
        self.resource_amount = [[0.0] * cols for _ in range(rows)]
        self.trainium_tier = [[0] * cols for _ in range(rows)]
        self.variant = [[0] * cols for _ in range(rows)]
        self.depleted_at = [[0.0] * cols for _ in range(rows)]
        self.game_buildings = []
        self.wall_cells = {}          # team index -> set of (col,row) covered by that team's walls
        self._regions = None          # lazily built land-connectivity labels
        self._path_cache = {}
        self.searches_left = 3        # A* searches allowed this frame (reset by Game.update)
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

        # keep every base start clear, and give each one a small starter field
        # so a crowded 4v4 map never leaves a base without resources
        for (cx, cy) in self.starts:
            for y in range(cy - 4, cy + 6):
                for x in range(cx - 4, cx + 6):
                    if 0 <= x < cols and 0 <= y < rows:
                        self.tiles[y][x] = TILE_GROUND
                        self.resource_amount[y][x] = 0
                        self.trainium_tier[y][x] = 0
        if len(self.starts) > 2:
            for (cx, cy) in self.starts:
                sx = 1 if cx < cols // 2 else -1
                sy = 1 if cy < rows // 2 else -1
                for (ox, oy, rad, ttype, amt) in ((12 * sx, -2 * sy, 2.4, TILE_TRAINIUM, TRAINIUM_PER_TILE),
                                                  (7 * sx, 9 * sy, 1.6, TILE_ORE, METAL_PER_ORE),
                                                  (2 * sx, 11 * sy, 2.0, TILE_TREE, WOOD_PER_TREE)):
                    bx, by = cx + 2 + ox, cy + 2 + oy
                    for y in range(int(by - rad) - 1, int(by + rad) + 2):
                        for x in range(int(bx - rad) - 1, int(bx + rad) + 2):
                            if self.in_bounds(x, y) and dist(x, y, bx, by) <= rad:
                                # never overwrite another base's cleared start area
                                if any(abs(x - sx2 - 0.5) < 5 and abs(y - sy2 - 0.5) < 6 for sx2, sy2 in self.starts):
                                    continue
                                self.tiles[y][x] = ttype
                                self.resource_amount[y][x] = amt
                                if ttype == TILE_TRAINIUM:
                                    self.trainium_tier[y][x] = 1

    def in_bounds(self, col, row):
        return 0 <= col < self.cols and 0 <= row < self.rows

    def vehicle_cell_blocked(self, col, row, unit):
        """Return whether terrain makes a vehicle cell unsafe.

        Buildings are pass-through scenery for vehicles. Walls, map edges,
        water, and other terrain rules still constrain routing below.
        """
        if not self.in_bounds(col, row):
            return True
        if self.tiles[row][col] == TILE_WATER and not UNIT_DATA[unit.kind].get("amphibious"):
            return True
        # Enemy walls are solid: route around them (own walls are walk-through).
        if self.wall_cells:
            my_team = unit.owner.team
            for tid, cells in self.wall_cells.items():
                if tid != my_team and (col, row) in cells:
                    return True
        return False

    def region_at(self, col, row):
        """Land-connectivity label of a cell (-1 = water / out of bounds).
        Two cells share a label only if a non-amphibious unit can walk between
        them, so a different label means the route needs a boat (APC)."""
        if self._regions is None:
            lab = [[-1] * self.cols for _ in range(self.rows)]
            nxt = 0
            for y0 in range(self.rows):
                for x0 in range(self.cols):
                    if lab[y0][x0] != -1 or self.tiles[y0][x0] == TILE_WATER:
                        continue
                    lab[y0][x0] = nxt
                    stack = [(x0, y0)]
                    while stack:
                        cx_, cy_ = stack.pop()
                        for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                            nx_, ny_ = cx_ + ddx, cy_ + ddy
                            if (0 <= nx_ < self.cols and 0 <= ny_ < self.rows
                                    and lab[ny_][nx_] == -1 and self.tiles[ny_][nx_] != TILE_WATER):
                                lab[ny_][nx_] = nxt
                                stack.append((nx_, ny_))
                    nxt += 1
            self._regions = lab
        if not self.in_bounds(col, row):
            return -1
        return self._regions[row][col]

    def vehicle_path(self, unit, start_xy, goal_xy, max_nodes=4200):
        """Find a short, corner-safe eight-neighbor path (A*) for a ground unit.

        Cached briefly so a whole group heading to the same place shares one
        search, and capped so a huge detour can never stall the frame - when
        the cap is hit the best partial path toward the goal is returned."""
        start = (int(start_xy[0] // TILE), int(start_xy[1] // TILE))
        goal = (int(goal_xy[0] // TILE), int(goal_xy[1] // TILE))
        key = (start, goal, bool(UNIT_DATA[unit.kind].get("amphibious")), unit.owner.team)
        now = pygame.time.get_ticks()
        hit = self._path_cache.get(key)
        if hit is not None and now - hit[0] < 900:
            return [tuple(pt) for pt in hit[1]]
        if len(self._path_cache) > 300:
            self._path_cache.clear()
        if self._straight_line_clear(unit, start_xy, goal_xy):
            result = []                   # open ground: walk straight, no search needed
        else:
            if self.searches_left <= 0:
                return None               # over this frame's budget: caller retries shortly
            self.searches_left -= 1
            result = self._vehicle_path_search(unit, start, goal, max_nodes)
        self._path_cache[key] = (now, result)
        return [tuple(pt) for pt in result]

    def _straight_line_clear(self, unit, a, b):
        """True when the straight segment a->b crosses no blocked cell (1/3-tile steps)."""
        d = dist(a[0], a[1], b[0], b[1])
        if d < 1:
            return True
        n = int(d / (TILE / 3.0)) + 1
        last = None
        for i in range(n + 1):
            t = i / float(n)
            cell = (int((a[0] + (b[0] - a[0]) * t) // TILE), int((a[1] + (b[1] - a[1]) * t) // TILE))
            if cell == last:
                continue
            last = cell
            if self.vehicle_cell_blocked(cell[0], cell[1], unit):
                return False
        # also make sure the target cell itself is usable (else the search picks a nearby cell)
        return True

    def _vehicle_path_search(self, unit, start, goal, max_nodes):
        if not self.in_bounds(*start):
            return []
        if self.vehicle_cell_blocked(*goal, unit):
            options = []
            for radius in range(1, 6):
                for dy in range(-radius, radius + 1):
                    for dx in range(-radius, radius + 1):
                        cell = (goal[0] + dx, goal[1] + dy)
                        if self.in_bounds(*cell) and not self.vehicle_cell_blocked(*cell, unit):
                            options.append((dx * dx + dy * dy, cell))
                if options:
                    goal = min(options)[1]
                    break
        if self.vehicle_cell_blocked(*goal, unit):
            return []
        if start == goal:
            return []
        frontier = [(0.0, start)]
        came_from = {start: None}
        cost_so_far = {start: 0.0}
        neighbors = ((-1, 0), (1, 0), (0, -1), (0, 1),
                     (-1, -1), (1, -1), (-1, 1), (1, 1))
        expanded = 0
        best_cell, best_h = start, math.hypot(goal[0] - start[0], goal[1] - start[1])
        while frontier:
            _, current = heapq.heappop(frontier)
            if current == goal:
                break
            expanded += 1
            h_cur = math.hypot(goal[0] - current[0], goal[1] - current[1])
            if h_cur < best_h:
                best_cell, best_h = current, h_cur
            if expanded > max_nodes:
                goal = best_cell          # give a best-effort partial route
                break
            for dx, dy in neighbors:
                nxt = (current[0] + dx, current[1] + dy)
                if self.vehicle_cell_blocked(*nxt, unit):
                    continue
                # Do not cut diagonally through the corner of a building/wall.
                if dx and dy and (self.vehicle_cell_blocked(current[0] + dx, current[1], unit)
                                  or self.vehicle_cell_blocked(current[0], current[1] + dy, unit)):
                    continue
                step = 1.4142 if dx and dy else 1.0
                new_cost = cost_so_far[current] + step
                if new_cost < cost_so_far.get(nxt, float("inf")):
                    cost_so_far[nxt] = new_cost
                    priority = new_cost + math.hypot(goal[0] - nxt[0], goal[1] - nxt[1])
                    heapq.heappush(frontier, (priority, nxt))
                    came_from[nxt] = current
        if goal not in came_from or goal == start:
            return []
        cells = []
        current = goal
        while current != start:
            cells.append(current)
            current = came_from[current]
        cells.reverse()
        return [((col + 0.5) * TILE, (row + 0.5) * TILE) for col, row in cells]

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
        self.w, self.h = _building_tile_size(kind)   # scaled tile footprint
        base_hp = data["hp"]
        if kind in DEFENSE_KINDS or kind in WALL_DRAG_KINDS:
            base_hp *= (1 + structure_hp_bonus_pct(owner))
        self.hp = base_hp
        self.max_hp = base_hp
        self._seen_hp = base_hp          # last HP observed (for damage detection)
        self._hp_bar_until = 0           # tick (ms) until which a wall's HP bar shows
        self.attack_cd = NUKE_BUILD_TIME if kind == "nuke_silo" else 0.0
        # Nuke silo assembly (human players): idle -> building -> ready -> (launch) idle
        self.nuke_state = "idle"
        self.nuke_timer = 0.0
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
        if self.kind not in WALL_DRAG_KINDS and self.kind not in DEFENSE_KINDS:
            return set()
        neighbors = set()
        for other in self.owner.buildings:
            if other is self or not other.alive:
                continue
            if self.kind in WALL_DRAG_KINDS:
                allowed = other.kind in WALL_DRAG_KINDS or other.kind in DEFENSE_KINDS
            else:
                allowed = other.kind in WALL_DRAG_KINDS
            if not allowed:
                continue
            row_overlap = other.row < self.row + self.h and other.row + other.h > self.row
            col_overlap = other.col < self.col + self.w and other.col + other.w > self.col
            if other.col + other.w == self.col and row_overlap:
                neighbors.add("left")
            if self.col + self.w == other.col and row_overlap:
                neighbors.add("right")
            if other.row + other.h == self.row and col_overlap:
                neighbors.add("up")
            if self.row + self.h == other.row and col_overlap:
                neighbors.add("down")
        return neighbors

    def visual_screen_rect(self, camera):
        """Screen-space rect including the sand perimeter — matches the outer_rect
        drawn in draw(), used for click-selection and right-click targeting."""
        r = self.rect
        sx0, sy0 = camera.to_screen(r.x, r.y)
        _P = 0 if self.kind in WALL_DRAG_KINDS else BUILDING_PERIMETER * TILE
        return pygame.Rect(sx0 - _P, sy0 - _P, r.w + _P * 2, r.h + _P * 2)

    def draw_foundation(self, surf, camera):
        """Draw only the grey-sand pad, before units and building sprites."""
        r = self.rect
        _CM = 320 + BUILDING_PERIMETER * TILE
        if r.right < camera.x - _CM or r.left > camera.x + VIEWPORT_W + _CM or \
           r.bottom < camera.y - _CM or r.top > camera.y + VIEWPORT_H + _CM:
            return
        if self.kind in WALL_DRAG_KINDS:
            return  # walls have no foundation pad; the ground shows through
        sx0, sy0 = camera.to_screen(r.x, r.y)
        _P = BUILDING_PERIMETER * TILE
        outer_rect = pygame.Rect(sx0 - _P, sy0 - _P, r.w + _P * 2, r.h + _P * 2)
        _tile_texture(surf, BUILDING_SAND_TEXTURE, outer_rect)
        pygame.draw.rect(surf, (103, 101, 92), outer_rect, 1)

    def take_damage(self, dmg):
        self.hp -= dmg
        self._hp_bar_until = pygame.time.get_ticks() + WALL_HP_BAR_MS
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
        is_wall = self.kind in WALL_DRAG_KINDS
        sprite = None if is_wall else self.sprite
        if sprite is not None and self.owner.color != PLAYER_COLOR:
            sprite = _owner_building_sprite(self.kind, sprite, self.owner.color)

        # Inner pad_rect = tile footprint exactly (owner coloured fill + border).
        pad_rect = pygame.Rect(sx0, sy0, r.w, r.h)

        if sprite is not None:
            sp_w, sp_h = sprite.get_size()
        else:
            sp_w, sp_h = r.w, r.h
        if not is_wall:
            # Fences / stone walls get no footprint square at all, so the
            # ground stays fully visible around the wall sprite.
            pad = pygame.Surface((pad_rect.w, pad_rect.h), pygame.SRCALPHA)
            pad.fill((*self.owner.color, BUILDING_OVERLAY_ALPHA))
            surf.blit(pad, pad_rect.topleft)
            overlay_border = pygame.Surface(pad_rect.size, pygame.SRCALPHA)
            pygame.draw.rect(overlay_border, (*self.owner.color, BUILDING_OVERLAY_ALPHA),
                             overlay_border.get_rect(), 2)
            surf.blit(overlay_border, pad_rect.topleft)
        # Sprite anchored midbottom at the tile footprint bottom-centre.
        iso_rect = (sprite or pygame.Surface((sp_w, sp_h), pygame.SRCALPHA)).get_rect(
            midbottom=(pad_rect.centerx, pad_rect.bottom))
        if sprite is not None:
            surf.blit(sprite, iso_rect)
        elif is_wall:
            pass  # walls draw only their transparent sprite (below), no box
        else:
            col = (80, 170, 70) if self.kind == "nuke_silo" else self.owner.color
            pygame.draw.rect(surf, col, iso_rect, border_radius=4)
            pygame.draw.rect(surf, (20, 20, 20), iso_rect, 2, border_radius=4)
            if self.kind == "nuke_silo":
                pygame.draw.circle(surf, (220, 240, 80), iso_rect.center, max(4, iso_rect.w // 5))
        if (self.kind == "nuke_silo" and NUKE_WARHEAD_SPRITE is not None
                and (self.nuke_state in ("building", "ready") or
                     (self.owner.is_ai and self.owner.credits >= NUKE_CREDIT_COST))):
            warhead = pygame.transform.smoothscale(NUKE_WARHEAD_SPRITE, (24, 40))
            if self.nuke_state == "building":
                progress = clamp(self.nuke_timer / NUKE_BUILD_TIME, 0.0, 1.0)
                warhead.set_alpha(int(110 + 145 * progress))
            surf.blit(warhead, warhead.get_rect(midbottom=(iso_rect.centerx, iso_rect.top + 28)))
        if self.kind in WALL_DRAG_KINDS:
            connections = self._wall_connections()
            tint = None if self.owner.color == PLAYER_COLOR else _soft_tint(self.owner.color)
            wall_img = _wall_variant(self.kind, connections, pad_rect.size, enemy=tint)
            surf.blit(wall_img, wall_img.get_rect(center=pad_rect.center))
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
            # A turret placed beside a wall gets a visible concrete/metal
            # connector so it reads as one fortified structure.
            for direction in self._wall_connections():
                wx, wy = {"left": (-1, 0), "right": (1, 0),
                          "up": (0, -1), "down": (0, 1)}[direction]
                pygame.draw.line(surf, (70, 74, 78), (cx, cy),
                                 (cx + wx * pad_rect.w // 2, cy + wy * pad_rect.h // 2), 10)
                pygame.draw.line(surf, (155, 160, 165), (cx, cy),
                                 (cx + wx * pad_rect.w // 2, cy + wy * pad_rect.h // 2), 4)
        fx, fy = FLAG_OFFSET.get(self.kind, (6, 6))
        if not is_wall:
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
        now = pygame.time.get_ticks()
        if self.hp < self._seen_hp - 0.01:
            # HP dropped by any route (direct hits, splash, network sync).
            self._hp_bar_until = now + WALL_HP_BAR_MS
        self._seen_hp = self.hp
        if not is_wall or now < self._hp_bar_until:
            draw_health_bar(surf, pad_rect.x, top_y - 4, pad_rect.w, 5, self.hp, self.max_hp)
        if self.kind == "nuke_silo" and not self.owner.is_ai and self.nuke_state != "idle":
            nb = pygame.Rect(pad_rect.x, top_y - 12, pad_rect.w, 5)
            pygame.draw.rect(surf, (35, 25, 10), nb)
            if self.nuke_state == "building":
                fill = int(nb.w * clamp(self.nuke_timer / NUKE_BUILD_TIME, 0, 1))
                pygame.draw.rect(surf, (255, 150, 40), (nb.x, nb.y, fill, nb.h))
            else:
                pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 180)
                pygame.draw.rect(surf, (255, int(90 + 120 * pulse), 40), nb)
            pygame.draw.rect(surf, (10, 10, 10), nb, 1)
        if self.demolish_timer > 0 and self.demolish_duration > 0:
            pct_left = 1.0 - min(self.demolish_timer / self.demolish_duration, 1.0)
            bar_x, bar_y = pad_rect.x, top_y + 4
            bar_w, bar_h = max(pad_rect.w, 20), 6
            pygame.draw.rect(surf, (50, 15, 15),   (bar_x, bar_y, bar_w, bar_h))
            fill_w = max(0, round(bar_w * pct_left))
            if fill_w > 0:
                pygame.draw.rect(surf, (210, 35, 35), (bar_x, bar_y, fill_w, bar_h))
            pygame.draw.rect(surf, (160, 20, 20),  (bar_x, bar_y, bar_w, bar_h), 1)


_RANK_BADGE_CACHE = {}


def _rank_badge(rank):
    """Military-style stacked-chevron rank insignia (Rookie = 1, Veteran = 2, Elite = 3 bars).

    Drawn at 8x and smoothscaled down so the edges stay crisp and clean, with a
    black outline around every bar. Colour comes from RANK_COLORS.
    """
    if rank in _RANK_BADGE_CACHE:
        return _RANK_BADGE_CACHE[rank]
    bars = rank + 1                       # rank 1 -> 2 chevrons, rank 2 -> 3
    S = 8                                 # supersample factor
    W, A, T, STEP, PAD = 13, 4.0, 3.4, 4.8, 2   # width, slope, bar thickness, spacing, pad (px)
    H = A + T + STEP * (bars - 1)
    w_px, h_px = int(math.ceil(W + PAD * 2)), int(math.ceil(H + PAD * 2))
    big = pygame.Surface((w_px * S, h_px * S), pygame.SRCALPHA)
    color = RANK_COLORS[min(rank, len(RANK_COLORS) - 1)]
    x0 = (w_px - W) / 2 * S
    y0 = (h_px - H) / 2 * S
    shapes = []
    for i in range(bars):
        oy = y0 + i * STEP * S
        shapes.append([(x0, oy + A * S), (x0 + W / 2 * S, oy), (x0 + W * S, oy + A * S),
                       (x0 + W * S, oy + (A + T) * S), (x0 + W / 2 * S, oy + T * S),
                       (x0, oy + (A + T) * S)])
    # 1px black outline: stamp each bar in black shifted 1px in 8 directions,
    # then lay the coloured bars on top (outlines first so bars never cover each other).
    r = 1.0 * S
    for pts in shapes:
        for dx, dy in ((-r, 0), (r, 0), (0, -r), (0, r), (-r, -r), (r, -r), (-r, r), (r, r)):
            pygame.draw.polygon(big, (0, 0, 0), [(x + dx, y + dy) for x, y in pts])
    for pts in shapes:
        pygame.draw.polygon(big, color, pts)
    badge = pygame.transform.smoothscale(big, (w_px, h_px))
    _RANK_BADGE_CACHE[rank] = badge
    return badge


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
        self.order_mode = None  # None, attack_move, or patrol
        self.patrol_points = []
        self.patrol_index = 0
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
        self._last_audio_gun_angle = 0.0
        self._vehicle_sound_timer = 0.0
        self._harvest_sound_timer = 0.0
        self._vehicle_path = []
        self._vehicle_path_goal = None
        self._vehicle_path_timer = 0.0
        self.cargo_units = []  # infantry/rocket units carried by an APC

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

    def load_infantry(self, player):
        """Load nearby friendly infantry into this APC, returning the count."""
        if self.kind != "apc" or not self.alive:
            return 0
        capacity = UNIT_DATA["apc"].get("transport_capacity", 0)
        room = max(0, capacity - len(self.cargo_units))
        if room <= 0:
            return 0
        candidates = [u for u in player.units
                      if u is not self and u.alive and u.kind in ("infantry", "rocket")
                      and dist(self.x, self.y, u.x, u.y) <= TILE * 2.2]
        candidates.sort(key=lambda u: dist(self.x, self.y, u.x, u.y))
        loaded = candidates[:room]
        for u in loaded:
            u.selected = False
            self.cargo_units.append(u)
            player.units.remove(u)
        return len(loaded)

    def unload_infantry(self, player, game_map, region=None):
        """Unload carried infantry onto nearby safe land.

        Each passenger tries every spot on widening rings around the APC, so a
        coastline or a building on one side no longer strands people aboard."""
        if self.kind != "apc" or not self.cargo_units:
            return 0
        placed, used = [], []
        dirs = [(0, -1), (1, 0), (0, 1), (-1, 0), (1, -1), (1, 1), (-1, 1), (-1, -1)]
        buildings = getattr(game_map, "game_buildings", [])
        for u in list(self.cargo_units):
            spot = None
            for ring in (1.25, 2.0, 2.75, 3.5):
                for dx, dy in dirs:
                    n = math.hypot(dx, dy) or 1.0
                    x = self.x + dx / n * ring * TILE
                    y = self.y + dy / n * ring * TILE
                    col, row = int(x // TILE), int(y // TILE)
                    if not game_map.in_bounds(col, row) or game_map.tiles[row][col] == TILE_WATER:
                        continue
                    if region is not None and game_map.region_at(col, row) != region:
                        continue          # only land on the intended landmass
                    if any(b.alive and b.rect.collidepoint(x, y) for b in buildings):
                        continue
                    if any(dist(x, y, ux, uy) < 14 for ux, uy in used):
                        continue
                    spot = (x, y)
                    break
                if spot:
                    break
            if spot is None:
                continue
            used.append(spot)
            u.x, u.y = spot
            u.target_pos = None
            u.target_entity = None
            player.units.append(u)
            placed.append(u)
        for u in placed:
            self.cargo_units.remove(u)
        return len(placed)

    def move_toward(self, tx, ty, dt):
        move_tx, move_ty = tx, ty
        followed_vehicle_path = False
        if CURRENT_MAP is not None and dist(self.x, self.y, tx, ty) > TILE * 1.5:
            goal_cell = (int(tx // TILE), int(ty // TILE))
            self._vehicle_path_timer -= dt
            if (self._vehicle_path_goal != goal_cell or self._vehicle_path_timer <= 0
                    or not self._vehicle_path):
                new_path = CURRENT_MAP.vehicle_path(self, (self.x, self.y), (tx, ty))
                if new_path is None:
                    # search budget used up this frame: keep following the old route
                    # (or wait a moment) and try again very soon
                    self._vehicle_path_timer = 0.05
                    if not self._vehicle_path:
                        return False
                else:
                    self._vehicle_path = new_path
                    self._vehicle_path_goal = goal_cell
                    self._vehicle_path_timer = 0.45 if self.kind in ("tank", "apc", "harvester") else 0.8
            had_vehicle_path = bool(self._vehicle_path)
            step_preview = effective_speed(self) * max(dt, 1 / FPS)
            while self._vehicle_path and dist(self.x, self.y, *self._vehicle_path[0]) <= max(8.0, step_preview * 1.25):
                self._vehicle_path.pop(0)
            if had_vehicle_path and not self._vehicle_path and dist(self.x, self.y, tx, ty) > 2:
                return True
            if self._vehicle_path:
                move_tx, move_ty = self._vehicle_path[0]
                followed_vehicle_path = True
        dx, dy = move_tx - self.x, move_ty - self.y
        d = math.hypot(dx, dy)
        if d < 2:
            return True
        self.heading = quantize_heading(math.atan2(dy, dx))
        if self.kind == "tank" and self.target_entity is None:
            self.gun_angle = self.heading
        if self.kind in ("tank", "apc", "harvester"):
            self._vehicle_sound_timer -= dt
            if self._vehicle_sound_timer <= 0:
                sound_name = {"harvester": "harvester_move", "tank": "tank_move", "apc": "apc_move"}[self.kind]
                play_sfx(sound_name, 0.20 if self.kind == "harvester" else 0.25)
                self._vehicle_sound_timer = 1.65
        step = effective_speed(self) * dt
        reached = step >= d
        nx, ny = (move_tx, move_ty) if reached else (self.x + dx / d * step, self.y + dy / d * step)
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
                if CURRENT_MAP.vehicle_cell_blocked(col, row, self):
                    self._vehicle_path = []
                    self._vehicle_path_timer = 0.0
                    return False
                for b in getattr(CURRENT_MAP, "game_buildings", []):
                    if b.alive and b.kind in WALL_DRAG_KINDS and b.owner.team != self.owner.team and b.rect.collidepoint(nx, ny):
                        self._vehicle_path = []
                        return False
        self.x, self.y = nx, ny
        if followed_vehicle_path and reached:
            return False
        return reached

    def draw(self, surf, camera):
        if not (camera.x - 30 <= self.x <= camera.x + VIEWPORT_W + 30 and
                camera.y - 30 <= self.y <= camera.y + VIEWPORT_H + 30):
            return
        px, py = camera.to_screen(self.x, self.y)
        px, py = int(px), int(py)
        color = self.owner.color
        on_building = any(b.alive and b.rect.collidepoint(self.x, self.y)
                          for b in getattr(CURRENT_MAP, "game_buildings", [])) if CURRENT_MAP is not None else False
        building_overlay_color = LIME_UNIT_COLOR if self.owner.color == PLAYER_COLOR else self.owner.color
        if on_building:
            color = building_overlay_color
        direction_index = _heading_direction_index(self.heading)
        directional = UNIT_DIRECTION_SPRITES.get(self.kind, {})
        ai_sprite = directional.get(direction_index)
        if ai_sprite is not None:
            # Vehicles and infantry use upright eight-way facings. The tank
            # hull never flips upside down; its gun remains independently aimed.
            if self.kind == "tank":
                if self.target_entity is not None:
                    tcx, tcy = get_center(self.target_entity)
                    tsx, tsy = camera.to_screen(tcx, tcy)
                    self.gun_angle = math.atan2(tsy - py, tsx - px)
                hull_source = _solid_sprite(ai_sprite, building_overlay_color) if on_building else ai_sprite
                hull_rect = hull_source.get_rect(center=(px, py))
                surf.blit(hull_source, hull_rect)
                if TANK_TURRET_SPRITE is not None:
                    turret_source = (_solid_sprite(TANK_TURRET_SPRITE, building_overlay_color)
                                     if on_building else TANK_TURRET_SPRITE)
                    turret_delta = (self.gun_angle - self._last_audio_gun_angle + math.pi) % (2 * math.pi) - math.pi
                    if abs(turret_delta) >= math.radians(7):
                        play_sfx("turret_rotate", 0.22)
                        self._last_audio_gun_angle = self.gun_angle
                    # The fresh hull is authored around a centered turret
                    # mount. Keep the turret circle locked to that center for
                    # every hull facing; rotating the old offset was the
                    # source of the detached/glitching diagonal composites.
                    pivot_screen = (px, py - 4)
                    turret_rotated = _rotate_tank_turret(
                        turret_source, self.gun_angle - TANK_TURRET_ART_ANGLE,
                        TANK_TURRET_PIVOT)
                    surf.blit(turret_rotated, turret_rotated.get_rect(center=pivot_screen))
                    if TANK_GUN_SPRITE is not None:
                        gun_source = (_solid_sprite(TANK_GUN_SPRITE, building_overlay_color)
                                      if on_building else TANK_GUN_SPRITE)
                        gun_rotated = _rotate_tank_turret(
                            gun_source, self.gun_angle - TANK_TURRET_ART_ANGLE,
                            TANK_TURRET_PIVOT)
                        surf.blit(gun_rotated, gun_rotated.get_rect(center=pivot_screen))
                else:
                    # Defensive fallback for an unavailable source layer.
                    surf.blit(hull_source, hull_rect)
            else:
                sprite_source = _solid_sprite(ai_sprite, building_overlay_color) if on_building else ai_sprite
                surf.blit(sprite_source, sprite_source.get_rect(center=(px, py)))
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
        if self.kind == "apc":
            cargo = len(self.cargo_units)
            badge = FONT_TINY.render(f"{cargo}/{UNIT_DATA['apc']['transport_capacity']}", True, (245, 245, 220))
            badge_bg = pygame.Surface((badge.get_width() + 4, badge.get_height() + 2), pygame.SRCALPHA)
            badge_bg.fill((20, 30, 25, 190))
            surf.blit(badge_bg, (px - badge.get_width() // 2 - 2, py + self.radius + 3))
            surf.blit(badge, (px - badge.get_width() // 2, py + self.radius + 4))
        if self.kind == "harvester" and self.state == "harvesting":
            cap = max(1.0, harvester_capacity(self.owner))
            pct = max(0.0, min(1.0, self.cargo / cap))
            bar_w, bar_h = 38, 5
            bar_x = px - bar_w // 2
            bar_y = py + self.radius + 4
            pygame.draw.rect(surf, (28, 25, 18), (bar_x, bar_y, bar_w, bar_h))
            fill = round(bar_w * pct)
            if fill:
                bar_color = {
                    TILE_TRAINIUM: (90, 220, 100), TILE_RADIOACTIVE: (90, 220, 100),
                    TILE_ORE: (155, 165, 180), TILE_TREE: (210, 170, 55),
                }.get(self.cargo_kind, (225, 195, 65))
                pygame.draw.rect(surf, bar_color, (bar_x, bar_y, fill, bar_h))
            pygame.draw.rect(surf, (235, 225, 170), (bar_x, bar_y, bar_w, bar_h), 1)
        top = py - self.radius - 10
        # Rank insignia (Rookie 1 yellow, Veteran 2 lime, Elite 3 orange chevrons)
        # sits to the LEFT of the health bar, centred on it.
        badge = _rank_badge(self.rank)
        surf.blit(badge, badge.get_rect(center=(px - 14 - 3 - badge.get_width() // 2, top + 2)))
        draw_health_bar(surf, px - 14, top, 28, 4, self.hp, effective_max_hp(self))
        # owner colour pip: tells allies from enemies at a glance, whatever colours were picked
        pip = pygame.Rect(px + 14 + 3, top - 1, 6, 6)
        pygame.draw.rect(surf, (0, 0, 0), pip.inflate(2, 2))
        pygame.draw.rect(surf, self.owner.color, pip)


FORMATION_MODES = ("auto", "line", "box", "row")
FORMATION_LABELS = {"auto": "Auto", "line": "Line", "box": "Box", "row": "Row"}


def _formation_layout(mode, n):
    """n slots as (forward, lateral) in spacing units, centred on (0, 0).

    forward  > 0 : toward the direction of travel
    lateral  > 0 : to the right of the direction of travel
    auto : a line for small groups, a box for bigger ones
    line : units abreast, side by side, perpendicular to travel
    box  : a compact grid
    row  : single file in the direction of travel
    """
    if n <= 1:
        return [(0.0, 0.0)] * n
    if mode == "auto":
        mode = "line" if n <= 3 else "box"
    slots = []
    if mode == "row":
        per_file = 10
        files = math.ceil(n / per_file)
        for k in range(n):
            f, idx = divmod(k, per_file)
            count = min(per_file, n - f * per_file)
            slots.append(((count - 1) / 2 - idx, f - (files - 1) / 2))
        return slots
    per_rank = 12 if mode == "line" else max(2, math.ceil(math.sqrt(n)))
    ranks = math.ceil(n / per_rank)
    for k in range(n):
        r, c = divmod(k, per_rank)
        count = min(per_rank, n - r * per_rank)
        slots.append(((ranks - 1) / 2 - r, c - (count - 1) / 2))
    return slots


def _draw_formation_icon(surf, mode, center):
    """Tiny dot-pattern icon for the formation buttons."""
    patterns = {
        "auto": [(-4, -3), (4, -3), (0, 0), (-4, 3), (4, 3)],
        "line": [(-6, 0), (-2, 0), (2, 0), (6, 0)],
        "box":  [(-4, -3), (0, -3), (4, -3), (-4, 3), (0, 3), (4, 3)],
        "row":  [(0, -6), (0, -2), (0, 2), (0, 6)],
    }
    for ox, oy in patterns[mode]:
        pygame.draw.circle(surf, (205, 235, 205), (center[0] + ox, center[1] + oy), 2)


class GroundTarget:
    """A bare map point used as the target of a manually aimed nuke."""
    alive = True
    owner = None

    def __init__(self, x, y):
        self.x, self.y = x, y

    def take_damage(self, dmg):
        pass


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
        self.nuke_phase = "ascent" if kind == "nuke" else None
        self.nuke_phase_age = 0.0
        self.nuke_altitude = 0.0
        self.nuke_origin = (float(x), float(y))
        self.nuke_cruise_elapsed = 0.0
        self.nuke_cruise_duration = 0.0
        if kind == "nuke" and target is not None:
            tx, ty = get_center(target)
            self.nuke_cruise_duration = max(0.55, dist(x, y, tx, ty) / self.speed)

    def _detonate_nuke(self, game, tx, ty):
        was_alive = getattr(self.target, "alive", False)
        if was_alive:
            self.target.take_damage(self.damage)
        game.explosions.append({"x": tx, "y": ty, "radius": NUKE_BLAST_RADIUS, "age": 0.0,
                                "max_age": NUKE_CLOUD_DURATION, "color": (180, 255, 80)})
        ground = isinstance(self.target, GroundTarget)
        for player in game.players:
            for entity in player.units + player.buildings:
                if entity is self.target or not getattr(entity, "alive", False):
                    continue
                ex, ey = get_center(entity)
                distance = dist(tx, ty, ex, ey)
                if distance <= NUKE_BLAST_RADIUS:
                    damage = (self.damage * (1 - 0.45 * distance / NUKE_BLAST_RADIUS)
                              if ground else self.damage * 0.55)
                    entity.take_damage(damage)
        game.fallout_zones.append({"x": tx, "y": ty, "radius": NUKE_FALLOUT_RADIUS,
                                   "age": 0.0, "max_age": NUKE_FALLOUT_DURATION,
                                   "tick_timer": 0.0, "damage": NUKE_FALLOUT_DAMAGE})
        target_owner = getattr(self.target, "owner", None)
        if (was_alive and not self.target.alive and self.shooter is not None
                and not (isinstance(self.target, Building) and target_owner is self.owner)):
            game.register_kill(self.shooter)
        self.alive = False

    def _update_nuke(self, dt, game):
        if not getattr(self.target, "alive", False):
            self.alive = False
            return
        self.nuke_phase_age += dt
        tx, ty = get_center(self.target)
        if self.nuke_phase == "ascent":
            progress = min(1.0, self.nuke_phase_age / NUKE_ASCENT_TIME)
            self.x, self.y = self.nuke_origin
            self.nuke_altitude = NUKE_LAUNCH_ALTITUDE * progress
            if progress >= 1.0:
                self.nuke_phase = "cruise"
                self.nuke_phase_age = 0.0
                self.nuke_altitude = NUKE_LAUNCH_ALTITUDE
        elif self.nuke_phase == "cruise":
            self.nuke_cruise_elapsed += dt
            progress = min(1.0, self.nuke_cruise_elapsed / self.nuke_cruise_duration)
            self.x = self.nuke_origin[0] + (tx - self.nuke_origin[0]) * progress
            self.y = self.nuke_origin[1] + (ty - self.nuke_origin[1]) * progress
            self.nuke_altitude = NUKE_LAUNCH_ALTITUDE
            if progress >= 1.0:
                self.nuke_phase = "descent"
                self.nuke_phase_age = 0.0
                self.x, self.y = tx, ty
        else:
            progress = min(1.0, self.nuke_phase_age / NUKE_DESCENT_TIME)
            self.x, self.y = tx, ty
            self.nuke_altitude = NUKE_LAUNCH_ALTITUDE * (1.0 - progress)
            if progress >= 1.0:
                self._detonate_nuke(game, tx, ty)

    def update(self, dt, game):
        self.age += dt
        if self.kind == "nuke":
            self._update_nuke(dt, game)
            return
        if not getattr(self.target, "alive", False):
            self.alive = False
            return
        tx, ty = get_center(self.target)
        dx, dy = tx - self.x, ty - self.y
        d = math.hypot(dx, dy)
        hit_radius = 14 if self.kind == "rocket" else 10
        step = self.speed * dt
        if d <= hit_radius or step >= d or self.age > 4.0:
            was_alive = self.target.alive
            self.target.take_damage(self.damage)
            if self.kind in ("shell", "rocket", "nuke"):
                radius = 150 if self.kind == "nuke" else (30 if self.kind == "shell" else 34)
                game.explosions.append({"x": tx, "y": ty, "radius": radius, "age": 0.0,
                                        "max_age": EXPLOSION_LIFETIME,
                                        "color": (180, 255, 80) if self.kind == "nuke" else
                                                  ((255, 115, 35) if self.kind == "shell" else (255, 150, 50))})
                if self.kind == "nuke":
                    ground = isinstance(self.target, GroundTarget)
                    for p in game.players:
                        for e in p.units + p.buildings:
                            if e is not self.target and getattr(e, "alive", False):
                                ex, ey = get_center(e)
                                d_e = dist(tx, ty, ex, ey)
                                if d_e <= radius:
                                    # manual strike: full damage at ground zero, fading to 55% at the edge
                                    dmg = (self.damage * (1 - 0.45 * d_e / radius)) if ground else self.damage * 0.55
                                    e.take_damage(dmg)
            tgt_owner = getattr(self.target, "owner", None)
            if (was_alive and not self.target.alive and self.shooter is not None
                    and not (isinstance(self.target, Building) and tgt_owner is self.owner)):
                game.register_kill(self.shooter)
            self.alive = False
            return
        if step >= d:
            self.x, self.y = tx, ty
        else:
            self.x += dx / d * step
            self.y += dy / d * step

    def draw(self, surf, camera):
        sx, sy = camera.to_screen(self.x, self.y)
        sx, sy = int(sx), int(sy)
        if self.kind == "nuke":
            if self.nuke_phase in ("ascent", "descent") and NUKE_WARHEAD_SPRITE is not None:
                warhead = NUKE_WARHEAD_SPRITE
                if self.nuke_phase == "descent":
                    warhead = pygame.transform.rotate(warhead, 180)
                sy -= int(self.nuke_altitude)
                surf.blit(warhead, warhead.get_rect(center=(sx, sy)))
            return  # the missile vanishes during its high-altitude crossing
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
    def __init__(self, name, color, is_ai, corner, is_remote=False, team=0, slot=0):
        self.name = name
        self.color = color
        self.team = team
        self.slot = slot
        self.eliminated = False
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

    def cancel_production(self, kind, all_items=False):
        """Cancel the last queued item of this kind (or every one of that kind
        when all_items is set) and refund its cost."""
        if kind not in BUILD_DATA and kind not in UNIT_DATA and kind not in UPGRADE_DATA:
            return False
        cat = self.category_of(kind)
        cancelled = False
        for i in range(len(self.queues[cat]) - 1, -1, -1):
            if self.queues[cat][i]["kind"] == kind:
                self.queues[cat].pop(i)
                cost = get_data(kind)["cost"]
                self.credits += cost.get("credits", 0)
                self.wood += cost.get("wood", 0)
                self.metal += cost.get("metal", 0)
                cancelled = True
                if not all_items:
                    return True
        return cancelled

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
# Fuzzy logic + strategic AI
# ---------------------------------------------------------------------------
def fz_low(x, a, b):
    """Membership: 1 at/below a, falling linearly to 0 at b."""
    if x <= a:
        return 1.0
    if x >= b:
        return 0.0
    return (b - x) / (b - a)


def fz_high(x, a, b):
    """Membership: 0 at/below a, rising linearly to 1 at b."""
    return 1.0 - fz_low(x, a, b)


def fz_tri(x, a, b, c):
    """Triangular membership peaking at b."""
    if x <= a or x >= c:
        return 0.0
    if x == b:
        return 1.0
    return (x - a) / (b - a) if x < b else (c - x) / (c - b)


AI_COMBAT_KINDS = ("infantry", "rocket", "tank")


class AIBrain:
    """The skirmish opponent.

    * Fuzzy logic (assess) turns raw numbers - cash, threat near the base,
      army strength vs. the enemy, game phase - into graded priorities
      (aggression / defence / offence / economy / tech) instead of hard
      if-else thresholds.
    * A strategic build planner keeps a balanced base (economy, production,
      tech, defences), remembers its peak composition and rebuilds anything
      that gets destroyed.
    * Armies assemble at a staging point, then advance waypoint by waypoint
      along an A* route, waiting for stragglers so they arrive together.
    * When the enemy sits on a different landmass (rivers / lakes cut the
      ground route) it builds APCs, ferries infantry across the water and
      lands them beside the target.
    """

    TRACKED = ("power", "refinery", "barracks", "factory", "research",
               "turret", "rockettower", "mgtower")
    PEAK_CAP = {"power": 6, "refinery": 3, "barracks": 3, "factory": 3, "research": 1,
                "turret": 8, "rockettower": 6, "mgtower": 6}
    DEFENSE_MIX = ("turret", "rockettower", "mgtower")
    TARGET_WEIGHT = {"yard": 2.2, "refinery": 1.7, "power": 1.5, "factory": 1.4,
                     "barracks": 1.2, "research": 1.0, "turret": 0.7,
                     "rockettower": 0.7, "mgtower": 0.6, "nuke_silo": 1.8}
    MAX_ARMY = 48

    def __init__(self, game, player):
        self.g = game
        self.p = player
        self.rng = random.Random(7)
        self.assess_t = 0.0
        self.macro_t = 0.0
        self.army_t = 0.0
        self.peak = {}
        self.fz = {"aggression": 0.2, "defense": 0.4, "offense": 0.5, "economy": 0.9,
                   "tech": 0.1, "threat": 0.0, "strength": 0.0}
        self.rally = None
        self.army = None            # active strike force
        self.op = None              # active APC airlift
        self.island = False         # enemy is across water -> needs APCs
        self.saving_for = 0
        self.threat_pos = None
        self.threat_value = 0.0
        self.ally_threat_pos = None
        self.ally_threat_value = 0.0
        self.last_defend = -99.0
        self.last_wave_end = 0.0
        self.caution = 1.0          # grows after failed assaults so the next wave is bigger
        self.log = []
        self.stats = {"waves": 0, "airlifts": 0, "rebuilt": 0, "landed": 0}

    # ---- small helpers ------------------------------------------------
    def note(self, text):
        self.log.append((round(self.g.elapsed, 1), text))
        del self.log[:-80]

    def minutes(self):
        return self.g.elapsed / 60.0

    def enemies(self):
        return self.g.enemies_of(self.p)

    def allies(self):
        return self.g.allies_of(self.p)

    def enemy(self):
        """The enemy player this team is currently focusing on.

        Chosen by distance from the team's centre of gravity, so every AI on
        the same side picks the same victim and their waves arrive together."""
        foes = self.enemies()
        if not foes:
            return self.p
        mates = [self.p] + self.allies()
        pts = []
        for m_ in mates:
            y = m_.buildings_of("yard")
            pts.append(y[0].center if y else ((m_.corner[0] + 0.5) * TILE, (m_.corner[1] + 0.5) * TILE))
        cx = sum(x for x, _ in pts) / len(pts)
        cy = sum(y for _, y in pts) / len(pts)

        def key(q):
            y = q.buildings_of("yard")
            qx, qy = y[0].center if y else ((q.corner[0] + 0.5) * TILE, (q.corner[1] + 0.5) * TILE)
            return dist(cx, cy, qx, qy)
        return min(foes, key=key)

    def home_building(self):
        yards = self.p.buildings_of("yard")
        if yards:
            return yards[0]
        alive = [b for b in self.p.buildings if b.alive]
        return alive[0] if alive else None

    def home_xy(self):
        b = self.home_building()
        if b is not None:
            return b.center
        cx, cy = self.p.corner
        return ((cx + 0.5) * TILE, (cy + 0.5) * TILE)

    def enemy_xy(self):
        e = self.enemy()
        pool = e.buildings_of("yard") or [b for b in e.buildings if b.alive]
        if pool:
            return pool[0].center
        cx, cy = e.corner
        return ((cx + 0.5) * TILE, (cy + 0.5) * TILE)

    @staticmethod
    def cell(xy):
        return (int(xy[0] // TILE), int(xy[1] // TILE))

    def uvalue(self, u):
        base = UNIT_DATA[u.kind]["cost"].get("credits", 0)
        if u.kind == "apc":
            base *= 0.5
        mh = effective_max_hp(u) or 1
        return base * (0.5 + 0.5 * clamp(u.hp / mh, 0.0, 1.0)) * (1 + 0.25 * u.rank)

    @staticmethod
    def svalue(b):
        c = BUILD_DATA[b.kind]["cost"]
        return c.get("credits", 0) + 0.8 * c.get("metal", 0)

    def combat_units(self):
        return [u for u in self.p.units if u.alive and u.kind in AI_COMBAT_KINDS]

    def busy_ids(self):
        ids = set()
        if self.op:
            ids.update(self.op["apcs"])
            ids.update(self.op["pax"])
        return ids

    def enemy_value_near(self, x, y, radius):
        v = 0.0
        for e in self.enemies():
            for u in e.units:
                if u.alive and u.kind in AI_COMBAT_KINDS and dist(u.x, u.y, x, y) <= radius:
                    v += self.uvalue(u)
            for b in e.buildings:
                if b.alive and b.kind in DEFENSE_KINDS:
                    bx, by = b.center
                    if dist(bx, by, x, y) <= radius:
                        v += self.svalue(b)
        return v

    # ---- rally / geography ---------------------------------------------
    def compute_rally(self):
        hx, hy = self.home_xy()
        ex, ey = self.enemy_xy()
        d = dist(hx, hy, ex, ey) or 1.0
        ux, uy = (ex - hx) / d, (ey - hy) / d
        m = self.g.map
        home_region = m.region_at(*self.cell((hx, hy)))
        for tiles in (13, 11, 9, 7, 5, 3):
            x, y = hx + ux * tiles * TILE, hy + uy * tiles * TILE
            c = self.cell((x, y))
            if m.in_bounds(*c) and m.tiles[c[1]][c[0]] != TILE_WATER and m.region_at(*c) == home_region:
                return (x, y)
        return (hx, hy + 3 * TILE)

    # ---- fuzzy assessment ------------------------------------------------
    def assess(self):
        g, p = self.g, self.p
        foes = self.enemies()
        m = self.minutes()
        hx, hy = self.home_xy()
        near_r = 24 * TILE
        mine = [b for b in p.buildings if b.alive]
        allied_bld = [b for a in self.allies() for b in a.buildings if b.alive]

        # threat: enemy combat units close to any of our buildings (and, separately, our allies')
        t_units, ally_t = [], []
        for e in foes:
            for u in e.units:
                if not (u.alive and u.kind in AI_COMBAT_KINDS):
                    continue
                hit = False
                for b in mine:
                    bx, by = b.center
                    if abs(u.x - bx) < near_r and abs(u.y - by) < near_r and dist(u.x, u.y, bx, by) < near_r:
                        t_units.append(u)
                        hit = True
                        break
                if not hit:
                    for b in allied_bld:
                        bx, by = b.center
                        if abs(u.x - bx) < near_r and abs(u.y - by) < near_r and dist(u.x, u.y, bx, by) < near_r:
                            ally_t.append(u)
                            break
        self.ally_threat_pos = ((sum(u.x for u in ally_t) / len(ally_t), sum(u.y for u in ally_t) / len(ally_t))
                                if ally_t else None)
        self.ally_threat_value = sum(self.uvalue(u) for u in ally_t)
        self.threat_value = sum(self.uvalue(u) for u in t_units)
        if t_units:
            self.threat_pos = (sum(u.x for u in t_units) / len(t_units),
                               sum(u.y for u in t_units) / len(t_units))
        else:
            self.threat_pos = None

        own_def = sum(self.svalue(b) for b in mine if b.kind in DEFENSE_KINDS and b.kind != "nuke_silo")
        units = self.combat_units()
        ally_army = sum(self.uvalue(u) for a in self.allies() for u in a.units
                        if u.alive and u.kind in AI_COMBAT_KINDS)
        army_val = sum(self.uvalue(u) for u in units) + 0.5 * ally_army     # allies fight beside us
        home_val = sum(self.uvalue(u) for u in units if dist(u.x, u.y, hx, hy) < near_r)
        t = self.threat_value / (own_def * 0.8 + home_val + 250.0)

        noise = 1.0 + self.rng.uniform(-0.12, 0.12)         # imperfect scouting
        # only the focused enemy counts in full; the rest weigh in at a third (they are further away)
        focus = self.enemy()
        e_army = e_def = 0.0
        for e in foes:
            w = 1.0 if e is focus else 0.33
            e_army += w * sum(self.uvalue(u) for u in e.units if u.alive and u.kind in AI_COMBAT_KINDS)
            e_def += w * sum(self.svalue(b) for b in e.buildings if b.alive and b.kind in DEFENSE_KINDS)
        e_army *= noise
        s = army_val / (e_army * 0.8 + e_def * 0.35 + 300.0)

        harv = sum(1 for u in p.units if u.alive and u.kind == "harvester")
        want_h = clamp(len(p.buildings_of("refinery")) * 2, 2, 6)
        h_ratio = harv / float(want_h)
        cash = p.credits

        th_low, th_med, th_high = fz_low(t, 0.25, 0.9), fz_tri(t, 0.5, 1.0, 1.7), fz_high(t, 1.2, 2.2)
        st_weak, st_even, st_strong = fz_low(s, 0.6, 1.0), fz_tri(s, 0.7, 1.1, 1.7), fz_high(s, 1.3, 2.1)
        cash_low, cash_high = fz_low(cash, 300, 1300), fz_high(cash, 2500, 6000)
        early, mid, late = fz_low(m, 2.5, 6.0), fz_tri(m, 4.0, 9.0, 16.0), fz_high(m, 12.0, 20.0)
        harv_low = fz_low(h_ratio, 0.5, 1.0)

        # Sugeno rules: strength -> (aggression, defence, offence, economy, tech)
        rules = [
            (th_high,                 (0.05, 0.95, 0.45, 0.15, 0.05)),
            (th_med,                  (0.25, 0.65, 0.60, 0.35, 0.25)),
            (min(th_low, st_strong),  (0.90, 0.20, 0.85, 0.35, 0.35)),
            (min(th_low, st_even),    (0.55, 0.35, 0.80, 0.45, 0.45)),
            (min(th_low, st_weak),    (0.15, 0.50, 0.90, 0.45, 0.30)),
            (early,                   (0.10, 0.40, 0.40, 0.95, 0.05)),
            (min(mid, cash_high),     (0.65, 0.40, 0.80, 0.45, 0.75)),
            (min(late, cash_high),    (0.85, 0.40, 0.90, 0.35, 0.85)),
            (cash_low,                (0.30, 0.30, 0.30, 0.90, 0.05)),
            (harv_low,                (0.20, 0.30, 0.30, 1.00, 0.00)),
        ]
        den = sum(w for w, _ in rules) or 1.0
        out = [sum(w * o[i] for w, o in rules) / den for i in range(5)]
        self.fz = {"aggression": out[0], "defense": out[1], "offense": out[2],
                   "economy": out[3], "tech": out[4], "threat": t, "strength": s}
        self.rally = self.compute_rally()

        # is the enemy base across water?  (decides APC production)
        hr = g.map.region_at(*self.cell((hx, hy)))
        er = g.map.region_at(*self.cell(self.enemy_xy()))
        self.island = (hr != er and hr >= 0 and er >= 0)

    # ---- main entry ---------------------------------------------------------
    def update(self, dt):
        if not self.p.buildings_of("yard") and not any(b.alive for b in self.p.buildings):
            return
        self.assess_t -= dt
        if self.assess_t <= 0:
            self.assess_t = 0.6
            self.assess()
        self.macro_t -= dt
        if self.macro_t <= 0:
            self.macro_t = 1.0
            self.track_peaks()
            self.plan_buildings()
            self.produce_units()
            self.do_research()
        self.army_t -= dt
        if self.army_t <= 0:
            self.army_t = 0.6
            self.army_tick()

    # ---- base building --------------------------------------------------------
    def track_peaks(self):
        for kind in self.TRACKED:
            n = len(self.p.buildings_of(kind))
            old = self.peak.get(kind, 0)
            if n > old:
                self.peak[kind] = n
            elif n < old and not getattr(self, "_flag_" + kind, False):
                self.note("lost %s (%d -> %d): will rebuild" % (kind, old, n))
                setattr(self, "_flag_" + kind, True)
            if n >= old:
                setattr(self, "_flag_" + kind, False)

    def queued(self, kind):
        return sum(1 for it in self.p.queues["building"] if it["kind"] == kind)

    def have(self, kind):
        return len(self.p.buildings_of(kind)) + self.queued(kind)

    def enemy_mix(self):
        t = sum(1 for e in self.enemies() for u in e.units if u.alive and u.kind == "tank")
        i = sum(1 for e in self.enemies() for u in e.units if u.alive and u.kind in ("infantry", "rocket"))
        tot = t + i
        if tot < 3:
            return 0.0, 0.0
        return t / float(tot), i / float(tot)

    def pick_defense_kind(self):
        tank_f, inf_f = self.enemy_mix()
        share = {"turret": 0.40, "rockettower": 0.30, "mgtower": 0.30}
        if tank_f > 0.55:
            share["rockettower"] += 0.20
            share["mgtower"] -= 0.20
        if inf_f > 0.55:
            share["mgtower"] += 0.25
            share["rockettower"] -= 0.15
            share["turret"] -= 0.10
        counts = {k: self.have(k) for k in self.DEFENSE_MIX}
        total = float(sum(counts.values())) or 1.0
        ranked = sorted(self.DEFENSE_MIX, key=lambda k: -(share[k] - counts[k] / total))
        for k in ranked:
            if self.p.can_start(k):
                return k
        return ranked[0]

    def plan_buildings(self):
        p = self.p
        if p.queues["building"] or p.pending_placement is not None:
            return
        m = self.minutes()
        fz = self.fz
        cash = p.credits
        needs = []

        margin = p.power_produced() - p.power_used()
        if margin < 30:
            needs.append((100 if (margin < 0 or not p.has_building("power")) else 92, "power"))

        want_ref = 1 + (1 if (m > 2.0 or cash > 2600) else 0) + (1 if (m > 7 and fz["economy"] > 0.4) else 0)
        surplus = int(clamp((cash - 3000) / 4000.0, 0, 2))      # idle cash -> more production lines
        want_bar = min(3, 1 + (1 if (m > 4 and cash > 1500) else 0) + surplus)
        want_fac = min(3, 1 + (1 if (m > 6 and cash > 3000) else 0) + surplus)
        want_res = 1 if m > 1.5 else 0
        wants = {"refinery": (want_ref, 96, 72), "barracks": (want_bar, 90, 52),
                 "factory": (want_fac, 88, 54), "research": (want_res, 62, 62)}
        for kind, (want, pri_first, pri_more) in wants.items():
            want = max(want, min(self.peak.get(kind, 0), self.PEAK_CAP[kind]))   # replenish
            have = self.have(kind)
            if have < want:
                needs.append((pri_first if len(p.buildings_of(kind)) == 0 else pri_more, kind))
        if self.have("power") < min(self.peak.get("power", 0), self.PEAK_CAP["power"]) and margin < 80:
            needs.append((70, "power"))

        # defences: scaled by fuzzy defence need and game time, never below the old peak
        nd = int(round(2 + 7 * fz["defense"] + m * 0.35 + clamp(cash / 4000.0, 0, 4)))
        nd = min(nd, 18)
        peak_def = sum(min(self.peak.get(k, 0), self.PEAK_CAP[k]) for k in self.DEFENSE_MIX)
        cur_def = sum(self.have(k) for k in self.DEFENSE_MIX)
        if cur_def < max(nd, peak_def) and m > 0.6:
            pri = 50 + 40 * fz["defense"] + (30 if self.threat_value > 0 else 0)
            needs.append((pri, self.pick_defense_kind()))

        if (m > 13 and cash > 6500 and p.metal >= 1200 and fz["aggression"] > 0.4
                and not p.buildings_of("nuke_silo") and not self.queued("nuke_silo")):
            needs.append((30, "nuke_silo"))

        needs.sort(key=lambda n: -n[0])
        self.saving_for = 0
        for pri, kind in needs:
            if p.can_start(kind):
                if len(p.buildings_of(kind)) < self.peak.get(kind, 0):
                    self.stats["rebuilt"] += 1
                    self.note("rebuilding %s" % kind)
                p.start_production(kind)
                return
            if pri >= 85:      # critical and unaffordable: stop spending elsewhere and save up
                self.saving_for = BUILD_DATA[kind]["cost"].get("credits", 0)
                return

    # ---- unit production ----------------------------------------------------------
    def pick_infantry_kind(self):
        tank_f, inf_f = self.enemy_mix()
        share = {"infantry": 0.55, "rocket": 0.45} if self.island else {"infantry": 0.45, "rocket": 0.55}
        if tank_f > 0.55:
            share["rocket"] += 0.2
            share["infantry"] -= 0.2
        elif inf_f > 0.55:
            share["infantry"] += 0.2
            share["rocket"] -= 0.2
        queued = {k: sum(1 for it in self.p.queues["infantry"] if it["kind"] == k) for k in share}
        cnt = {k: sum(1 for u in self.p.units if u.alive and u.kind == k) + queued[k] for k in share}
        total = float(sum(cnt.values())) or 1.0
        return max(share, key=lambda k: share[k] - cnt[k] / total)

    def pick_vehicle_kind(self):
        units = self.p.units
        tanks = sum(1 for u in units if u.alive and u.kind == "tank") + \
            sum(1 for it in self.p.queues["vehicle"] if it["kind"] == "tank")
        apcs = sum(1 for u in units if u.alive and u.kind == "apc") + \
            sum(1 for it in self.p.queues["vehicle"] if it["kind"] == "apc")
        foot = sum(1 for u in units if u.alive and u.kind in ("infantry", "rocket"))
        if self.island:
            need_apc = min(5, int(math.ceil(max(foot, 4) / 5.0)))
            if apcs < need_apc and (foot >= 3 or apcs == 0):
                return "apc"
            return "tank" if tanks < 4 else None
        return "tank"

    def produce_units(self):
        p = self.p
        reserve = self.saving_for or 250
        if len(self.combat_units()) >= self.MAX_ARMY:
            return
        # harvesters: keep the economy running and replace losses immediately
        if p.has_building("factory"):
            harv = sum(1 for u in p.units if u.alive and u.kind == "harvester")
            qh = sum(1 for it in p.queues["vehicle"] if it["kind"] == "harvester")
            want_h = int(clamp(len(p.buildings_of("refinery")) * 2, 2, 6))
            cost = UNIT_DATA["harvester"]["cost"].get("credits", 0)
            if harv + qh < want_h and len(p.queues["vehicle"]) < 2 and p.can_start("harvester"):
                if harv < 2 or p.credits - cost >= reserve:
                    p.start_production("harvester")
        rich = p.credits > 2500
        if p.has_building("factory") and len(p.queues["vehicle"]) < (2 if rich else 1):
            kind = self.pick_vehicle_kind()
            if kind and p.can_start(kind) and p.credits - UNIT_DATA[kind]["cost"].get("credits", 0) >= reserve:
                p.start_production(kind)
        if p.has_building("barracks") and len(p.queues["infantry"]) < (2 if rich else 1):
            kind = self.pick_infantry_kind()
            if p.can_start(kind) and p.credits - UNIT_DATA[kind]["cost"].get("credits", 0) >= reserve:
                p.start_production(kind)

    def do_research(self):
        p = self.p
        if not p.has_building("research") or p.queues["research"]:
            return
        fz = self.fz
        best, best_score = None, -1.0
        for kind, d in UPGRADE_DATA.items():
            if kind == "fortified_walls" or not p.can_start(kind):
                continue
            cost = d["cost"].get("credits", 0)
            if p.credits - cost < 700:
                continue
            branch_w = {0: fz["economy"], 1: fz["defense"], 2: fz["offense"]}.get(d.get("branch", 3), 0.3)
            score = branch_w + 0.15 * fz["tech"] - 0.08 * d.get("tier", 0) + self.rng.uniform(0, 0.05)
            if score > best_score:
                best, best_score = kind, score
        if best:
            p.start_production(best)

    # ---- structure placement ---------------------------------------------------------
    def place(self, kind):
        """Pick a sensible spot for a finished structure (called on completion)."""
        g, p = self.g, self.p
        w, h = _building_tile_size(kind)
        hx, hy = self.home_xy()
        hcx, hcy = hx / TILE, hy / TILE
        ex, ey = self.enemy_xy()
        d = dist(hcx, hcy, ex / TILE, ey / TILE) or 1.0
        ux, uy = (ex / TILE - hcx) / d, (ey / TILE - hcy) / d
        defenders = [b for b in p.buildings if b.alive and b.kind in DEFENSE_KINDS]
        res_c = None
        if kind == "refinery":
            pts = [(c + 0.5, r + 0.5)
                   for r in range(max(0, int(hcy) - 30), min(g.map.rows, int(hcy) + 31))
                   for c in range(max(0, int(hcx) - 30), min(g.map.cols, int(hcx) + 31))
                   if g.map.tiles[r][c] in RESOURCE_TILE_TYPES]
            if pts:
                res_c = (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
        best, best_s = None, None
        R = 22
        for row in range(int(hcy) - R, int(hcy) + R + 1):
            for col in range(int(hcx) - R, int(hcx) + R + 1):
                if not g.can_place(p, kind, col, row):
                    continue
                cx, cy = col + w / 2.0, row + h / 2.0
                rx, ry = cx - hcx, cy - hcy
                fwd = rx * ux + ry * uy
                lat = -rx * uy + ry * ux
                dd = math.hypot(rx, ry)
                if kind == "nuke_silo":
                    score = -0.5 * dd - 0.6 * fwd
                elif kind in DEFENSE_KINDS:
                    score = -abs(fwd - 10.0) - 0.35 * abs(lat)
                    for o in defenders:
                        od = math.hypot(cx - (o.col + o.w / 2.0), cy - (o.row + o.h / 2.0))
                        if od < 4:
                            score -= (4 - od) * 2.0
                elif kind == "refinery" and res_c is not None:
                    score = -0.8 * math.hypot(cx - res_c[0], cy - res_c[1]) - 0.2 * dd
                else:
                    score = -dd - 0.4 * max(0.0, fwd)
                score += self.rng.uniform(0, 0.5)
                if best_s is None or score > best_s:
                    best, best_s = (col, row), score
        if best is None:
            cost = BUILD_DATA[kind]["cost"]
            p.credits += cost.get("credits", 0)
            p.wood += cost.get("wood", 0)
            p.metal += cost.get("metal", 0)
            return False
        g.place_building(p, kind, best[0], best[1])
        return True

    # ---- army ------------------------------------------------------------------------------
    def army_tick(self):
        g, p = self.g, self.p
        units = self.combat_units()
        busy = self.busy_ids()
        free = [u for u in units if u.id not in busy]

        # 1. defend the base - always has priority
        if self.threat_pos is not None and self.threat_value > 0:
            self.defend(free)
        elif (getattr(self, "ally_threat_pos", None) is not None and self.ally_threat_value > 600
              and self.g.elapsed - self.last_defend > 6.0):
            # an ally is being attacked and we are quiet: send about half of the idle units to help
            self.last_defend = self.g.elapsed
            ax, ay = self.ally_threat_pos
            helpers = [u for u in free if dist(u.x, u.y, ax, ay) > 4 * TILE][: max(1, len(free) // 2)]
            if helpers and dist(*self.home_xy(), ax, ay) < 60 * TILE:
                self.g._apply_attack_move_order(helpers, ax, ay, "auto")
                self.note("sending %d units to help an ally" % len(helpers))

        # 2. airlift in progress
        if self.op:
            self.op_tick()
        # 3. strike force in progress
        if self.army:
            self.advance_army()

        # 4. assemble idle units at the staging point
        army_ids = set(self.army["ids"]) if self.army else set()
        self.assemble([u for u in free if u.id not in army_ids])
        for apc in [u for u in p.units if u.alive and u.kind == "apc" and u.id not in busy]:
            if (apc.target_pos is None and apc.order_mode is None
                    and dist(apc.x, apc.y, *self.rally) > 8 * TILE):
                apc.target_pos = (self.rally[0] + self.rng.uniform(-30, 30),
                                  self.rally[1] + self.rng.uniform(-30, 30))

        # 5. decide whether to launch a new operation
        if not self.army and not self.op:
            self.consider_attack(free)

    def defend(self, free):
        g = self.g
        if g.elapsed - self.last_defend < 2.0:
            return
        self.last_defend = g.elapsed
        tx, ty = self.threat_pos
        responders = list(free)
        if self.army and self.fz["threat"] > 1.0:       # base in real danger: recall the strike force
            alive = [u for u in self.p.units if u.id in set(self.army["ids"]) and u.alive]
            responders += alive
            self.army = None
            self.note("recalled strike force to defend the base")
        elif self.army:
            ids = set(self.army["ids"])
            responders = [u for u in responders if u.id not in ids]
        responders = [u for u in responders if dist(u.x, u.y, tx, ty) > 3 * TILE]
        if responders:
            g._apply_attack_move_order(responders, tx, ty, "auto")

    def assemble(self, units):
        if self.rally is None:
            return
        rx, ry = self.rally
        idle = [u for u in units
                if u.target_pos is None and u.target_entity is None and u.order_mode is None
                and dist(u.x, u.y, rx, ry) > 7 * TILE]
        if not idle:
            return
        hx, hy = self.home_xy()
        d = dist(hx, hy, rx, ry) or 1.0
        direction = ((rx - hx) / d, (ry - hy) / d) if d > 1 else None
        self.g._apply_move_order(idle, rx, ry, "box", direction=direction)

    # -- target selection
    def pick_target(self, army_value, region=None):
        g = self.g
        focus = self.enemy()
        structs = [b for e in self.enemies() for b in e.buildings
                   if b.alive and b.kind not in WALL_DRAG_KINDS]
        if not structs:
            return None, True
        hx, hy = self.home_xy()
        home_region = region if region is not None else g.map.region_at(*self.cell((hx, hy)))
        best, best_val, best_reach = None, -1.0, True
        for b in structs:
            bx, by = b.center
            local = self.enemy_value_near(bx, by, 12 * TILE)
            dtiles = dist(hx, hy, bx, by) / TILE
            cost = BUILD_DATA[b.kind]["cost"]
            w = self.TARGET_WEIGHT.get(b.kind, 1.0)
            val = w * (cost.get("credits", 0) + 0.8 * cost.get("metal", 0) + 250) / (1 + local / max(army_value, 400.0))
            val /= (1 + dtiles / 70.0)
            if b.owner is focus:
                val *= 1.35                   # the team's chosen victim: converge on it
            if b.kind == "yard" and local < 0.8 * army_value:
                val *= 2.0
            reach = g.map.region_at(*self.cell((bx, by))) == home_region
            if not reach:
                val *= 0.85
            if val > best_val:
                best, best_val, best_reach = b, val, reach
        return best, best_reach

    def consider_attack(self, free):
        g = self.g
        if self.minutes() < 3.0 or g.elapsed - self.last_wave_end < 12.0 or self.rally is None:
            return
        rx, ry = self.rally
        staged = [u for u in free if dist(u.x, u.y, rx, ry) <= 12 * TILE]
        need_units = 6 if self.minutes() < 6 else 5
        if len(staged) < need_units:
            return
        staged_val = sum(self.uvalue(u) for u in staged)
        tgt, reachable = self.pick_target(staged_val)
        if tgt is None:
            return
        tx, ty = tgt.center
        local = self.enemy_value_near(tx, ty, 12 * TILE)
        required = (500 + 1.25 * local) * (1.5 - self.fz["aggression"]) * self.caution
        guard_frac = 0.1 + 0.3 * self.fz["defense"]
        staged.sort(key=lambda u: -self.uvalue(u))
        if reachable:
            wave = staged[:max(1, int(len(staged) * (1 - guard_frac)))]
            if sum(self.uvalue(u) for u in wave) >= required:
                self.launch_ground(wave, tgt)
        else:
            pax = [u for u in staged if u.kind in ("infantry", "rocket")]
            apcs = [u for u in self.p.units if u.alive and u.kind == "apc"]
            if apcs and len(pax) >= 3 and sum(self.uvalue(u) for u in pax) >= required * 0.7:
                self.start_airlift(pax, apcs, tgt)

    # -- ground assault with coordinated A* waypoints
    def launch_ground(self, wave, tgt):
        g = self.g
        cx = sum(u.x for u in wave) / len(wave)
        cy = sum(u.y for u in wave) / len(wave)
        tx, ty = tgt.center
        g.map.searches_left = max(g.map.searches_left, 1)      # planning a wave deserves one real search
        path = g.map.vehicle_path(wave[0], (cx, cy), (tx, ty), max_nodes=9000) or []
        # tighter spacing when the enemy is dangerous: smaller hops, regroup more often
        hop = 6 if self.fz["threat"] > 0.8 or self.enemy_value_near(tx, ty, 14 * TILE) > 2500 else 9
        wps = path[hop - 1::hop] if path else []
        wps = [w for w in wps if dist(w[0], w[1], tx, ty) > 9 * TILE]
        wps.append((tx, ty))
        val = sum(self.uvalue(u) for u in wave)
        self.army = {"ids": [u.id for u in wave], "target": tgt, "wps": wps, "wp": 0,
                     "t": g.elapsed, "t_start": g.elapsed, "launch_val": val, "last_order": g.elapsed}
        self.stats["waves"] += 1
        self.note("wave #%d: %d units -> %s, %d waypoints" % (self.stats["waves"], len(wave), tgt.kind, len(wps)))
        self.order_army()

    def order_army(self):
        a = self.army
        alive = [u for u in self.p.units if u.id in set(a["ids"]) and u.alive]
        if not alive:
            return
        wx, wy = a["wps"][a["wp"]]
        last = a["wp"] == len(a["wps"]) - 1
        self.g._apply_attack_move_order(alive, wx, wy, "line" if (last and len(alive) >= 6) else "box")
        a["last_order"] = self.g.elapsed

    def end_army(self, retreat=False):
        a = self.army
        self.last_wave_end = self.g.elapsed
        if retreat:
            self.caution = min(3.0, self.caution * 1.35)     # that went badly: ask for more next time
        else:
            self.caution = max(1.0, self.caution * 0.8)
        if a:
            alive = [u for u in self.p.units if u.id in set(a["ids"]) and u.alive]
            if alive and self.rally and not a.get("landed"):
                self.g._apply_move_order(alive, self.rally[0], self.rally[1], "box")
        self.note("wave ended (%s), caution x%.2f" % ("retreat" if retreat else "target cleared", self.caution))
        self.army = None

    def advance_army(self):
        g, p = self.g, self.p
        a = self.army
        ids = set(a["ids"])
        alive = [u for u in p.units if u.id in ids and u.alive]
        if not alive:
            self.end_army(retreat=True)
            return
        tgt_region = g.map.region_at(*self.cell(a["target"].center))
        stranded = [u for u in alive if g.map.region_at(*self.cell((u.x, u.y))) != tgt_region]
        if stranded:                      # cannot walk to the target from where they stand: release them
            sid = {u.id for u in stranded}
            a["ids"] = [i for i in a["ids"] if i not in sid]
            alive = [u for u in alive if u.id not in sid]
            for u in stranded:
                u.target_entity = None
                u.order_mode = None
                u.target_pos = None
            if not alive:
                self.end_army(retreat=True)
                return
        if g.elapsed - a.get("t_start", g.elapsed) > 300.0:
            self.end_army(retreat=True)   # stalled assault: regroup and come back bigger
            return
        val = sum(self.uvalue(u) for u in alive)
        if val < 0.35 * a["launch_val"] and not a.get("landed"):
            self.end_army(retreat=True)           # fuzzy "this is going badly": fall back and rebuild
            return
        tgt = a["target"]
        if not tgt.alive:
            reg = g.map.region_at(*self.cell((alive[0].x, alive[0].y))) if a.get("landed") else None
            nxt, reach = self.pick_target(val, region=reg)
            if nxt is not None and reach and (a.get("landed") or val > 0.6 * a["launch_val"]):
                cx = sum(u.x for u in alive) / len(alive)
                cy = sum(u.y for u in alive) / len(alive)
                a["target"] = nxt
                g.map.searches_left = max(g.map.searches_left, 1)
                path = g.map.vehicle_path(alive[0], (cx, cy), nxt.center, max_nodes=9000) or []
                wps = [w for w in (path[8::9] if path else []) if dist(w[0], w[1], *nxt.center) > 9 * TILE]
                wps.append(nxt.center)
                a["wps"], a["wp"], a["t"] = wps, 0, g.elapsed
                self.order_army()
                self.note("next target: %s" % nxt.kind)
            else:
                self.end_army()
            return
        wp = a["wps"][a["wp"]]
        last = a["wp"] == len(a["wps"]) - 1
        if not last:
            cohesion = 0.6 + 0.3 * (1.0 - self.fz["aggression"])
            near = sum(1 for u in alive if dist(u.x, u.y, wp[0], wp[1]) < 6 * TILE)
            if near >= cohesion * len(alive) or g.elapsed - a["t"] > 14.0:
                a["wp"] += 1
                a["t"] = g.elapsed
                self.order_army()
            elif g.elapsed - a["last_order"] > 3.0:
                idle = [u for u in alive if u.target_pos is None and u.order_mode is None and u.target_entity is None]
                if idle:
                    g._apply_attack_move_order(idle, wp[0], wp[1], "box")
                a["last_order"] = g.elapsed
        else:
            for u in alive:
                if u.target_pos is None and u.order_mode is None and u.target_entity is None:
                    near_e = g.nearest_enemy(p, u.x, u.y, 18 * TILE)
                    u.target_entity = near_e if near_e is not None else tgt

    # -- amphibious assault: APCs ferry infantry over water
    def pick_landing(self, tgt):
        g = self.g
        m = g.map
        tc = self.cell(tgt.center)
        region = m.region_at(*tc)
        hx, hy = self.home_xy()
        defs = [b for e in self.enemies() for b in e.buildings if b.alive and b.kind in DEFENSE_KINDS]
        best, best_s = None, None
        for r in range(tc[1] - 24, tc[1] + 25, 2):
            for c in range(tc[0] - 24, tc[0] + 25, 2):
                if not m.in_bounds(c, r) or m.tiles[r][c] == TILE_WATER or m.region_at(c, r) != region:
                    continue
                d_t = math.hypot(c - tc[0], r - tc[1])
                if d_t < 7 or d_t > 24:
                    continue
                near_def = min([dist((c + 0.5) * TILE, (r + 0.5) * TILE, *b.center) / TILE for b in defs] or [99])
                pen = (12 - near_def) * 6 if near_def < 12 else 0
                score = dist((c + 0.5) * TILE, (r + 0.5) * TILE, hx, hy) / TILE + pen + 0.3 * d_t
                if best_s is None or score < best_s:
                    best, best_s = ((c + 0.5) * TILE, (r + 0.5) * TILE), score
        return best

    def start_airlift(self, pax, apcs, tgt):
        g = self.g
        rx, ry = self.rally
        landing = self.pick_landing(tgt)
        if landing is None:
            return
        apcs = sorted(apcs, key=lambda a: dist(a.x, a.y, rx, ry))[:5]
        pax = pax[:5 * len(apcs)]
        self.op = {"state": "gather", "target": tgt, "landing": landing,
                   "apcs": [a.id for a in apcs], "pax": [u.id for u in pax],
                   "t": g.elapsed, "state_t": g.elapsed, "landed": []}
        for a in apcs:
            a.target_pos = (rx + self.rng.uniform(-40, 40), ry + self.rng.uniform(-40, 40))
            a.order_mode = None
            a.target_entity = None
        for i, u in enumerate(pax):
            a = apcs[i % len(apcs)]
            ang = i * 2.4
            u.target_entity = None
            u.order_mode = None
            u.target_pos = (a.x + math.cos(ang) * TILE * 0.9, a.y + math.sin(ang) * TILE * 0.9)
        self.stats["airlifts"] += 1
        self.note("airlift #%d: %d infantry in %d APCs -> %s (no land route)" %
                  (self.stats["airlifts"], len(pax), len(apcs), tgt.kind))

    def abort_op(self, why):
        self.note("airlift aborted: " + why)
        self.last_wave_end = self.g.elapsed
        self.op = None

    def op_tick(self):
        g, p = self.g, self.p
        op = self.op
        apcs = [u for u in p.units if u.id in op["apcs"] and u.alive]
        if not apcs:
            self.abort_op("transport lost")
            return
        tgt = op["target"]
        st = op["state"]
        if st == "gather":
            pax = [u for u in p.units if u.id in op["pax"] and u.alive]
            close = sum(1 for u in pax if any(dist(u.x, u.y, a.x, a.y) < 2.0 * TILE for a in apcs))
            if (pax and close >= len(pax)) or g.elapsed - op["state_t"] > 25.0 or not pax:
                loaded = sum(a.load_infantry(p) for a in apcs)
                if loaded == 0 and not any(a.cargo_units for a in apcs):
                    self.abort_op("nobody boarded")
                    return
                lx, ly = op["landing"]
                for i, a in enumerate(apcs):
                    a.order_mode = None
                    a.target_entity = None
                    a.target_pos = (lx + (i - len(apcs) / 2.0) * TILE * 1.2, ly)
                op["state"], op["state_t"] = "sail", g.elapsed
                self.note("loaded %d infantry, sailing" % loaded)
        elif st == "sail":
            lx, ly = op["landing"]
            land_region = g.map.region_at(*self.cell((lx, ly)))
            for a in apcs:
                d_l = dist(a.x, a.y, lx, ly)
                arrived = d_l < 2.0 * TILE or (a.target_pos is None and d_l < 6 * TILE)
                if a.cargo_units and arrived:
                    before = list(a.cargo_units)
                    a.unload_infantry(p, g.map, region=land_region)
                    landed = [u for u in before if u not in a.cargo_units]
                    op["landed"] += [u.id for u in landed]
            if op["landed"]:
                landed_units = [u for u in p.units if u.id in op["landed"] and u.alive]
                if landed_units:
                    if not self.army:
                        tx, ty = tgt.center
                        self.army = {"ids": list(op["landed"]), "target": tgt, "wps": [(tx, ty)], "wp": 0,
                                     "t": g.elapsed, "t_start": g.elapsed,
                                     "launch_val": max(1.0, sum(self.uvalue(u) for u in landed_units)),
                                     "last_order": g.elapsed, "landed": True}
                    else:
                        self.army["ids"] = list(set(self.army["ids"]) | set(op["landed"]))
                    self.stats["landed"] += len(landed_units)
                    self.order_army()
                    self.note("landed %d troops, attacking %s" % (len(landed_units), tgt.kind))
                    op["landed"] = []
            if not any(a.cargo_units for a in apcs):
                for a in apcs:
                    a.target_pos = self.rally
                op["state"], op["state_t"] = "return", g.elapsed
            elif g.elapsed - op["state_t"] > 150.0:
                self.abort_op("took too long at sea")
        elif st == "return":
            if g.elapsed - op["state_t"] > 25.0 or all(dist(a.x, a.y, *self.rally) < 8 * TILE for a in apcs):
                self.op = None
                self.last_wave_end = g.elapsed



# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------
class Game:
    def __init__(self, cols, rows, seed=None, biome="grass", net_role=None, net=None,
                 match=None, local_slot=0):
        self.net_role = net_role      # None (skirmish), "host", or "client"
        self.net = net
        self.net_send_timer = 0.0
        self.dirty_tiles = []         # (col,row,tile_type,tier) - depleted resource tiles to sync
        if match is None:
            match = default_match()
            if net_role is not None:
                match["slots"][1]["kind"] = "human"
            if net_role == "client":
                local_slot = 1
        # ---- build the players from the match setup (1..8 slots, teams A-D) ----
        active = [(i, sl) for i, sl in enumerate(match["slots"]) if sl["kind"] in ("human", "ai")]
        order = sorted(active, key=lambda t: (t[1]["team"], t[0]))
        starts = start_positions(cols, rows, len(order))
        corner_of = {i: starts[k] for k, (i, _sl) in enumerate(order)}
        self.map = GameMap(cols, rows, seed=seed, biome=biome, starts=[corner_of[i] for i, _ in active])
        global CURRENT_MAP
        CURRENT_MAP = self.map
        self.players = []
        self.players_by_slot = {}
        for i, sl in active:
            is_ai = sl["kind"] == "ai"
            colour = COLOR_PALETTE[sl.get("color", i) % len(COLOR_PALETTE)][1]
            nm = sl.get("name") or ("AI %d" % (i + 1) if is_ai else "Player %d" % (i + 1))
            pl = Player(nm, colour, is_ai, corner_of[i],
                        is_remote=(net_role == "host" and not is_ai and i != local_slot),
                        team=sl["team"], slot=i)
            pl.cid = sl.get("cid")          # network connection id of this slot's human (host only)
            self.players.append(pl)
            self.players_by_slot[i] = pl
        self.local_slot = local_slot if local_slot in self.players_by_slot else self.players[0].slot
        self.match = match
        self.winner_team = None
        self.ai_brains = {}
        self.visible_tiles = [[False for _ in range(cols)] for _ in range(rows)]
        self.explored_tiles = [[False for _ in range(cols)] for _ in range(rows)]
        self.radar_pings = []
        self._radar_last_seen = {}
        map_px_w, map_px_h = cols * TILE, rows * TILE
        self.camera = Camera(map_px_w, map_px_h)
        self.selected_units = []
        self.selected_entity = None
        self.drag_start = None
        self.drag_rect = None
        self.wall_drag_tile = None
        self.game_over = None
        self.projectiles = []
        self.explosions = []
        self.fallout_zones = []
        self.muzzle_flashes = []
        self.elapsed = 0.0
        for pl in self.players:
            self._setup_base(pl)
        self.map.game_buildings = [b for pl in self.players for b in pl.buildings]
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
        self.hack_until = 0.0           # game-time until which the enemy-intel hack is active
        self.hack_ready_at = 0.0        # game-time when it can be started again
        self.hack_button = None
        self._hack_cache = (-99.0, [])
        self.nuke_targeting = None      # silo currently aiming a manual nuke strike
        self.nuke_buttons = []
        self.banner_text = ""
        self.banner_until = 0
        self.formation_mode = "auto"   # how selected groups arrange on move orders
        self.formation_buttons = []
        self.command_mode = None  # keyboard-armed order mode
        self.patrol_anchor = None
        self.tech_tree_nodes = None  # lazily built: kind -> pygame.Rect
        self.tech_tree_close_button = None
        self.update_visibility(0.0)

    # "player" is the local human's side; everything else is relative to it.
    @property
    def player(self):
        return self.players_by_slot[self.local_slot]

    @property
    def ai(self):
        """First opposing player (kept for convenience / tests)."""
        foes = self.enemies_of(self.player)
        return foes[0] if foes else self.player

    # ---- teams ------------------------------------------------------------
    def is_ally(self, a, b):
        return a is not b and a.team == b.team

    def enemies_of(self, p, alive_only=True):
        return [q for q in self.players
                if q.team != p.team and not (alive_only and q.eliminated)]

    def allies_of(self, p):
        return [q for q in self.players if q.team == p.team and q is not p and not q.eliminated]

    def team_players(self, team):
        return [q for q in self.players if q.team == team]

    def enemy_entities(self, of=None):
        of = of or self.player
        out = []
        for q in self.enemies_of(of):
            out += q.units
            out += q.buildings
        return out

    def _setup_base(self, p):
        cx, cy = p.corner
        cols, rows = self.map.cols, self.map.rows
        yard = Building("yard", p, cx, cy)
        gap = BUILDING_PERIMETER + 1
        power = Building("power", p, cx + yard.w + gap, cy)
        ref_row = cy + yard.h + gap
        if ref_row + _building_tile_size("refinery")[1] > rows:
            ref_row = cy - _building_tile_size("refinery")[1] - gap
        refinery = Building("refinery", p, cx, ref_row)
        # If the base is near a horizontal edge, put the power plant on the
        # opposite side of the yard instead of letting clamping collapse it
        # onto the yard footprint.
        if power.col + power.w > cols:
            power.col = cx - power.w - gap
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
        """Nearest living enemy player (compat helper)."""
        foes = self.enemies_of(p)
        if not foes:
            return p
        yard = p.buildings_of("yard")
        ox, oy = yard[0].center if yard else ((p.corner[0] + 0.5) * TILE, (p.corner[1] + 0.5) * TILE)
        def d(q):
            y = q.buildings_of("yard")
            qx, qy = y[0].center if y else ((q.corner[0] + 0.5) * TILE, (q.corner[1] + 0.5) * TILE)
            return dist(ox, oy, qx, qy)
        return min(foes, key=d)

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

    def _wall_collision_rects(self, b):
        """The thin strips of a wall tile that really stand in the way (matches
        what is drawn: a centre post plus an arm toward each connected side)."""
        now = pygame.time.get_ticks()
        cache = getattr(b, "_los_cache", None)
        if cache is not None and now - cache[0] < 800:
            return cache[1]
        r = b.rect
        cx, cy = r.center
        t = WALL_LOS_THICKNESS
        h = t // 2
        dirs = b._wall_connections() or {"up", "down"}
        rects = [pygame.Rect(cx - h, cy - h, t, t)]
        if "left" in dirs:
            rects.append(pygame.Rect(r.left, cy - h, cx - r.left, t))
        if "right" in dirs:
            rects.append(pygame.Rect(cx, cy - h, r.right - cx, t))
        if "up" in dirs:
            rects.append(pygame.Rect(cx - h, r.top, t, cy - r.top))
        if "down" in dirs:
            rects.append(pygame.Rect(cx - h, cy, t, r.bottom - cy))
        b._los_cache = (now, rects)
        return rects

    def line_of_fire_blocker(self, shooter, target):
        """First fence / stone wall (anyone's - friendly, enemy or the shooter's
        own) lying across the straight line from shooter to target, else None."""
        sx, sy = get_center(shooter)
        tx, ty = get_center(target)
        x_lo, x_hi = min(sx, tx) - TILE, max(sx, tx) + TILE
        y_lo, y_hi = min(sy, ty) - TILE, max(sy, ty) + TILE
        best, best_d = None, None
        for p in self.players:
            for b in p.buildings:
                if (not b.alive or b.kind not in WALL_DRAG_KINDS
                        or b is shooter or b is target):
                    continue
                r = b.rect
                if r.right < x_lo or r.left > x_hi or r.bottom < y_lo or r.top > y_hi:
                    continue
                for rc in self._wall_collision_rects(b):
                    # a shooter/target standing inside this wall is not blocked by it
                    if rc.collidepoint(sx, sy) or rc.collidepoint(tx, ty):
                        continue
                    clip = rc.clipline(int(sx), int(sy), int(tx), int(ty))
                    if clip:
                        d = dist(sx, sy, clip[0][0], clip[0][1])
                        if best_d is None or d < best_d:
                            best, best_d = b, d
        return best

    def spawn_projectile(self, shooter, owner, target, damage, kind):
        if kind != "nuke" and not isinstance(target, GroundTarget):
            # Walls absorb direct-fire shots: the projectile hits the wall instead.
            blocker = self.line_of_fire_blocker(shooter, target)
            if blocker is not None:
                target = blocker
        x, y = get_center(shooter)
        self.projectiles.append(Projectile(shooter, owner, target, damage, kind, x, y))
        if isinstance(shooter, Unit) and shooter.kind == "tank":
            play_sfx("tank_fire", 0.75)
            angle = shooter.gun_angle
            self.muzzle_flashes.append({
                "x": x + math.cos(angle) * 25,
                "y": y + math.sin(angle) * 25,
                "angle": angle,
                "age": 0.0,
                "max_age": MUZZLE_FLASH_LIFETIME,
            })

    # ---- networking -----------------------------------------------------
    def notify_remote_ready_to_place(self, player, kind):
        # host telling that player's client "your building is done, place it"
        if self.net_role == "host":
            cid = getattr(player, "cid", None)
            if cid is not None:
                self.net.send_to(cid, {"type": "ready_to_place", "kind": kind})

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
            for cid, msg in self.net.poll():
                pl = next((q for q in self.players if getattr(q, "cid", None) == cid), None)
                if pl is not None and not pl.eliminated:
                    self.handle_client_command(msg, pl)
            # a client that drops mid-game forfeits: their base is handed to the scrap heap
            for cid in self.net.dropped():
                pl = next((q for q in self.players if getattr(q, "cid", None) == cid), None)
                if pl is not None and not pl.eliminated:
                    for b in pl.buildings_of("yard"):      # no yard = eliminated next tick
                        b.alive = False
                    self.banner_text = "%s DISCONNECTED" % pl.name.upper()
                    self.banner_until = pygame.time.get_ticks() + 4000
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

    def handle_client_command(self, msg, p2):
        # Host-side: apply a command sent by one connected human client (p2 = their player).
        t = msg.get("type")
        if t == "produce":
            p2.start_production(msg["kind"])
        elif t == "cancel_produce":
            p2.cancel_production(msg["kind"], all_items=bool(msg.get("all")))
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
            self._apply_move_order(units, msg["x"], msg["y"], msg.get("formation", "auto"))
        elif t == "attack_move":
            ids = set(msg.get("unit_ids", []))
            units = [u for u in p2.units if u.id in ids]
            self._apply_attack_move_order(units, msg["x"], msg["y"], msg.get("formation", "auto"))
        elif t == "nuke":
            silo = self.find_entity_by_id(msg.get("building_id"))
            if isinstance(silo, Building):
                self._apply_nuke_command(p2, silo, msg.get("action"), msg.get("x"), msg.get("y"))
        elif t == "align":
            ids = set(msg.get("unit_ids", []))
            units = [u for u in p2.units if u.id in ids]
            mode = msg.get("mode", "auto")
            if mode in FORMATION_MODES:
                self._apply_align_order(units, mode)
        elif t == "patrol":
            ids = set(msg.get("unit_ids", []))
            units = [u for u in p2.units if u.id in ids]
            self._apply_patrol_order(units, (msg["x1"], msg["y1"]), (msg["x2"], msg["y2"]))
        elif t == "attack":
            target = self.find_entity_by_id(msg.get("target_id"))
            ids = set(msg.get("unit_ids", []))
            if target is not None:
                for u in p2.units:
                    if u.id in ids:
                        u.target_entity = target
                        u.target_pos = None
                        u.manual_harvest_tile = None
        elif t == "transport":
            ids = set(msg.get("unit_ids", []))
            for u in p2.units:
                if u.id in ids and u.kind == "apc":
                    if msg.get("action") == "load":
                        u.load_infantry(p2)
                    elif msg.get("action") == "unload":
                        u.unload_infantry(p2, self.map)

    def build_snapshot(self):
        def uinfo(u):
            return {"id": u.id, "kind": u.kind, "owner": u.owner.slot,
                    "x": u.x, "y": u.y, "hp": u.hp, "rank": u.rank}

        def binfo(b):
            return {"id": b.id, "kind": b.kind, "owner": b.owner.slot,
                    "col": b.col, "row": b.row, "hp": b.hp, "max_hp": b.max_hp,
                    "ns": b.nuke_state, "nt": b.nuke_timer}

        def pinfo(p):
            return {"slot": p.slot, "credits": p.credits, "wood": p.wood, "metal": p.metal,
                    "upgrades": list(p.upgrades), "queues": p.queues, "elim": p.eliminated}

        msg = {
            "type": "state",
            "players": [pinfo(p) for p in self.players],
            "units": [uinfo(u) for p in self.players for u in p.units],
            "buildings": [binfo(b) for p in self.players for b in p.buildings],
            "projectiles": [{"x": pr.x, "y": pr.y, "kind": pr.kind,
                             "phase": pr.nuke_phase, "altitude": pr.nuke_altitude}
                            for pr in self.projectiles],
            "fallout_zones": self.fallout_zones,
            "dirty_tiles": self.dirty_tiles,
            "game_over": self.game_over,
        }
        self.dirty_tiles = []
        return msg

    def apply_snapshot(self, msg):
        for data in msg["players"]:
            player = self.players_by_slot.get(data["slot"])
            if player is None:
                continue
            player.credits = data["credits"]
            player.wood = data["wood"]
            player.metal = data["metal"]
            player.upgrades = set(data["upgrades"])
            player.eliminated = data.get("elim", False)
            for k, v in data["queues"].items():
                player.queues[k] = v

        selected_ids = {u.id for u in self.selected_units}
        existing_units = {u.id: u for p in self.players for u in p.units}
        new_units = {p.slot: [] for p in self.players}
        for ud in msg["units"]:
            owner = self.players_by_slot.get(ud["owner"])
            if owner is None:
                continue
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
            new_units[owner.slot].append(u)
        for p in self.players:
            p.units = new_units[p.slot]
        self.selected_units = [u for u in self.player.units if u.selected]

        existing_b = {b.id: b for p in self.players for b in p.buildings}
        new_b = {p.slot: [] for p in self.players}
        for bd in msg["buildings"]:
            owner = self.players_by_slot.get(bd["owner"])
            if owner is None:
                continue
            b = existing_b.get(bd["id"])
            if b is None:
                b = Building(bd["kind"], owner, bd["col"], bd["row"])
                b.id = bd["id"]
            b.hp = bd["hp"]
            b.max_hp = bd["max_hp"]
            b.nuke_state = bd.get("ns", "idle")
            b.nuke_timer = bd.get("nt", 0.0)
            new_b[owner.slot].append(b)
        for p in self.players:
            p.buildings = new_b[p.slot]

        self.projectiles = [Projectile(None, None, None, 0, pd["kind"], pd["x"], pd["y"])
                             for pd in msg["projectiles"]]
        for projectile, pd in zip(self.projectiles, msg["projectiles"]):
            projectile.nuke_phase = pd.get("phase")
            projectile.nuke_altitude = pd.get("altitude", 0.0)
        self.fallout_zones = msg.get("fallout_zones", [])

        for (col, row, ttype, tier) in msg.get("dirty_tiles", []):
            if self.map.in_bounds(col, row):
                self.map.tiles[row][col] = ttype
                self.map.trainium_tier[row][col] = tier

        self.game_over = msg.get("game_over")
        if isinstance(self.game_over, str) and self.game_over.startswith("team_win:"):
            try:
                self.winner_team = int(self.game_over.split(":")[1])
            except ValueError:
                self.winner_team = None

    # ---- building placement --------------------------------------------
    def can_place(self, p, kind, col, row):
        data = BUILD_DATA[kind]
        w, h = _building_tile_size(kind)
        cols, rows = self.map.cols, self.map.rows
        if col < 0 or row < 0 or col + w > cols or row + h > rows:
            return False
        for x in range(col, col + w):
            for y in range(row, row + h):
                if self.map.tiles[y][x] != TILE_GROUND:
                    return False
        for other in [b for q in self.players for b in q.buildings]:
            if not other.alive:
                continue
            pad = 0 if kind in WALL_DRAG_KINDS or other.kind in WALL_DRAG_KINDS else BUILDING_PERIMETER
            orect = pygame.Rect(other.col - pad, other.row - pad,
                                other.w + pad * 2, other.h + pad * 2)
            nrect = pygame.Rect(col, row, w, h)
            if orect.colliderect(nrect):
                return False
        near = False
        for b in p.buildings:
            if not b.alive:
                continue
            bd = max(abs((col + w / 2) - (b.col + b.w / 2)), abs((row + h / 2) - (b.row + b.h / 2)))
            if bd <= ADJ_RANGE * BUILDING_PLACEMENT_RANGE_MULT:
                near = True
                break
        return near

    def place_building(self, p, kind, col, row):
        b = Building(kind, p, col, row)
        p.buildings.append(b)
        p.pending_placement = None
        p.pending_cost = None

    def ai_auto_place(self, p, kind):
        """Finished AI structure: let that player's brain choose where it goes."""
        self.brain_for(p).place(kind)

    def nearest_enemy(self, p, x, y, max_range=None):
        best, best_d = None, None
        for foe in self.enemies_of(p):
            for target in foe.units:
                if not target.alive:
                    continue
                d = dist(x, y, target.x, target.y)
                if max_range is not None and d > max_range:
                    continue
                if best_d is None or d < best_d:
                    best, best_d = target, d
            for target in foe.buildings:
                if not target.alive:
                    continue
                tx, ty = target.center
                d = dist(x, y, tx, ty)
                if max_range is not None and d > max_range:
                    continue
                if best_d is None or d < best_d:
                    best, best_d = target, d
        return best

    def _mark_vision_disc(self, col, row, radius):
        r = int(math.ceil(radius))
        for y in range(max(0, row - r), min(self.map.rows, row + r + 1)):
            for x in range(max(0, col - r), min(self.map.cols, col + r + 1)):
                if (x - col) ** 2 + (y - row) ** 2 <= radius * radius:
                    self.visible_tiles[y][x] = True
                    self.explored_tiles[y][x] = True

    def _mark_vision_square(self, col, row, half):
        """Reveal a square (Chebyshev) area - matches how build range is measured."""
        half = int(math.ceil(half))
        for y in range(max(0, row - half), min(self.map.rows, row + half + 1)):
            for x in range(max(0, col - half), min(self.map.cols, col + half + 1)):
                self.visible_tiles[y][x] = True
                self.explored_tiles[y][x] = True

    def yard_build_vision_half(self):
        """Half-width (tiles) of the area the Construction Yard can place in.

        can_place() accepts a building whose centre is within
        ADJ_RANGE * BUILDING_PLACEMENT_RANGE_MULT tiles (Chebyshev) of a
        friendly building's centre, so its edge can reach half its own
        footprint beyond that. Reveal the whole of it.
        """
        reach = ADJ_RANGE * BUILDING_PLACEMENT_RANGE_MULT
        max_half = max(max(_building_tile_size(k)) / 2 for k in BUILD_DATA)
        return reach + max_half

    def is_world_visible(self, wx, wy):
        col, row = int(wx // TILE), int(wy // TILE)
        return (self.map.in_bounds(col, row) and self.visible_tiles[row][col])

    def update_visibility(self, dt):
        """Rebuild local vision and turn newly spotted enemy contacts into pings."""
        for row in range(self.map.rows):
            for col in range(self.map.cols):
                self.visible_tiles[row][col] = False
        if self.hack_active():
            # Hacked: the whole map is visible (exploration memory is left untouched,
            # so the fog comes back as it was when the hack runs out).
            for row in range(self.map.rows):
                vrow = self.visible_tiles[row]
                for col in range(self.map.cols):
                    vrow[col] = True
            return
        # Vision is shared with allies: whatever a teammate sees, you see.
        for p in [self.player] + [a for a in self.players if a.team == self.player.team and a is not self.player]:
            for u in p.units:
                if u.alive:
                    self._mark_vision_disc(int(u.x // TILE), int(u.y // TILE), FOG_VISION_RADIUS_TILES)
            for b in p.buildings:
                if b.alive:
                    if b.kind == "yard":
                        # Whole build range of the Construction Yard stays clear of fog.
                        self._mark_vision_square(b.col + b.w // 2, b.row + b.h // 2,
                                                 self.yard_build_vision_half())
                    else:
                        self._mark_vision_disc(b.col + b.w // 2, b.row + b.h // 2,
                                               FOG_BUILDING_VISION_TILES)

        now = self.elapsed
        for enemy in self.enemy_entities():
            if not enemy.alive:
                continue
            ex, ey = get_center(enemy)
            if self.is_world_visible(ex, ey):
                last = self._radar_last_seen.get(enemy.id, -999.0)
                if now - last >= RADAR_PING_COOLDOWN:
                    self.radar_pings.append({"x": ex, "y": ey, "age": 0.0,
                                             "max_age": RADAR_PING_LIFETIME,
                                             "kind": "unit" if isinstance(enemy, Unit) else "building"})
                    self._radar_last_seen[enemy.id] = now
        for ping in self.radar_pings:
            ping["age"] += dt
        self.radar_pings = [p for p in self.radar_pings if p["age"] < p["max_age"]]

    def render_fog_of_war(self):
        """Dim explored ground and fully conceal terrain/entities never explored."""
        fog = pygame.Surface((VIEWPORT_W, VIEWPORT_H), pygame.SRCALPHA)
        col0 = max(0, int(self.camera.x // TILE) - 1)
        row0 = max(0, int(self.camera.y // TILE) - 1)
        col1 = min(self.map.cols, int((self.camera.x + VIEWPORT_W) // TILE) + 2)
        row1 = min(self.map.rows, int((self.camera.y + VIEWPORT_H) // TILE) + 2)
        for row in range(row0, row1):
            for col in range(col0, col1):
                if self.visible_tiles[row][col]:
                    continue
                sx, sy = self.camera.to_screen(col * TILE, row * TILE)
                rect = pygame.Rect(int(sx - VIEWPORT_X0), int(sy - VIEWPORT_Y0), TILE + 1, TILE + 1)
                if self.explored_tiles[row][col]:
                    pygame.draw.rect(fog, (5, 8, 12, 118), rect)
                else:
                    pygame.draw.rect(fog, (2, 4, 8, 238), rect)
        screen.blit(fog, (VIEWPORT_X0, VIEWPORT_Y0))

    def render_radar_pings(self):
        for ping in self.radar_pings:
            sx, sy = self.camera.to_screen(ping["x"], ping["y"])
            pct = ping["age"] / ping["max_age"]
            radius = 7 + int(RADAR_PING_RING_SPEED * ping["age"])
            alpha = int(220 * (1.0 - pct))
            if alpha <= 2:
                continue
            layer = pygame.Surface((radius * 2 + 12, radius * 2 + 12), pygame.SRCALPHA)
            center = (radius + 6, radius + 6)
            color = (255, 70, 70, alpha) if ping["kind"] == "unit" else (255, 190, 55, alpha)
            pygame.draw.circle(layer, color, center, radius, 2)
            pygame.draw.circle(layer, color, center, 3)
            screen.blit(layer, (int(sx - center[0]), int(sy - center[1])))

    # ---- update ---------------------------------------------------------
    def update(self, dt):
        self.elapsed += dt
        self.map.game_buildings = [b for pl in self.players for b in pl.buildings]
        self.map.searches_left = 3
        self._wall_cell_timer = getattr(self, "_wall_cell_timer", 0.0) - dt
        if self._wall_cell_timer <= 0:
            self._wall_cell_timer = 0.4
            cells = {}
            for b in self.map.game_buildings:
                if b.alive and b.kind in WALL_DRAG_KINDS:
                    cells.setdefault(b.owner.team, set()).update(b.footprint())
            self.map.wall_cells = cells
        self.update_camera(dt)
        self._update_overview(dt)
        self.update_visibility(dt)
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
        for pl in self.players:
            if not pl.eliminated:
                self.update_units(pl, dt)
        for pl in self.players:
            if not pl.eliminated:
                self.update_defenses(pl, dt)
        if self.net_role != "client":
            self.update_ai(dt)

        for pr in self.projectiles:
            pr.update(dt, self)
        self.projectiles = [pr for pr in self.projectiles if pr.alive]
        for fx in self.explosions:
            fx["age"] += dt
        self.explosions = [fx for fx in self.explosions if fx["age"] < fx["max_age"]]
        self.update_fallout(dt)
        for flash in self.muzzle_flashes:
            flash["age"] += dt
        self.muzzle_flashes = [f for f in self.muzzle_flashes if f["age"] < f["max_age"]]

        for p in self.players:
            p.units = [u for u in p.units if u.alive]
            p.buildings = [b for b in p.buildings if b.alive]
        self.selected_units = [u for u in self.selected_units if u.alive]

        self.check_eliminations()

        if self.net_role == "host":
            self.net_send_timer -= dt
            if self.net_send_timer <= 0:
                self.net_send_timer = 0.08
                self.net.send(self.build_snapshot())

    def update_fallout(self, dt):
        """Apply persistent area damage and expire spent fallout clouds."""
        for zone in self.fallout_zones:
            zone["age"] += dt
            zone["tick_timer"] += dt
            while zone["tick_timer"] >= NUKE_FALLOUT_TICK:
                zone["tick_timer"] -= NUKE_FALLOUT_TICK
                for player in self.players:
                    for entity in player.units + player.buildings:
                        if getattr(entity, "alive", False):
                            ex, ey = get_center(entity)
                            if dist(zone["x"], zone["y"], ex, ey) <= zone["radius"]:
                                entity.take_damage(zone.get("damage", NUKE_FALLOUT_DAMAGE))
        self.fallout_zones = [zone for zone in self.fallout_zones
                              if zone["age"] < zone["max_age"]]

    def render_fallout(self):
        """Draw a translucent green contamination cloud under the fog layer."""
        for zone in self.fallout_zones:
            sx, sy = self.camera.to_screen(zone["x"], zone["y"])
            radius = int(zone["radius"])
            if (sx + radius < 0 or sx - radius > VIEWPORT_W or
                    sy + radius < TOPBAR_H or sy - radius > SCREEN_H):
                continue
            pct_left = max(0.0, 1.0 - zone["age"] / zone["max_age"])
            pulse = 0.5 + 0.5 * math.sin(self.elapsed * 2.6)
            layer = pygame.Surface((radius * 2 + 8, radius * 2 + 8), pygame.SRCALPHA)
            center = (radius + 4, radius + 4)
            alpha = int((24 + 14 * pulse) * pct_left)
            pygame.draw.circle(layer, (82, 205, 73, alpha), center, radius)
            pygame.draw.circle(layer, (124, 235, 86, int(alpha * 2.0)), center,
                               radius, max(2, radius // 70))
            pygame.draw.circle(layer, (177, 236, 102, int(alpha * 1.4)), center,
                               int(radius * 0.64), max(1, radius // 120))
            screen.blit(layer, (int(sx - center[0]), int(sy - center[1])))

    # ---- hack: lift the fog and read the enemy's books for 5 minutes ----------
    def hack_active(self):
        return self.elapsed < self.hack_until

    def hack_cooldown_left(self):
        return max(0.0, self.hack_ready_at - self.elapsed) if not self.hack_active() else 0.0

    def start_hack(self):
        """Hack the enemy network: no fog of war and a live readout of their
        resources and trainium for HACK_DURATION seconds."""
        if self.hack_active() or self.elapsed < self.hack_ready_at or self.game_over:
            return False
        if not self.enemies_of(self.player):
            return False
        self.hack_until = self.elapsed + HACK_DURATION
        self.hack_ready_at = self.hack_until + HACK_COOLDOWN
        self.banner_text = "HACK ONLINE - FOG LIFTED, ENEMY INTEL FOR %d:%02d" % divmod(int(HACK_DURATION), 60)
        self.banner_until = pygame.time.get_ticks() + 4000
        self.update_visibility(0.0)
        return True

    def trainium_stock_near(self, p, radius=32):
        """Trainium (credit value) still sitting in the fields around p's base."""
        yard = p.buildings_of("yard")
        if yard:
            cc, rr = yard[0].col + yard[0].w // 2, yard[0].row + yard[0].h // 2
        else:
            cc, rr = p.corner
        total = 0.0
        m = self.map
        for y in range(max(0, rr - radius), min(m.rows, rr + radius + 1)):
            for x in range(max(0, cc - radius), min(m.cols, cc + radius + 1)):
                if m.tiles[y][x] in (TILE_TRAINIUM, TILE_RADIOACTIVE):
                    total += m.resource_amount[y][x] * TRAINIUM_TIER_MULT[m.trainium_tier[y][x]]
        return total

    def hack_stats(self):
        """Per-enemy intel rows, refreshed about once a second."""
        if self.elapsed - self._hack_cache[0] < 1.0:
            return self._hack_cache[1]
        rows = []
        for q in self.enemies_of(self.player, alive_only=False):
            rows.append({"name": q.name, "color": q.color, "team": q.team, "elim": q.eliminated,
                         "credits": q.credits, "wood": q.wood, "metal": q.metal,
                         "trainium": 0.0 if q.eliminated else self.trainium_stock_near(q),
                         "units": len(q.units), "bldgs": len(q.buildings)})
        self._hack_cache = (self.elapsed, rows)
        return rows

    def render_hack_button(self):
        """Hack button: top-right corner of the map view (hotkey H)."""
        hb = pygame.Rect(VIEWPORT_W - 156, TOPBAR_H + 6, 150, 26)
        self.hack_button = hb
        mxp, myp = pygame.mouse.get_pos()
        cd = self.hack_cooldown_left()
        if self.hack_active():
            left = int(self.hack_until - self.elapsed)
            label, fill, tcol = "HACK ON  %d:%02d" % (left // 60, left % 60), (30, 90, 55), (150, 255, 180)
        elif cd > 0:
            label, fill, tcol = "Hack cooldown %d:%02d" % (int(cd) // 60, int(cd) % 60), (36, 36, 40), COL_TEXT_DIM
        else:
            label, fill, tcol = "HACK  [H]", (40, 70, 52), (130, 235, 160)
            if hb.collidepoint(mxp, myp):
                fill = (56, 100, 72)
        pygame.draw.rect(screen, fill, hb, border_radius=5)
        pygame.draw.rect(screen, (90, 170, 120) if cd <= 0 else (70, 70, 76), hb, 1, border_radius=5)
        lt = FONT_SMALL.render(label, True, tcol)
        screen.blit(lt, lt.get_rect(center=hb.center))

    def render_hack_panel(self):
        self.render_hack_button()
        if not self.hack_active():
            return
        rows = self.hack_stats()
        left = int(self.hack_until - self.elapsed)
        x, y, w = 6, TOPBAR_H + 4, 560
        h = 24 + 20 * max(1, len(rows)) + 6
        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        panel.fill((8, 22, 14, 215))
        screen.blit(panel, (x, y))
        pygame.draw.rect(screen, (70, 220, 120), (x, y, w, h), 1)
        head = FONT_SMALL.render("HACKED ENEMY INTEL   %d:%02d left" % (left // 60, left % 60), True, (110, 240, 150))
        screen.blit(head, (x + 8, y + 5))
        # thin timer bar along the header
        frac = clamp((self.hack_until - self.elapsed) / HACK_DURATION, 0, 1)
        pygame.draw.rect(screen, (30, 70, 45), (x + 1, y + 20, w - 2, 3))
        pygame.draw.rect(screen, (90, 235, 140), (x + 1, y + 20, int((w - 2) * frac), 3))
        for i, r in enumerate(rows):
            ry = y + 26 + i * 20
            pygame.draw.rect(screen, (0, 0, 0), (x + 7, ry + 3, 10, 10))
            pygame.draw.rect(screen, r["color"], (x + 8, ry + 4, 8, 8))
            nm = FONT_TINY.render("%s [%s]" % (r["name"][:12], TEAM_LETTERS[r["team"] % 4]), True,
                                  (150, 150, 150) if r["elim"] else COL_TEXT)
            screen.blit(nm, (x + 22, ry + 3))
            if r["elim"]:
                screen.blit(FONT_TINY.render("ELIMINATED", True, COL_BAD), (x + 150, ry + 3))
                continue
            screen.blit(FONT_TINY.render("$%d" % r["credits"], True, COL_GOOD), (x + 150, ry + 3))
            screen.blit(FONT_TINY.render("W %d" % r["wood"], True, COL_WOOD), (x + 225, ry + 3))
            screen.blit(FONT_TINY.render("M %d" % r["metal"], True, COL_METAL), (x + 290, ry + 3))
            screen.blit(FONT_TINY.render("Trainium %d" % r["trainium"], True, COL_LIME), (x + 355, ry + 3))
            screen.blit(FONT_TINY.render("%du %db" % (r["units"], r["bldgs"]), True, COL_TEXT_DIM), (x + 480, ry + 3))

    def check_eliminations(self):
        """A player with no Construction Yard is out; the match ends when only
        one team still has players in it."""
        if self.net_role == "client":
            return
        for pl in self.players:
            if not pl.eliminated and pl.is_defeated():
                pl.eliminated = True
                for u in pl.units:
                    u.alive = False
                for b in pl.buildings:
                    b.alive = False
                self.banner_text = "%s HAS BEEN ELIMINATED" % pl.name.upper()
                self.banner_until = pygame.time.get_ticks() + 4500
        alive_teams = {pl.team for pl in self.players if not pl.eliminated}
        if len(alive_teams) <= 1 and not self.game_over:
            self.winner_team = next(iter(alive_teams), None)
            self.game_over = "team_win:%s" % self.winner_team

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

    # ---- nuke silo: assemble (5 min) then aim --------------------------------
    def nuke_command(self, silo, action, x=None, y=None):
        """UI entry point: runs locally, or is forwarded to the host when we are a client."""
        if silo is None:
            return False
        if action == "build" and self.player.credits < NUKE_CREDIT_COST:
            return False
        if self.net_role == "client":
            self.net.send({"type": "nuke", "building_id": silo.id, "action": action, "x": x, "y": y})
            if action == "launch":
                self.nuke_targeting = None
            play_sfx("negative" if action == "cancel" else "affirmative", 0.85)
            return True
        succeeded = self._apply_nuke_command(self.player, silo, action, x, y)
        if succeeded:
            play_sfx("negative" if action == "cancel" else "affirmative", 0.85)
        return succeeded

    def _apply_nuke_command(self, player, silo, action, x=None, y=None):
        if (silo is None or not silo.alive or silo.kind != "nuke_silo"
                or silo.owner is not player or player.is_ai):
            return False
        if action == "build" and silo.nuke_state == "idle":
            if player.credits < NUKE_CREDIT_COST:
                return False
            player.credits -= NUKE_CREDIT_COST
            silo.nuke_state, silo.nuke_timer = "building", 0.0
            return True
        elif action == "cancel" and silo.nuke_state == "building":
            player.credits += NUKE_CREDIT_COST
            silo.nuke_state, silo.nuke_timer = "idle", 0.0
            return True
        elif action == "launch" and silo.nuke_state == "ready" and x is not None and y is not None:
            x = clamp(x, 0, self.map.cols * TILE)
            y = clamp(y, 0, self.map.rows * TILE)
            self.projectiles.append(Projectile(silo, player, GroundTarget(x, y),
                                               structure_damage(silo), "nuke", *silo.center))
            silo.nuke_state, silo.nuke_timer = "idle", 0.0
            self.banner_text, self.banner_until = "NUCLEAR LAUNCH DETECTED", pygame.time.get_ticks() + 3500
            return True
        return False

    def _update_nuke_silo(self, p, b, dt):
        if b.nuke_state != "building":
            return
        b.nuke_timer += dt / (2.0 if p.low_power() else 1.0)
        if b.nuke_timer >= NUKE_BUILD_TIME:
            b.nuke_timer = NUKE_BUILD_TIME
            b.nuke_state = "ready"
            if p is self.player:
                self.banner_text = "NUKE ASSEMBLED - SELECT THE SILO TO TARGET IT"
                self.banner_until = pygame.time.get_ticks() + 5000

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
            if b.kind == "nuke_silo" and not p.is_ai:
                self._update_nuke_silo(p, b, dt)   # players aim their own nukes
                continue
            data = BUILD_DATA[b.kind]
            if b.kind == "nuke_silo" and p.is_ai and p.credits < NUKE_CREDIT_COST:
                continue
            b.attack_cd -= dt
            if b.attack_cd <= 0:
                cx, cy = b.center
                target = self.nearest_enemy(p, cx, cy, data["range"] * BUILDING_RANGE_MULT)
                if target is not None:
                    tx, ty = get_center(target)
                    b.turret_angle = math.atan2(ty - cy, tx - cx)
                    dmg = structure_damage(b)
                    self.spawn_projectile(b, p, target, dmg, data.get("projectile", "bullet"))
                    if b.kind == "nuke_silo" and p.is_ai:
                        p.credits -= NUKE_CREDIT_COST
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
                if u.kind == "tank":
                    u.gun_angle = u.heading
            data = UNIT_DATA[u.kind]
            proj_kind = data.get("projectile", "bullet")

            def try_fire(target):
                if u.attack_cd <= 0:
                    self.spawn_projectile(u, p, target, effective_damage(u), proj_kind)
                    u.attack_cd = data["cooldown"]

            if u.order_mode == "attack_move":
                if u.target_entity is None:
                    u.target_entity = self.nearest_enemy(p, u.x, u.y, ATTACK_MOVE_SCAN_RANGE)
                if u.target_entity is not None:
                    tx, ty = get_center(u.target_entity)
                    u.gun_angle = math.atan2(ty - u.y, tx - u.x)
                    if dist(u.x, u.y, tx, ty) <= data["range"] * UNIT_FIRE_RANGE_MULT:
                        try_fire(u.target_entity)
                    else:
                        u.move_toward(tx, ty, dt)
                elif u.target_pos is not None:
                    if u.move_toward(u.target_pos[0], u.target_pos[1], dt):
                        u.target_pos = None
                        u.order_mode = None
                continue

            if u.order_mode == "patrol":
                if len(u.patrol_points) < 2:
                    u.order_mode = None
                    continue
                if u.target_entity is None:
                    u.target_entity = self.nearest_enemy(p, u.x, u.y, ATTACK_MOVE_SCAN_RANGE)
                if u.target_entity is not None:
                    tx, ty = get_center(u.target_entity)
                    u.gun_angle = math.atan2(ty - u.y, tx - u.x)
                    if dist(u.x, u.y, tx, ty) <= data["range"] * UNIT_FIRE_RANGE_MULT:
                        try_fire(u.target_entity)
                    else:
                        u.move_toward(tx, ty, dt)
                else:
                    tx, ty = u.patrol_points[u.patrol_index]
                    if u.move_toward(tx, ty, dt):
                        u.patrol_index = (u.patrol_index + 1) % len(u.patrol_points)
                        u.target_pos = u.patrol_points[u.patrol_index]
                continue

            if u.target_entity is not None:
                tx, ty = get_center(u.target_entity)
                u.gun_angle = math.atan2(ty - u.y, tx - u.x)
                d = dist(u.x, u.y, tx, ty)
                if d <= data["range"] * UNIT_FIRE_RANGE_MULT:
                    try_fire(u.target_entity)
                else:
                    u.move_toward(tx, ty, dt)
            elif u.target_pos is not None:
                reached = u.move_toward(u.target_pos[0], u.target_pos[1], dt)
                target = self.nearest_enemy(p, u.x, u.y, data["range"] * UNIT_FIRE_RANGE_MULT)
                if target is not None:
                    tx, ty = get_center(target)
                    u.gun_angle = math.atan2(ty - u.y, tx - u.x)
                    try_fire(target)
                if reached:
                    u.target_pos = None
            else:
                target = self.nearest_enemy(p, u.x, u.y, data["range"] * UNIT_FIRE_RANGE_MULT)
                if target is not None:
                    tx, ty = get_center(target)
                    u.gun_angle = math.atan2(ty - u.y, tx - u.x)
                    try_fire(target)
                elif u.kind == "tank":
                    u.gun_angle = u.heading

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
            u._harvest_sound_timer -= dt
            if u._harvest_sound_timer <= 0:
                play_sfx("resource_gather", 0.28)
                u._harvest_sound_timer = 0.42
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
    def brain_for(self, p):
        brain = self.ai_brains.get(p.slot)
        if brain is None:
            brain = self.ai_brains[p.slot] = AIBrain(self, p)
        return brain

    @property
    def ai_brain(self):
        """First AI brain (convenience for tests / debugging)."""
        for pl in self.players:
            if pl.is_ai and pl.slot in self.ai_brains:
                return self.ai_brains[pl.slot]
        return None

    def update_ai(self, dt):
        for pl in self.players:
            if pl.is_ai and not pl.eliminated:
                self.brain_for(pl).update(dt)

    # ---- input --------------------------------------------------------
    def handle_left_down(self, pos):
        x, y = pos
        if self.hack_button is not None and self.hack_button.collidepoint(pos):
            self.start_hack()
            return
        if x >= VIEWPORT_W:
            self.handle_sidebar_click(pos)
            return
        if y < TOPBAR_H:
            return
        if not self.camera.in_viewport(x, y):
            return

        if self.nuke_targeting is not None:
            silo = self.nuke_targeting
            self.nuke_targeting = None
            if silo.alive and silo.nuke_state == "ready":
                wx, wy = self.camera.to_world(x, y)
                self.nuke_command(silo, "launch", wx, wy)
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

    def _group_direction(self, units, wx, wy):
        """Unit vector the group is travelling in (falls back to its facing)."""
        n = max(1, len(units))
        cx = sum(u.x for u in units) / n
        cy = sum(u.y for u in units) / n
        dx, dy = wx - cx, wy - cy
        d = math.hypot(dx, dy)
        if d >= 4:
            return (dx / d, dy / d)
        hx = sum(math.cos(u.heading) for u in units)
        hy = sum(math.sin(u.heading) for u in units)
        hd = math.hypot(hx, hy)
        return (hx / hd, hy / hd) if hd > 1e-3 else (0.0, -1.0)

    def _formation_point_walkable(self, u, px, py):
        col, row = int(px // TILE), int(py // TILE)
        if not self.map.in_bounds(col, row):
            return False
        if u.kind in ("tank", "apc", "harvester"):
            return not self.map.vehicle_cell_blocked(col, row, u)
        return (self.map.tiles[row][col] != TILE_WATER
                or bool(UNIT_DATA[u.kind].get("amphibious")))

    def _valid_formation_point(self, u, x, y, cx, cy, taken, gap):
        """Keep a formation slot on walkable ground and clear of other slots.

        If the ideal slot is blocked (water, cliffs, edge of the map) or already
        used, take the nearest free walkable point around it instead."""
        cands = [(x, y)]
        for ring in range(1, 5):
            for k in range(8):
                ang = k * math.pi / 4
                cands.append((x + math.cos(ang) * gap * ring, y + math.sin(ang) * gap * ring))
        cands.append((cx, cy))
        for px, py in cands:
            px = clamp(px, TILE / 2, self.map.cols * TILE - TILE / 2)
            py = clamp(py, TILE / 2, self.map.rows * TILE - TILE / 2)
            if not self._formation_point_walkable(u, px, py):
                continue
            if all(dist(px, py, tx, ty) >= gap * 0.7 for tx, ty in taken):
                return (px, py)
        return (cx, cy)

    def _formation_targets(self, units, wx, wy, direction, mode):
        """[(unit, (x, y))] - one formation slot per unit around (wx, wy)."""
        n = len(units)
        if n == 0:
            return []
        if n == 1:
            return [(units[0], (wx, wy))]
        spacing = max(26.0, max(u.radius for u in units) * 2 + 16)
        fx, fy = direction
        rx, ry = -fy, fx                      # right-hand side of travel (screen coords)
        gx = sum(u.x for u in units) / n
        gy = sum(u.y for u in units) / n
        ranks = {}
        for f, l in _formation_layout(mode, n):
            ranks.setdefault(round(f, 3), []).append(l)
        # front rank first; units nearest the front of the group take the front slots
        ordered = sorted(units, key=lambda u: -((u.x - gx) * fx + (u.y - gy) * fy))
        out, taken, i = [], [], 0
        for key in sorted(ranks, reverse=True):
            laterals = sorted(ranks[key])
            chunk = ordered[i:i + len(laterals)]
            i += len(laterals)
            chunk.sort(key=lambda u: (u.x - gx) * rx + (u.y - gy) * ry)
            for u, lat in zip(chunk, laterals):
                x = wx + (fx * key + rx * lat) * spacing
                y = wy + (fy * key + ry * lat) * spacing
                pos = self._valid_formation_point(u, x, y, wx, wy, taken, spacing)
                taken.append(pos)
                out.append((u, pos))
        return out

    def _apply_move_order(self, units, wx, wy, formation="auto", direction=None, align_only=False):
        """Shared by local right-click and the networked 'move' command.
        Units arrive in formation (see FORMATION_MODES) instead of piling on one spot.
        If the destination is a resource tile, any harvesters in the group
        are pinned to mine that specific tile instead of just walking
        there and resuming their own (Trainium-priority) auto-search.
        align_only: re-arrange in place (formation buttons); harvesters are left alone."""
        if formation not in FORMATION_MODES:
            formation = "auto"
        col, row = int(wx // TILE), int(wy // TILE)
        is_resource = (not align_only and self.map.in_bounds(col, row)
                       and self.map.tiles[row][col] in RESOURCE_TILE_TYPES)
        movers = []
        dispatched_harvester = False
        for u in units:
            if align_only and u.kind == "harvester":
                continue
            u.target_entity = None
            u.order_mode = None
            u.patrol_points = []
            u.patrol_index = 0
            if is_resource and u.kind == "harvester":
                u.manual_harvest_tile = (col, row)
                u.target_pos = None
                u.state = "idle"
                dispatched_harvester = True
            else:
                u.manual_harvest_tile = None
                movers.append(u)
        if dispatched_harvester:
            play_sfx("harvest_ack", 0.9)
        if movers:
            d = direction or self._group_direction(movers, wx, wy)
            for u, pos in self._formation_targets(movers, wx, wy, d, formation):
                u.target_pos = pos

    def align_selected_units(self, mode):
        """Formation buttons: remember the mode and re-arrange the selection now."""
        if mode not in FORMATION_MODES:
            return
        self.formation_mode = mode
        units = [u for u in self.selected_units if u.alive and u.kind != "harvester"]
        if len(units) < 2:
            return
        if self.net_role == "client":
            self.net.send({"type": "align", "unit_ids": [u.id for u in self.selected_units],
                           "mode": mode})
            return
        self._apply_align_order(units, mode)

    def _apply_align_order(self, units, mode):
        units = [u for u in units if u.alive and u.kind != "harvester"]
        if len(units) < 2:
            return
        n = len(units)
        cx = sum(u.x for u in units) / n
        cy = sum(u.y for u in units) / n
        hx = sum(math.cos(u.heading) for u in units)
        hy = sum(math.sin(u.heading) for u in units)
        hd = math.hypot(hx, hy)
        direction = (hx / hd, hy / hd) if hd > 1e-3 else (0.0, -1.0)
        self._apply_move_order(units, cx, cy, formation=mode, direction=direction, align_only=True)

    def _combat_order_units(self, units):
        return [u for u in units if u.alive and u.kind in ("tank", "apc", "infantry", "rocket")]

    def _apply_attack_move_order(self, units, wx, wy, formation="auto"):
        if formation not in FORMATION_MODES:
            formation = "auto"
        combat = self._combat_order_units(units)
        if not combat:
            return
        d = self._group_direction(combat, wx, wy)
        for u, pos in self._formation_targets(combat, wx, wy, d, formation):
            u.target_entity = None
            u.target_pos = pos
            u.order_mode = "attack_move"
            u.patrol_points = []
            u.patrol_index = 0
            u.manual_harvest_tile = None

    def _apply_patrol_order(self, units, first, second):
        for u in self._combat_order_units(units):
            u.target_entity = None
            u.patrol_points = [first, second]
            u.patrol_index = 0
            u.target_pos = first
            u.order_mode = "patrol"
            u.manual_harvest_tile = None

    def transport_selected(self, action):
        """Load or unload infantry for every selected friendly APC."""
        apcs = [u for u in self.selected_units if u.alive and u.kind == "apc"]
        if not apcs:
            return 0
        if self.net_role == "client":
            self.net.send({"type": "transport", "action": action,
                           "unit_ids": [u.id for u in apcs]})
            return 0
        total = 0
        for apc in apcs:
            if action == "load":
                total += apc.load_infantry(self.player)
            elif action == "unload":
                total += apc.unload_infantry(self.player, self.map)
        return total

    def _marker_kind(self, target, wx, wy):
        if target is not None:
            return "attack"
        col, row = int(wx // TILE), int(wy // TILE)
        is_resource = self.map.in_bounds(col, row) and self.map.tiles[row][col] in RESOURCE_TILE_TYPES
        has_harvester = any(u.kind == "harvester" for u in self.selected_units)
        return "harvest" if (is_resource and has_harvester) else "move"

    def handle_right_click(self, pos):
        x, y = pos
        if self.nuke_targeting is not None:
            self.nuke_targeting = None
            play_sfx("negative", 0.8)
            return
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
            play_sfx("negative", 0.8)
            return
        if x >= VIEWPORT_W or y < TOPBAR_H or not self.selected_units:
            return
        if not self.camera.in_viewport(x, y):
            return
        wx, wy = self.camera.to_world(x, y)
        target = None
        for foe in self.enemies_of(self.player):
            for u in foe.units:
                if u.alive and dist(u.x, u.y, wx, wy) <= u.radius + 4 and self.is_world_visible(u.x, u.y):
                    target = u
                    break
            if target is not None:
                break
        if target is None:
            for foe in self.enemies_of(self.player):
                for b in foe.buildings:
                    if b.alive and b.visual_screen_rect(self.camera).collidepoint(x, y):
                        target = b
                        break
                if target is not None:
                    break
        order_col, order_row = int(wx // TILE), int(wy // TILE)
        harvest_order = (target is None and self.map.in_bounds(order_col, order_row)
                         and self.map.tiles[order_row][order_col] in RESOURCE_TILE_TYPES
                         and any(u.kind == "harvester" for u in self.selected_units))
        if self.command_mode == "patrol":
            if self.patrol_anchor is None:
                self.patrol_anchor = (wx, wy)
                self.move_marker = {"x": wx, "y": wy, "age": 0.0, "kind": "patrol"}
                return
            first = self.patrol_anchor
            second = (wx, wy)
            self.move_marker = {"x": wx, "y": wy, "age": 0.0, "kind": "patrol"}
            ids = [u.id for u in self.selected_units]
            if self.net_role == "client":
                self.net.send({"type": "patrol", "unit_ids": ids,
                               "x1": first[0], "y1": first[1], "x2": second[0], "y2": second[1]})
            else:
                self._apply_patrol_order(self.selected_units, first, second)
            play_sfx("affirmative", 0.8)
            self.command_mode = None
            self.patrol_anchor = None
            return
        if self.command_mode == "attack_move" and target is None:
            self.move_marker = {"x": wx, "y": wy, "age": 0.0, "kind": "attack_move"}
            ids = [u.id for u in self.selected_units]
            if self.net_role == "client":
                self.net.send({"type": "attack_move", "unit_ids": ids, "x": wx, "y": wy,
                               "formation": self.formation_mode})
            else:
                self._apply_attack_move_order(self.selected_units, wx, wy, self.formation_mode)
            play_sfx("affirmative", 0.8)
            self.command_mode = None
            return
        self.move_marker = {"x": wx, "y": wy, "age": 0.0, "kind": self._marker_kind(target, wx, wy)}
        if self.net_role == "client":
            ids = [u.id for u in self.selected_units]
            if target is not None:
                self.net.send({"type": "attack", "unit_ids": ids, "target_id": target.id})
            else:
                self.net.send({"type": "move", "unit_ids": ids, "x": wx, "y": wy,
                               "formation": self.formation_mode})
            play_sfx("harvest_ack" if harvest_order else "affirmative",
                     0.9 if harvest_order else 0.8)
            self.command_mode = None
            self.patrol_anchor = None
            return
        if target is not None:
            for u in self.selected_units:
                u.target_entity = target
                u.target_pos = None
                u.order_mode = None
                u.patrol_points = []
                u.manual_harvest_tile = None
        else:
            self._apply_move_order(self.selected_units, wx, wy, self.formation_mode)
        if not harvest_order:
            play_sfx("affirmative", 0.8)
        self.command_mode = None
        self.patrol_anchor = None

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
        for rect, mode in self.formation_buttons:
            if rect.collidepoint(pos):
                self.align_selected_units(mode)
                return
        for rect, action in self.nuke_buttons:
            if rect.collidepoint(pos):
                silo = self.selected_entity
                if not (isinstance(silo, Building) and silo.kind == "nuke_silo"):
                    return
                if action == "target":
                    if silo.nuke_state == "ready":
                        self.nuke_targeting = silo
                        play_sfx("affirmative", 0.8)
                elif action == "stop_target":
                    self.nuke_targeting = None
                    play_sfx("negative", 0.8)
                else:
                    self.nuke_command(silo, action)
                return
        for rect, kind, cancel_all in self.queue_cancel_buttons:
            if rect.collidepoint(pos):
                if self.net_role == "client":
                    self.net.send({"type": "cancel_produce", "kind": kind, "all": cancel_all})
                    play_sfx("negative", 0.8)
                elif self.player.cancel_production(kind, all_items=cancel_all):
                    play_sfx("negative", 0.8)
                return
        for rect, kind in self.sidebar_buttons:
            if rect.collidepoint(pos):
                if kind in WALL_DRAG_KINDS:
                    placing_other = self.player.pending_placement is not None and self.player.pending_placement != kind
                    if self.player.can_afford(BUILD_DATA[kind]["cost"]) and not placing_other:
                        self.player.pending_placement = kind
                        self.player.pending_cost = None
                elif self.net_role == "client":
                    if kind in UNIT_DATA and not (isinstance(self.selected_entity, Building) and
                                                   self.selected_entity.kind == UNIT_DATA[kind]["built_from"]):
                        return
                    if self.player.can_start(kind):
                        self.net.send({"type": "produce", "kind": kind})
                        play_sfx("affirmative", 0.8)
                else:
                    if kind in UNIT_DATA and not (isinstance(self.selected_entity, Building) and
                                                   self.selected_entity.kind == UNIT_DATA[kind]["built_from"]):
                        return
                    if self.player.start_production(kind):
                        play_sfx("affirmative", 0.8)
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
        wall_draw = []
        building_draw = []
        infantry_draw = []

        for p in self.players:
            for b in p.buildings:
                r = b.rect
                if r.right < cx - _CM or r.left > cx + cw + _CM or \
                   r.bottom < cy - _CM or r.top > cy + ch + _CM:
                    continue
                # Foundations are ground decoration. Draw them before any
                # building or infantry so a neighboring pad cannot cover an
                # entity during the later depth-sorted sprite pass.
                b.draw_foundation(screen, self.camera)
                if b.kind in WALL_DRAG_KINDS:
                    wall_draw.append(b)
                else:
                    building_draw.append((float(r.bottom) - r.centerx * 0.5, b))
            for u in p.units:
                if u.x < cx - _CM or u.x > cx + cw + _CM or \
                   u.y < cy - _CM or u.y > cy + ch + _CM:
                    continue
                infantry_draw.append((u.y - u.x * 0.5, u))

        for b in wall_draw:
            b.draw(screen, self.camera, selected=(b is self.selected_entity))

        # Buildings are painted as a coherent structure layer, then infantry
        # and vehicles are painted on top so units never disappear behind a
        # building sprite or its foundation perimeter.
        building_draw.sort(key=lambda t: t[0])
        for _, entity in building_draw:
            entity.draw(screen, self.camera, selected=(entity is self.selected_entity))
        infantry_draw.sort(key=lambda t: t[0])
        for _, entity in infantry_draw:
            entity.draw(screen, self.camera)
        for flash in self.muzzle_flashes:
            sx, sy = self.camera.to_screen(flash["x"], flash["y"])
            pct = flash["age"] / flash["max_age"]
            alpha = int(255 * (1.0 - pct))
            angle = flash["angle"]
            perp = (-math.sin(angle), math.cos(angle))
            length = 22 + int(10 * (1.0 - pct))
            base = (int(sx - math.cos(angle) * 7), int(sy - math.sin(angle) * 7))
            tip = (int(sx + math.cos(angle) * length), int(sy + math.sin(angle) * length))
            flash_surf = pygame.Surface((length + 34, length + 34), pygame.SRCALPHA)
            ox, oy = length // 2 + 17, length // 2 + 17
            pts = [
                (ox - int(perp[0] * 6), oy - int(perp[1] * 6)),
                (ox + int(math.cos(angle) * length), oy + int(math.sin(angle) * length)),
                (ox + int(perp[0] * 6), oy + int(perp[1] * 6)),
            ]
            pygame.draw.polygon(flash_surf, (255, 210, 70, alpha), pts)
            pygame.draw.circle(flash_surf, (255, 245, 180, alpha), (ox, oy), 7)
            screen.blit(flash_surf, (int(sx - ox), int(sy - oy)))
        for pr in self.projectiles:
            pr.draw(screen, self.camera)
        for fx in self.explosions:
            sx, sy = self.camera.to_screen(fx["x"], fx["y"])
            pct = fx["age"] / fx["max_age"]
            r = max(4, int(fx["radius"] * (0.35 + 0.65 * pct)))
            if fx["color"] == (180, 255, 80) and NUKE_CLOUD_FRAMES:
                frame_idx = min(len(NUKE_CLOUD_FRAMES) - 1,
                                int(clamp(pct, 0.0, 0.9999) * len(NUKE_CLOUD_FRAMES)))
                if fx.get("cloud_frame_idx") != frame_idx:
                    cloud_size = NUKE_BLAST_RADIUS * 2
                    fx["cloud_sprite"] = pygame.transform.smoothscale(
                        NUKE_CLOUD_FRAMES[frame_idx], (cloud_size, cloud_size))
                    fx["cloud_frame_idx"] = frame_idx
                cloud_sprite = fx["cloud_sprite"]
                screen.blit(cloud_sprite, cloud_sprite.get_rect(center=(int(sx), int(sy))))
            elif fx["color"] == (180, 255, 80) and AI_NUKE_EXPLOSION_SPRITE is not None:
                sprite = pygame.transform.smoothscale(AI_NUKE_EXPLOSION_SPRITE, (r * 2 + 8, r * 2 + 8))
                sprite.set_alpha(int(255 * (1 - pct)))
                screen.blit(sprite, (int(sx - r - 4), int(sy - r - 4)))
            else:
                layer = pygame.Surface((r * 2 + 8, r * 2 + 8), pygame.SRCALPHA)
                alpha = int(210 * (1 - pct))
                pygame.draw.circle(layer, (*fx["color"], alpha), (r + 4, r + 4), r)
                pygame.draw.circle(layer, (255, 235, 160, alpha), (r + 4, r + 4), max(2, r // 2), 3)
                screen.blit(layer, (int(sx - r - 4), int(sy - r - 4)))
        self.render_fallout()
        self.render_fog_of_war()
        self.render_radar_pings()
        self.render_move_marker()
        self.render_nuke_overlays()

        if self.drag_rect and self.drag_rect.w > 2 and self.drag_rect.h > 2:
            s = pygame.Surface((self.drag_rect.w, self.drag_rect.h), pygame.SRCALPHA)
            s.fill((255, 255, 255, 40))
            screen.blit(s, self.drag_rect.topleft)
            pygame.draw.rect(screen, COL_SELECT, self.drag_rect, 1)

        if self.player.pending_placement:
            mx, my = pygame.mouse.get_pos()
            kind = self.player.pending_placement
            w, h = _building_tile_size(kind)
            wx, wy = self.camera.to_world(mx, my)
            col, row = int(wx // TILE), int(wy // TILE)
            if kind in WALL_DRAG_KINDS and self.wall_drag_tile is not None:
                tiles = self._wall_line_tiles(self.wall_drag_tile[0], self.wall_drag_tile[1], col, row)
                for (tc, tr) in tiles:
                    ok = self.can_place(self.player, kind, tc, tr)
                    sx, sy = self.camera.to_screen(tc * TILE, tr * TILE)
                    _P = 0 if kind in WALL_DRAG_KINDS else BUILDING_PERIMETER * TILE
                    inner = pygame.Rect(sx, sy, w * TILE, h * TILE)
                    outer = pygame.Rect(sx - _P, sy - _P, w * TILE + _P * 2, h * TILE + _P * 2)
                    ghost = pygame.Surface((inner.w, inner.h), pygame.SRCALPHA)
                    ghost.fill((60, 220, 90, 110) if ok else (220, 60, 60, 110))
                    screen.blit(ghost, inner.topleft)
                    pygame.draw.rect(screen, (255, 255, 255), inner, 1)
            else:
                ok = self.can_place(self.player, kind, col, row)
                sx, sy = self.camera.to_screen(col * TILE, row * TILE)
                _P = 0 if kind in WALL_DRAG_KINDS else BUILDING_PERIMETER * TILE
                inner = pygame.Rect(sx, sy, w * TILE, h * TILE)
                outer = pygame.Rect(sx - _P, sy - _P, w * TILE + _P * 2, h * TILE + _P * 2)
                if kind not in WALL_DRAG_KINDS:
                    _tile_texture(screen, BUILDING_SAND_TEXTURE, outer)
                    pygame.draw.rect(screen, (103, 101, 92), outer, 1)
                ghost = pygame.Surface((inner.w, inner.h), pygame.SRCALPHA)
                ghost.fill((60, 220, 90, 100) if ok else (220, 60, 60, 100))
                screen.blit(ghost, inner.topleft)
                pygame.draw.rect(screen, (255, 255, 255), inner, 2)

        screen.set_clip(None)
        self.render_topbar()
        self.render_sidebar()
        self.render_hack_panel()
        if self.show_tech_tree:
            self.render_tech_tree()
        if self.game_over:
            self.render_gameover()

    def render_nuke_overlays(self):
        now = pygame.time.get_ticks()
        _dy = 84 if self.hack_active() else 0     # keep banners clear of the hack intel panel
        silo = self.nuke_targeting
        if silo is not None and (not silo.alive or silo.nuke_state != "ready"):
            self.nuke_targeting = silo = None
        if silo is not None:
            mx, my = pygame.mouse.get_pos()
            if self.camera.in_viewport(mx, my):
                r = int(NUKE_BLAST_RADIUS)
                layer = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
                c = (r + 2, r + 2)
                pulse = 0.5 + 0.5 * math.sin(now / 150)
                pygame.draw.circle(layer, (255, 60, 40, 45), c, r)
                pygame.draw.circle(layer, (255, 90, 50, 230), c, r, 2)
                pygame.draw.circle(layer, (255, 200, 80, int(150 + 90 * pulse)), c, r // 2, 1)
                pygame.draw.line(layer, (255, 230, 120, 230), (c[0] - 18, c[1]), (c[0] + 18, c[1]), 2)
                pygame.draw.line(layer, (255, 230, 120, 230), (c[0], c[1] - 18), (c[0], c[1] + 18), 2)
                screen.blit(layer, (mx - r - 2, my - r - 2))
            msg = FONT_SMALL.render("NUKE TARGETING - click to launch   (right-click / Esc to cancel)",
                                    True, (255, 190, 80))
            screen.blit(msg, msg.get_rect(midtop=(VIEWPORT_X0 + VIEWPORT_W // 2, VIEWPORT_Y0 + 8 + _dy)))
        elif self.player.eliminated and not self.game_over:
            t = FONT.render("YOU HAVE BEEN ELIMINATED - spectating your team", True, COL_BAD)
            box = t.get_rect(midtop=(VIEWPORT_X0 + VIEWPORT_W // 2, VIEWPORT_Y0 + 10 + _dy)).inflate(24, 10)
            pygame.draw.rect(screen, (30, 12, 12), box, border_radius=5)
            pygame.draw.rect(screen, COL_BAD, box, 2, border_radius=5)
            screen.blit(t, t.get_rect(center=box.center))
        elif now < self.banner_until and self.banner_text:
            t = FONT.render(self.banner_text, True, (255, 210, 90))
            box = t.get_rect(midtop=(VIEWPORT_X0 + VIEWPORT_W // 2, VIEWPORT_Y0 + 10 + _dy)).inflate(24, 10)
            pygame.draw.rect(screen, (30, 18, 10), box, border_radius=5)
            pygame.draw.rect(screen, (255, 150, 40), box, 2, border_radius=5)
            screen.blit(t, t.get_rect(center=box.center))

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
        color = ((235, 80, 65) if kind == "attack" else
                 (245, 175, 55) if kind == "attack_move" else
                 (100, 175, 255) if kind == "patrol" else (95, 225, 120))
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
        elif kind == "attack_move":
            pygame.draw.polygon(s, rgba, [(c[0], c[1] - 7), (c[0] + 7, c[1]),
                                          (c[0], c[1] + 7), (c[0] - 7, c[1])], 2)
            pygame.draw.circle(s, rgba, c, 3)
        elif kind == "patrol":
            pygame.draw.line(s, rgba, (c[0] - 7, c[1]), (c[0] + 7, c[1]), 2)
            pygame.draw.line(s, rgba, (c[0], c[1] - 7), (c[0], c[1] + 7), 2)
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
        foes = self.enemies_of(p)
        screen.blit(FONT.render("Enemy units %d  bldgs %d" % (sum(len(q.units) for q in foes),
                                                              sum(len(q.buildings) for q in foes)),
                                True, (150, 90, 90)), (724, 8))
        tm = FONT_SMALL.render("Team %s" % TEAM_LETTERS[p.team % len(TEAM_LETTERS)], True, p.color)
        screen.blit(tm, (652, 11))

        if self.command_mode == "attack_move":
            screen.blit(FONT_SMALL.render("A: ATTACK-MOVE - right click", True, (245, 175, 55)), (470, 9))
        elif self.command_mode == "patrol":
            patrol_text = "P: PATROL - choose second point" if self.patrol_anchor else "P: PATROL - choose first point"
            screen.blit(FONT_SMALL.render(patrol_text, True, (100, 175, 255)), (470, 9))
        screen.blit(FONT_SMALL.render("F11: fullscreen   ESC: pause", True, COL_TEXT_DIM), (SCREEN_W - 210, 10))

    def render_sidebar(self):
        x0 = VIEWPORT_W
        pygame.draw.rect(screen, COL_SIDEBAR, (x0, TOPBAR_H, SIDEBAR_W, SCREEN_H - TOPBAR_H))
        y = TOPBAR_H + 8
        self.sidebar_buttons = []
        self.queue_cancel_buttons = []
        self.formation_buttons = []
        self.nuke_buttons = []
        self.tab_buttons = []
        self.open_tree_button = None
        mx, my = pygame.mouse.get_pos()
        p = self.player
        selected_producer_kind = self.selected_entity.kind if isinstance(self.selected_entity, Building) else None

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
        local_cancel_buttons = []
        local_formation_buttons = []
        local_nuke_buttons = []

        selected = self.selected_entity or (self.selected_units[0] if self.selected_units else None)
        selected_sprite = None
        if isinstance(selected, Building):
            selected_sprite = BUILDING_SPRITES.get(selected.kind)
        elif selected is not None:
            selected_sprite = AI_APC_SPRITE if selected.kind == "apc" else AI_UNIT_SPRITES.get(selected.kind)
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
                if selected.kind == "apc":
                    detail += f"  |  Cargo {len(selected.cargo_units)}/{UNIT_DATA['apc']['transport_capacity']}  [L]oad/[U]nload"
            text_x = 18
            if selected_sprite is not None:
                thumb = selected_sprite.copy()
                thumb_rect = thumb.get_rect()
                thumb_rect.size = (min(42, thumb_rect.w), min(42, thumb_rect.h))
                thumb = pygame.transform.smoothscale(selected_sprite, thumb_rect.size)
                content_surf.blit(thumb, thumb.get_rect(center=(37, cy + 31)))
                text_x = 66
            content_surf.blit(FONT_MED.render(label, True, COL_TEXT), (text_x, cy + 5))
            if isinstance(selected, Building):
                content_surf.blit(FONT_TINY.render(detail, True, COL_TEXT_DIM), (text_x, cy + 29))
            else:
                lead = FONT_TINY.render("Unit selected  |  ", True, COL_TEXT_DIM)
                content_surf.blit(lead, (text_x, cy + 29))
                rk = FONT_TINY.render(RANK_NAMES[selected.rank], True,
                                      RANK_COLORS[min(selected.rank, len(RANK_COLORS) - 1)])
                content_surf.blit(rk, (text_x + lead.get_width(), cy + 29))
                if selected.kind == "apc":
                    extra = f"  |  Cargo {len(selected.cargo_units)}/{UNIT_DATA['apc']['transport_capacity']}  [L]oad/[U]nload"
                    content_surf.blit(FONT_TINY.render(extra, True, COL_TEXT_DIM),
                                      (text_x + lead.get_width() + rk.get_width(), cy + 29))
            draw_health_bar(content_surf, text_x, cy + 46, SIDEBAR_W - text_x - 18, 7, hp, maxhp)
        else:
            content_surf.blit(FONT.render("No selection", True, COL_TEXT_DIM), (18, cy + 20))
        cy += 72

        # Nuke silo panel: assemble (5 min bar) -> ready -> aim & launch
        if (isinstance(selected, Building) and selected.kind == "nuke_silo"
                and selected.owner is p and not p.is_ai):
            silo = selected
            content_surf.blit(FONT_TINY.render("NUCLEAR SILO", True, COL_TEXT_DIM), (12, cy))
            cy += 15

            def nuke_btn(label, action, color, y, h=30, w=None, x=10):
                w = w or (SIDEBAR_W - 20)
                r = pygame.Rect(x, y, w, h)
                screen_r = pygame.Rect(x0 + r.x, content_top - self.sidebar_scroll + r.y, r.w, r.h)
                hot = screen_r.collidepoint(mx, my)
                base = tuple(min(255, c + 25) for c in color) if hot else color
                pygame.draw.rect(content_surf, base, r, border_radius=4)
                pygame.draw.rect(content_surf, (230, 200, 160), r, 1, border_radius=4)
                t = FONT_SMALL.render(label, True, (255, 245, 230))
                content_surf.blit(t, t.get_rect(center=r.center))
                local_nuke_buttons.append((r, action))
                return r

            if silo.nuke_state == "idle":
                mins = NUKE_BUILD_TIME // 60
                afford_credits = p.credits >= NUKE_CREDIT_COST
                cost_text = FONT_TINY.render(
                    f"Tirainium: {p.credits} / {NUKE_CREDIT_COST} credits",
                    True, COL_GOOD if afford_credits else COL_BAD)
                content_surf.blit(cost_text, (12, cy))
                cy += 18
                nuke_btn(f"BUILD NUKE  ({mins}:00)", "build",
                         (120, 70, 30) if afford_credits else (70, 55, 45), cy)
                cy += 38
            elif silo.nuke_state == "building":
                frac = clamp(silo.nuke_timer / NUKE_BUILD_TIME, 0, 1)
                bar = pygame.Rect(10, cy, SIDEBAR_W - 20, 18)
                pygame.draw.rect(content_surf, (40, 28, 14), bar, border_radius=3)
                pygame.draw.rect(content_surf, (255, 150, 40),
                                 (bar.x, bar.y, int(bar.w * frac), bar.h), border_radius=3)
                pygame.draw.rect(content_surf, (230, 200, 160), bar, 1, border_radius=3)
                left = max(0, NUKE_BUILD_TIME - silo.nuke_timer) * (2.0 if p.low_power() else 1.0)
                txt = FONT_TINY.render(f"Assembling  {int(frac * 100)}%   {int(left) // 60}:{int(left) % 60:02d} left",
                                       True, (255, 245, 230))
                content_surf.blit(txt, txt.get_rect(center=bar.center))
                cy += 24
                nuke_btn("Cancel assembly", "cancel", (95, 38, 42), cy, h=22)
                cy += 30
            else:  # ready
                if self.nuke_targeting is silo:
                    t = FONT_SMALL.render("Click the map to launch", True, (255, 200, 90))
                    content_surf.blit(t, (12, cy + 2))
                    cy += 22
                    nuke_btn("Cancel targeting", "stop_target", (95, 38, 42), cy, h=24)
                    cy += 32
                else:
                    pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 220)
                    col = (int(150 + 60 * pulse), 45, 35)
                    nuke_btn("NUKE READY - TARGET", "target", col, cy, h=34)
                    cy += 42
            cy += 4

        # Formation controls for the current selection (2+ units)
        if len([u for u in self.selected_units if u.alive]) >= 2:
            content_surf.blit(FONT_TINY.render("FORMATION", True, COL_TEXT_DIM), (12, cy))
            cy += 15
            gap = 4
            n_modes = len(FORMATION_MODES)
            bw = (SIDEBAR_W - 20 - gap * (n_modes - 1)) // n_modes
            for i, mode in enumerate(FORMATION_MODES):
                r = pygame.Rect(10 + i * (bw + gap), cy, bw, 26)
                active = self.formation_mode == mode
                screen_r = pygame.Rect(x0 + r.x, content_top - self.sidebar_scroll + r.y, r.w, r.h)
                hover = screen_r.collidepoint(mx, my)
                pygame.draw.rect(content_surf, COL_TAB_ACTIVE if active else
                                 (COL_BTN_HOVER if hover else COL_BTN), r, border_radius=4)
                pygame.draw.rect(content_surf, COL_GOOD if active else (70, 70, 80), r, 1, border_radius=4)
                _draw_formation_icon(content_surf, mode, (r.x + 12, r.centery))
                lbl = FONT_TINY.render(FORMATION_LABELS[mode], True, COL_TEXT if active else COL_TEXT_DIM)
                content_surf.blit(lbl, (r.x + 23, r.centery - lbl.get_height() // 2))
                local_formation_buttons.append((r, mode))
            cy += 26 + 10

        def button(kind, category, extra_note=None):
            nonlocal cy
            data = get_data(kind)
            rect_h = 50
            rect = pygame.Rect(10, cy, SIDEBAR_W - 20, rect_h)
            is_wall = kind in WALL_DRAG_KINDS
            afford = p.can_afford(data["cost"])
            prereq = True
            if kind in UNIT_DATA:
                prereq = (selected_producer_kind == UNIT_DATA[kind]["built_from"])
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
            thumb = None
            if kind in BUILD_DATA:
                thumb = BUILDING_SPRITES.get(kind)
            elif kind in UNIT_DATA:
                thumb = AI_APC_SPRITE if kind == "apc" else AI_UNIT_SPRITES.get(kind)
            text_x = rect.x + 8
            if thumb is not None:
                tw, th = thumb.get_size()
                scale = min(34 / max(tw, 1), 34 / max(th, 1))
                icon = pygame.transform.smoothscale(thumb, (max(1, round(tw * scale)), max(1, round(th * scale))))
                content_surf.blit(icon, icon.get_rect(center=(rect.x + 23, rect.centery)))
                text_x = rect.x + 46
            name = data["name"] + (" \u2713" if already else "")
            content_surf.blit(FONT.render(name, True, COL_TEXT if enabled else COL_TEXT_DIM), (text_x, rect.y + 4))
            content_surf.blit(FONT_SMALL.render(format_cost(data["cost"]), True, COL_TEXT_DIM), (text_x, rect.y + 21))
            note_y = rect.y + 34
            if is_wall:
                if p.pending_placement == kind:
                    content_surf.blit(FONT_TINY.render("click + drag on the map", True, COL_GOOD), (rect.x + 8, note_y))
                else:
                    content_surf.blit(FONT_TINY.render("click, then drag to place a line", True, COL_TEXT_DIM), (rect.x + 8, note_y))
            else:
                items = p.queues[category]
                count = sum(1 for it in items if it["kind"] == kind)
                if count > 0:
                    # right-hand side: "-1" removes one from the queue, "X" clears every
                    # queued item of this type (only offered when there is more than one)
                    one_rect = pygame.Rect(rect.right - 30, rect.y + 5, 25, 20)
                    pygame.draw.rect(content_surf, (100, 38, 42), one_rect, border_radius=3)
                    lbl = FONT_TINY.render("-1" if count > 1 else "X", True, (255, 220, 220))
                    content_surf.blit(lbl, lbl.get_rect(center=one_rect.center))
                    local_cancel_buttons.append((one_rect, kind, False))
                    if count > 1:
                        all_rect = pygame.Rect(one_rect.x - 29, rect.y + 5, 25, 20)
                        pygame.draw.rect(content_surf, (140, 40, 44), all_rect, border_radius=3)
                        pygame.draw.rect(content_surf, (230, 120, 120), all_rect, 1, border_radius=3)
                        lbl = FONT_TINY.render("All", True, (255, 235, 235))
                        content_surf.blit(lbl, lbl.get_rect(center=all_rect.center))
                        local_cancel_buttons.append((all_rect, kind, True))
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
                    content_surf.blit(FONT_TINY.render(f"select {UNIT_DATA[kind]['built_from']}", True, (150, 90, 90)), (text_x, note_y))
                elif extra_note:
                    content_surf.blit(FONT_TINY.render(extra_note, True, COL_TEXT_DIM), (text_x, note_y))
            if not already:
                local_buttons.append((rect, kind))
            cy += rect_h + 6

        if self.selected_units:
            content_surf.blit(FONT.render(f"SELECTED: {len(self.selected_units)}", True,
                                          SELECTED_HEADER_COLOR), (12, cy))
            cy += 20
            counts = {}
            ranks = {}
            for u in self.selected_units:
                counts[u.kind] = counts.get(u.kind, 0) + 1
                ranks[u.kind] = max(ranks.get(u.kind, 0), u.rank)
            for kind, n in counts.items():
                name_surf = FONT_TINY.render(f"  {UNIT_DATA[kind]['name']} x{n} ", True, SELECTED_TEXT_COLOR)
                content_surf.blit(name_surf, (12, cy))
                rank = ranks[kind]
                rank_surf = FONT_TINY.render(f"[{RANK_NAMES[rank]}]", True,
                                             RANK_COLORS[min(rank, len(RANK_COLORS) - 1)])
                content_surf.blit(rank_surf, (12 + name_surf.get_width(), cy))
                cy += 15
            cy += 6

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
        for local_rect, kind, cancel_all in local_cancel_buttons:
            screen_rect = pygame.Rect(x0 + local_rect.x, content_top - self.sidebar_scroll + local_rect.y,
                                       local_rect.w, local_rect.h)
            self.queue_cancel_buttons.append((screen_rect, kind, cancel_all))
        for local_rect, action in local_nuke_buttons:
            screen_rect = pygame.Rect(x0 + local_rect.x, content_top - self.sidebar_scroll + local_rect.y,
                                       local_rect.w, local_rect.h)
            self.nuke_buttons.append((screen_rect, action))
        for local_rect, mode in local_formation_buttons:
            screen_rect = pygame.Rect(x0 + local_rect.x, content_top - self.sidebar_scroll + local_rect.y,
                                       local_rect.w, local_rect.h)
            self.formation_buttons.append((screen_rect, mode))
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
        cell_w = mm_w / self.map.cols
        cell_h = mm_h / self.map.rows
        for row in range(self.map.rows):
            for col in range(self.map.cols):
                if self.visible_tiles[row][col]:
                    continue
                alpha = 165 if self.explored_tiles[row][col] else 245
                cover = pygame.Surface((max(1, int(cell_w) + 1), max(1, int(cell_h) + 1)), pygame.SRCALPHA)
                cover.fill((2, 4, 8, alpha))
                screen.blit(cover, (mm_x + int(col * cell_w), mm_y + int(row * cell_h)))
        for pl in self.players:
            for b in pl.buildings:
                if pl is not self.player and not self.is_world_visible(*b.center):
                    continue
                fx = b.col / self.map.cols
                fy = b.row / self.map.rows
                dot = pygame.Rect(0, 0, 4, 4)
                dot.center = (mm_x + fx * mm_w, mm_y + fy * mm_h)
                pygame.draw.rect(screen, pl.color, dot)
            for u in pl.units:
                if not u.alive or (pl is not self.player and not self.is_world_visible(u.x, u.y)):
                    continue
                fx, fy = u.x / (self.map.cols * TILE), u.y / (self.map.rows * TILE)
                dot = pygame.Rect(0, 0, 3, 3)
                dot.center = (mm_x + fx * mm_w, mm_y + fy * mm_h)
                pygame.draw.rect(screen, pl.color, dot)
        for ping in self.radar_pings:
            fx = ping["x"] / (self.map.cols * TILE)
            fy = ping["y"] / (self.map.rows * TILE)
            px = int(mm_x + fx * mm_w)
            py = int(mm_y + fy * mm_h)
            pct = ping["age"] / ping["max_age"]
            radius = max(2, int(2 + 8 * min(1.0, ping["age"] / 0.8)))
            alpha = int(230 * (1.0 - pct))
            ping_layer = pygame.Surface((radius * 2 + 8, radius * 2 + 8), pygame.SRCALPHA)
            color = (255, 60, 60, alpha) if ping["kind"] == "unit" else (255, 190, 55, alpha)
            pygame.draw.circle(ping_layer, color, (radius + 4, radius + 4), radius, 1)
            pygame.draw.circle(ping_layer, color, (radius + 4, radius + 4), 2)
            screen.blit(ping_layer, (px - radius - 4, py - radius - 4))
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
                            play_sfx("affirmative", 0.8)
                    else:
                        if self.player.start_production(kind):
                            play_sfx("affirmative", 0.8)
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
        if self.game_over == "disconnected":
            msg, col = "CONNECTION LOST", COL_BAD
        elif self.winner_team is not None and self.winner_team == self.player.team:
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
# Match setup (teams / slots / colours) - pure data, used by skirmish + lobby
# ---------------------------------------------------------------------------
LAYOUTS = [("1v1", [1, 1]), ("2v2", [2, 2]), ("3v3", [3, 3]), ("4v4", [4, 4]),
           ("3 Teams", [2, 2, 2]), ("4 Sides", [1, 1, 1, 1])]
SLOT_KIND_LABEL = {"human": "Human", "ai": "AI", "open": "Open", "closed": "Closed"}


class MatchSetup:
    """The slot table shown on the setup screen.

    mode: "skirmish" (you vs AI), "host" (you run a lobby) or "client"
    (you joined someone's lobby). Up to 8 slots, 4 teams (A-D), at most 4
    players per team, every slot has its own selectable colour."""

    def __init__(self, mode, preset, layout="1v1"):
        self.mode = mode
        self.preset = preset
        self.local = 0
        self.free_teams = True
        self.layout = layout
        self.slots = [self._blank(i) for i in range(MAX_SLOTS)]
        if mode != "client":
            self.apply_layout(layout)

    # ---- construction ---------------------------------------------------
    @staticmethod
    def _blank(i):
        return {"kind": "closed", "name": "", "team": 0, "color": i, "cid": None, "prev": "closed"}

    def _filler(self):
        return "open" if self.mode == "host" else "ai"

    def apply_layout(self, name):
        sizes = dict(LAYOUTS).get(name, [1, 1])
        remotes = [(s["cid"], s["name"]) for s in self.slots if s["kind"] == "human" and s["cid"] is not None]
        self.layout = name
        self.slots = [self._blank(i) for i in range(MAX_SLOTS)]
        i = 0
        for team, n in enumerate(sizes):
            for _ in range(n):
                if i >= MAX_SLOTS:
                    break
                self.slots[i].update(kind=self._filler(), team=team, prev=self._filler())
                i += 1
        self.local = 0
        self.slots[0].update(kind="human", name="You", prev=self._filler(), cid=None)
        # keep connected players: seat them in the first free open seats
        for cid, nm in remotes:
            for s in self.slots:
                if s["kind"] in ("open", "ai"):
                    s.update(prev=s["kind"], kind="human", cid=cid, name=nm)
                    break

    # ---- queries ----------------------------------------------------------
    def active(self):
        return [i for i, s in enumerate(self.slots) if s["kind"] in ("human", "ai", "open")]

    def players(self):
        return [i for i, s in enumerate(self.slots) if s["kind"] in ("human", "ai")]

    def team_counts(self):
        c = {}
        for i in self.active():
            t = self.slots[i]["team"]
            c[t] = c.get(t, 0) + 1
        return c

    def slot_of_cid(self, cid):
        for i, s in enumerate(self.slots):
            if s["kind"] == "human" and s["cid"] == cid and cid is not None:
                return i
        return -1

    def used_colors(self, except_slot=None):
        return {s["color"] for i, s in enumerate(self.slots)
                if i != except_slot and s["kind"] != "closed"}

    # ---- editing ------------------------------------------------------------
    def cycle_kind(self, i):
        s = self.slots[i]
        if s["kind"] == "human":
            return False
        order = ["ai", "closed"] if self.mode == "skirmish" else ["open", "ai", "closed"]
        cur = order.index(s["kind"]) if s["kind"] in order else -1
        nxt = order[(cur + 1) % len(order)]
        if nxt != "closed" and self.team_counts().get(s["team"], 0) >= MAX_TEAM_SIZE and s["kind"] == "closed":
            return False
        s["kind"] = nxt
        s["prev"] = nxt
        if nxt != "closed" and s["color"] in self.used_colors(i):
            self.cycle_color(i, 1)
        return True

    def cycle_team(self, i, step=1):
        s = self.slots[i]
        counts = self.team_counts()
        for k in range(1, len(TEAM_LETTERS) + 1):
            t = (s["team"] + step * k) % len(TEAM_LETTERS)
            if s["kind"] == "closed" or counts.get(t, 0) < MAX_TEAM_SIZE:
                s["team"] = t
                return True
        return False

    def cycle_color(self, i, step=1):
        s = self.slots[i]
        used = self.used_colors(i)
        n = len(COLOR_PALETTE)
        for k in range(1, n + 1):
            c = (s["color"] + step * k) % n
            if c not in used:
                s["color"] = c
                return True
        return False

    def take(self, i):
        """Local human moves to slot i (skirmish / host)."""
        s = self.slots[i]
        if i == self.local or s["kind"] == "human":
            return False
        old = self.slots[self.local]
        if self.team_counts().get(s["team"], 0) >= MAX_TEAM_SIZE and s["kind"] == "closed":
            return False
        old.update(kind=old["prev"] if old["prev"] in ("ai", "open") else self._filler(), name="", cid=None)
        s.update(prev=s["kind"], kind="human", name="You", cid=None)
        self.local = i
        if s["color"] in self.used_colors(i):
            self.cycle_color(i, 1)
        return True

    def claim(self, i, cid, name):
        """A connected client sits down in slot i (host side)."""
        s = self.slots[i]
        if s["kind"] not in ("open", "ai"):
            return False
        self.release_cid(cid)
        s.update(prev=s["kind"], kind="human", cid=cid, name=name)
        return True

    def release_cid(self, cid):
        for s in self.slots:
            if s["kind"] == "human" and s["cid"] == cid and cid is not None:
                s.update(kind=s["prev"] if s["prev"] in ("ai", "open") else "open", cid=None, name="")

    def balance(self):
        """Pad smaller teams with AI allies so every team ends up the same size."""
        counts = self.team_counts()
        if len(counts) < 2:
            return False
        target = min(MAX_TEAM_SIZE, max(counts.values()))
        changed = False
        for team in sorted(counts):
            while counts[team] < target and len(self.active()) < MAX_SLOTS:
                free = next((i for i, s in enumerate(self.slots) if s["kind"] == "closed"), None)
                if free is None:
                    return changed
                s = self.slots[free]
                s.update(kind="ai", prev="ai", team=team)
                if s["color"] in self.used_colors(free):
                    self.cycle_color(free, 1)
                counts[team] += 1
                changed = True
        return changed

    def validate(self):
        """(ok, message). Open seats are closed at the start, so they are only a warning."""
        pl = self.players()
        teams = {self.slots[i]["team"] for i in pl}
        if not any(self.slots[i]["kind"] == "human" for i in pl):
            return False, "Need at least one human player"
        if len(teams) < 2:
            return False, "Need at least two opposing teams"
        for t in teams:
            if sum(1 for i in pl if self.slots[i]["team"] == t) > MAX_TEAM_SIZE:
                return False, "A team can have at most %d players" % MAX_TEAM_SIZE
        return True, ""

    def to_match(self):
        """The match dict handed to Game (open seats become closed)."""
        out = []
        for s in self.slots:
            d = dict(s)
            if d["kind"] == "open":
                d["kind"] = "closed"
            out.append(d)
        return {"slots": out}

    # ---- network ------------------------------------------------------------
    def serialize(self):
        return {"slots": self.slots, "layout": self.layout, "free_teams": self.free_teams}

    @classmethod
    def from_net(cls, cfg, preset, you):
        m = cls("client", preset, cfg.get("layout", "1v1"))
        m.slots = [dict(s) for s in cfg["slots"]]
        m.free_teams = cfg.get("free_teams", True)
        m.local = you
        return m


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
        self.setup = None            # MatchSetup while on the setup / lobby screen
        self.setup_buttons = []      # (rect, action, arg) rebuilt every frame
        self.setup_message = ""
        self.cid_names = {}          # host: connection id -> display name
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
            "new_game": make_button(pygame.Rect(SCREEN_W // 2 - 130, 330, 260, 54), "New Game (Skirmish)"),
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
    def start_new_game(self, preset, match=None, local_slot=0):
        seed = preset["seed"] if preset["seed"] is not None else random.randint(0, 999999)
        self.game = Game(preset["cols"], preset["rows"], seed=seed, biome=preset["biome"],
                         match=match, local_slot=local_slot)
        self.state = "PLAYING"
        self.paused = False

    def open_setup(self, mode, preset):
        self.setup = MatchSetup(mode, preset)
        self.setup_message = ""
        self.state = "SETUP"

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
        self.cid_names = {}
        self.open_setup("host", preset)

    def host_broadcast(self):
        st = self.setup
        if not (self.net and st):
            return
        idx = MAP_PRESETS.index(st.preset) if st.preset in MAP_PRESETS else 0
        for cid in self.net.client_ids:
            self.net.send_to(cid, {"type": "lobby", "cfg": st.serialize(), "you": st.slot_of_cid(cid),
                                   "preset_index": idx})

    def host_lobby_poll(self):
        st = self.setup
        if not (self.net and st):
            return
        changed = False
        for cid in self.net.new_connections():
            self.cid_names[cid] = "Player %d" % (cid + 1)
            # seat newcomers in the first open seat so they can see the lobby at once
            first = next((i for i, sl in enumerate(st.slots) if sl["kind"] == "open"), None)
            if first is not None:
                st.claim(first, cid, self.cid_names[cid])
            changed = True
        for cid, msg in self.net.poll():
            t = msg.get("type")
            me = st.slot_of_cid(cid)
            if t == "hello":
                self.cid_names[cid] = str(msg.get("name") or "Player %d" % (cid + 1))[:16]
                if me >= 0:
                    st.slots[me]["name"] = self.cid_names[cid]
            elif t == "claim":
                i = int(msg.get("slot", -1))
                if 0 <= i < MAX_SLOTS:
                    st.claim(i, cid, self.cid_names.get(cid, "Player %d" % (cid + 1)))
            elif t == "color" and me >= 0 and msg.get("slot") == me:
                st.cycle_color(me, 1 if msg.get("dir", 1) > 0 else -1)
            elif t == "team" and me >= 0 and msg.get("slot") == me and st.free_teams:
                st.cycle_team(me, 1 if msg.get("dir", 1) > 0 else -1)
            changed = True
        for cid in self.net.dropped():
            st.release_cid(cid)
            changed = True
        if changed:
            self.host_broadcast()

    def host_start_game(self):
        st = self.setup
        ok, msg = st.validate()
        if not ok:
            self.setup_message = msg
            return
        for cid in self.net.client_ids:
            if st.slot_of_cid(cid) < 0:
                self.setup_message = "Every connected player needs a seat"
                return
        preset = st.preset
        seed = preset["seed"] if preset["seed"] is not None else random.randint(0, 999999)
        match = st.to_match()
        clients = self.net.client_ids
        for cid in clients:
            self.net.send_to(cid, {"type": "start", "seed": seed, "cols": preset["cols"],
                                   "rows": preset["rows"], "biome": preset["biome"],
                                   "slots": match["slots"], "you": st.slot_of_cid(cid)})
        self.net.stop_accepting()
        if clients:
            self.game = Game(preset["cols"], preset["rows"], seed=seed, biome=preset["biome"],
                             net_role="host", net=self.net, match=match, local_slot=st.local)
        else:
            self.close_network()      # nobody joined: it is just a skirmish
            self.game = Game(preset["cols"], preset["rows"], seed=seed, biome=preset["biome"],
                             match=match, local_slot=st.local)
        self.state = "PLAYING"
        self.paused = False

    def skirmish_start(self):
        st = self.setup
        ok, msg = st.validate()
        if not ok:
            self.setup_message = msg
            return
        self.start_new_game(st.preset, st.to_match(), st.local)

    # ---- multiplayer: joining ---------------------------------------------
    def start_joining(self):
        ip, port = net.parse_address(self.ip_input.text)
        if not ip:
            self.join_error = "Enter the host's IP address"
            return
        self.join_error = None
        self.net = net.Client(ip, port)
        self.hello_sent = False
        self.state = "MP_JOIN_WAIT"

    def check_join_start(self):
        if not self.net:
            return
        if not getattr(self, "hello_sent", True) and self.net.connected:
            self.net.send({"type": "hello", "name": getattr(self, "player_name", "") or ""})
            self.hello_sent = True
        for msg in self.net.poll():
            self.client_lobby_message(msg)

    def client_lobby_message(self, msg):
        t = msg.get("type")
        if t == "lobby":
            idx = int(msg.get("preset_index", 0))
            preset = MAP_PRESETS[idx] if 0 <= idx < len(MAP_PRESETS) else MAP_PRESETS[0]
            self.setup = MatchSetup.from_net(msg["cfg"], preset, msg.get("you", -1))
            if self.state in ("MP_JOIN_WAIT", "SETUP"):
                self.state = "SETUP"
        elif t == "start":
            you = msg.get("you", -1)
            if you < 0:
                self.setup_message = "You have no seat in this match"
                return
            self.game = Game(msg["cols"], msg["rows"], seed=msg["seed"], biome=msg["biome"],
                             net_role="client", net=self.net,
                             match={"slots": msg["slots"]}, local_slot=you)
            self.state = "PLAYING"
            self.paused = False

    # ---- setup screen: clicks ---------------------------------------------
    def setup_click(self, pos, button=1):
        for rect, action, arg in self.setup_buttons:
            if rect.collidepoint(pos):
                self.setup_action(action, arg, button)
                return

    def setup_action(self, action, arg, button=1):
        st = self.setup
        step = 1 if button == 1 else -1
        changed = False
        self.setup_message = ""
        if action == "back":
            self.close_network()
            self.setup = None
            self.state = "MENU" if st.mode == "skirmish" else "MP_MENU"
            return
        if action == "start":
            if st.mode == "skirmish":
                self.skirmish_start()
            elif st.mode == "host":
                self.host_start_game()
            return
        if st.mode == "client":
            if action == "take":
                self.net.send({"type": "claim", "slot": arg})
            elif action == "color":
                self.net.send({"type": "color", "slot": arg, "dir": step})
            elif action == "team":
                self.net.send({"type": "team", "slot": arg, "dir": step})
            return
        if action == "color":
            changed = st.cycle_color(arg, step)
        elif action == "team":
            changed = st.cycle_team(arg, step)
        elif action == "kind":
            changed = st.cycle_kind(arg)
        elif action == "take":
            changed = st.take(arg)
        elif action == "layout":
            st.apply_layout(arg)
            changed = True
        elif action == "balance":
            changed = st.balance()
            if not changed:
                self.setup_message = "Teams are already balanced"
        elif action == "free_teams":
            st.free_teams = not st.free_teams
            changed = True
        if changed and st.mode == "host":
            self.host_broadcast()

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
                        self.open_setup("skirmish", card["preset"])
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

        elif self.state == "SETUP":
            if event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
                self.setup_click(event.pos, event.button)
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.setup_action("back", None)

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
                if self.game.nuke_targeting is not None:
                    self.game.nuke_targeting = None
                    play_sfx("negative", 0.8)
                    return
                if self.game.command_mode is not None:
                    self.game.command_mode = None
                    self.game.patrol_anchor = None
                    play_sfx("negative", 0.8)
                    return
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
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_h:
                self.game.start_hack()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_l:
                self.game.transport_selected("load")
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_u:
                self.game.transport_selected("unload")
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_a:
                self.game.command_mode = "attack_move"
                self.game.patrol_anchor = None
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_p:
                self.game.command_mode = "patrol"
                self.game.patrol_anchor = None

    def update(self, dt):
        if self.state == "MP_JOIN_WAIT":
            self.check_join_start()
        elif self.state == "SETUP" and self.setup is not None:
            if self.setup.mode == "host":
                self.host_lobby_poll()
            elif self.setup.mode == "client":
                self.check_join_start()
                if self.net is not None and not self.net.connected and not self.net.connecting:
                    self.close_network()
                    self.setup = None
                    self.join_error = "Disconnected from the host"
                    self.state = "MP_JOIN_ENTER"
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
        elif self.state == "SETUP":
            self.render_setup()
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

    TEAM_LABEL_COLORS = [(120, 175, 255), (255, 125, 125), (125, 225, 135), (245, 205, 95)]

    def render_setup(self):
        st = self.setup
        screen.fill((14, 16, 14))
        mx, my = pygame.mouse.get_pos()
        self.setup_buttons = []
        mode = st.mode
        title = {"skirmish": "SKIRMISH SETUP", "host": "HOST LOBBY", "client": "LOBBY"}[mode]
        screen.blit(FONT_MED.render(title, True, COL_TEXT), (40, 30))
        sub = {"skirmish": "Pick your side, set the AI teams and colours.",
               "host": "Set up the teams. Players can join open seats; AI seats can be taken over.",
               "client": "Pick a seat. The host starts the match."}[mode]
        screen.blit(FONT_SMALL.render(sub, True, COL_TEXT_DIM), (40, 62))

        def button(rect, label, action=None, arg=None, enabled=True, fill=None, text_col=None, font=FONT_SMALL):
            hover = enabled and rect.collidepoint(mx, my)
            col = fill if fill is not None else (COL_BTN_DISABLED if not enabled else
                                                  (COL_BTN_HOVER if hover else COL_BTN))
            if fill is not None and hover:
                col = tuple(min(255, c + 22) for c in fill)
            pygame.draw.rect(screen, col, rect, border_radius=5)
            pygame.draw.rect(screen, (110, 110, 120) if enabled else (55, 55, 60), rect, 1, border_radius=5)
            t = font.render(label, True, text_col or (COL_TEXT if enabled else COL_TEXT_DIM))
            screen.blit(t, t.get_rect(center=rect.center))
            if enabled and action:
                self.setup_buttons.append((rect, action, arg))

        # ---- slot table ----
        tx, ty, row_h = 40, 100, 50
        table_w = max(560, SCREEN_W - tx - 330)
        for hx_, label in ((tx + 40, "COLOR"), (tx + 100, "PLAYER"), (tx + 300, "TYPE"),
                           (tx + 400, "TEAM"), (tx + 490, "")):
            screen.blit(FONT_TINY.render(label, True, COL_TEXT_DIM), (hx_, ty))
        editing = mode in ("skirmish", "host")
        for i, sl in enumerate(st.slots):
            y = ty + 20 + i * row_h
            row = pygame.Rect(tx, y, table_w, row_h - 6)
            kind = sl["kind"]
            mine = (i == st.local)
            pygame.draw.rect(screen, (30, 40, 30) if mine else ((26, 30, 26) if kind != "closed" else (19, 21, 19)),
                             row, border_radius=6)
            pygame.draw.rect(screen, (110, 190, 110) if mine else (60, 66, 60), row, 2 if mine else 1, border_radius=6)
            screen.blit(FONT.render(str(i + 1), True, COL_TEXT_DIM), (tx + 12, y + 12))
            # colour swatch
            sw = pygame.Rect(tx + 40, y + 6, 40, row_h - 18)
            if kind == "closed":
                pygame.draw.rect(screen, (34, 36, 34), sw, border_radius=4)
                pygame.draw.rect(screen, (60, 62, 60), sw, 1, border_radius=4)
            else:
                pygame.draw.rect(screen, COLOR_PALETTE[sl["color"]][1], sw, border_radius=4)
                pygame.draw.rect(screen, (240, 240, 240) if sw.collidepoint(mx, my) else (10, 10, 10), sw, 2, border_radius=4)
                can_color = (mode != "client") or mine
                if can_color:
                    self.setup_buttons.append((sw, "color", i))
            # name
            if kind == "human":
                nm = sl["name"] or "Player"
                if mine:
                    nm = "You" if mode != "host" else "You (host)"
                col = COL_GOOD
            elif kind == "ai":
                nm, col = "AI Commander", (225, 190, 120)
            elif kind == "open":
                nm, col = "- open seat -", COL_TEXT_DIM
            else:
                nm, col = "closed", (95, 95, 100)
            screen.blit(FONT.render(nm, True, col), (tx + 100, y + 12))
            # type button
            kb = pygame.Rect(tx + 300, y + 6, 88, row_h - 18)
            can_kind = editing and kind != "human"
            button(kb, SLOT_KIND_LABEL[kind], "kind" if can_kind else None, i, enabled=can_kind)
            # team button
            tb = pygame.Rect(tx + 400, y + 6, 76, row_h - 18)
            can_team = (editing) or (mode == "client" and mine and st.free_teams)
            tcol = self.TEAM_LABEL_COLORS[sl["team"] % 4]
            button(tb, "Team " + TEAM_LETTERS[sl["team"] % 4], "team" if can_team else None, i,
                   enabled=can_team and kind != "closed" or (editing and kind == "closed"),
                   text_col=tcol if kind != "closed" else (90, 90, 95))
            # take-seat button
            can_take = (not mine) and (kind in ("open", "ai") or (editing and kind == "closed"))
            if mode == "client" and kind == "closed":
                can_take = False
            if can_take:
                label = "Sit here" if mode == "client" else "Take"
                button(pygame.Rect(tx + 490, y + 6, 88, row_h - 18), label, "take", i)

        # ---- right-hand panel ----
        rx = tx + table_w + 30
        rw = SCREEN_W - rx - 30
        card = next((c for c in self.map_cards if c["preset"] is st.preset), None)
        yy = 100
        if card is not None:
            thumb = pygame.transform.smoothscale(card["thumb"], (rw, int(rw * card["thumb"].get_height() / card["thumb"].get_width())))
            screen.blit(thumb, (rx, yy))
            pygame.draw.rect(screen, (110, 110, 120), pygame.Rect(rx, yy, thumb.get_width(), thumb.get_height()), 1)
            yy += thumb.get_height() + 6
        pr = st.preset
        screen.blit(FONT_SMALL.render("%s  (%s, %dx%d)" % (pr["name"], pr["biome"], pr["cols"], pr["rows"]), True, COL_TEXT), (rx, yy))
        yy += 26
        if editing:
            screen.blit(FONT_TINY.render("TEAM LAYOUT", True, COL_TEXT_DIM), (rx, yy))
            yy += 16
            bw = (rw - 8) // 2
            for k, (nm, _sizes) in enumerate(LAYOUTS):
                r = pygame.Rect(rx + (k % 2) * (bw + 8), yy + (k // 2) * 36, bw, 30)
                button(r, nm, "layout", nm, fill=(60, 90, 70) if st.layout == nm else None)
            yy += 3 * 36 + 4
            button(pygame.Rect(rx, yy, rw, 32), "Balance teams (add AI allies)", "balance")
            yy += 40
            if mode == "host":
                button(pygame.Rect(rx, yy, rw, 30), "Players choose team: %s" % ("ON" if st.free_teams else "OFF"),
                       "free_teams")
                yy += 38
        counts = st.team_counts()
        summary = "  ".join("%s:%d" % (TEAM_LETTERS[t], n) for t, n in sorted(counts.items()))
        screen.blit(FONT_SMALL.render("Teams  " + summary, True, COL_TEXT), (rx, yy))
        yy += 22
        if len(set(counts.values())) > 1:
            screen.blit(FONT_TINY.render("Teams are uneven", True, (240, 190, 90)), (rx, yy))
            yy += 16
        if mode == "host":
            ip = net.get_local_ip()
            if self.net and self.net.error:
                screen.blit(FONT_SMALL.render("Hosting failed: " + str(self.net.error)[:40], True, COL_BAD), (rx, yy))
            else:
                screen.blit(FONT_SMALL.render("Share: %s:%d" % (ip, net.DEFAULT_PORT), True, COL_TEXT), (rx, yy))
                n_clients = len(self.net.client_ids) if self.net else 0
                screen.blit(FONT_TINY.render("%d player(s) connected" % n_clients, True, COL_TEXT_DIM), (rx, yy + 18))

        # ---- messages + start/back ----
        ok, vmsg = st.validate() if mode != "client" else (True, "")
        note = self.setup_message or (vmsg if not ok else "")
        if mode != "client" and any(sl["kind"] == "open" for sl in st.slots) and ok:
            note = note or "Empty open seats will be closed when the match starts"
        if note:
            screen.blit(FONT_SMALL.render(note, True, COL_BAD if (not ok or self.setup_message) else (240, 190, 90)),
                        (tx, ty + 20 + MAX_SLOTS * row_h + 4))
        if mode == "client" and st.local < 0:
            screen.blit(FONT_SMALL.render("Pick a seat to play", True, (240, 190, 90)), (tx, ty + 20 + MAX_SLOTS * row_h + 4))
        start_rect = pygame.Rect(SCREEN_W - 290, SCREEN_H - 80, 260, 50)
        if mode == "client":
            button(start_rect, "Waiting for host...", None, None, enabled=False, font=FONT_MED)
        else:
            button(start_rect, "Start Match", "start", None, enabled=ok, font=FONT_MED)
        button(self.back_button["rect"], "Back", "back", None, font=FONT)

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
                  f"ai(credits={int(g.ai.credits)}, buildings={len(g.ai.buildings)}, units={len(g.ai.units)}) players={len(g.players)} "
                  f"projectiles={len(g.projectiles)} camera=({g.camera.x:.0f},{g.camera.y:.0f}) game_over={g.game_over}")
            running = False

    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
