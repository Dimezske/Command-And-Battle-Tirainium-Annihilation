"""
iso_assets.py
=============
Procedural art generator for the Tiberium Clone (Isometric Edition).

Everything here is drawn with pygame primitives (rects, polygons, circles,
per-pixel speckle noise) - no external art files, nothing copyrighted.
Generated images are cached to PNG files under ./assets/ next to this
script so subsequent launches are instant; delete the assets/ folder to
force a fresh art generation pass.

Produces:
  * Ground tiles for three biomes (grass, desert/sand, snow)
  * Water tiles
  * Resource tiles: Trainium (4 tiers: green/yellow/blue/red), trees
    (wood), and ore rock (metal)
  * Plain impassable rock/cliff tiles
  * Isometric building sprites, including defensive walls/towers

Units/vehicles/projectiles are drawn directly by the game code as simple
flat shapes and are not part of this module.
"""

import os
import random
import pygame

ART_SEED = "tiberium-clone-art-v2"
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
TILE_DIR = os.path.join(ASSET_DIR, "tiles")
BUILDING_DIR = os.path.join(ASSET_DIR, "buildings")

GRASS_VARIANTS = 5
SAND_VARIANTS = 5
SNOW_VARIANTS = 2          # explicitly just two, per spec
ROCK_VARIANTS = 3
WATER_VARIANTS = 2
TREE_VARIANTS = 2
ORE_VARIANTS = 2
TRAINIUM_TIERS = 4         # green, yellow, blue, red
TRAINIUM_VARIANTS_PER_TIER = 2


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _rng(name):
    return random.Random(f"{ART_SEED}:{name}")


def _ensure_dirs():
    os.makedirs(TILE_DIR, exist_ok=True)
    os.makedirs(BUILDING_DIR, exist_ok=True)


def _load_or_make(path, maker, alpha=False):
    if os.path.exists(path):
        try:
            surf = pygame.image.load(path)
            return surf.convert_alpha() if alpha else surf.convert()
        except Exception:
            pass
    surf = maker()
    try:
        pygame.image.save(surf, path)
    except Exception:
        pass
    return surf.convert_alpha() if alpha else surf.convert()


def _speckle(surf, rng, base, n, spread=(-14, 16), size=1):
    w, h = surf.get_size()
    for _ in range(n):
        x = rng.randint(0, w - size)
        y = rng.randint(0, h - size)
        shade = rng.choice(spread) if isinstance(spread, tuple) else rng.randint(*spread)
        c = tuple(_clamp(ch + shade, 0, 255) for ch in base)
        if size == 1:
            surf.set_at((x, y), c)
        else:
            pygame.draw.rect(surf, c, (x, y, size, size))


