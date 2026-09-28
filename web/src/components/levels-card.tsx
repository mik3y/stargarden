import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Skeleton from "@mui/material/Skeleton";
import Slider from "@mui/material/Slider";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useRef, useState } from "react";

import type { Act } from "@/lib/api";

/** How often a slider mid-drag sends its value, so the audio follows the hand. */
const DRAG_SEND_MS = 80;
/** How long a released slider keeps showing its own value before trusting the stream again. */
const SETTLE_MS = 400;

/**
 * Per-layer audio levels and the lighting peak: whatever `levels` the status
 * carries, in its order, so a new level in Python shows up here unasked.
 */
const LevelsCard = ({
  levels,
  act,
}: {
  levels: Record<string, number> | undefined;
  act: Act;
}) => {
  // A slider being dragged shows its own value, not the stream's (which lags a tick).
  const [pending, setPending] = useState<Record<string, number>>({});
  const lastSent = useRef<Record<string, number>>({});
  const settle = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const change = (name: string, value: number) => {
    setPending((p) => ({ ...p, [name]: value }));
    const now = Date.now();
    if (now - (lastSent.current[name] ?? 0) >= DRAG_SEND_MS) {
      lastSent.current[name] = now;
      act("set_level", { name, value });
    }
  };

  const commit = (name: string, value: number) => {
    lastSent.current[name] = Date.now();
    act("set_level", { name, value });
    clearTimeout(settle.current[name]);
    settle.current[name] = setTimeout(() => {
      setPending((p) => {
        const { [name]: _, ...rest } = p;
        return rest;
      });
    }, SETTLE_MS);
  };

  return (
    <Card>
      <CardContent>
        <Typography variant="overline" color="text.secondary">
          levels
        </Typography>
        <Stack spacing={0.5} sx={{ mt: 1 }}>
          {!levels && <Skeleton height={32} />}
          {levels &&
            Object.entries(levels).map(([name, value]) => {
              const shown = pending[name] ?? value;
              return (
                <Box
                  key={name}
                  sx={{
                    display: "grid",
                    gridTemplateColumns: "6em 1fr 3em",
                    alignItems: "center",
                    columnGap: 2,
                  }}
                >
                  <Typography variant="caption">{name}</Typography>
                  <Slider
                    size="small"
                    min={0}
                    max={1}
                    step={0.01}
                    value={shown}
                    color={name === "peak" ? "secondary" : "primary"}
                    aria-label={name}
                    onChange={(_, v) => change(name, v as number)}
                    onChangeCommitted={(_, v) => commit(name, v as number)}
                  />
                  <Typography variant="caption" sx={{ textAlign: "right" }}>
                    {shown.toFixed(2)}
                  </Typography>
                </Box>
              );
            })}
        </Stack>
      </CardContent>
    </Card>
  );
};

export default LevelsCard;
