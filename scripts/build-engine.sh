#!/bin/sh
# Builds the scaling/frame generation engine shipped with this plugin: MAKO Renderer 5.0.0
# (GPL-3.0-or-later, https://github.com/eugeniosegala/MAKO), modified by lumen-tools
# (patches/mako-5.0.0-fsr1.patch): its scaler is AMD FidelityFX Super Resolution 1 (EASU + RCAS,
# MIT) instead of MAKO Scaler, Steam's frame limit is held while MAKO keeps the game off
# Gamescope's WSI layer, and frame_generation_compare keeps the base frame rate limit while frame
# generation is off (A/B comparison).
#
# The Vulkan layer is built from source for 64- and 32-bit games; mako-launch, the layer manifests
# and MAKO's license files come unmodified from the official release archive. Output: bin/engine.
#
# Needs: git, curl, xz, python3, glslangValidator, cmake, ninja, a C++20 compiler with -m32
# (e.g. Ubuntu: g++-multilib), X11/XCB headers.
set -eu
here="$(cd "$(dirname "$0")/.." && pwd)"

VERSION=5.0.0
TAG="render-v$VERSION"
RELEASE_URL="https://github.com/eugeniosegala/MAKO/releases/download/$TAG/MAKO-Renderer-v$VERSION-linux.tar.xz"
RELEASE_SHA256=c59eda9681aab614474fc74a99194fe6445190fcea500eed89367e09b299fb9f
SOURCE_COMMIT=61f9dc4dca37bdd46bf3c7d0c833ee5301bc8e9b
HEADERS_TAG=v1.4.365
PATCH="$here/patches/mako-$VERSION-fsr1.patch"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

git -c advice.detachedHead=false clone -q --depth 1 -b "$TAG" https://github.com/eugeniosegala/MAKO "$work/mako"
[ "$(git -C "$work/mako" rev-parse HEAD)" = "$SOURCE_COMMIT" ] || { echo "unexpected MAKO source commit" >&2; exit 1; }
git -C "$work/mako" apply --whitespace=nowarn "$PATCH"
python3 "$work/mako/engine/scripts/generate-spatial-scaling-spirv.py"
git -c advice.detachedHead=false clone -q --depth 1 -b "$HEADERS_TAG" https://github.com/KhronosGroup/Vulkan-Headers "$work/vkh"

build() {  # build <dir> [compiler flags]
  dir="$1"; shift
  CFLAGS="$*" CXXFLAGS="$*" LDFLAGS="$*" cmake -S "$work/mako/engine" -B "$work/$dir" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DMAKO_BUILD_CLI=OFF -DBUILD_TESTING=OFF \
    -DMAKO_VULKAN_HEADERS_INCLUDE_DIR="$work/vkh/include" >/dev/null
  ninja -C "$work/$dir" mako-render >/dev/null
}
build build64
build build32 -m32

curl -fsSL -o "$work/release.tar.xz" "$RELEASE_URL"
echo "$RELEASE_SHA256  $work/release.tar.xz" | sha256sum -c - >/dev/null
mkdir "$work/release"
tar -xJf "$work/release.tar.xz" -C "$work/release"

out="$here/bin/engine"
rm -rf "$out"
mkdir -p "$out/bin" "$out/lib" "$out/lib32" "$out/share/mako-render/vulkan/implicit_layer.d" "$out/licenses"
cp "$work/release/bin/mako-launch" "$out/bin/"
cp "$work/release/share/mako-render/vulkan/implicit_layer.d/VkLayer_MAKO_render.json" \
   "$work/release/share/mako-render/vulkan/implicit_layer.d/VkLayer_MAKO_render.x86.json" \
   "$out/share/mako-render/vulkan/implicit_layer.d/"
cp "$work/build64/mako-render/libmako-render.so" "$out/lib/"
cp "$work/build32/mako-render/libmako-render.so" "$out/lib32/"
strip --strip-unneeded "$out/lib/libmako-render.so" "$out/lib32/libmako-render.so"
cp "$work/release/share/doc/mako-render/LICENSE.md" "$out/licenses/MAKO-LICENSE.md"
cp "$work/release/share/doc/mako-render/THIRD_PARTY_NOTICES.md" "$out/licenses/MAKO-THIRD_PARTY_NOTICES.md"
sed -n '1,/^\/\/ MIT LICENSE/p' "$work/mako/engine/mako-render/src/shaders/ffx_a.h" > "$out/licenses/AMD-FSR1-LICENSE.txt"
cp "$PATCH" "$out/licenses/"
echo "$VERSION+fsr1.3" > "$out/VERSION"
echo "engine: MAKO Renderer $VERSION with FSR 1 -> $out"
