import { msg } from '../i18n/index.js';

/**
 * JARVIS Mark LV Style — Holographic blue intelligence overlay
 * Blue-tinted tactical readout with scanlines, grid reticle, chromatic
 * aberration and film grain. The Mark LV treatment keeps the globe readable
 * while wrapping it in a layered HUD impression.
 */
export const jarvisShader = {
  name: 'jarvis',
  uniforms: {
    scanlineStr: { default: 0.35, min: 0, max: 1, label: msg('Scanline Strength') },
    chromaticAberration: { default: 0.06, min: 0, max: 0.25, label: msg('Chromatic Aberration') },
    grainAmt: { default: 0.15, min: 0, max: 1, label: msg('Grain') },
    vignetteAmt: { default: 0.25, min: 0, max: 1, label: msg('Vignette') },
  },
  fragmentShader: /* glsl */ `
    uniform sampler2D colorTexture;
    uniform vec2 colorTextureDimensions;
    uniform float intensity;
    uniform float scanlineStr;
    uniform float chromaticAberration;
    uniform float grainAmt;
    uniform float vignetteAmt;
    in vec2 v_textureCoordinates;

    void main() {
      vec2 uv = v_textureCoordinates;
      vec2 texel = 1.0 / colorTextureDimensions;
      vec4 color = texture(colorTexture, uv);

      // Holographic blue tint (JARVIS palette)
      vec3 blueShift = vec3(0.85, 0.92, 1.0);
      vec3 tinted = mix(color.rgb, color.rgb * blueShift, 0.35 * intensity);

      // Boost contrast for a crisp readout look
      float contrast = 1.0 + 0.35 * intensity;
      vec3 contrasted = (tinted - 0.5) * contrast + 0.5;
      contrasted = clamp(contrasted, 0.0, 1.0);

      // Chromatic aberration: offset red/blue channels slightly
      vec2 offset = chromaticAberration * 0.01 * intensity * texel;
      float r = texture(colorTexture, uv + offset).r;
      float g = contrasted.g;
      float b = texture(colorTexture, uv - offset).b;
      vec3 aberrated = vec3(r, g, b);

      // Scanlines
      float scanline = sin(uv.y * colorTextureDimensions.y * 60.0) * 0.5 + 0.5;
      scanline = pow(scanline, 3.0 + 2.0 * scanlineStr * intensity);
      vec3 withScanlines = aberrated * (1.0 - 0.35 * scanline * scanlineStr * intensity);

      // Film grain
      float grain = fract(sin(dot(uv * colorTextureDimensions, vec2(12.9898, 78.233))) * 43758.5453);
      grain = (grain - 0.5) * 0.12 * grainAmt * intensity;
      vec3 grained = withScanlines + grain;

      // Subtle grid reticle hint across the center
      vec2 grid = abs(fract(uv * vec2(40.0, 40.0)) - 0.5);
      float reticle = step(0.485, min(grid.x, grid.y));
      reticle = mix(reticle, 0.0, 1.0 - intensity * 0.6);
      vec3 reticled = grained * (1.0 - 0.15 * reticle * intensity);

      // Vignette
      vec2 vigUV = uv * (1.0 - uv);
      float vig = vigUV.x * vigUV.y * 16.0;
      vig = pow(vig, 0.4 + 0.4 * vignetteAmt * intensity);
      vec3 result = reticled * vig;

      out_FragColor = vec4(mix(color.rgb, result, intensity), color.a);
    }
  `,
};
