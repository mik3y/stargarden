import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useEffect, useRef, useState } from "react";

import type { LogLine } from "@/lib/api";
import { fmtLogTime } from "@/lib/format";
import { FONT_MONO } from "@/theme";

interface LevelStyle {
  badge: string;
  color: string;
  bgcolor?: string;
  /** The message takes the level's color too (WARNING and up). */
  loud: boolean;
}

// Badge text and style per level, as in the TUI.
const LEVEL_STYLES: Record<string, LevelStyle> = {
  DEBUG: { badge: "DEBUG", color: "text.disabled", loud: false },
  INFO: { badge: "INFO ", color: "success.main", loud: false },
  WARNING: { badge: "WARN ", color: "warning.main", loud: true },
  ERROR: { badge: "ERROR", color: "error.main", loud: true },
  CRITICAL: {
    badge: "CRIT ",
    color: "common.white",
    bgcolor: "error.main",
    loud: true,
  },
};

const styleFor = (level: string): LevelStyle =>
  LEVEL_STYLES[level] ?? {
    badge: level.slice(0, 5).padEnd(5),
    color: "text.primary",
    loud: false,
  };

/** How close to the bottom (px) still counts as following the tail. */
const FOLLOW_SLACK = 12;

/**
 * The log stream, newest at the bottom. Follows the tail until the reader
 * scrolls up; a button brings them back.
 */
const LogPane = ({ lines, debug }: { lines: LogLine[]; debug: boolean }) => {
  const scroller = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);

  useEffect(() => {
    const el = scroller.current;
    if (following && el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [lines, following]);

  const onScroll = () => {
    const el = scroller.current;
    if (el) {
      setFollowing(
        el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_SLACK,
      );
    }
  };

  return (
    <Card>
      <CardContent sx={{ pb: 0 }}>
        <Stack direction="row" sx={{ alignItems: "center" }}>
          <Typography variant="overline" color="text.secondary">
            log{debug ? " (debug)" : ""}
          </Typography>
          <Box sx={{ flex: 1 }} />
          {!following && (
            <Button size="small" onClick={() => setFollowing(true)}>
              jump to latest
            </Button>
          )}
        </Stack>
      </CardContent>
      <Box
        ref={scroller}
        onScroll={onScroll}
        sx={{
          height: "40vh",
          minHeight: 200,
          overflowY: "auto",
          px: 2,
          pb: 2,
          fontFamily: FONT_MONO,
          fontSize: 12,
          lineHeight: 1.6,
        }}
      >
        {lines.map((line) => {
          const style = styleFor(line.level);
          return (
            <Box
              key={line.seq}
              sx={{
                display: "flex",
                gap: 1,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              <Box
                component="span"
                sx={{ color: "text.disabled", flexShrink: 0 }}
              >
                {fmtLogTime(line.t)}
              </Box>
              <Box
                component="span"
                sx={{
                  color: style.color,
                  bgcolor: style.bgcolor,
                  fontWeight: style.loud ? 700 : 400,
                  flexShrink: 0,
                }}
              >
                {style.badge}
              </Box>
              <Box
                component="span"
                title={line.name}
                sx={{
                  color: "secondary.light",
                  flexShrink: 0,
                  width: "11em",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {line.name}
              </Box>
              <Box
                component="span"
                sx={{ color: style.loud ? style.color : "text.primary" }}
              >
                {line.msg}
                {line.exc && (
                  <Box component="pre" sx={{ m: 0, color: "error.main" }}>
                    {line.exc}
                  </Box>
                )}
              </Box>
            </Box>
          );
        })}
      </Box>
    </Card>
  );
};

export default LogPane;
