// Keyboard shortcuts: the same keys as the TUI (see KEYS in
// src/stargarden/tui/app.py), so either console feels the same. The buttons
// look their own key up here for their hints.

export interface Shortcut {
  key: string;
  action: string;
  params?: Record<string, unknown>;
}

export const SHORTCUTS: Shortcut[] = [
  { key: "m", action: "motion", params: { role: "platform" } },
  { key: "w", action: "motion", params: { role: "walkway" } },
  { key: "0", action: "force", params: { state: "off" } },
  { key: "1", action: "force", params: { state: "ambient" } },
  { key: "2", action: "force", params: { state: "presence" } },
  { key: "3", action: "force", params: { state: "show" } },
  { key: "r", action: "release" },
  { key: "n", action: "toggle_night" },
  { key: "l", action: "lightning" },
  { key: "s", action: "discrete" },
  { key: "d", action: "toggle_debug" },
];

/** The key bound to an action (with these exact params), if any. */
export function keyFor(
  action: string,
  params?: Record<string, unknown>,
): string | undefined {
  const wanted = JSON.stringify(params ?? null);
  return SHORTCUTS.find(
    (s) => s.action === action && JSON.stringify(s.params ?? null) === wanted,
  )?.key;
}
