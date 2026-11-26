"""
LS Deck backend.

Lossless Scaling frame generation (LSFG 3.1) on the Steam Deck, with the settings of Lossless
Scaling's "Frame Generation" panel. The frames are made by the LSFG model in the user's own copy of
Lossless Scaling (Lossless.dll from the Steam library); nothing of Lossless Scaling ships here.

The Vulkan side is the MAKO Renderer layer (https://github.com/eugeniosegala/MAKO, GPL-3.0-or-later),
unmodified, reduced to what frame generation needs (scripts/fetch-engine.sh). It is installed into a
private folder and only loaded through its own launcher with a private layer path, so it never
clashes with a full MAKO installation.

Layout:
  ~/.local/share/ls-deck/engine/      bin/mako-launch, lib/, lib32/, layer manifests
  ~/.local/share/ls-deck/conf.toml    MAKO profile per game (re-read live by the layer)
  ~/.local/share/ls-deck/runtime-state/  live records the layer writes
  ~/.local/share/ls-deck/ls-deck-run  wrapper used in Steam launch options
  ~/.local/share/ls-deck/games/<appid> "1" or "0": does the wrapper start the layer
  DECKY_PLUGIN_SETTINGS_DIR/settings.json            UI state, single source of truth
"""

import asyncio
import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
import time

import decky

PLUGIN_NAME = "LS Deck"
BUNDLE_DIR = os.path.join(decky.DECKY_PLUGIN_DIR, "bin", "engine")  # shipped inside the plugin ZIP

HOME = decky.DECKY_USER_HOME
# Steam splits launch options at spaces: everything the launch option touches has a path without any.
DATA_DIR = os.path.join(HOME, ".local", "share", "ls-deck")
ENGINE_DIR = os.path.join(DATA_DIR, "engine")
LAUNCHER = os.path.join(ENGINE_DIR, "bin", "mako-launch")
CONF_PATH = os.path.join(DATA_DIR, "conf.toml")
RUNTIME_STATE_DIR = os.path.join(DATA_DIR, "runtime-state")  # MAKO: next to the configuration file
GAMES_DIR = os.path.join(DATA_DIR, "games")
WRAPPER_PATH = os.path.join(DATA_DIR, "ls-deck-run")

SETTINGS_DIR = decky.DECKY_PLUGIN_SETTINGS_DIR
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")
LOG_DIR = decky.DECKY_PLUGIN_LOG_DIR
STATUS_DIR = os.path.join(LOG_DIR, "games")  # <appid>.session and <appid>.log per launch
STATUS_LOG_MAX = 4 * 1024 * 1024
APPID_VAR = "LS_DECK_APPID"
LS_APPID = "993090"  # Lossless Scaling on Steam


def _deck_model():
    """'lcd', 'oled' or None, from the DMI product name (Jupiter / Galileo)."""
    try:
        with open("/sys/devices/virtual/dmi/id/board_vendor", "r") as fh:
            vendor = fh.read().strip()
        with open("/sys/devices/virtual/dmi/id/product_name", "r") as fh:
            product = fh.read().strip()
    except OSError:
        return None
    if vendor != "Valve":
        return None
    return {"Jupiter": "lcd", "Galileo": "oled"}.get(product)


DECK_MODEL = _deck_model()
REFRESH = {"lcd": 60, "oled": 90}.get(DECK_MODEL or "", 60)

# Lossless Scaling's "Frame Generation" panel. Type is always LSFG 3.1, the only one on Linux.
DEFAULT_PROFILE = {
    "mode": "fixed",          # Mode: Fixed / Adaptive
    "multiplier": 2,          # Multiplier (Fixed)
    "target": REFRESH,        # Target (Adaptive): the screen's refresh rate
    "flow_scale": 100,        # Flow Scale in percent: full at the Deck's 800p
    "performance": True,      # Performance: the lighter LSFG model, recommended on the Deck's GPU
    # Fixed mode: limit for the game's real frames (0 = off). Steam's limit acts after frame
    # generation, so on a screen without VRR this keeps base x multiplier at the refresh rate.
    "limit": REFRESH // 2,
}
CHOICES = {"mode": ("fixed", "adaptive")}
INTS = {"multiplier": (2, 4), "target": (30, 240), "flow_scale": (25, 100), "limit": (0, 240)}
BOOLS = ("performance",)


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------

