import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import FormControlLabel from "@mui/material/FormControlLabel";
import InputAdornment from "@mui/material/InputAdornment";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { useEffect, useState } from "react";

import LevelSlider from "@/components/level-slider";
import type { Act, Status } from "@/lib/api";

/** Minutes from orange to purple offered as one-tap choices. */
const PRESETS_MIN = [5, 10, 15, 30, 60];

/** Enough digits to read, no trailing noise. */
const fmt = (value: number): string =>
  Number.isInteger(value) ? String(value) : value.toFixed(1);

/**
 * Minutes from orange to purple: presets, and a field for anything else,
 * sent when the field is left or Enter is pressed.
 */
const LengthField = ({ seconds, act }: { seconds: number; act: Act }) => {
  const minutes = seconds / 60;
  const shown = fmt(minutes);
  const [text, setText] = useState(shown);
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    if (!editing) {
      setText(shown);
    }
  }, [shown, editing]);

  const send = (value: number) => {
    if (value * 60 !== seconds) {
      act("set_leg", { seconds: value * 60 });
    }
  };
  const commit = () => {
    setEditing(false);
    const value = Number(text);
    if (!Number.isFinite(value) || value <= 0 || text.trim() === "") {
      setText(shown);
      return;
    }
    send(value);
  };

  return (
    <Stack
      direction="row"
      spacing={2}
      useFlexGap
      sx={{ alignItems: "center", flexWrap: "wrap" }}
    >
      <TextField
        size="small"
        type="number"
        label="orange to purple"
        value={text}
        onFocus={() => setEditing(true)}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            (e.target as HTMLInputElement).blur();
          }
        }}
        slotProps={{
          input: {
            endAdornment: <InputAdornment position="end">min</InputAdornment>,
          },
          htmlInput: { min: 0, step: 1, inputMode: "decimal" },
        }}
        sx={{ width: "11em" }}
      />
      <ToggleButtonGroup
        size="small"
        exclusive
        value={minutes}
        onChange={(_, value: number | null) => {
          if (value !== null) {
            send(value);
          }
        }}
      >
        {PRESETS_MIN.map((preset) => (
          <ToggleButton key={preset} value={preset} sx={{ width: 44 }}>
            {preset}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>
    </Stack>
  );
};

/**
 * What persists on the Pi: the sunset's length and the two brightness levels.
 * Below, the setup check, debug logging, and a way back to the config file.
 */
const SettingsCard = ({ status, act }: { status: Status | null; act: Act }) => (
  <Card>
    <CardContent>
      <Typography variant="overline" color="text.secondary">
        settings
      </Typography>
      {!status && <Skeleton height={120} />}
      {status && (
        <Stack spacing={2} sx={{ mt: 1.5 }}>
          <LengthField seconds={status.leg_s} act={act} />
          <Stack spacing={0.5}>
            <LevelSlider
              label="brightness"
              value={status.peak}
              onSend={(value) => act("set_peak", { value })}
            />
            <LevelSlider
              label="purple end"
              value={status.dusk_level}
              min={0.05}
              onSend={(value) => act("set_dusk_level", { value })}
            />
          </Stack>
          <Stack>
            <FormControlLabel
              control={
                <Switch
                  size="small"
                  color="secondary"
                  checked={status.check}
                  onChange={(_, on) => act("set_check", { on })}
                />
              }
              label={<Typography variant="body2">setup check</Typography>}
            />
            <FormControlLabel
              control={
                <Switch
                  size="small"
                  checked={status.debug}
                  onChange={(_, debug) => act("set_debug", { debug })}
                />
              }
              label={<Typography variant="body2">debug logging</Typography>}
            />
          </Stack>
          <Button
            size="small"
            variant="outlined"
            color="inherit"
            sx={{ alignSelf: "flex-start" }}
            onClick={() => act("reset_defaults")}
          >
            reset to defaults
          </Button>
        </Stack>
      )}
    </CardContent>
  </Card>
);

export default SettingsCard;
