/** "m:ss" for a countdown or an age; "—" when there is none. */
export function fmtSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return "—";
  }
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

/** "HH:MM" (local time) for an ISO instant; "—" when there is none. */
export function fmtClock(iso: string | null): string {
  if (!iso) {
    return "—";
  }
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "HH:MM:SS.mmm" for a log line's Unix time. */
export function fmtLogTime(seconds: number): string {
  const date = new Date(seconds * 1000);
  const hms = date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  return `${hms}.${String(date.getMilliseconds()).padStart(3, "0")}`;
}
