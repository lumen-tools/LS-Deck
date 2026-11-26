# Third-party components

## MAKO Renderer 5.0.0 (bundled in `bin/engine`)

- Project: https://github.com/eugeniosegala/MAKO
- License: GPL-3.0-or-later, with the third-party notices of the MAKO project
  (`bin/engine/licenses/MAKO-LICENSE.md`, `bin/engine/licenses/MAKO-THIRD_PARTY_NOTICES.md`)
- Files: `libmako-render.so` (64- and 32-bit), its Vulkan layer manifests and `mako-launch`, taken
  unmodified from the release archive `MAKO-Renderer-v5.0.0-linux.tar.xz`
  (SHA-256 `c59eda9681aab614474fc74a99194fe6445190fcea500eed89367e09b299fb9f`)
- Corresponding source: https://github.com/eugeniosegala/MAKO/tree/render-v5.0.0

## Lossless Scaling

Not included. The LSFG model is loaded at runtime from the user's own installation of Lossless Scaling
(THS) from Steam. Users are responsible for complying with the terms of their copy.

## Decky libraries

`@decky/ui`, `@decky/api` (LGPL-2.1), `react-icons` (MIT) and `tslib` (0BSD) are bundled into
`dist/index.js` by the build.
