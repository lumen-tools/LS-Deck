# LS Deck

Lossless Scaling frame generation (LSFG 3.1) and scaling on the Steam Deck, as a Decky plugin, with the
settings of Lossless Scaling's *Frame Generation* and *Scaling* panels and nothing else. Frame
generation and scaling work on their own or together.

You need your own copy of [Lossless Scaling](https://store.steampowered.com/app/993090/Lossless_Scaling/)
from Steam for LSFG and LS1. It only has to be installed, not started: the plugin uses the models in its
`Lossless.dll`. Nothing of Lossless Scaling ships with this plugin. FSR scaling works without it.

> **Not affiliated with or endorsed by Lossless Scaling (THS), AMD, Valve or the MAKO project.**
> "Lossless Scaling", "AMD", "FidelityFX", "FSR", "Steam" and "Steam Deck" are trademarks of their owners.

## Use

1. Install the plugin (Decky → Settings → Developer → *Install plugin from ZIP*).
2. Start a game, open the plugin and switch **Lossless Scaling** on.
3. Restart the game once. Turning a game on only prepares it: switch on *Frame Generation* and/or
   *Scaling* below, both start off. From then on the toggle,
   frame generation and most settings switch instantly while the game runs.

Under the toggle you see the game, whether frame generation and scaling are really active, the frame
rates and the resolutions.

## Settings

### Frame Generation

As in Lossless Scaling's *Frame Generation* panel:

| Setting | Default | |
|---|---|---|
| Type | Off | *Off* or *LSFG 3.1*, the only LSFG version available on Linux. Switches instantly while the game runs. With Off the game runs untouched and without a frame limit. |
| Compare | off | A/B while the game runs: real frames only, still at the limit (Fixed) or up to the target (Adaptive). Off again at the next game start. |
| Mode | Fixed | *Fixed* multiplies the frame rate; *Adaptive* generates as many frames as needed to reach a target |
| Multiplier | ×2 | Fixed mode: ×2, ×3 or ×4 |
| Target | 60 (LCD), 90 (OLED) | Adaptive mode: frames per second on screen |
| Flow Scale | 100 % | resolution of the motion estimation; full resolution suits the Deck's 800p |
| Performance | on | the lighter LSFG model, recommended on the Deck |
| Frame Rate Limit | 30 (LCD), 45 (OLED) | Fixed mode only, not in Lossless Scaling: limits the game's real frames, see below |

**Frame Rate Limit:** Steam's frame limit acts after frame generation, so it cannot hold the game's real
frames. In *Fixed* mode the plugin's own limit does that: on the Deck's screen (no VRR) it keeps real
frames × multiplier at the refresh rate (30 × 2 = 60 on the LCD, 45 × 2 = 90 on the OLED). More real frames
than that only pile up in front of the screen and add latency. Leave Steam's limit at the refresh rate.
*Adaptive* lets the game run free below the target and fills in frames up to it, as Lossless Scaling does; a game that runs faster is held at the target, so frames cannot pile up.

**Which frame limit to use**

| You use | Limit with | Steam's frame limit |
|---|---|---|
| Scaling only (or nothing) | Steam's frame limit | as you like |
| Frame generation, with or without scaling | the plugin's limit (*Frame Rate Limit*; Adaptive: *Target*) | at the refresh rate (60 LCD, 90 OLED) or off |
| A/B: real frames against frame generation | *Compare* | at the refresh rate or off |

With frame generation, Steam's limit counts the frames on screen, generated ones included, so it would
cut frame generation instead of holding the real frames. The live status warns while frame generation runs and Steam's
limit is set below the refresh rate. Steam's limit works at every value without frame generation, also at
40 FPS on the LCD, where Steam lowers the screen to 40 Hz.

### Scaling

As in Lossless Scaling's *Scaling* panel:

| Setting | Default | |
|---|---|---|
| Type | Off | *LS1* or *LS1 Performance* (Lossless Scaling's scaler) or *FSR* (AMD FidelityFX Super Resolution 1, both passes: EASU and RCAS). Lower the resolution in the game's settings; the scaler brings it up, before frame generation. |
| Scaling mode | Auto | *Auto* scales up to the screen size (at most 2×, aspect ratio kept) and follows resolution changes in the game; *Custom* uses the factor |
| Factor | 1.5 | *Custom* only: 1.0–2.0 in 0.05 steps, the game's resolution × factor, at most the screen size |
| Sharpness | 90 % | |

Turning scaling on or off and changing the mode or factor need a game restart; type and sharpness apply
live. Set Steam's *Game Resolution* (game properties) to the screen's maximum. If LS1 cannot be loaded, FSR
scales instead and the status says so.

Everything else Lossless Scaling offers (capture, cursor, cropping, render and GPU options) has no meaning
on the Deck or is set automatically.

## How it works

The Vulkan part is the [MAKO Renderer](https://github.com/eugeniosegala/MAKO) layer (GPL-3.0-or-later),
which loads LSFG and LS1 from your Lossless Scaling installation. The plugin builds it from source with three
changes: MAKO's own scaler is replaced by AMD FidelityFX Super Resolution 1, Steam's frame limit works
while scaling, and *Compare* keeps the limit while frame generation is off
(`patches/mako-5.0.0-fsr1.patch`, `scripts/build-engine.sh`). MAKO's own frame generation model and its
UI are not included. It is installed into `~/.local/share/ls-deck` and only loaded for games where you
switch it on, through the launch option the plugin sets:

```
~/.local/share/ls-deck/ls-deck-run <appid> %command%
```

Use only one frame generation tool per game (not together with Decky Smooth Frames, MAKO or lsfg-vk on
the same game).

## Uninstalling

Press **Remove from all games** first: it removes the launch options. Then uninstall the plugin in Decky.

## Building

```
./scripts/release.sh   # builds the engine and the frontend → release/LS-Deck.zip
```

Needs git, curl, xz, Python 3, glslangValidator, CMake, Ninja, a C++20 compiler with 32-bit support
(e.g. `g++-multilib`), X11/XCB headers, Node.js and pnpm.

## License

The plugin's own code is BSD-3-Clause, see [LICENSE](LICENSE). The bundled engine (`bin/engine`) is a
modified MAKO Renderer and stays under **GPL-3.0-or-later**; its source is MAKO's `render-v5.0.0` tag plus
`patches/mako-5.0.0-fsr1.patch` in this repository. Third-party notices in [THIRD_PARTY.md](THIRD_PARTY.md).
