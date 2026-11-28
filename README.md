# LS Deck

Lossless Scaling frame generation (LSFG 3.1) on the Steam Deck, as a Decky plugin, with the settings of
Lossless Scaling's *Frame Generation* panel and nothing else.

You need your own copy of [Lossless Scaling](https://store.steampowered.com/app/993090/Lossless_Scaling/)
from Steam. It only has to be installed, not started: the plugin uses the LSFG model from its
`Lossless.dll`. Nothing of Lossless Scaling ships with this plugin.

Not affiliated with Lossless Scaling (THS), MAKO or Valve.

## Use

1. Install the plugin (Decky → Settings → Developer → *Install plugin from ZIP*).
2. Start a game, open the plugin and switch **Lossless Scaling** on.
3. Restart the game once. From then on the toggle and most settings switch instantly while the game runs.

Under the toggle you see the game, whether frame generation is really active and the frame rates.

## Settings

As in Lossless Scaling's *Frame Generation* panel:

| Setting | Default | |
|---|---|---|
| Type | LSFG 3.1 | fixed: the only LSFG version available on Linux |
| Mode | Fixed | *Fixed* multiplies the frame rate; *Adaptive* generates as many frames as needed to reach a target. Switching needs a game restart. |
| Multiplier | ×2 | Fixed mode: ×2, ×3 or ×4 |
| Target | 60 (LCD), 90 (OLED) | Adaptive mode: frames per second on screen |
| Flow Scale | 100 % | resolution of the motion estimation; full resolution suits the Deck's 800p |
| Performance | on | the lighter LSFG model, recommended on the Deck |
| Frame Rate Limit | 30 (LCD), 45 (OLED) | Fixed mode only, not in Lossless Scaling: limits the game's real frames, see below |

### Scaling

As in Lossless Scaling's *Scaling* panel, with Lossless Scaling's own LS1 scaler only:

| Setting | Default | |
|---|---|---|
| Type | Off | *LS1* or *LS1 Performance*: the game renders at a lower resolution and LS1 scales it to the screen |
| Factor | 150 % | the game renders at 1/1.5 of the screen's width and height (853×533 on the Deck) |
| Sharpness | 80 % | |

Turning scaling on or off and changing the factor need a game restart; type and sharpness apply live.
LS1 costs GPU time on top of frame generation. The Deck can also scale by itself (Steam's *Scaling
Filter*: FSR, NIS), at no cost to the game.

Everything else Lossless Scaling offers (capture, cursor, cropping, render and GPU options) has no meaning
on the Deck or is set automatically.

**Frame Rate Limit:** Steam's frame limit acts after frame generation, so it cannot hold the game's real
frames. In *Fixed* mode the plugin's own limit does that: on the Deck's screen (no VRR) it keeps real
frames × multiplier at the refresh rate (30 × 2 = 60 on the LCD, 45 × 2 = 90 on the OLED). More real frames
than that only pile up in front of the screen and add latency. Leave Steam's limit at the refresh rate.
*Adaptive* lets the game run free below the target and fills in frames up to it, as Lossless Scaling does; a game that runs faster is held at the target, so frames cannot pile up.

Under the toggle you also see the game's real frame rate and what reaches the screen, e.g.
`30 real FPS → ~60 FPS`.

## How it works

The Vulkan part is the [MAKO Renderer](https://github.com/eugeniosegala/MAKO) layer (GPL-3.0-or-later),
which loads LSFG from your Lossless Scaling installation. The plugin ships it unmodified, reduced to the
frame generation and scaling layer and its launcher (`scripts/fetch-engine.sh`): MAKO's own model, shaders
and UI are not included. It is installed into `~/.local/share/ls-deck` and only loaded for games where you
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
./scripts/release.sh   # needs curl, xz, Node.js and pnpm
```

## License

BSD-3-Clause for this plugin's code, see [LICENSE](LICENSE). The bundled MAKO Renderer is GPL-3.0-or-later;
see [THIRD_PARTY.md](THIRD_PARTY.md).
