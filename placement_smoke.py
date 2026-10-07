import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
pygame.init()

import cnc_isometric as game

# Grid geometry must be independent of sprite scale.
g = game.Game(32, 32, seed=7)
g.camera.x = 0
g.camera.y = 0
r1 = game.grid_screen_rect(g.camera, 4, 5, 2, 3)
r2 = game.grid_screen_rect(g.camera, 6, 5, 1, 1)
assert r1.topleft == (128, 160 + game.TOPBAR_H)
assert r1.size == (64, 96)
assert r1.right == r2.left

# Visual selection boxes must enclose the scaled artwork while remaining
# aligned to whole 32×32 groups.
yard_box = game.building_visual_grid_rect(g.camera, "yard", 8, 8, 3, 3)
assert yard_box.left % game.TILE == 0 and yard_box.top % game.TILE == 0
assert yard_box.width % game.TILE == 0 and yard_box.height % game.TILE == 0
yard_sprite = game.BUILDING_SPRITES["yard"]
yard_anchor = (8 * game.TILE + 3 * game.TILE // 2,
               8 * game.TILE + 3 * game.TILE + game.TOPBAR_H)
sprite_left = yard_anchor[0] - yard_sprite.get_width() // 2
sprite_top = yard_anchor[1] - yard_sprite.get_height()
assert yard_box.left <= sprite_left
assert yard_box.top <= sprite_top
assert yard_box.right >= sprite_left + yard_sprite.get_width()
assert yard_box.bottom >= sprite_top + yard_sprite.get_height()

# Use a clean map and a single construction yard for deterministic placement checks.
p = g.player
e = g.enemy_of(p)
g.map.tiles = [[game.TILE_GROUND for _ in range(g.map.cols)] for _ in range(g.map.rows)]
p.buildings = [game.Building("yard", p, 8, 8)]
e.buildings = []
yard = p.buildings[0]

# Close placements whose visual boxes overlap are rejected.
assert not g.can_place(p, "power", yard.col + yard.w, yard.row)
# A diagonal placement with non-intersecting visual boxes is valid inside the
# larger range, even though it is not directly beside the yard.
assert g.can_place(p, "power", 18, 0)
# A placement outside the map-relative range is invalid.
assert not g.can_place(p, "power", 22, 0)
# Overlap is invalid.
assert not g.can_place(p, "power", yard.col + yard.w - 1, yard.row)

print("placement smoke checks passed")
pygame.quit()
