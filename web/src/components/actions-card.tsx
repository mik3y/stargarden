import BoltIcon from "@mui/icons-material/Bolt";
import DirectionsWalkIcon from "@mui/icons-material/DirectionsWalk";
import GraphicEqIcon from "@mui/icons-material/GraphicEq";
import HikingIcon from "@mui/icons-material/Hiking";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import FormControlLabel from "@mui/material/FormControlLabel";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Typography from "@mui/material/Typography";

import Kbd from "@/components/kbd";
import type { Act, Status } from "@/lib/api";
import { keyFor } from "@/lib/keys";

/**
 * One-shot actions: fake a sensor (the platform sensor starts a visit, the
 * walkway one only refreshes it), fire a lightning strike or a discrete
 * sound, and the debug-logging switch.
 */
const ActionsCard = ({ status, act }: { status: Status | null; act: Act }) => (
  <Card>
    <CardContent>
      <Typography variant="overline" color="text.secondary">
        actions
      </Typography>
      <Stack
        direction="row"
        useFlexGap
        spacing={1}
        sx={{ mt: 1, flexWrap: "wrap" }}
      >
        <Button
          variant="outlined"
          startIcon={<DirectionsWalkIcon />}
          onClick={() => act("motion", { role: "platform" })}
        >
          platform motion
          <Kbd>{keyFor("motion", { role: "platform" })}</Kbd>
        </Button>
        <Button
          variant="outlined"
          startIcon={<HikingIcon />}
          onClick={() => act("motion", { role: "walkway" })}
        >
          walkway motion
          <Kbd>{keyFor("motion", { role: "walkway" })}</Kbd>
        </Button>
        <Button
          variant="outlined"
          color="secondary"
          startIcon={<BoltIcon />}
          onClick={() => act("lightning")}
        >
          lightning
          <Kbd>{keyFor("lightning")}</Kbd>
        </Button>
        <Button
          variant="outlined"
          color="secondary"
          startIcon={<GraphicEqIcon />}
          onClick={() => act("discrete")}
        >
          sound
          <Kbd>{keyFor("discrete")}</Kbd>
        </Button>
      </Stack>
      <FormControlLabel
        sx={{ mt: 1.5 }}
        control={
          <Switch
            size="small"
            checked={status?.debug ?? false}
            disabled={!status}
            onChange={(_, checked) => act("set_debug", { debug: checked })}
          />
        }
        label={
          <Typography variant="body2">
            debug logging
            <Kbd>{keyFor("toggle_debug")}</Kbd>
          </Typography>
        }
      />
    </CardContent>
  </Card>
);

export default ActionsCard;
