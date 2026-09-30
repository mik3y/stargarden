import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import InputAdornment from "@mui/material/InputAdornment";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useEffect, useState } from "react";

import type { Act, Setting } from "@/lib/api";

/** How a setting is shown: its label and the unit its field works in (the server takes seconds). */
interface Field {
  group: string;
  label: string;
  unit: "s" | "min";
}

const FIELDS: Record<string, Field> = {
  "timers.show_delay_s": { group: "shows", label: "first after", unit: "min" },
  "timers.show_repeat_delay_s": {
    group: "shows",
    label: "then every",
    unit: "min",
  },
  "discretes.min_interval_s": {
    group: "discretes",
    label: "at least",
    unit: "s",
  },
  "discretes.max_interval_s": {
    group: "discretes",
    label: "at most",
    unit: "s",
  },
  "lightning.mean_interval_s": {
    group: "lightning",
    label: "about every",
    unit: "min",
  },
  "lightning.min_interval_s": {
    group: "lightning",
    label: "never closer than",
    unit: "min",
  },
};

const HINTS: Record<string, string> = {
  shows:
    "how long the space stays occupied before the first show, and between one show and the next",
  discretes:
    "a bird call or wing flap, this long after the last, while ambience plays",
  lightning:
    "strikes come at random this far apart on average, but never closer than the floor",
};

const toUnit = (seconds: number, unit: Field["unit"]): number =>
  unit === "min" ? seconds / 60 : seconds;
const toSeconds = (value: number, unit: Field["unit"]): number =>
  unit === "min" ? value * 60 : value;

/** Enough digits to read, no trailing noise. */
const fmt = (value: number): string =>
  Number.isInteger(value) ? String(value) : value.toFixed(1);

/**
 * One setting as a number field: edits are sent when the field is left or
 * Enter is pressed, and the stream's value fills it in between. The config
 * file's value is shown underneath when the setting differs from it.
 */
const SettingField = ({
  setting,
  field,
  act,
}: {
  setting: Setting;
  field: Field;
  act: Act;
}) => {
  const shown = fmt(toUnit(setting.value, field.unit));
  const [text, setText] = useState(shown);
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    if (!editing) {
      setText(shown);
    }
  }, [shown, editing]);

  const commit = () => {
    setEditing(false);
    const value = Number(text);
    if (!Number.isFinite(value) || value <= 0 || text.trim() === "") {
      setText(shown);
      return;
    }
    const seconds = toSeconds(value, field.unit);
    if (seconds !== setting.value) {
      act("set_setting", { name: setting.name, value: seconds });
    }
  };

  const overridden = setting.value !== setting.default;
  return (
    <TextField
      size="small"
      type="number"
      label={field.label}
      value={text}
      onFocus={() => setEditing(true)}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          (e.target as HTMLInputElement).blur();
        }
      }}
      helperText={
        overridden ? `config: ${fmt(toUnit(setting.default, field.unit))}` : " "
      }
      slotProps={{
        input: {
          endAdornment: (
            <InputAdornment position="end">{field.unit}</InputAdornment>
          ),
        },
        htmlInput: { min: 0, step: field.unit === "min" ? 0.5 : 5 },
      }}
      sx={{ width: "11em" }}
    />
  );
};

/**
 * The timing settings: how often discrete sounds and lightning come. Values
 * apply at once and persist on the Pi; reset to defaults (on the programs
 * card) puts the config file's values back.
 */
const SettingsCard = ({
  settings,
  act,
}: {
  settings: Setting[] | undefined;
  act: Act;
}) => {
  const groups = Array.from(new Set(Object.values(FIELDS).map((f) => f.group)));
  return (
    <Card>
      <CardContent>
        <Typography variant="overline" color="text.secondary">
          timing
        </Typography>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {groups.map((group) => (
            <Stack key={group} spacing={1}>
              <Typography variant="caption" color="text.secondary">
                {group}
              </Typography>
              <Stack
                direction="row"
                spacing={2}
                useFlexGap
                sx={{ flexWrap: "wrap" }}
              >
                {(settings ?? [])
                  .filter((s) => FIELDS[s.name]?.group === group)
                  .map((s) => (
                    <SettingField
                      key={s.name}
                      setting={s}
                      field={FIELDS[s.name]}
                      act={act}
                    />
                  ))}
              </Stack>
              <Typography variant="caption" color="text.secondary">
                {HINTS[group]}
              </Typography>
            </Stack>
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
};

export default SettingsCard;
