import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import SkipNextIcon from "@mui/icons-material/SkipNext";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import FormControlLabel from "@mui/material/FormControlLabel";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { Act, Track } from "@/lib/api";
import { FONT_MONO } from "@/theme";

/** What the manifest and the tempo measurement say about a track, or nothing yet. */
const details = (t: Track): string => {
  const parts = [];
  if (t.theme) {
    parts.push(t.theme);
  }
  if (t.bpm !== null) {
    parts.push(`${t.bpm.toFixed(0)} bpm`);
  }
  return parts.join(" · ");
};

/**
 * The show tracks. A checked track is in the random rotation (at least one
 * stays checked; the server refuses the last), "next" queues one for the
 * next show whatever the rotation would pick (again to unqueue), and "now"
 * starts a show with it at once, or starts the running show over. The
 * checks persist on the Pi; the queue lasts until the next show.
 */
const TracksCard = ({
  tracks,
  act,
}: {
  tracks: Track[] | undefined;
  act: Act;
}) => (
  <Card>
    <CardContent>
      <Typography variant="overline" color="text.secondary">
        tracks
      </Typography>
      <Stack spacing={0.5} sx={{ mt: 1 }}>
        {(tracks ?? []).map((t) => (
          <Stack
            key={t.id}
            direction="row"
            spacing={1}
            useFlexGap
            sx={{ alignItems: "center", flexWrap: "wrap" }}
          >
            <FormControlLabel
              sx={{ flex: 1, mr: 0, minWidth: 0 }}
              control={
                <Checkbox
                  size="small"
                  checked={t.enabled}
                  onChange={(_, checked) =>
                    act("set_track_enabled", { id: t.id, enabled: checked })
                  }
                />
              }
              label={
                <Stack sx={{ minWidth: 0 }}>
                  <Typography variant="body2" noWrap>
                    {t.title}
                  </Typography>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ fontFamily: FONT_MONO }}
                  >
                    {details(t) || " "}
                  </Typography>
                </Stack>
              }
            />
            {t.playing && (
              <Chip
                size="small"
                color="primary"
                variant="outlined"
                label="playing"
              />
            )}
            <Button
              size="small"
              variant={t.next ? "contained" : "text"}
              startIcon={<SkipNextIcon />}
              onClick={() => act("queue_track", { id: t.next ? null : t.id })}
            >
              next
            </Button>
            <Button
              size="small"
              startIcon={<PlayArrowIcon />}
              onClick={() => act("play_track", { id: t.id })}
            >
              now
            </Button>
          </Stack>
        ))}
        {tracks && tracks.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            No music in the manifest.
          </Typography>
        )}
      </Stack>
      <Typography
        variant="caption"
        color="text.secondary"
        component="p"
        sx={{ mt: 1 }}
      >
        Unchecked tracks stay out of the random rotation. "next" queues a track
        for the next show; "now" starts a show with it at once, or starts the
        running one over.
      </Typography>
    </CardContent>
  </Card>
);

export default TracksCard;
