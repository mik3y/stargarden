// The wire format of src/stargarden/web.py. The types mirror the dataclasses
// in src/stargarden/console.py: a new field there is a new field here.

export type State = "off" | "ambient" | "presence" | "show";
export const STATES: State[] = ["off", "ambient", "presence", "show"];

export type SensorRole = "platform" | "walkway";

/** `console.Status`: everything the status panel shows. */
export interface Status {
  site: string;
  state: State;
  forced: State | null;
  night: boolean;
  night_override: boolean | null;
  /** ISO 8601 in the site's timezone; null when the schedule is off. */
  next_transition: string | null;
  occupied: boolean;
  hold_remaining_s: number | null;
  motion_ago_s: Record<string, number | null>;
  show_in_s: number | null;
  shows_this_visit: number;
  theme: string;
  driver: string;
  master: number;
  storm_in_s: number | null;
  lightning_allowed: boolean;
  audio_out: string;
  audio_mode: string;
  samplerate: number;
  bed: string | null;
  music: string | null;
  bpm: number | null;
  /** Audio layers and the lighting peak, 0..1, in display order. */
  levels: Record<string, number>;
  debug: boolean;
  /** The setup check is walking the corners (tone per speaker, colors per bar). */
  check: boolean;
  /** Every lighting program by pool: in the random rotation or not, and which is on now. */
  programs: Program[];
  /** Every show track in manifest order: in the rotation or not, playing, queued for the next show. */
  tracks: Track[];
  /** The timing settings (`app.SETTINGS`), in order: what is in force and the config file's value. */
  settings: Setting[];
}

/** `console.SettingStatus`: values are seconds. */
export interface Setting {
  name: string;
  value: number;
  default: number;
}

/** `console.TrackStatus`. */
export interface Track {
  /** The manifest entry's `file`: what the track actions take. */
  id: string;
  title: string;
  /** The manifest's choice of lighting program; null for the rotation's. */
  theme: string | null;
  /** The manifest's or the measured tempo; null until measured. */
  bpm: number | null;
  enabled: boolean;
  playing: boolean;
  next: boolean;
}

/** `console.ProgramStatus`. */
export interface Program {
  name: string;
  pool: "ambient" | "show";
  enabled: boolean;
  playing: boolean;
}

/** `console.CellPreview`: one cell, previewed as if the peak were 1.0. */
export interface CellPreview {
  /** The cell's name in its fixture mode: stable across frames. */
  name: string;
  rgb: [number, number, number];
  strobe: boolean;
}

/** `console.FixturePreview`: color cells row by row (top first); white cells as greys. */
export interface FixturePreview {
  name: string;
  rows: CellPreview[][];
  whites: CellPreview[];
}

/** `console.record_to_dict`: one log line; `seq` numbers lines across reconnects. */
export interface LogLine {
  seq: number;
  /** Unix time, seconds. */
  t: number;
  level: string;
  name: string;
  msg: string;
  exc: string | null;
}

export type StreamMessage =
  | { type: "status"; status: Status }
  | { type: "fixtures"; fixtures: FixturePreview[] }
  | { type: "log"; lines: LogLine[] };

/** Runs a console action; rejects with the server's message on a bad request. */
export type Act = (
  name: string,
  params?: Record<string, unknown>,
) => Promise<void>;

interface ActionResponse {
  ok?: boolean;
  result?: unknown;
  error?: string;
}

/**
 * Run a `Console` action by name (`POST /api/actions/<name>`); the params are
 * its keyword arguments. Resolves to the action's result.
 */
export async function act(
  name: string,
  params: Record<string, unknown> = {},
): Promise<unknown> {
  const response = await fetch(`/api/actions/${name}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  const body = (await response.json().catch(() => ({}))) as ActionResponse;
  if (!response.ok || !body.ok) {
    throw new Error(body.error ?? `${name} failed (${response.status})`);
  }
  return body.result;
}

/** The stream's URL, asking for log lines numbered `since` and up. */
export function streamUrl(since: number): string {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}/ws?since=${since}`;
}