def _atomic_write(path: str, data: bytes, mode: int = 0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)  # new inode: a running game keeps what it has mapped
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _write_if_changed(path: str, data: bytes, mode: int = 0o644):
    try:
        with open(path, "rb") as fh:
            if fh.read() == data:
                return
    except OSError:
        pass
    _atomic_write(path, data, mode)


def sanitize_profile(raw) -> dict:
    """Whitelist every key and value: they end up in the layer's configuration."""
    out = copy.deepcopy(DEFAULT_PROFILE)
    if not isinstance(raw, dict):
        return out
    for key, allowed in CHOICES.items():
        if raw.get(key) in allowed:
            out[key] = raw[key]
    for key, (lo, hi) in INTS.items():
        val = raw.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            val = int(round(val))
            out[key] = 0 if key == "limit" and val <= 0 else max(lo if key != "limit" else 10, min(hi, val))
    for key in BOOLS:
        if isinstance(raw.get(key), bool):
            out[key] = raw[key]
    return out


def valid_appid(appid) -> str:
    s = str(appid).strip()
    if not s.isdigit() or len(s) > 20:
        raise ValueError(f"invalid app id: {appid!r}")
    return s


def _toml_str(s: str) -> str:
    return json.dumps(s)  # a JSON string is a valid TOML basic string


# ---------------------------------------------------------------------------------------------
# Lossless Scaling (the user's own copy)
# ---------------------------------------------------------------------------------------------

def _steam_roots():
    roots = []
    for p in (os.path.join(HOME, ".local", "share", "Steam"), os.path.join(HOME, ".steam", "steam")):
        if os.path.isdir(p) and os.path.realpath(p) not in [os.path.realpath(r) for r in roots]:
            roots.append(p)
    return roots


def _library_paths():
    paths = []
    for root in _steam_roots():
        paths.append(root)
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, "r", encoding="utf-8", errors="replace") as fh:
                for m in re.finditer(r'"path"\s+"([^"]+)"', fh.read()):
                    paths.append(m.group(1).replace("\\\\", "\\"))
        except OSError:
            pass
    seen, out = set(), []
    for p in paths:
        r = os.path.realpath(p)
        if r not in seen:
            seen.add(r)
            out.append(p)
    return out


def find_lossless_dll():
    for lib in _library_paths():
        path = os.path.join(lib, "steamapps", "common", "Lossless Scaling", "Lossless.dll")
        if os.path.isfile(path):
            return path
    return None


# ---------------------------------------------------------------------------------------------
# settings -> MAKO configuration
# ---------------------------------------------------------------------------------------------

def profile_to_toml(appid: str, game: dict) -> str:
    p = sanitize_profile(game["profile"])
    adaptive = p["mode"] == "adaptive"
    lines = [
        "[[profile]]",
        f"name = {_toml_str(appid)}",
        # only LSFG: never MAKO's own model
        'frame_generation_model = "lossless-scaling"',
        "frame_generation_provisioned = true",
        # the toggle, live: off keeps the layer loaded but passes the game's frames through
        f"frame_generation_enabled = {'true' if game['enabled'] else 'false'}",
        f"adaptive = {'true' if adaptive else 'false'}",
        f"multiplier = {p['multiplier']}",
        f"target_fps = {p['target']}",
        # Lossless Scaling's Adaptive has no ceiling to set; MAKO's default
        "adaptive_max_multiplier = 3",
        # as in Lossless Scaling, Adaptive leaves the game's frame rate alone (MAKO's Steady Base Cap off)
        "adaptive_auto_base_fps_cap = false",
        f"flow_scale = {p['flow_scale'] / 100:.2f}",
        f"performance_mode = {'true' if p['performance'] else 'false'}",
        # Fixed: the plugin's limit. Adaptive: the target. Below it the game runs free, as in Lossless
        # Scaling; above it, where Lossless Scaling's capture skips the extra frames on Windows, the
        # layer sits in the game's own presents, so the game is held at the target instead of queuing.
        f"base_fps_cap = {p['target'] if adaptive else p['limit']}",
        "scaling_enabled = false",
    ]
    return "\n".join(lines) + "\n"


