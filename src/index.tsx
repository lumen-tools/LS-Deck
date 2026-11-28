import {
  ButtonItem,
  DropdownItem,
  PanelSection,
  PanelSectionRow,
  Router,
  SliderField,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useCallback, useEffect, useRef, useState } from "react";
import { MdAutoAwesomeMotion } from "react-icons/md";

// ---------------------------------------------------------------------------------------------
// backend
// ---------------------------------------------------------------------------------------------

// Lossless Scaling's "Frame Generation" panel (Type: always LSFG 3.1)
interface Profile {
  fg: "off" | "lsfg";
  mode: "fixed" | "adaptive";
  multiplier: number;
  target: number;
  flow_scale: number;
  performance: boolean;
  // Fixed mode: real frame limit (0 = off)
  limit: number;
  // Lossless Scaling's Scaling panel
  scaling: "off" | "ls1" | "ls1-performance" | "fsr";
  scale_mode: "auto" | "custom";
  scale_factor: number; // hundredths, 100-200 = 1.00-2.00
  sharpness: number; // percent
}

interface Status {
  installed: boolean;
  engine_version: string | null;
  wrapper: string;
  deck_model: "lcd" | "oled" | null;
  refresh: number;
  dll: string | null;
  error: string | null;
}

interface GameState {
  appid: string;
  enabled: boolean;
  profile: Profile;
}

interface GameEntry {
  appid: string;
  name: string;
  enabled: boolean;
}

type LiveState =
  | "no_session"
  | "off"
  | "starting"
  | "not_loaded"
  | "preparing"
  | "active"
  | "live_off"
  | "unavailable"
  | "wrong_model"
  | "failed"
  | "stale"
  | "at_target"
  | "scaling_only"
  | "settling"
  | "error";

interface Live {
  state: LiveState;
  age?: number;
  problem?: string | null;
  adaptive?: boolean;
  multiplier?: number;
  target?: number;
  restart_needed?: boolean;
  real_fps?: number;
  output_fps?: number;
  menu_pause?: boolean;
  scaling?: { method: string; requested: string; source: number[]; output: number[]; fallback: string | null };
}

const getStatus = callable<[], Status>("get_status");
const repairEngine = callable<[], { ok: boolean; error?: string }>("repair_engine");
const getGame = callable<[string], GameState>("get_game");
const setGameEnabled = callable<[string, string, boolean], GameState>("set_game_enabled");
const setGameProfile = callable<[string, Profile], GameState>("set_game_profile");
const resetGameProfile = callable<[string], GameState>("reset_game_profile");
const forgetGame = callable<[string], boolean>("forget_game");
const listGames = callable<[], GameEntry[]>("list_games");
const getLiveStatus = callable<[string], Live>("get_live_status");

// ---------------------------------------------------------------------------------------------
// Steam launch options
// ---------------------------------------------------------------------------------------------

const SHORTCUT_APP_TYPE = 1073741824;

interface RunningApp {
  appid: string;
  name: string;
  shortcut: boolean;
}

function currentApp(): RunningApp | null {
  const app = Router.MainRunningApp;
  if (!app || !app.appid) return null;
  return {
    appid: String(app.appid),
    name: app.display_name || `App ${app.appid}`,
    shortcut: Number(app.app_type) === SHORTCUT_APP_TYPE,
  };
}

function isShortcut(appid: string): boolean {
  try {
    const ov = appStore.GetAppOverviewByAppID(Number(appid));
    return Number(ov?.app_type) === SHORTCUT_APP_TYPE;
  } catch {
    return false;
  }
}

function readLaunchOptions(appid: string, shortcut: boolean): Promise<string> {
  return new Promise((resolve, reject) => {
    let done = false;
    let reg: { unregister: () => void } | null = null;
    const finish = (value: string | null, err?: string) => {
      if (done) return;
      done = true;
      // the callback may fire synchronously, before `reg` is assigned
      setTimeout(() => reg?.unregister(), 0);
      if (value === null) reject(new Error(err ?? "Could not read launch options"));
      else resolve(value);
    };
    reg = SteamClient.Apps.RegisterForAppDetails(Number(appid), (details) => {
      const opts = shortcut ? details?.strShortcutLaunchOptions : details?.strLaunchOptions;
      finish(opts ?? "");
    });
    setTimeout(() => finish(null, "Timed out reading launch options"), 4000);
  });
}

