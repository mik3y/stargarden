import Box from "@mui/material/Box";
import Slider from "@mui/material/Slider";
import Typography from "@mui/material/Typography";
import { useRef, useState } from "react";

/** How often a slider mid-drag sends its value, so the lights follow the hand. */
const DRAG_SEND_MS = 80;
/** How long a released slider keeps showing its own value before trusting the stream again. */
const SETTLE_MS = 600;

/**
 * A slider's value while a hand is on it: the hand's own value, sent as it
 * moves; otherwise the stream's.
 */
export function useDragValue(
  value: number,
  send: (value: number) => void,
): {
  shown: number;
  change: (value: number) => void;
  commit: (value: number) => void;
} {
  const [pending, setPending] = useState<number | null>(null);
  const lastSent = useRef(0);
  const settle = useRef<ReturnType<typeof setTimeout>>(undefined);

  const change = (next: number) => {
    clearTimeout(settle.current);
    setPending(next);
    const now = Date.now();
    if (now - lastSent.current >= DRAG_SEND_MS) {
      lastSent.current = now;
      send(next);
    }
  };

  const commit = (next: number) => {
    lastSent.current = Date.now();
    send(next);
    clearTimeout(settle.current);
    settle.current = setTimeout(() => setPending(null), SETTLE_MS);
  };

  return { shown: pending ?? value, change, commit };
}

interface LevelSliderProps {
  label: string;
  value: number;
  min?: number;
  onSend: (value: number) => void;
}

/** A labelled 0..1 level shown as a percentage. */
const LevelSlider = ({ label, value, min = 0, onSend }: LevelSliderProps) => {
  const { shown, change, commit } = useDragValue(value, onSend);
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: "8.5em 1fr 3em",
        alignItems: "center",
        columnGap: 2,
      }}
    >
      <Typography variant="caption">{label}</Typography>
      <Slider
        min={min}
        max={1}
        step={0.01}
        value={shown}
        aria-label={label}
        onChange={(_, v) => change(v as number)}
        onChangeCommitted={(_, v) => commit(v as number)}
      />
      <Typography variant="caption" sx={{ textAlign: "right" }}>
        {Math.round(shown * 100)}%
      </Typography>
    </Box>
  );
};

export default LevelSlider;
