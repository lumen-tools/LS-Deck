# Third-party components

## MAKO Renderer 5.0.0 (bundled in `bin/engine`, modified)

- Project: https://github.com/eugeniosegala/MAKO
- License: GPL-3.0-or-later, with the third-party notices of the MAKO project
  (`bin/engine/licenses/MAKO-LICENSE.md`, `bin/engine/licenses/MAKO-THIRD_PARTY_NOTICES.md`)
- Modified by lumen-tools, 2026: MAKO Scaler's reconstruction is replaced by AMD FidelityFX Super
  Resolution 1 in two passes (EASU, then RCAS); Steam's frame limit is held for the game while MAKO
  keeps it off Gamescope's WSI layer; and a `frame_generation_compare` setting keeps the base frame
  rate limit while frame generation is off. The complete change is
  `patches/mako-5.0.0-fsr1.patch` (also shipped as `bin/engine/licenses/mako-5.0.0-fsr1.patch`).
- Files: `libmako-render.so` (64- and 32-bit), built from source by `scripts/build-engine.sh`;
  `mako-launch` and the Vulkan layer manifests unmodified from the release archive
  `MAKO-Renderer-v5.0.0-linux.tar.xz`
  (SHA-256 `c59eda9681aab614474fc74a99194fe6445190fcea500eed89367e09b299fb9f`).
- Corresponding source: MAKO's tag `render-v5.0.0` (commit
  `61f9dc4dca37bdd46bf3c7d0c833ee5301bc8e9b`) plus the patch above.

## AMD FidelityFX Super Resolution 1

`ffx_a.h` and `ffx_fsr1.h` (FSR 1 v1.20210629) are included in the patch above: MIT License,
Copyright (c) 2021 Advanced Micro Devices, Inc. (`bin/engine/licenses/AMD-FSR1-LICENSE.txt`).
AMD, FidelityFX and FSR are trademarks of Advanced Micro Devices, Inc.; this plugin is not affiliated
with or endorsed by AMD.

## Lossless Scaling

Not included. The LSFG and LS1 models are loaded at runtime from the user's own installation of
Lossless Scaling (THS) from Steam. Users are responsible for complying with the terms of their copy.

## Decky libraries

`@decky/ui`, `@decky/api` (LGPL-2.1), `react-icons` (MIT) and `tslib` (0BSD) are bundled into
`dist/index.js` by the build.
