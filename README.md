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

Under the toggle you see the game and whether frame generation is really active.

## Settings

As in Lossless Scaling's *Frame Generation* panel:

| Setting | Default | |
|---|---|---|
| Type | LSFG 3.1 | fixed: the only LSFG version available on Linux |
| Mode | Fixed | *Fixed* multiplies the frame rate; *Adaptive* generates as many frames as needed to reach a target. Switching needs a game restart. |
| Multiplier | ×2 | Fixed mode: ×2, ×3 or ×4 |
| Target | 60 (LCD), 90 (OLED) | Adaptive mode: frames per second on screen |
| Flow Scale | 80 % | resolution of the motion estimation |
| Performance | on | the lighter LSFG model, recommended on the Deck |

Everything else Lossless Scaling offers (capture, cursor, cropping, scaling, render and GPU options) has
no meaning on the Deck or is set automatically.

**On the Deck's own screen (no VRR):** with *Fixed ×2*, keep the game at half the refresh rate (30 on the
LCD, 45 on the OLED), for example with Steam's frame limit. With *Adaptive*, leave the game unlimited and
set the target to the refresh rate.

## How it works

The Vulkan part is the [MAKO Renderer](https://github.com/eugeniosegala/MAKO) layer (GPL-3.0-or-later),
which loads LSFG from your Lossless Scaling installation. The plugin ships it unmodified, reduced to the
frame generation layer and its launcher (`scripts/fetch-engine.sh`): MAKO's own model, scaling, shaders and
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
./scripts/release.sh   # needs curl, xz, Node.js and pnpm
```

## License

BSD-3-Clause for this plugin's code, see [LICENSE](LICENSE). The bundled MAKO Renderer is GPL-3.0-or-later;
see [THIRD_PARTY.md](THIRD_PARTY.md).
