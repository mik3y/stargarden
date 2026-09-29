import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip, { type ChipProps } from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import FormControlLabel from "@mui/material/FormControlLabel";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";

import Kbd from "@/components/kbd";
import { type Act, STATES, type State, type Status } from "@/lib/api";
import { fmtClock, fmtSeconds } from "@/lib/format";
import { keyFor } from "@/lib/keys";
import { FONT_MONO } from "@/theme";

const STATE_COLORS: Record<State, ChipProps["color"]> = {
  off: "default",
  ambient: "primary",
  presence: "success",
  show: "secondary",
};

const Fact = ({ label, children }: { label: string; children: ReactNode }) => (
  <Box sx={{ display: "grid", gridTemplateColumns: "6em 1fr", gap: 1 }}>
    <Typography variant="caption" color="text.secondary" sx={{ pt: "1px" }}>
      {label}
    </Typography>
    <Typography variant="body2" sx={{ fontFamily: FONT_MONO }}>
      {children}
    </Typography>
  </Box>
);

/**
 * The program's state and the controls that pin it: force a state (or
 * release), override the sunset schedule. Below, the same facts as the TUI's
 * status panel.
 */
const StateCard = ({ status, act }: { status: Status | null; act: Act }) => {
  if (!status) {
    return (
      <Card>
        <CardContent>
          <Skeleton width={140} height={40} />
          <Skeleton />
          <Skeleton />
          <Skeleton width="60%" />
        </CardContent>
      </Card>
    );
  }
  const night = `${status.night ? "night" : "day"}${status.night_override !== null ? " (override)" : ""}`;
  const motion = Object.entries(status.motion_ago_s)
    .map(([role, ago]) => `${role} ${fmtSeconds(ago)} ago`)
    .join(", ");

  return (
    <Card>
      <CardContent>
        <Stack
          direction="row"
          spacing={1.5}
          useFlexGap
          sx={{ alignItems: "center", flexWrap: "wrap" }}
        >
          <Chip
            label={status.state.toUpperCase()}
            color={STATE_COLORS[status.state]}
            sx={{
              fontFamily: FONT_MONO,
              fontWeight: 700,
              fontSize: 18,
              height: 40,
              px: 1,
            }}
          />
          {status.forced && (
            <Chip
              size="small"
              variant="outlined"
              color="warning"
              label="forced"
            />
          )}
          {status.check && (
            <Chip
              size="small"
              variant="outlined"
              color="secondary"
              label="setup check"
            />
          )}
          <Box sx={{ flex: 1 }} />
          <FormControlLabel
            control={
              <Switch
                checked={status.night}
                onChange={(_, checked) => act("set_night", { night: checked })}
              />
            }
            label={
              <Typography variant="body2">
                {night}
                <Kbd>{keyFor("toggle_night")}</Kbd>
              </Typography>
            }
          />
          {status.night_override !== null && (
            <Button
              size="small"
              onClick={() => act("set_night", { night: null })}
            >
              follow schedule
            </Button>
          )}
        </Stack>

        <Stack
          direction="row"
          spacing={1.5}
          useFlexGap
          sx={{ mt: 2, alignItems: "center", flexWrap: "wrap" }}
        >
          <Typography variant="overline" color="text.secondary">
            force
          </Typography>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={status.forced}
            // Clicking the pinned state again yields null: release.
            onChange={(_, state: State | null) => act("force", { state })}
          >
            {STATES.map((state) => (
              <ToggleButton key={state} value={state} sx={{ px: 1.5 }}>
                {state}
                <Kbd>{keyFor("force", { state })}</Kbd>
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
          <Button
            size="small"
            variant="outlined"
            disabled={!status.forced}
            onClick={() => act("release")}
          >
            release
            <Kbd>{keyFor("release")}</Kbd>
          </Button>
        </Stack>

        <Divider sx={{ my: 2 }} />

        <Stack spacing={0.5}>
          <Fact label="schedule">
            {night}; next {fmtClock(status.next_transition)}
          </Fact>
          <Fact label="space">
            {status.occupied ? "occupied" : "vacant"}; hold{" "}
            {fmtSeconds(status.hold_remaining_s)}
          </Fact>
          <Fact label="motion">{motion}</Fact>
          <Fact label="show">
            in {fmtSeconds(status.show_in_s)}; #{status.shows_this_visit} this
            visit
          </Fact>
          <Fact label="lights">
            {status.theme} via {status.driver}, master{" "}
            {status.master.toFixed(2)}
          </Fact>
          <Fact label="storm">
            next strike in {fmtSeconds(status.storm_in_s)}
            {status.lightning_allowed ? "" : " (held: not in presence)"}
          </Fact>
          <Fact label="audio">
            {status.audio_out}, {status.audio_mode} @ {status.samplerate} Hz
          </Fact>
          <Fact label="bed">{status.bed ?? "—"}</Fact>
          <Fact label="music">{status.music ?? "—"}</Fact>
        </Stack>
      </CardContent>
    </Card>
  );
};

export default StateCard;
