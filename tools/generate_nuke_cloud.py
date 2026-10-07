#!/usr/bin/env python3
"""Render the game's nuke mushroom-cloud sprites from mushroom_cloud.frag."""
from pathlib import Path
import moderngl
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "nuke_cloud"
FRAG = OUT / "mushroom_cloud.frag"
WIDTH = HEIGHT = 384
FRAME_COUNT = 72

VERT = """#version 330
in vec2 in_pos;
out vec2 v_uv;
void main() {
    v_uv = in_pos * 0.5 + 0.5;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""


def main():
    ctx = moderngl.create_standalone_context(backend="egl")
    program = ctx.program(vertex_shader=VERT, fragment_shader=FRAG.read_text())
    # Explicit packed float32 vertex data keeps the script independent of numpy.
    import struct
    vertices = ctx.buffer(data=struct.pack("8f", -1, -1, 1, -1, -1, 1, 1, 1))
    vao = ctx.vertex_array(program, [(vertices, "2f", "in_pos")])
    texture = ctx.texture((WIDTH, HEIGHT), 4, dtype="f1")
    texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
    framebuffer = ctx.framebuffer(color_attachments=[texture])
    framebuffer.use()
    ctx.viewport = (0, 0, WIDTH, HEIGHT)
    OUT.mkdir(parents=True, exist_ok=True)

    for i in range(FRAME_COUNT):
        progress = i / (FRAME_COUNT - 1)
        framebuffer.clear(0.0, 0.0, 0.0, 0.0)
        program["u_progress"].value = progress
        program["u_frame"].value = float(i)
        vao.render(mode=moderngl.TRIANGLE_STRIP)
        rgba = framebuffer.read(components=4, alignment=1)
        image = Image.frombytes("RGBA", (WIDTH, HEIGHT), rgba)
        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        image.save(OUT / f"cloud_{i:03d}.png", optimize=True)
        if i % 10 == 0:
            print(f"Rendered {i + 1}/{FRAME_COUNT}")

    vao.release(); vertices.release(); framebuffer.release(); texture.release()
    program.release(); ctx.release()
    print(f"Wrote {FRAME_COUNT} alpha sprites to {OUT}")


if __name__ == "__main__":
    main()