class Store:
    def __init__(self):
        self.data = {"games": {}}

    def load(self):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except FileNotFoundError:
            return
        except Exception as err:  # noqa: BLE001
            decky.logger.error(f"settings.json unreadable, using defaults: {err}")
            return
        games = {}
        for appid, g in (raw.get("games") or {}).items():
            if not str(appid).isdigit() or not isinstance(g, dict):
                continue
            raw_profile = g.get("profile")
            if isinstance(raw_profile, dict) and "limit" not in raw_profile and raw_profile.get("flow_scale") == 80:
                # 1.0.0 started Flow Scale at 80 %: move untouched profiles to the new default
                raw_profile = {**raw_profile, "flow_scale": DEFAULT_PROFILE["flow_scale"]}
            games[str(appid)] = {
                "name": str(g.get("name") or "")[:200],
                "enabled": bool(g.get("enabled", True)),
                "profile": sanitize_profile(raw_profile),
            }
        self.data["games"] = games

    def save(self):
        _atomic_write(SETTINGS_PATH, json.dumps(self.data, indent=2, ensure_ascii=False).encode("utf-8"))
        self.write_config()

    def effective_profile(self, appid: str) -> dict:
        g = self.data["games"].get(appid)
        return g["profile"] if g else copy.deepcopy(DEFAULT_PROFILE)

    def write_config(self):
        dll = find_lossless_dll()
        parts = [
            f"# Generated by {PLUGIN_NAME}. Edits are overwritten; use the plugin instead.",
            "version = 2",
            "",
            "[global]",
            "allow_fp16 = true",
        ]
        if dll:
            parts.append(f"dll = {_toml_str(dll)}")
        for appid, g in sorted(self.data["games"].items()):
            parts += ["", profile_to_toml(appid, g).rstrip("\n")]
        _write_if_changed(CONF_PATH, ("\n".join(parts) + "\n").encode("utf-8"))
        os.makedirs(GAMES_DIR, exist_ok=True)
        for appid, g in self.data["games"].items():
            _write_if_changed(os.path.join(GAMES_DIR, appid), b"1\n" if g["enabled"] else b"0\n")
        for name in os.listdir(GAMES_DIR):
            if name.isdigit() and name not in self.data["games"]:
                _write_if_changed(os.path.join(GAMES_DIR, name), b"0\n")


WRAPPER_TEMPLATE = r"""#!/bin/sh
# ls-deck-run - generated by the __PLUGIN__ plugin.
# Steam launch option:  __WRAPPER__ <appid> %command%
# Starts the game through MAKO's launcher with this plugin's configuration, or unchanged.
GAMES_DIR='__GAMES_DIR__'
CONF='__CONF__'
LAUNCHER='__LAUNCHER__'
STATUS_DIR='__STATUS_DIR__'

appid="$1"
case "$appid" in
  ''|*[!0-9]*) appid=0 ;;   # called without an app id: keep every argument
  *) shift ;;
esac

if [ "$#" -eq 0 ]; then
  echo "ls-deck-run: no command given (the launch option must end in %command%)" >&2
  exit 1
fi

on=0
[ "$(cat "$GAMES_DIR/$appid" 2>/dev/null)" = 1 ] && [ -x "$LAUNCHER" ] && on=1

export __APPID_VAR__="$appid"
if mkdir -p "$STATUS_DIR" 2>/dev/null; then
  {
    echo "pid=$$"
    echo "start=$(date +%s)"
    echo "on=$on"
  } > "$STATUS_DIR/$appid.session" 2>/dev/null
fi

if [ "$on" != 1 ]; then
  exec "$@"
fi

export MAKO_CONFIG="$CONF"
export MAKO_PROFILE_FALLBACK="$appid"
export MAKO_PRESENT_ACQUIRE_TIMEOUT_MS="${MAKO_PRESENT_ACQUIRE_TIMEOUT_MS:-50}"
# never two frame generators in one game: Decky Smooth Frames' layer (and afmf-linux) stay out
export SMOOTH_FRAMES_DISABLE=1 DISABLE_AFMF=1
# MAKO's per-second frame statistics for the live status; only slow presents above 250 ms are logged
export MAKO_PRESENT_DIAGNOSTICS="${MAKO_PRESENT_DIAGNOSTICS:-1}"
export MAKO_PRESENT_DIAGNOSTICS_THRESHOLD_MS="${MAKO_PRESENT_DIAGNOSTICS_THRESHOLD_MS:-250}"
# MAKO logs to stderr; a plain file (no pipe) cannot stall the game
: > "$STATUS_DIR/$appid.log" 2>/dev/null && exec 2>>"$STATUS_DIR/$appid.log"
exec "$LAUNCHER" "$@"
"""


