#!/bin/sh
# Fetches the MAKO Renderer release (GPL-3.0-or-later) and keeps only what Lossless Scaling frame
# generation needs: the Vulkan layer (64- and 32-bit), its private layer manifests and the
# mako-launch script. MAKO FG, scaling, shaders, Remote Play and MAKO's own UI are left out.
set -eu
here="$(cd "$(dirname "$0")/.." && pwd)"

VERSION=5.0.0
URL="https://github.com/eugeniosegala/MAKO/releases/download/render-v$VERSION/MAKO-Renderer-v$VERSION-linux.tar.xz"
SHA256=c59eda9681aab614474fc74a99194fe6445190fcea500eed89367e09b299fb9f

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
curl -fsSL -o "$work/mako.tar.xz" "$URL"
echo "$SHA256  $work/mako.tar.xz" | sha256sum -c - >/dev/null
mkdir "$work/x"
tar -xJf "$work/mako.tar.xz" -C "$work/x"

out="$here/bin/engine"
rm -rf "$out"
mkdir -p "$out/bin" "$out/lib" "$out/lib32" "$out/share/mako-render/vulkan/implicit_layer.d" "$out/licenses"
cp "$work/x/bin/mako-launch" "$out/bin/"
cp "$work/x/lib/libmako-render.so" "$out/lib/"
cp "$work/x/lib32/libmako-render.so" "$out/lib32/"
cp "$work/x/share/mako-render/vulkan/implicit_layer.d/VkLayer_MAKO_render.json" \
   "$work/x/share/mako-render/vulkan/implicit_layer.d/VkLayer_MAKO_render.x86.json" \
   "$out/share/mako-render/vulkan/implicit_layer.d/"
cp "$work/x/share/doc/mako-render/LICENSE.md" "$out/licenses/MAKO-LICENSE.md"
cp "$work/x/share/doc/mako-render/THIRD_PARTY_NOTICES.md" "$out/licenses/MAKO-THIRD_PARTY_NOTICES.md"
echo "$VERSION" > "$out/VERSION"
echo "engine: MAKO Renderer $VERSION -> $out"
