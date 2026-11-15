import PauseIcon from "@mui/icons-material/Pause";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip, { type ChipProps } from "@mui/material/Chip";
import FormControlLabel from "@mui/material/FormControlLabel";
import Skeleton from "@mui/material/Skeleton";
import Slider from "@mui/material/Slider";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Typography from "@mui/material/Typography";

import { useDragValue } from "@/components/level-slider";
import type { Act, Status } from "@/lib/api";
import { fmtSeconds } from "@/lib/format";
import { FONT_MONO } from "@/theme";

const BAR_HEIGHT = 56;

const stateOf = (
  status: Status,
): { label: string; color: ChipProps["color"] } => {
  if (!status.on) {
    return { label: "OFF", color: "default" };
  }
  if (status.paused) {
    return { label: "HELD", color: "warning" };
  }
  return { label: "RUNNING", color: "primary" };
};

/**
 * The sunset as a strip from orange to purple with a handle at its place.
 * Dragging the handle, or stepping it darker or brighter, holds the sunset
 * there until resumed.
 */
const SunsetCard = ({ status, act }: { status: Status | null; act: Act }) => {
  const { shown, change, commit } = useDragValue(
    status?.position ?? 0,
    (position) => act("set_position", { position }),
  );
  if (!status) {
    return (
      <Card>
        <CardContent>
          <Skeleton width={140} height={40} />
          <Skeleton height={BAR_HEIGHT} />
          <Skeleton width="60%" />
        </CardContent>
      </Card>
    );
  }
  const state = stateOf(status);
  const gradient = `linear-gradient(to right, ${status.palette
    .map((rgb) => `rgb(${rgb.join(",")})`)
    .join(", ")})`;
  const heading = status.direction === "darkening" ? "purple" : "orange";

  return (
    <Card>
      <CardContent>
        <Stack direction="row" spacing={1.5} sx={{ alignItems: "center" }}>
          <Chip
            label={state.label}
            color={state.color}
            sx={{
              fontFamily: FONT_MONO,
              fontWeight: 700,
              fontSize: 18,
              height: 40,
              px: 1,
            }}
          />
          <Box sx={{ flex: 1 }} />
          <FormControlLabel
            sx={{ mr: 0 }}
            control={
              <Switch
                checked={status.on}
                onChange={(_, on) => act("set_on", { on })}
              />
            }
            label={<Typography variant="body2">lights</Typography>}
          />
        </Stack>
        <Typography variant="body2" sx={{ fontFamily: FONT_MONO, mt: 1.5 }}>
          {Math.round(shown * 100)}%
          {status.paused
            ? ""
            : `, ${heading} in ${fmtSeconds(status.leg_remaining_s)}`}
        </Typography>

        <Box sx={{ position: "relative", mt: 2, px: 1.5 }}>
          <Slider
            min={0}
            max={1}
            step={0.005}
            value={shown}
            track={false}
            aria-label="sunset position"
            onChange={(_, v) => change(v as number)}
            onChangeCommitted={(_, v) => commit(v as number)}
            sx={{
              height: BAR_HEIGHT,
              p: "0 !important",
              display: "block",
              "& .MuiSlider-rail": {
                opacity: 1,
                background: gradient,
                borderRadius: 1,
                // The strip runs under the handle at both ends.
                left: -12,
                right: -12,
                width: "auto",
              },
              "& .MuiSlider-thumb": {
                width: 10,
                height: BAR_HEIGHT + 12,
                borderRadius: 1,
                bgcolor: "common.white",
                boxShadow: "0 0 0 2px rgba(0,0,0,0.6)",
              },
            }}
          />
          <Box
            // Where the lights are now, while they glide to the handle.
            sx={{
              position: "absolute",
              top: -4,
              left: 12,
              right: 12,
              height: 4,
              pointerEvents: "none",
            }}
          >
            <Box
              sx={{
                position: "absolute",
                left: `${status.shown * 100}%`,
                width: 8,
                height: 4,
                ml: "-4px",
                borderRadius: 0.5,
                bgcolor: "text.secondary",
              }}
            />
          </Box>
        </Box>

        <Stack direction="row" spacing={1} sx={{ mt: 2.5 }}>
          <Button
            variant="outlined"
            sx={{ flex: 1 }}
            onClick={() => act("nudge", { steps: -1 })}
          >
            brighter
          </Button>
          <Button
            variant="contained"
            sx={{ flex: 1 }}
            startIcon={status.paused ? <PlayArrowIcon /> : <PauseIcon />}
            onClick={() => act("set_paused", { paused: !status.paused })}
          >
            {status.paused ? "resume" : "hold"}
          </Button>
          <Button
            variant="outlined"
            color="secondary"
            sx={{ flex: 1 }}
            onClick={() => act("nudge", { steps: 1 })}
          >
            darker
          </Button>
        </Stack>
        <Button
          size="small"
          sx={{ mt: 1.5 }}
          startIcon={<RestartAltIcon />}
          onClick={() => act("restart")}
        >
          restart from orange
        </Button>
      </CardContent>
    </Card>
  );
};

export default SunsetCard;