def write_wrapper():
    script = (
        WRAPPER_TEMPLATE.replace("__PLUGIN__", PLUGIN_NAME)
        .replace("__WRAPPER__", WRAPPER_PATH)
        .replace("__GAMES_DIR__", GAMES_DIR)
        .replace("__CONF__", CONF_PATH)
        .replace("__LAUNCHER__", LAUNCHER)
        .replace("__STATUS_DIR__", STATUS_DIR)
        .replace("__APPID_VAR__", APPID_VAR)
    )
    _write_if_changed(WRAPPER_PATH, script.encode("utf-8"), mode=0o755)


# ---------------------------------------------------------------------------------------------
# engine install
# ---------------------------------------------------------------------------------------------

def _sha256_file(path: str):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _bundle_files():
    for root, _dirs, files in os.walk(BUNDLE_DIR):
        for name in files:
            src = os.path.join(root, name)
            yield src, os.path.relpath(src, BUNDLE_DIR)


def install_engine() -> str:
    if not os.path.isfile(os.path.join(BUNDLE_DIR, "bin", "mako-launch")):
        raise RuntimeError(f"bundled engine missing: {BUNDLE_DIR}")
    for src, rel in _bundle_files():
        dst = os.path.join(ENGINE_DIR, rel)
        if _sha256_file(dst) == _sha256_file(src):
            continue
        with open(src, "rb") as fh:
            blob = fh.read()
        executable = rel.startswith("bin" + os.sep)
        _atomic_write(dst, blob, mode=0o755 if executable else 0o644)
    with open(os.path.join(BUNDLE_DIR, "VERSION"), "r") as fh:
        version = fh.read().strip()
    decky.logger.info(f"engine ready: MAKO Renderer {version} in {ENGINE_DIR}")
    return version


def engine_version():
    try:
        with open(os.path.join(ENGINE_DIR, "VERSION"), "r") as fh:
            return fh.read().strip()
    except OSError:
        return None


def remove_engine():
    shutil.rmtree(ENGINE_DIR, ignore_errors=True)


# ---------------------------------------------------------------------------------------------
# live status: the records MAKO's layer publishes for each running swapchain
# ---------------------------------------------------------------------------------------------

def _read_session(appid: str):
    try:
        with open(os.path.join(STATUS_DIR, appid + ".session"), "r", encoding="utf-8", errors="replace") as fh:
            data = dict(line.strip().split("=", 1) for line in fh if "=" in line)
        return {"pid": int(data.get("pid", "0")), "start": int(data.get("start", "0")), "on": data.get("on") == "1"}
    except (OSError, ValueError):
        return None


def _env_has(pid: int, appid: str) -> bool:
    try:
        with open(f"/proc/{pid}/environ", "rb") as fh:
            return f"{APPID_VAR}={appid}".encode() in fh.read().split(b"\0")
    except OSError:
        return False


