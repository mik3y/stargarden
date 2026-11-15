// The wire format of src/stargarden/web.py. The types mirror the dataclasses
// in src/stargarden/console.py: a new field there is a new field here.

export type Direction = "darkening" | "brightening";

/** `console.Status`: everything the panels show. */
export interface Status {
  site: string;
  on: boolean;
  /** The on/off fade, 0..1. */
  master: number;
  driver: string;
  /** The sunset's place, 0 (orange) to 1 (purple). */
  position: number;
  /** The place the lights show, gliding toward `position`. */
  shown: number;
  direction: Direction;
  paused: boolean;
  /** Seconds from orange to purple; the way back takes the same. */
  leg_s: number;
  leg_remaining_s: number;
  /** Ceiling on brightness, 0..1. */
  peak: number;
  /** Brightness at the purple end, relative to the orange end. */
  dusk_level: number;
  /** The sunset end to end, evenly spaced, at the current dusk level. */
  palette: [number, number, number][];
  debug: boolean;
  /** The setup check is walking the bars. */
  check: boolean;
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