function writeLaunchOptions(appid: string, shortcut: boolean, value: string) {
  if (shortcut) SteamClient.Apps.SetShortcutLaunchOptions(Number(appid), value);
  else SteamClient.Apps.SetAppLaunchOptions(Number(appid), value);
}

function escapeRe(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function stripWrapper(opts: string, wrapper: string): string {
  // "<wrapper> <appid> " directly in front of %command%, wherever the user put it
  const re = new RegExp(`\\s*${escapeRe(wrapper)}\\s+\\d+(?=\\s+%command%)`, "g");
  let out = opts.replace(re, " ").replace(/\s{2,}/g, " ").trim();
  if (out === "%command%") out = "";
  return out;
}

function addWrapper(opts: string, wrapper: string, appid: string): string {
  const clean = stripWrapper(opts, wrapper);
  const part = `${wrapper} ${appid} %command%`;
  if (clean.includes("%command%")) return clean.replace("%command%", part);
  return clean ? `${part} ${clean}` : part;
}

function hasWrapper(opts: string, wrapper: string): boolean {
  return opts.includes(wrapper);
}

// another frame generator's launcher in the same game
const OTHER_WRAPPERS = ["smooth-frames-run", "mako-run", "mako-launch", "lsfg-vk", "~/lsfg"];

async function applyLaunchOptions(appid: string, wrapper: string, enable: boolean): Promise<boolean> {
  const shortcut = isShortcut(appid);
  const before = await readLaunchOptions(appid, shortcut);
  const next = enable ? addWrapper(before, wrapper, appid) : stripWrapper(before, wrapper);
  if (next !== before) writeLaunchOptions(appid, shortcut, next);
  await new Promise((r) => setTimeout(r, 400));
  const after = await readLaunchOptions(appid, shortcut);
  return hasWrapper(after, wrapper) === enable;
}

// ---------------------------------------------------------------------------------------------
// live status
// ---------------------------------------------------------------------------------------------

type Tone = "green" | "yellow" | "red" | "grey";
const TONE_COLOR: Record<Tone, string> = {
  green: "#5ba32b",
  yellow: "#d6a01d",
  red: "#d9453a",
  grey: "#8b929a",
};

function modeText(live: Live): string {
  const mode = live.adaptive ? `Adaptive, target ${live.target}` : `Fixed ×${live.multiplier}`;
  if (live.real_fps === undefined) return `LSFG 3.1 · ${mode}`;
  const out = live.output_fps !== undefined ? ` → ~${live.output_fps} FPS` : "";
  return `${live.real_fps} real FPS${out} · ${mode}`;
}

function describe(live: Live | null, enabled: boolean, launchOk: boolean): { tone: Tone; title: string; detail?: string } {
  if (!live) return { tone: "grey", title: "Loading status…" };
  if (live.state === "live_off" || (!enabled && live.state !== "no_session" && live.state !== "off"))
    return {
      tone: "grey",
      title: enabled ? "Frame generation off" : "Off",
      detail: "Real frames only, no frame limit. Frame generation switches instantly while the game runs.",
    };
  switch (live.state) {
    case "no_session":
      if (enabled && !launchOk) return { tone: "red", title: "Launch option missing", detail: "Turn the toggle off and on again." };
      return enabled
        ? { tone: "yellow", title: "On – restart the game", detail: "Lossless Scaling loads when the game starts." }
        : { tone: "grey", title: "Off" };
    case "off":
      return enabled
        ? { tone: "yellow", title: "On – restart the game", detail: "This session was started without Lossless Scaling." }
        : { tone: "grey", title: "Off" };
    case "starting":
      return { tone: "grey", title: "Game starting…" };
    case "not_loaded":
      return {
        tone: "red",
        title: "Not loaded",
        detail: live.problem ?? "The game did not open a Vulkan swapchain with Lossless Scaling. OpenGL games and some launchers are not supported.",
      };
    case "preparing":
      return { tone: "yellow", title: "Preparing frame generation…", detail: live.problem ?? undefined };
    case "active":
      return { tone: "green", title: "Active – generating frames", detail: modeText(live) };
    case "unavailable":
    case "wrong_model":
      return {
        tone: "red",
        title: "Lossless Scaling could not be loaded",
        detail: live.problem ?? "Check that Lossless Scaling is installed (it does not need to run) and restart the game.",
      };
    case "failed":
      return { tone: "red", title: "Frame generation failed", detail: live.problem ?? undefined };
    case "stale":
      return { tone: "grey", title: "No new frames", detail: "Game paused, in a menu or in the background." };
    case "scaling_only":
      return { tone: "green", title: "Scaling active – frame generation off", detail: "Frame generation switches instantly while the game runs." };
    case "at_target":
      return {
        tone: "grey",
        title: "Game at target – no frames needed",
        detail: `${live.real_fps} real FPS. Frames are generated as soon as the game drops below ${live.target} FPS.`,
      };
    case "settling":
      return {
        tone: "yellow",
        title: "Waiting – frame generation is settling",
        detail: `${live.real_fps} real FPS → ${live.output_fps} FPS. Adaptive is measuring the new frame rate and generates nothing yet.`,
      };
    default:
      return { tone: "red", title: "Could not read status", detail: live.problem ?? undefined };
  }
}

const SCALER_NAME: Record<string, string> = {
  ls1: "LS1",
  "ls1-performance": "LS1 Performance",
  mako: "FSR",
  native: "Native",
};

function ScalingLine({ scaling }: { scaling: NonNullable<Live["scaling"]> }) {
  const name = SCALER_NAME[scaling.method] ?? scaling.method;
  const size =
    scaling.source[0] && scaling.output[0]
      ? ` · ${scaling.source[0]}×${scaling.source[1]} → ${scaling.output[0]}×${scaling.output[1]}`
      : "";
  if (scaling.method !== scaling.requested)
    return (
      <div style={{ color: TONE_COLOR.yellow }}>
        {SCALER_NAME[scaling.requested] ?? scaling.requested} could not be loaded, {name} scales instead{size}.{scaling.fallback ? ` ${scaling.fallback}` : ""}
      </div>
    );
  return <div style={{ opacity: 0.8 }}>Scaling: {name}{size}</div>;
}

function GameLine({ app, live, enabled, launchOk }: { app: RunningApp; live: Live | null; enabled: boolean; launchOk: boolean }) {
  const d = describe(live, enabled, launchOk);
  const restart = enabled && live?.restart_needed;
  return (
    <div>
      <div style={{ fontWeight: "bold", color: "#dcdedf" }}>
        {app.name}
        {app.shortcut && <span style={{ opacity: 0.6, fontWeight: "normal" }}> (Non-Steam)</span>}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "2px" }}>
        <span
          style={{
            width: "8px",
            height: "8px",
            borderRadius: "50%",
            background: TONE_COLOR[d.tone],
            boxShadow: d.tone === "green" ? `0 0 6px ${TONE_COLOR.green}` : undefined,
            flexShrink: 0,
          }}
        />
        <span>{d.title}</span>
      </div>
      {d.detail && <div style={{ opacity: 0.8 }}>{d.detail}</div>}
      {enabled && live?.scaling && <ScalingLine scaling={live.scaling} />}
      {live?.menu_pause && ["active", "at_target", "settling"].includes(live.state) && (
        <div style={{ opacity: 0.6 }}>
          Frame generation pauses while Steam's menu is open. The numbers are from the
          game just before; generation resumes when you return.
        </div>
      )}
      {restart && <div style={{ color: TONE_COLOR.yellow }}>Restart the game to apply your changes.</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// settings: Lossless Scaling's Frame Generation panel
// ---------------------------------------------------------------------------------------------

// Factor as in Lossless Scaling: 1.0, 1.25, 1.5 …
function formatFactor(hundredths: number): string {
  return (hundredths / 100).toFixed(hundredths % 10 === 0 ? 1 : 2);
}

function useDebounced<T>(fn: (v: T) => void, ms: number) {
  const t = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef(fn);
  latest.current = fn;
  return useCallback(
    (v: T) => {
      if (t.current) clearTimeout(t.current);
      t.current = setTimeout(() => latest.current(v), ms);
    },
    [ms],
  );
}

function FrameGeneration({
  profile,
  refresh,
  onChange,
  onReset,
}: {
  profile: Profile;
  refresh: number;
  onChange: (p: Profile) => void;
  onReset: () => void;
}) {
  const [p, setP] = useState<Profile>(profile);
  useEffect(() => setP(profile), [profile]);
  const save = useDebounced<Profile>(onChange, 350);
  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => {
    const next = { ...p, [k]: v };
    setP(next);
    save(next);
  };
  const adaptive = p.mode === "adaptive";
  const typeRow = (
    <PanelSectionRow>
      <DropdownItem
        label="Type"
        description={
          p.fg === "lsfg"
            ? "Lossless Scaling's frame generation. Switches instantly while the game runs."
            : "Off – real frames only. Switches instantly while the game runs."
        }
        rgOptions={[
          { data: "off", label: "Off" },
          { data: "lsfg", label: "LSFG 3.1" },
        ]}
        selectedOption={p.fg}
        onChange={(o) => set("fg", o.data)}
      />
    </PanelSectionRow>
  );
  if (p.fg === "off") return typeRow;

  return (
    <>
      {typeRow}
      <PanelSectionRow>
        <DropdownItem
          label="Mode"
          description={
            adaptive
              ? "Generates as many frames as needed to reach the target, from any base frame rate."
              : "Multiplies the game's frame rate by a fixed factor."
          }
          rgOptions={[
            { data: "fixed", label: "Fixed" },
            { data: "adaptive", label: "Adaptive" },
          ]}
          selectedOption={p.mode}
          onChange={(o) => set("mode", o.data)}
        />
      </PanelSectionRow>
      {adaptive ? (
        <PanelSectionRow>
          <SliderField
            label="Target"
            description={`Frames per second on screen. ${refresh} matches this screen.`}
            value={p.target}
            min={30}
            max={Math.max(144, refresh)}
            step={1}
            showValue={true}
            editableValue={true}
            valueSuffix=" FPS"
            onChange={(n) => set("target", n)}
          />
        </PanelSectionRow>
      ) : (
        <>
          <PanelSectionRow>
            <DropdownItem
              label="Multiplier"
              description={`Real frames × ${p.multiplier} on screen.`}
              rgOptions={[2, 3, 4].map((m) => ({ data: m, label: `×${m}` }))}
              selectedOption={p.multiplier}
              onChange={(o) => {
                // a limit at the old "refresh ÷ multiplier" follows the new multiplier
                const followed = p.limit === Math.round(refresh / p.multiplier);
                const next = { ...p, multiplier: o.data, limit: followed ? Math.round(refresh / o.data) : p.limit };
                setP(next);
                save(next);
              }}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ToggleField
              label="Frame Rate Limit"
              description={
                p.limit > 0
                  ? `Limits the game's real frames to ${p.limit} FPS: ${p.limit} × ${p.multiplier} = ${p.limit * p.multiplier} FPS on screen. Steam's limit acts after frame generation, so leave it at ${refresh}.`
                  : `Off – the game's real frames are not limited. On this ${refresh} Hz screen, more than ${Math.round(refresh / p.multiplier)} real FPS add latency.`
              }
              checked={p.limit > 0}
              onChange={(on) => set("limit", on ? Math.round(refresh / p.multiplier) : 0)}
            />
          </PanelSectionRow>
          {p.limit > 0 && (
            <PanelSectionRow>
              <SliderField
                label="Base FPS"
                value={p.limit}
                min={10}
                max={120}
                step={1}
                showValue={true}
                editableValue={true}
                valueSuffix=" FPS"
                onChange={(n) => set("limit", n)}
              />
            </PanelSectionRow>
          )}
        </>
      )}
      <PanelSectionRow>
        <SliderField
          label="Flow Scale"
          description="Resolution of the motion estimation. Lower is faster, higher is more accurate."
          value={p.flow_scale}
          min={25}
          max={100}
          step={5}
          showValue={true}
          valueSuffix=" %"
          onChange={(n) => set("flow_scale", n)}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Performance"
          description="Lighter LSFG model: much less GPU load, slightly lower quality. Recommended on the Steam Deck."
          checked={p.performance}
          onChange={(v) => set("performance", v)}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={onReset}>
          Reset to defaults
        </ButtonItem>
      </PanelSectionRow>
    </>
  );
}

function Scaling({ profile, onChange }: { profile: Profile; onChange: (p: Profile) => void }) {
  const [p, setP] = useState<Profile>(profile);
  useEffect(() => setP(profile), [profile]);
  const save = useDebounced<Profile>(onChange, 350);
  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => {
    const next = { ...p, [k]: v };
    setP(next);
    save(next);
  };
  const on = p.scaling !== "off";
  return (
    <>
      <PanelSectionRow>
        <DropdownItem
          label="Type"
          description={
            on
              ? `Lower the resolution in the game's settings: ${p.scaling === "fsr" ? "FSR 1" : "LS1"} scales it up. Restart the game after turning it on or off.`
              : "Off – the game is shown at its own resolution. Restart the game after turning it on."
          }
          rgOptions={[
            { data: "off", label: "Off" },
            { data: "ls1", label: "LS1" },
            { data: "ls1-performance", label: "LS1 Performance" },
            { data: "fsr", label: "FSR" },
          ]}
          selectedOption={p.scaling}
          onChange={(o) => set("scaling", o.data)}
        />
      </PanelSectionRow>
      {on && (
        <>
          <PanelSectionRow>
            <DropdownItem
              label="Scaling mode"
              description={
                p.scale_mode === "custom"
                  ? "The game's resolution × the factor, at most the screen size. Restart the game after changing it."
                  : "Scales the game's resolution up to the screen size (at most 2×), keeping its aspect ratio."
              }
              rgOptions={[
                { data: "auto", label: "Auto" },
                { data: "custom", label: "Custom" },
              ]}
              selectedOption={p.scale_mode}
              onChange={(o) => set("scale_mode", o.data)}
            />
          </PanelSectionRow>
          {p.scale_mode === "custom" && (
            <PanelSectionRow>
              <SliderField
                label={`Factor  ${formatFactor(p.scale_factor)}`}
                value={p.scale_factor}
                min={100}
                max={200}
                step={5}
                notchCount={5}
                notchLabels={[
                  { notchIndex: 0, label: "1.0", value: 100 },
                  { notchIndex: 1, label: "1.25", value: 125 },
                  { notchIndex: 2, label: "1.5", value: 150 },
                  { notchIndex: 3, label: "1.75", value: 175 },
                  { notchIndex: 4, label: "2.0", value: 200 },
                ]}
                onChange={(n) => set("scale_factor", n)}
              />
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <SliderField
              label="Sharpness"
              value={p.sharpness}
              min={0}
              max={100}
              step={5}
              showValue={true}
              valueSuffix=" %"
              onChange={(n) => set("sharpness", n)}
            />
          </PanelSectionRow>
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------------------------
// main panel
// ---------------------------------------------------------------------------------------------

function Content() {
  const [status, setStatus] = useState<Status | null>(null);
  const [app, setApp] = useState<RunningApp | null>(currentApp());
  const [game, setGame] = useState<GameState | null>(null);
  const [launchOk, setLaunchOk] = useState(true);
  const [conflict, setConflict] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [live, setLive] = useState<Live | null>(null);
  const [games, setGames] = useState<GameEntry[]>([]);
  const [cleaning, setCleaning] = useState(false);
  const enabledCount = games.filter((g) => g.enabled).length;
  // the two sections save independently: each sends only its own keys on top of the latest profile
  const gameRef = useRef<GameState | null>(null);
  gameRef.current = game;
  const saveKeys = (keys: (keyof Profile)[]) => async (p: Profile) => {
    const cur = gameRef.current;
    if (!app || !cur) return;
    const merged = { ...cur.profile } as Record<string, unknown>;
    for (const k of keys) merged[k] = p[k];
    setGame(await setGameProfile(app.appid, merged as unknown as Profile));
  };
  const FG_KEYS: (keyof Profile)[] = ["fg", "mode", "multiplier", "target", "flow_scale", "performance", "limit"];
  const SCALING_KEYS: (keyof Profile)[] = ["scaling", "scale_mode", "scale_factor", "sharpness"];

  const refreshStatus = useCallback(async () => setStatus(await getStatus()), []);
  const refreshGames = useCallback(async () => setGames(await listGames()), []);

  useEffect(() => {
    refreshStatus();
    refreshGames();
  }, []);

  // follow the running game
  useEffect(() => {
    const id = setInterval(() => {
      const a = currentApp();
      setApp((prev) => (prev?.appid === a?.appid ? prev : a));
    }, 1500);
    return () => clearInterval(id);
  }, []);

  // the running game's settings and launch option
  useEffect(() => {
    setGame(null);
    setLive(null);
    setConflict(false);
    if (!app) return;
    let cancelled = false;
    (async () => {
      const g = await getGame(app.appid);
      if (cancelled) return;
      setGame(g);
      if (status) {
        try {
          const opts = await readLaunchOptions(app.appid, app.shortcut);
          if (cancelled) return;
          if (g.enabled) setLaunchOk(hasWrapper(opts, status.wrapper));
          setConflict(OTHER_WRAPPERS.some((w) => opts.includes(w)));
        } catch {
          /* keep the last value */
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [app?.appid, status?.wrapper]);

  // live status every 2 s while the panel is open
  useEffect(() => {
    if (!app) return;
    let stop = false;
    const tick = async () => {
      try {
        const l = await getLiveStatus(app.appid);
        if (!stop) setLive(l);
      } catch {
        /* ignore */
      }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [app?.appid]);

  const toggleGame = async (on: boolean) => {
    if (!app || !status) return;
    setToggling(true);
    try {
      const ok = await applyLaunchOptions(app.appid, status.wrapper, on);
      setGame(await setGameEnabled(app.appid, app.name, on));
      setTimeout(async () => setLive(await getLiveStatus(app.appid)), 800);
      setLaunchOk(on ? ok : true);
      if (on && !ok) toaster.toast({ title: "LS Deck", body: "Could not set the launch option." });
      refreshGames();
    } catch (e) {
      toaster.toast({ title: "LS Deck", body: String(e) });
    } finally {
      setToggling(false);
    }
  };

  const removeAll = async () => {
    if (!status) return;
    setCleaning(true);
    for (const g of games) {
      try {
        await applyLaunchOptions(g.appid, status.wrapper, false);
      } catch {
        /* app may be uninstalled: forget it anyway */
      }
      await forgetGame(g.appid);
    }
    setCleaning(false);
    if (app) setGame(await getGame(app.appid));
    refreshGames();
    toaster.toast({ title: "LS Deck", body: "Lossless Scaling removed from all games." });
  };

  const doRepair = async () => {
    const r = await repairEngine();
    toaster.toast({ title: "LS Deck", body: r.ok ? "Reinstalled." : `Failed: ${r.error}` });
    await refreshStatus();
  };

  const ready = !!status?.installed;
  const haveDll = !!status?.dll;
  const enabled = !!game?.enabled;

  return (
    <>
      <PanelSection>
        {status && !ready && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              label="Frame generation layer missing"
              description={status.error ?? "The plugin could not set up its layer."}
              onClick={doRepair}
            >
              Repair
            </ButtonItem>
          </PanelSectionRow>
        )}
        {status && ready && !haveDll && (
          <PanelSectionRow>
            <div style={{ color: TONE_COLOR.red }}>
              Lossless Scaling not found. LSFG and LS1 need it installed from your Steam library (it does not need
              to run); FSR scaling works without it.
            </div>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <ToggleField
            label="Lossless Scaling"
            description={
              app ? (
                <GameLine app={app} live={ready ? live : null} enabled={enabled} launchOk={launchOk} />
              ) : (
                "Start a game to turn Lossless Scaling on for it."
              )
            }
            checked={enabled}
            disabled={!app || !ready || toggling || !game}
            onChange={toggleGame}
          />
        </PanelSectionRow>
        {app && conflict && (
          <PanelSectionRow>
            <div style={{ color: TONE_COLOR.yellow }}>
              Another frame generation tool is in this game's launch options. Use only one per game.
            </div>
          </PanelSectionRow>
        )}
      </PanelSection>

      {app && game?.enabled && (
        <PanelSection title="Frame Generation">
          <FrameGeneration
            profile={game.profile}
            refresh={status?.refresh ?? 60}
            onChange={saveKeys(FG_KEYS)}
            onReset={async () => setGame(await resetGameProfile(app.appid))}
          />
        </PanelSection>
      )}

      {app && game?.enabled && (
        <PanelSection title="Scaling">
          <Scaling profile={game.profile} onChange={saveKeys(SCALING_KEYS)} />
          {game.profile.fg === "off" && game.profile.scaling === "off" && (
            <PanelSectionRow>
              <div style={{ color: TONE_COLOR.yellow }}>Nothing is active yet: turn on Frame Generation or Scaling.</div>
            </PanelSectionRow>
          )}
        </PanelSection>
      )}

      {enabledCount > 0 && (
        <PanelSection>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={cleaning}
              description={`Lossless Scaling is on in ${enabledCount} game${enabledCount === 1 ? "" : "s"}. This turns it off everywhere and cleans up the launch options – do this before uninstalling the plugin.`}
              onClick={removeAll}
            >
              {cleaning ? "Removing…" : "Remove from all games"}
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      )}
    </>
  );
}

export default definePlugin(() => ({
  name: "LS Deck",
  titleView: <div className={staticClasses.Title}>LS Deck</div>,
  content: <Content />,
  icon: <MdAutoAwesomeMotion />,
  onDismount() {},
}));