def _game_running(appid: str, sess) -> bool:
    """The wrapper's process (exec'd into the launcher, then Proton) or any of its descendants."""
    if sess and sess["pid"] > 1 and _env_has(sess["pid"], appid):
        return True
    try:
        pids = [int(p) for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return False
    return any(_env_has(p, appid) for p in pids)


def _lock_held(path: str) -> bool:
    """MAKO holds an exclusive lock on <record>.lock for as long as the swapchain context lives."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def _runtime_records(appid: str, since: int):
    mine, unattributed = [], []
    try:
        names = os.listdir(RUNTIME_STATE_DIR)
    except OSError:
        return mine
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(RUNTIME_STATE_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        pid = rec.get("pid")
        if rec.get("role", "frame-generation") != "frame-generation" or not isinstance(pid, int):
            continue
        if not _lock_held(path + ".lock"):
            continue  # left over from a game that has ended
        if _env_has(pid, appid):
            mine.append(rec)
        elif not os.path.exists(f"/proc/{pid}") and rec.get("updated_unix_ms", 0) >= since * 1000:
            # the game may see other process ids (container): live and newer than this session
            unattributed.append(rec)
    return mine or unattributed


APP_PRESENT_RE = re.compile(
    r"operation=application-queue-present .*?pid=(\d+) .*?sample_end_monotonic_ms=(\d+) .*?calls=(\d+) "
    r".*?entry_interval_mean_ms=([\d.]+)"
)
PLAN_RE = re.compile(r"operation=adaptive-plan .*?base_fps=([\d.]+) target_fps=([\d.]+) generated=(\d+)")
PROBLEM_RE = re.compile(r"MAKO.*\b(error|failed|unavailable)\b", re.I)
TAIL_BYTES = 128 * 1024


def _log_path(appid: str) -> str:
    return os.path.join(STATUS_DIR, appid + ".log")


def trim_log(appid: str):
    """The wrapper opened the log with O_APPEND: truncating lets the game write on at the new start."""
    try:
        if os.path.getsize(_log_path(appid)) > STATUS_LOG_MAX:
            os.truncate(_log_path(appid), 0)
    except OSError:
        pass


def _read_log(appid: str) -> dict:
    """Last problem line, the game's own present rate and the last adaptive plan from MAKO's log."""
    trim_log(appid)
    try:
        path = _log_path(appid)
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - TAIL_BYTES))
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return {}
    out, presents = {}, {}
    for line in text.splitlines():
        m = APP_PRESENT_RE.search(line)
        if m:
            # one line per second and swapchain; the game's swapchain is the busiest one
            presents[m.group(1)] = (int(m.group(2)), int(m.group(3)), float(m.group(4)))
            continue
        m = PLAN_RE.search(line)
        if m:
            out["plan"] = (float(m.group(1)), float(m.group(2)), int(m.group(3)))
            continue
        if PROBLEM_RE.search(line) and "present diagnostics" not in line:
            out["problem"] = line.strip()[:240]
    if presents:
        end_ms, calls, interval = max(presents.values(), key=lambda v: (v[1], v[0]))
        out["real_fps"] = round(1000.0 / interval) if interval > 0 else 0
        out["stats_age"] = time.monotonic() - end_ms / 1000.0
    return out


def live_status(appid: str) -> dict:
    sess = _read_session(appid)
    if not sess or not _game_running(appid, sess):
        return {"state": "no_session"}
    age = max(0, int(time.time() - sess["start"]))
    base = {"age": age, "start": sess["start"]}
    if not sess["on"]:
        return {**base, "state": "off"}
    records = _runtime_records(appid, sess["start"])
    if not records:
        if age < 30:
            return {**base, "state": "starting"}
        return {**base, "state": "not_loaded", "problem": _read_log(appid).get("problem")}
    # the swapchain that generates frames, else the most recent one
    records.sort(key=lambda r: (bool(r.get("frame_generation_active")), r.get("updated_unix_ms", 0)))
    rec = records[-1]
    applied = rec.get("applied") if isinstance(rec.get("applied"), dict) else {}
    requested = rec.get("requested") if isinstance(rec.get("requested"), dict) else {}
    pending = rec.get("pending") if isinstance(rec.get("pending"), dict) else {}
    profile = applied or requested
    out = {
        **base,
        "model": profile.get("frame_generation_model"),
        "adaptive": bool(profile.get("adaptive")),
        "multiplier": profile.get("multiplier"),
        "target": profile.get("target_fps"),
        "restart_needed": bool(pending.get("process_restart")),
        "phase": rec.get("phase"),
    }
    unavailable = rec.get("frame_generation_unavailable")
    if unavailable:
        reason = unavailable.get("reason") if isinstance(unavailable, dict) else str(unavailable)
        return {**out, "state": "unavailable", "problem": reason}
    if out["model"] and out["model"] != "lossless-scaling":
        return {**out, "state": "wrong_model"}
    if rec.get("phase") == "failed":
        return {**out, "state": "failed", "problem": rec.get("reason")}
    if not requested.get("frame_generation_enabled", profile.get("frame_generation_enabled", True)):
        return {**out, "state": "live_off"}
    if rec.get("frame_generation_active"):
        log = _read_log(appid)
        real = log.get("real_fps")
        if real is not None:
            if log.get("stats_age", 0) > 5:
                return {**out, "state": "stale"}
            out["real_fps"] = real
            if out["adaptive"] and log.get("plan"):
                base_fps, _target, generated = log["plan"]
                out["output_fps"] = min(round(base_fps * (1 + generated)), int(out["target"] or 1000))
            elif not out["adaptive"] and isinstance(out["multiplier"], int):
                out["output_fps"] = real * out["multiplier"]
        return {**out, "state": "active"}
    return {**out, "state": "preparing", "problem": rec.get("reason")}


# ---------------------------------------------------------------------------------------------
# plugin API (called from the frontend)
# ---------------------------------------------------------------------------------------------

class Plugin:
    store: Store

    async def _main(self):
        self.store = Store()
        self.store.load()
        self._lock = asyncio.Lock()
        self.engine_error = None
        try:
            install_engine()
        except Exception as err:  # noqa: BLE001
            self.engine_error = str(err)
            decky.logger.error(f"engine install failed: {err}")
        try:
            write_wrapper()
            self.store.save()
        except Exception as err:  # noqa: BLE001
            decky.logger.error(f"startup write failed: {err}")
        self._trimmer = asyncio.get_running_loop().create_task(self._trim_logs())
        decky.logger.info(f"{PLUGIN_NAME} ready")

    async def _trim_logs(self):
        # MAKO's statistics keep a running game's log growing, also while the panel is closed
        while True:
            await asyncio.sleep(30)
            for appid in list(self.store.data["games"]):
                await self._run(trim_log, appid)

    async def _unload(self):
        task = getattr(self, "_trimmer", None)
        if task:
            task.cancel()

    async def _uninstall(self):
        # Decky also calls this on updates (the old version is uninstalled before the new one
        # starts), so the settings stay. Only the engine goes; the new version installs it again.
        # Games that still have the launch option start normally: the wrapper then finds no launcher.
        try:
            remove_engine()
        except Exception as err:  # noqa: BLE001
            decky.logger.error(f"uninstall cleanup failed: {err}")

    async def _run(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)

    async def get_status(self) -> dict:
        def status():
            dll = find_lossless_dll()
            return {
                "installed": os.access(LAUNCHER, os.X_OK) and engine_version() is not None,
                "engine_version": engine_version(),
                "wrapper": WRAPPER_PATH,
                "deck_model": DECK_MODEL,
                "refresh": REFRESH,
                "dll": dll,
            }
        st = await self._run(status)
        st["error"] = self.engine_error
        if st["dll"]:
            # the library may have moved since the last save (e.g. installed in the meantime)
            await self._run(self.store.write_config)
        return st

    async def repair_engine(self) -> dict:
        async with self._lock:
            try:
                await self._run(install_engine)
                self.engine_error = None
                return {"ok": True}
            except Exception as err:  # noqa: BLE001
                self.engine_error = str(err)
                return {"ok": False, "error": str(err)}

    def _game_view(self, appid: str) -> dict:
        g = self.store.data["games"].get(appid)
        return {"appid": appid, "enabled": bool(g and g["enabled"]), "profile": self.store.effective_profile(appid)}

    async def get_game(self, appid) -> dict:
        return self._game_view(valid_appid(appid))

    async def set_game_enabled(self, appid, name: str, enabled: bool) -> dict:
        appid = valid_appid(appid)
        g = self.store.data["games"].setdefault(
            appid, {"name": "", "enabled": False, "profile": copy.deepcopy(DEFAULT_PROFILE)}
        )
        g["name"] = str(name or g["name"])[:200]
        g["enabled"] = bool(enabled)
        await self._run(self.store.save)
        return self._game_view(appid)

    async def set_game_profile(self, appid, profile: dict) -> dict:
        appid = valid_appid(appid)
        g = self.store.data["games"].get(appid)
        if g is None:
            raise ValueError("game is not enabled")
        new = sanitize_profile(profile)
        if new != g["profile"]:
            g["profile"] = new
            await self._run(self.store.save)
        return self._game_view(appid)

    async def reset_game_profile(self, appid) -> dict:
        return await self.set_game_profile(appid, copy.deepcopy(DEFAULT_PROFILE))

    async def forget_game(self, appid) -> bool:
        appid = valid_appid(appid)
        self.store.data["games"].pop(appid, None)
        await self._run(self.store.save)
        return True

    async def list_games(self) -> list:
        return [
            {"appid": a, "name": g["name"], "enabled": g["enabled"]}
            for a, g in sorted(self.store.data["games"].items(), key=lambda kv: kv[1]["name"].lower())
        ]

    async def get_live_status(self, appid) -> dict:
        appid = valid_appid(appid)
        try:
            return await self._run(live_status, appid)
        except Exception as err:  # noqa: BLE001
            decky.logger.error(f"live status failed: {err}")
            return {"state": "error", "problem": str(err)}
