import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";

import LevelSlider from "@/components/level-slider";
import type { Act, SpotColor, Status } from "@/lib/api";

const SPOT_COLORS: SpotColor[] = ["white", "match"];

/**
 * What the bars show, the sunset or one of the dance patterns, with the
 * patterns' tempo; and, when pin spots are patched, their level and color.
 */
const ProgramCard = ({ status, act }: { status: Status | null; act: Act }) => (
  <Card>
    <CardContent>
      <Typography variant="overline" color="text.secondary">
        program
      </Typography>
      {!status && <Skeleton height={80} />}
      {status && (
        <Stack spacing={1.5} sx={{ mt: 1 }}>
          <ToggleButtonGroup
            size="small"
            exclusive
            fullWidth
            color="primary"
            value={status.program}
            onChange={(_, name: string | null) => {
              if (name !== null) {
                act("set_program", { name });
              }
            }}
          >
            {status.programs.map((name) => (
              <ToggleButton key={name} value={name} sx={{ px: 0.5 }}>
                {name}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
          <LevelSlider
            label="tempo"
            value={status.tempo}
            min={40}
            max={180}
            step={1}
            format={(bpm) => `${Math.round(bpm)} bpm`}
            onSend={(bpm) => act("set_tempo", { bpm })}
          />
          {status.spots && (
            <>
              <Typography variant="overline" color="text.secondary">
                pin spots
              </Typography>
              <LevelSlider
                label="level"
                value={status.spot_level}
                onSend={(value) => act("set_spot_level", { value })}
              />
              <ToggleButtonGroup
                size="small"
                exclusive
                color="primary"
                value={status.spot_color}
                onChange={(_, color: SpotColor | null) => {
                  if (color !== null) {
                    act("set_spot_color", { color });
                  }
                }}
              >
                {SPOT_COLORS.map((color) => (
                  <ToggleButton key={color} value={color} sx={{ width: 88 }}>
                    {color}
                  </ToggleButton>
                ))}
              </ToggleButtonGroup>
            </>
          )}
        </Stack>
      )}
    </CardContent>
  </Card>
);

export default ProgramCard;