# ---------------------------------------------------------------------------
# Ground tiles (per biome)
# ---------------------------------------------------------------------------
def _make_grass(ts, variant):
    rng = _rng(f"grass{variant}")
    surf = pygame.Surface((ts, ts))
    base = (24 + variant * 4, 66 + variant * 7, 28 + variant * 4)
    surf.fill(base)
    _speckle(surf, rng, base, ts * ts // 12, spread=(-16, -8, 10, 18))
    tuft_col = (base[0] + 8, base[1] + 34, base[2] + 8)
    for _ in range(rng.randint(4, 8)):
        x, y = rng.randint(2, ts - 3), rng.randint(2, ts - 3)
        h = rng.randint(2, 4)
        pygame.draw.line(surf, tuft_col, (x, y), (x, y - h), 1)
    if variant % 2 == 0:
        shade = pygame.Surface((ts, ts), pygame.SRCALPHA)
        pygame.draw.polygon(shade, (0, 0, 0, 18), [(0, ts), (ts, 0), (ts, ts * 0.3), (0, ts * 0.7)])
        surf.blit(shade, (0, 0))
    return surf


def _make_sand(ts, variant):
    rng = _rng(f"sand{variant}")
    surf = pygame.Surface((ts, ts))
    base = (196 - variant * 4, 168 - variant * 5, 118 - variant * 6)
    surf.fill(base)
    _speckle(surf, rng, base, ts * ts // 10, spread=(-14, -8, 10, 16))
    ripple = (base[0] - 22, base[1] - 18, base[2] - 14)
    for _ in range(rng.randint(2, 4)):
        y = rng.randint(4, ts - 4)
        x0 = rng.randint(-4, 6)
        pygame.draw.arc(surf, ripple, (x0, y - 4, ts, 8), 3.4, 6.0, 1)
    return surf


def make_building_sand_texture(ts):
    """Make the muted grey-sand used beneath buildings and their perimeter."""
    rng = _rng(f"building-sand-{ts}")
    surf = pygame.Surface((ts, ts))
    base = (145, 142, 128)
    surf.fill(base)
    _speckle(surf, rng, base, ts * ts // 7, spread=(-18, -10, 8, 14), size=1)
    pebble_dark = (112, 109, 98)
    pebble_light = (177, 171, 151)
    for _ in range(5):
        x, y = rng.randint(2, ts - 3), rng.randint(2, ts - 3)
        pygame.draw.line(surf, pebble_dark, (x, y), (x + rng.randint(1, 3), y), 1)
    for _ in range(3):
        x, y = rng.randint(2, ts - 3), rng.randint(2, ts - 3)
        surf.set_at((x, y), pebble_light)
    return surf


def _make_snow(ts, variant):
    rng = _rng(f"snow{variant}")
    surf = pygame.Surface((ts, ts))
    base = (218 + variant * 8, 226 + variant * 6, 234 + variant * 4)
    surf.fill(base)
    _speckle(surf, rng, base, ts * ts // 14, spread=(-16, -10, 8, 14))
    shade = pygame.Surface((ts, ts), pygame.SRCALPHA)
    pygame.draw.polygon(shade, (140, 160, 190, 30), [(0, ts), (ts * 0.6, ts * 0.3), (ts, ts * 0.6), (ts * 0.4, ts)])
    surf.blit(shade, (0, 0))
    return surf


BIOME_MAKERS = {
    "grass": (_make_grass, GRASS_VARIANTS),
    "desert": (_make_sand, SAND_VARIANTS),
    "snow": (_make_snow, SNOW_VARIANTS),
}


def _make_rock(ts, variant):
    rng = _rng(f"rock{variant}")
    surf = pygame.Surface((ts, ts))
    base = (58 + variant * 6, 56 + variant * 6, 52 + variant * 6)
    surf.fill(base)
    _speckle(surf, rng, base, ts * ts // 8, spread=(-20, -12, 12, 22), size=1)
    crack_col = (base[0] - 26, base[1] - 26, base[2] - 26)
    for _ in range(rng.randint(2, 4)):
        x, y = rng.randint(2, ts - 2), rng.randint(2, ts - 2)
        for _ in range(rng.randint(2, 4)):
            nx = _clamp(x + rng.randint(-6, 6), 0, ts - 1)
            ny = _clamp(y + rng.randint(-6, 6), 0, ts - 1)
            pygame.draw.line(surf, crack_col, (x, y), (nx, ny), 1)
            x, y = nx, ny
    pygame.draw.rect(surf, (base[0] - 10, base[1] - 10, base[2] - 10), (0, 0, ts, ts), 1)
    return surf


def _make_water(ts, variant):
    rng = _rng(f"water{variant}")
    surf = pygame.Surface((ts, ts))
    base = (28 + variant * 4, 78 + variant * 6, 130 + variant * 10)
    surf.fill(base)
    wave = (base[0] + 30, base[1] + 40, base[2] + 40)
    for _ in range(rng.randint(3, 5)):
        y = rng.randint(2, ts - 2)
        x0 = rng.randint(-6, 4)
        pygame.draw.arc(surf, wave, (x0, y - 5, ts * 0.8, 10), 3.6, 5.8, 1)
    _speckle(surf, rng, base, ts * ts // 30, spread=(10, 18), size=1)
    return surf


def _make_tree(ts, variant):
    rng = _rng(f"tree{variant}")
    surf = pygame.Surface((ts, ts))
    ground = (40 + variant * 4, 62 + variant * 4, 34 + variant * 4)
    surf.fill(ground)
    _speckle(surf, rng, ground, ts * ts // 14, spread=(-12, 10))
    trunk = (70, 46, 26)
    leaf_dark = (18, 60, 26)
    leaf_light = (30, 92, 40)
    positions = [(ts * 0.32, ts * 0.62), (ts * 0.68, ts * 0.52)] if variant == 0 else [(ts * 0.5, ts * 0.55)]
    for (tx, ty) in positions:
        pygame.draw.rect(surf, trunk, (tx - 2, ty, 4, ts * 0.3))
        pygame.draw.polygon(surf, leaf_dark, [(tx, ty - ts * 0.42), (tx - ts * 0.22, ty + 2), (tx + ts * 0.22, ty + 2)])
        pygame.draw.polygon(surf, leaf_light, [(tx, ty - ts * 0.34), (tx - ts * 0.15, ty - 4), (tx + ts * 0.15, ty - 4)])
    return surf


def _make_ore(ts, variant):
    rng = _rng(f"ore{variant}")
    surf = pygame.Surface((ts, ts))
    base = (72 + variant * 6, 70 + variant * 6, 68 + variant * 6)
    surf.fill(base)
    _speckle(surf, rng, base, ts * ts // 10, spread=(-18, -10, 10, 18))
    for _ in range(rng.randint(3, 5)):
        cx, cy = rng.randint(6, ts - 6), rng.randint(6, ts - 6)
        r = rng.randint(3, 6)
        pygame.draw.polygon(surf, (base[0] - 20, base[1] - 20, base[2] - 22),
                             [(cx - r, cy + r), (cx, cy - r), (cx + r, cy + r)])
    glint = (255, 205, 90)
    for _ in range(rng.randint(4, 7)):
        x, y = rng.randint(2, ts - 3), rng.randint(2, ts - 3)
        surf.set_at((x, y), glint)
    return surf


TRAINIUM_COLORS = [
    # (dirt_base, dark, glow)  -- tier 0=green, 1=yellow, 2=blue, 3=red
    ((36, 42, 30), (20, 90, 40), (80, 220, 100)),
    ((44, 38, 24), (110, 96, 20), (235, 210, 60)),
    ((26, 34, 44), (30, 70, 130), (90, 160, 240)),
    ((44, 28, 26), (120, 30, 30), (235, 80, 70)),
]


def _make_trainium(ts, tier, variant):
    rng = _rng(f"trainium{tier}_{variant}")
    surf = pygame.Surface((ts, ts))
    dirt, dark, glow = TRAINIUM_COLORS[tier]
    surf.fill(dirt)
    _speckle(surf, rng, dirt, ts * ts // 14, spread=(-10, 8))
    count = 10 + tier * 2
    for _ in range(count):
        cx, cy = rng.randint(3, ts - 4), rng.randint(3, ts - 4)
        r = rng.randint(2, 4 + tier // 2)
        pts = []
        spikes = 4
        for i in range(spikes * 2):
            ang = i * (3.14159 / spikes)
            rad = r if i % 2 == 0 else r * 0.45
            pts.append((cx + rad * pygame.math.Vector2(1, 0).rotate_rad(ang).x,
                        cy + rad * pygame.math.Vector2(1, 0).rotate_rad(ang).y))
        pygame.draw.polygon(surf, dark, pts)
        pygame.draw.polygon(surf, glow, pts, 0 if r > 2 else 1)
        surf.set_at((_clamp(int(cx), 0, ts - 1), _clamp(int(cy - 1), 0, ts - 1)), (245, 250, 245))
    return surf


def load_terrain_tiles(tile_size):
    """Returns dict with:
       'biomes': {'grass': [...], 'desert': [...], 'snow': [...]}
       'rock': [...]  'water': [...]  'tree': [...]  'ore': [...]
       'trainium': [ [tier0 variants], [tier1], [tier2], [tier3] ]
    """
    _ensure_dirs()
    biomes = {}
    for biome, (maker, count) in BIOME_MAKERS.items():
        biomes[biome] = [
            _load_or_make(os.path.join(TILE_DIR, f"{biome}_{i}_{tile_size}.png"),
                           lambda maker=maker, i=i: maker(tile_size, i))
            for i in range(count)
        ]
    rock = [
        _load_or_make(os.path.join(TILE_DIR, f"rock_{i}_{tile_size}.png"),
                       lambda i=i: _make_rock(tile_size, i))
        for i in range(ROCK_VARIANTS)
    ]
    water = [
        _load_or_make(os.path.join(TILE_DIR, f"water_{i}_{tile_size}.png"),
                       lambda i=i: _make_water(tile_size, i))
        for i in range(WATER_VARIANTS)
    ]
    tree = [
        _load_or_make(os.path.join(TILE_DIR, f"tree_{i}_{tile_size}.png"),
                       lambda i=i: _make_tree(tile_size, i))
        for i in range(TREE_VARIANTS)
    ]
    ore = [
        _load_or_make(os.path.join(TILE_DIR, f"ore_{i}_{tile_size}.png"),
                       lambda i=i: _make_ore(tile_size, i))
        for i in range(ORE_VARIANTS)
    ]
    trainium = []
    for tier in range(TRAINIUM_TIERS):
        variants = [
            _load_or_make(os.path.join(TILE_DIR, f"trainium_{tier}_{v}_{tile_size}.png"),
                           lambda tier=tier, v=v: _make_trainium(tile_size, tier, v))
            for v in range(TRAINIUM_VARIANTS_PER_TIER)
        ]
        trainium.append(variants)
    return {"biomes": biomes, "rock": rock, "water": water, "tree": tree, "ore": ore, "trainium": trainium}


# ---------------------------------------------------------------------------
# Isometric building sprites
# ---------------------------------------------------------------------------
def _shade(color, amt):
    return tuple(_clamp(c + amt, 0, 255) for c in color)


def _iso_box(surf, cx, top_y, half_w, top_h, wall_h, color):
    T = (cx, top_y)
    R = (cx + half_w, top_y + top_h)
    B = (cx, top_y + 2 * top_h)
    L = (cx - half_w, top_y + top_h)
    left_face = [L, B, (B[0], B[1] + wall_h), (L[0], L[1] + wall_h)]
    right_face = [B, R, (R[0], R[1] + wall_h), (B[0], B[1] + wall_h)]
    pygame.draw.polygon(surf, _shade(color, -34), left_face)
    pygame.draw.polygon(surf, _shade(color, -14), right_face)
    pygame.draw.polygon(surf, _shade(color, 26), [T, R, B, L])
    pygame.draw.polygon(surf, _shade(color, -50), [T, R, B, L], 1)
    return T, R, B, L


ISO_SIZE = {
    "yard": (200, 170),
    "power": (140, 160),
    "refinery": (176, 170),
    "barracks": (128, 130),
    "factory": (196, 168),
    "turret": (86, 90),
    "research": (170, 160),
    "fence": (60, 50),
    "stonewall": (60, 56),
    "rockettower": (86, 100),
    "mgtower": (86, 96),
}

TARGET_ISO_SIZE = {
    "yard": (128, 116),
    "power": (92, 108),
    "refinery": (118, 110),
    "barracks": (92, 94),
    "factory": (122, 110),
    "turret": (58, 64),
    "research": (110, 108),
    "fence": (36, 26),
    "stonewall": (36, 30),
    "rockettower": (46, 56),
    "mgtower": (46, 54),
}

FLAG_OFFSET = {
    "yard": (14, 18),
    "power": (10, 14),
    "refinery": (12, 16),
    "barracks": (96, 12),
    "factory": (14, 14),
    "turret": (8, 8),
    "research": (10, 14),
    "fence": (4, 6),
    "stonewall": (4, 6),
    "rockettower": (6, 10),
    "mgtower": (6, 10),
}


def _make_building(kind):
    w, h = ISO_SIZE[kind]
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    cx = w // 2

    if kind == "yard":
        base = (150, 150, 165)
        _iso_box(surf, cx - 18, 46, 66, 22, 44, base)
        _iso_box(surf, cx + 44, 60, 30, 14, 30, _shade(base, 10))
        pygame.draw.line(surf, (200, 60, 40), (cx - 18, 46), (cx - 18, 20), 2)
        pygame.draw.circle(surf, (220, 70, 50), (cx - 18, 18), 3)
        pygame.draw.line(surf, (60, 60, 70), (cx - 18, 8), (cx - 30, 8), 2)

    elif kind == "power":
        base = (205, 178, 55)
        T, R, B, L = _iso_box(surf, cx, 40, 44, 18, 52, base)
        for i in range(4):
            fx = R[0] - 8 - i * 8
            pygame.draw.line(surf, _shade(base, -55), (fx, R[1] + 10), (fx, R[1] + 44), 3)
        pygame.draw.circle(surf, (255, 240, 120), (cx, 34), 6)
        pygame.draw.circle(surf, (255, 255, 200), (cx, 34), 2)

    elif kind == "refinery":
        base = (60, 140, 205)
        T, R, B, L = _iso_box(surf, cx, 54, 54, 20, 48, base)
        tank_rect = pygame.Rect(0, 0, 46, 40)
        tank_rect.center = (cx, 34)
        pygame.draw.ellipse(surf, _shade(base, 24), tank_rect)
        pygame.draw.ellipse(surf, _shade(base, -30), tank_rect, 2)
        pygame.draw.line(surf, _shade(base, -20), (cx - 30, 50), (L[0] + 6, L[1] + 8), 3)
        pygame.draw.line(surf, _shade(base, -20), (cx + 30, 50), (R[0] - 6, R[1] + 8), 3)

    elif kind == "barracks":
        base = (150, 96, 55)
        T, R, B, L = _iso_box(surf, cx, 40, 40, 16, 34, base)
        door = pygame.Rect(0, 0, 14, 20)
        door.midbottom = ((L[0] + B[0]) / 2, B[1] + 34)
        pygame.draw.rect(surf, _shade(base, -60), door)
        pygame.draw.line(surf, (90, 70, 50), (T[0] + 30, T[1] - 26), (T[0] + 30, T[1] + 2), 2)
        pygame.draw.polygon(surf, (220, 210, 200), [(T[0] + 30, T[1] - 26), (T[0] + 44, T[1] - 20), (T[0] + 30, T[1] - 14)])

    elif kind == "factory":
        base = (95, 95, 205)
        T, R, B, L = _iso_box(surf, cx, 42, 62, 20, 46, base)
        gate = pygame.Rect(0, 0, 30, 26)
        gate.midbottom = ((L[0] + B[0]) / 2 + 4, B[1] + 46)
        pygame.draw.rect(surf, _shade(base, -70), gate)
        pygame.draw.rect(surf, _shade(base, -30), gate, 2)
        chimney = pygame.Rect(0, 0, 10, 22)
        chimney.midbottom = (cx + 16, T[1] + 2)
        pygame.draw.rect(surf, _shade(base, -20), chimney)
        pygame.draw.circle(surf, (200, 200, 210, 140), (chimney.centerx, chimney.top - 4), 5)
        pygame.draw.circle(surf, (200, 200, 210, 100), (chimney.centerx + 4, chimney.top - 12), 6)

    elif kind == "turret":
        base = (170, 55, 55)
        T, R, B, L = _iso_box(surf, cx, 30, 26, 10, 20, base)
        pygame.draw.circle(surf, _shade(base, 30), (cx, T[1] + 6), 13)
        pygame.draw.circle(surf, _shade(base, -40), (cx, T[1] + 6), 13, 2)
        pygame.draw.line(surf, (30, 30, 30), (cx, T[1] + 6), (cx + 22, T[1] + 6), 4)

    elif kind == "research":
        base = (90, 175, 165)
        T, R, B, L = _iso_box(surf, cx, 46, 58, 20, 46, base)
        pygame.draw.circle(surf, _shade(base, -30), (cx, T[1] + 4), 20, 3)
        pygame.draw.circle(surf, (230, 230, 235), (cx, T[1] + 4), 9)
        pygame.draw.line(surf, (210, 210, 215), (cx, T[1] - 16), (cx, T[1] + 4), 3)
        pygame.draw.circle(surf, (255, 240, 150), (cx, T[1] - 16), 3)

    elif kind == "fence":
        base = (154, 112, 62)
        top = h * 0.34
        rail_dark = _shade(base, -48)
        rail_light = _shade(base, 28)
        pygame.draw.polygon(surf, _shade(base, -18),
                            [(3, h - 7), (w - 3, top), (w - 3, top + 9), (3, h + 3)])
        pygame.draw.line(surf, rail_dark, (3, top + 3), (w - 3, top - 5), 4)
        pygame.draw.line(surf, rail_light, (4, top + 1), (w - 4, top - 7), 1)
        pygame.draw.line(surf, rail_dark, (3, top + 12), (w - 3, top + 5), 3)
        for i in range(4):
            px = 6 + i * (w - 12) / 3
            pygame.draw.line(surf, (72, 51, 35), (px, h - 5), (px, top - 10 + i * 2), 5)
            pygame.draw.line(surf, _shade(base, 18), (px - 1, h - 5), (px - 1, top - 10 + i * 2), 1)
            pygame.draw.line(surf, (45, 38, 32), (px - 2, top - 10 + i * 2),
                             (px + 2, top - 10 + i * 2), 1)

    elif kind == "stonewall":
        base = (132, 136, 142)
        top = h * 0.28
        left = _shade(base, -30)
        right = _shade(base, -12)
        cap = _shade(base, 22)
        pygame.draw.polygon(surf, left, [(3, h - 4), (3, top + 2), (w // 2, top - 8),
                                         (w // 2, h - 12)])
        pygame.draw.polygon(surf, right, [(w // 2, h - 12), (w // 2, top - 8),
                                          (w - 3, top), (w - 3, h - 7)])
        pygame.draw.polygon(surf, cap, [(3, top + 2), (w // 2, top - 8), (w - 3, top),
                                        (w // 2, top + 7)])
        for row in range(3):
            y = top + 7 + row * 5
            pygame.draw.line(surf, (74, 78, 84), (4, y + 1), (w // 2, y - 5), 1)
            pygame.draw.line(surf, (88, 92, 98), (w // 2, y - 5), (w - 4, y - 1), 1)
        for x in (10, 25, 40):
            pygame.draw.line(surf, (82, 86, 92), (x, top + 4), (x, h - 7), 1)

    elif kind in ("rockettower", "mgtower"):
        base = (120, 120, 130) if kind == "mgtower" else (150, 90, 60)
        T, R, B, L = _iso_box(surf, cx, 40, 26, 12, 30, base)
        pygame.draw.rect(surf, _shade(base, 20), (cx - 14, T[1] - 22, 28, 22))
        pygame.draw.rect(surf, _shade(base, -30), (cx - 14, T[1] - 22, 28, 22), 2)
        if kind == "rockettower":
            pygame.draw.rect(surf, (60, 60, 65), (cx - 4, T[1] - 40, 8, 20))
            pygame.draw.polygon(surf, (200, 80, 60), [(cx - 4, T[1] - 40), (cx, T[1] - 50), (cx + 4, T[1] - 40)])
        else:
            pygame.draw.line(surf, (30, 30, 30), (cx - 6, T[1] - 12), (cx - 6, T[1] - 34), 3)
            pygame.draw.line(surf, (30, 30, 30), (cx + 6, T[1] - 12), (cx + 6, T[1] - 34), 3)

    target = TARGET_ISO_SIZE[kind]
    surf = pygame.transform.smoothscale(surf, target)
    return surf


WALL_SPRITE_DIR = os.path.join(ASSET_DIR, "walls")
_WALL_SRC_CACHE = {}


def _wall_source(kind, orient):
    """Load a cleaned, fully transparent wall sprite ('h' or 'v')."""
    key = (kind, orient)
    if key not in _WALL_SRC_CACHE:
        path = os.path.join(WALL_SPRITE_DIR, f"{kind}_{orient}.png")
        try:
            _WALL_SRC_CACHE[key] = pygame.image.load(path).convert_alpha()
        except (pygame.error, OSError):
            _WALL_SRC_CACHE[key] = None
    return _WALL_SRC_CACHE[key]


def _fit_wall(src, size, orient):
    """Scale a wall sprite so its long axis spans the tile exactly."""
    w, h = size
    if orient == "h":
        scale = w / src.get_width()
    else:
        scale = h / src.get_height()
    return pygame.transform.smoothscale(
        src, (max(1, round(src.get_width() * scale)),
              max(1, round(src.get_height() * scale))))


def make_wall_variant(kind, connections, size, enemy=False):
    """Build a wall-only image (transparent background) for the connections.

    Straight pieces use the cleaned wall sprites directly. Elbows, T-joints
    and crossings are assembled from half-sprites meeting at the tile centre.
    There is no pad, fill or shadow: every pixel outside the wall is fully
    transparent so the ground shows through.
    """
    w, h = size
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    dirs = set(connections) or {"up", "down"}
    src_h = _wall_source(kind, "h")
    src_v = _wall_source(kind, "v")
    if src_h is None or src_v is None:
        return surf

    horiz = _fit_wall(src_h, size, "h")
    vert = _fit_wall(src_v, size, "v")
    cx, cy = w // 2, h // 2

    has_h = bool(dirs & {"left", "right"})
    has_v = bool(dirs & {"up", "down"})

    if has_h and not has_v and dirs == {"left", "right"} or \
       has_h and not has_v and len(dirs) == 1:
        surf.blit(horiz, horiz.get_rect(center=(cx, cy)))
    elif has_v and not has_h and dirs == {"up", "down"} or \
         has_v and not has_h and len(dirs) == 1:
        surf.blit(vert, vert.get_rect(center=(cx, cy)))
    else:
        hw, vh = horiz.get_width(), vert.get_height()
        hr = horiz.get_rect(center=(cx, cy))
        vr = vert.get_rect(center=(cx, cy))
        if "left" in dirs:
            surf.blit(horiz, hr.topleft, pygame.Rect(0, 0, hw // 2 + 1, horiz.get_height()))
        if "right" in dirs:
            surf.blit(horiz, (hr.x + hw // 2, hr.y),
                      pygame.Rect(hw // 2, 0, hw - hw // 2, horiz.get_height()))
        if "up" in dirs:
            surf.blit(vert, vr.topleft, pygame.Rect(0, 0, vert.get_width(), vh // 2 + 1))
        if "down" in dirs:
            surf.blit(vert, (vr.x, vr.y + vh // 2),
                      pygame.Rect(0, vh // 2, vert.get_width(), vh - vh // 2))
        # Centre post (the end-cap of the straight sprite) hides the seam
        # where the arms meet so elbows / T-joints read as one piece.
        post_w = min(horiz.get_height(), horiz.get_width())
        post = horiz.subsurface(pygame.Rect(0, 0, post_w, horiz.get_height())).copy()
        surf.blit(post, post.get_rect(center=(cx, cy)))

    if enemy:
        # Tint while leaving the alpha channel (and transparency) intact.
        # `enemy` may be True (classic red) or an (r, g, b) multiply colour.
        tint = tuple(enemy) if isinstance(enemy, (tuple, list)) else (255, 110, 110)
        surf.fill((tint[0], tint[1], tint[2], 255), special_flags=pygame.BLEND_RGBA_MULT)
    return surf


def make_wall_icon(kind, size):
    """Sidebar thumbnail: the flat wall sprite on a transparent background."""
    src = _wall_source(kind, "h")
    surf = pygame.Surface(size, pygame.SRCALPHA)
    if src is None:
        return surf
    icon = _fit_wall(src, size, "h")
    surf.blit(icon, icon.get_rect(center=(size[0] // 2, size[1] // 2)))
    return surf


def load_building_sprites():
    _ensure_dirs()
    sprites = {}
    for kind in ISO_SIZE:
        tw, th = TARGET_ISO_SIZE[kind]
        version = "_v3" if kind in ("fence", "stonewall") else ""
        path = os.path.join(BUILDING_DIR, f"{kind}{version}_{tw}x{th}.png")
        if kind in ("fence", "stonewall"):
            # The default thumbnail/fallback is a clean vertical wall; the
            # game generates horizontal and elbow variants from connections.
            sprites[kind] = make_wall_icon(kind, (tw, th))
            pygame.image.save(sprites[kind], path)
        else:
            sprites[kind] = _load_or_make(path, lambda kind=kind: _make_building(kind), alpha=True)
    return sprites


def _scaled_flag_offsets():
    scaled = {}
    for kind, (fx, fy) in FLAG_OFFSET.items():
        ow, oh = ISO_SIZE[kind]
        tw, th = TARGET_ISO_SIZE[kind]
        scaled[kind] = (fx * tw / ow, fy * th / oh)
    return scaled


def generate_all(tile_size):
    """Convenience entry point used by the game at startup."""
    tiles = load_terrain_tiles(tile_size)
    buildings = load_building_sprites()
    return tiles, buildings, dict(TARGET_ISO_SIZE), _scaled_flag_offsets()
