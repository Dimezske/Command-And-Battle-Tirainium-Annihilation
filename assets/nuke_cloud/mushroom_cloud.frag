#version 330

in vec2 v_uv;
out vec4 fragColor;
uniform float u_progress;
uniform float u_frame;

float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

float noise2(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash21(i);
    float b = hash21(i + vec2(1.0, 0.0));
    float c = hash21(i + vec2(0.0, 1.0));
    float d = hash21(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float fbm(vec2 p) {
    float v = 0.0;
    float amp = 0.5;
    for (int i = 0; i < 5; ++i) {
        v += amp * noise2(p);
        p = mat2(1.62, 1.18, -1.18, 1.62) * p;
        amp *= 0.5;
    }
    return v;
}

void main() {
    float t = clamp(u_progress, 0.0, 1.0);
    vec2 p = v_uv * 2.0 - 1.0;
    float r = length(p);
    float angle = atan(p.y, p.x);

    // From directly above, the cap reads as a broad, turbulent circular bloom.
    // Its edge billows and curls as the fallout ring races outward.
    float grow = smoothstep(0.02, 0.88, t);
    float cloudRadius = mix(0.08, 0.98, grow);
    float rot = u_frame * 0.018;
    vec2 rotated = mat2(cos(rot), -sin(rot), sin(rot), cos(rot)) * p;
    float coarse = fbm(rotated * 5.2 + vec2(u_frame * 0.018, -u_frame * 0.013));
    float detail = fbm(rotated * 12.0 + vec2(-u_frame * 0.032, u_frame * 0.026));
    float angularBillow = fbm(vec2(angle * 2.8 + u_frame * 0.012, r * 7.0 - u_frame * 0.018));
    float edgeWarp = ((coarse - 0.48) * 0.18 + (angularBillow - 0.5) * 0.16)
                     * smoothstep(0.12, 0.56, t);
    float edge = cloudRadius + edgeWarp;
    float cloudDisk = 1.0 - smoothstep(edge - 0.12, edge + 0.045, r);

    // Nested whorls suggest an overhead view into the rotating mushroom cap.
    float spiral = 0.5 + 0.5 * sin(5.0 * angle + r * 19.0 - u_frame * 0.10
                                   + (coarse - 0.5) * 3.2);
    float innerPlume = 1.0 - smoothstep(cloudRadius * 0.60, cloudRadius * 0.98, r);
    float innerVortex = 1.0 - smoothstep(0.02, 0.32, r);
    float density = cloudDisk * (0.52 + 0.24 * coarse + 0.12 * detail + 0.12 * spiral);
    density += innerVortex * 0.20 * smoothstep(0.10, 0.36, t);

    // A bright, expanding ground-zero flash and shock ring lead the smoke bloom.
    float flashRadius = mix(0.035, 0.39, smoothstep(0.0, 0.19, t));
    float flashDisk = 1.0 - smoothstep(flashRadius - 0.035, flashRadius + 0.12, r);
    float flashFade = 1.0 - smoothstep(0.045, 0.29, t);
    float shockRadius = mix(0.08, 1.02, smoothstep(0.02, 0.48, t));
    float shockRing = exp(-abs(r - shockRadius) * 42.0)
                      * (1.0 - smoothstep(0.22, 0.72, t));

    // Heat dissipates into ochre smoke, then a muted green-grey fallout canopy.
    float age = smoothstep(0.16, 0.78, t);
    vec3 hotSmoke = mix(vec3(0.62, 0.24, 0.075), vec3(0.78, 0.48, 0.22),
                        0.5 + 0.5 * spiral);
    vec3 falloutSmoke = mix(vec3(0.27, 0.39, 0.30), vec3(0.62, 0.62, 0.43),
                            0.45 + 0.45 * coarse);
    vec3 smokeColor = mix(hotSmoke, falloutSmoke, age);
    float mottling = 0.72 + 0.52 * coarse + 0.22 * detail;
    smokeColor *= mottling;

    float centerHeat = exp(-r * r * 16.0) * (1.0 - smoothstep(0.04, 0.40, t));
    vec3 fire = mix(vec3(1.0, 0.97, 0.72), vec3(1.0, 0.30, 0.035),
                    smoothstep(0.0, 0.82, r / max(flashRadius, 0.001)));
    vec3 color = mix(smokeColor, fire, clamp(max(centerHeat, flashDisk * flashFade), 0.0, 1.0));
    color += vec3(0.72, 0.78, 0.34) * shockRing * (0.20 + 0.25 * (1.0 - age));

    float cloudFade = 1.0 - smoothstep(0.82, 1.0, t);
    float alpha = max(density * smoothstep(0.06, 0.27, t), flashDisk * flashFade);
    alpha = max(alpha, shockRing * 0.55);
    alpha *= cloudFade;
    fragColor = vec4(color, clamp(alpha, 0.0, 0.96));
}
