import RestartAltIcon from "@mui/icons-material/RestartAlt";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogContentText from "@mui/material/DialogContentText";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useState } from "react";

import Kbd from "@/components/kbd";
import type { Act, Program } from "@/lib/api";
import { keyFor } from "@/lib/keys";
import { FONT_MONO } from "@/theme";

const POOLS: Program["pool"][] = ["ambient", "show"];

/**
 * The lighting programs by pool. A checked program is in the random rotation
 * (at least one per pool stays checked; the server refuses the last), "play"
 * puts one on now, and the reset button hands levels, peak and these choices
 * back to the config file, after a confirmation. All of it persists on the Pi.
 */
const ProgramsCard = ({
  programs,
  act,
}: {
  programs: Program[] | undefined;
  act: Act;
}) => {
  const [confirm, setConfirm] = useState(false);

  return (
    <Card>
      <CardContent>
        <Typography variant="overline" color="text.secondary">
          programs
        </Typography>
        {POOLS.map((pool) => (
          <Box key={pool} sx={{ mt: 1 }}>
            <Typography variant="caption" color="text.secondary">
              {pool}
            </Typography>
            {(programs ?? [])
              .filter((p) => p.pool === pool)
              .map((p) => (
                <Stack
                  key={p.name}
                  direction="row"
                  spacing={1}
                  sx={{ alignItems: "center" }}
                >
                  <FormControlLabel
                    sx={{ flex: 1, mr: 0 }}
                    control={
                      <Checkbox
                        size="small"
                        checked={p.enabled}
                        onChange={(_, checked) =>
                          act("set_theme_enabled", {
                            name: p.name,
                            enabled: checked,
                          })
                        }
                      />
                    }
                    label={
                      <Typography
                        variant="body2"
                        sx={{ fontFamily: FONT_MONO }}
                      >
                        {p.name}
                      </Typography>
                    }
                  />
                  {p.playing ? (
                    <Chip
                      size="small"
                      color="primary"
                      variant="outlined"
                      label="playing"
                    />
                  ) : (
                    <Button
                      size="small"
                      onClick={() => act("set_theme", { name: p.name })}
                    >
                      play
                    </Button>
                  )}
                </Stack>
              ))}
          </Box>
        ))}
        <Typography
          variant="caption"
          color="text.secondary"
          component="p"
          sx={{ mt: 1 }}
        >
          Unchecked programs stay out of the random rotation. Program choices,
          levels and the peak are kept across restarts.
          <Kbd>{keyFor("next_theme")}</Kbd> steps through every program.
        </Typography>
        <Button
          size="small"
          color="warning"
          startIcon={<RestartAltIcon />}
          sx={{ mt: 1 }}
          onClick={() => setConfirm(true)}
        >
          reset to defaults
        </Button>
        <Dialog open={confirm} onClose={() => setConfirm(false)}>
          <DialogTitle>Reset to defaults?</DialogTitle>
          <DialogContent>
            <DialogContentText>
              Levels, the lighting peak and the program choices go back to the
              values in the config file.
            </DialogContentText>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setConfirm(false)}>cancel</Button>
            <Button
              color="warning"
              onClick={() => {
                setConfirm(false);
                act("reset_defaults");
              }}
            >
              reset
            </Button>
          </DialogActions>
        </Dialog>
      </CardContent>
    </Card>
  );
};

export default ProgramsCard;
