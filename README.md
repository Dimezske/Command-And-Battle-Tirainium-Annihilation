# Command and Battle: Tirainium Anihilation

A Pygame-based isometric RTS prototype.

## Run

```bash
python3 -m pip install -r requirements.txt
python3 cnc_isometric.py
```

Headless startup check:

```bash
python3 cnc_isometric.py --selftest 30
```

## Nuclear silo

- Assembling a warhead costs **20,000 Tirainium credits**. The silo panel shows the current balance and price.
- Assembly takes five minutes; cancelling refunds the credits.
- Radioactive-crystal deposits are not required for silo operation. Harvested resources continue to pay out through the normal credit economy.
- A ready warhead is visible on the silo. Launching shows it rising, disappearing during high-altitude travel, and descending at the target.
- The impact radius is **450 px** (three times the previous 150 px), followed by a **40-second** damaging fallout cloud.
- The impact now transitions through a **three-second, top-down swirling fallout bloom**, rendered from the included GLSL shader.

To regenerate the baked animation sprites, install `moderngl` and `Pillow`, then run `python3 tools/generate_nuke_cloud.py` (requires EGL/OpenGL). The game loads the resulting PNG frames and does not require a shader runtime.

## Audio

`assets/sounds/` contains distinct movement loops for the Harvester, Medium Tank, and APC, plus radio replies for **Affirmative**, **Negative**, and **We can do that!** (harvester resource dispatch). If audio hardware is unavailable, the game continues with its existing optional-audio behavior.
