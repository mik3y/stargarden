import Alert from "@mui/material/Alert";
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Container from "@mui/material/Container";
import Grid from "@mui/material/Grid";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import { useCallback, useEffect, useState } from "react";

import ActionsCard from "@/components/actions-card";
import FixturesCard from "@/components/fixtures-card";
import LevelsCard from "@/components/levels-card";
import LogPane from "@/components/log-pane";
import StateCard from "@/components/state-card";
import { type Act, act } from "@/lib/api";
import { useConsole } from "@/lib/hooks";
import { SHORTCUTS } from "@/lib/keys";

/** Keys typed into a field or onto a slider are theirs, not shortcuts. */
const ownsKeys = (target: EventTarget | null): boolean => {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return (
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.isContentEditable ||
    target.getAttribute("role") === "slider"
  );
};

/**
 * The console: the same panels as the TUI (status and overrides, fixtures,
 * levels, one-shot actions, log), fed by one stream and driving the program
 * through named actions.
 */
const App = () => {
  const { connected, status, fixtures, log } = useConsole();
  const [error, setError] = useState("");

  const run: Act = useCallback(async (name, params) => {
    try {
      await act(name, params);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        ownsKeys(event.target)
      ) {
        return;
      }
      const shortcut = SHORTCUTS.find((s) => s.key === event.key);
      if (shortcut) {
        event.preventDefault();
        run(shortcut.action, shortcut.params);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [run]);

  useEffect(() => {
    document.title = status
      ? `${status.state.toUpperCase()} · Stargarden`
      : "Stargarden";
  }, [status?.state]);

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppBar position="sticky">
        <Toolbar variant="dense">
          <Typography variant="h6" component="h1">
            Stargarden
          </Typography>
          {status && (
            <Typography variant="caption" color="text.secondary" sx={{ ml: 2 }}>
              {status.site}
            </Typography>
          )}
          <Box sx={{ flex: 1 }} />
          <Chip
            size="small"
            variant="outlined"
            color={connected ? "success" : "default"}
            label={connected ? "live" : "reconnecting…"}
          />
        </Toolbar>
      </AppBar>

      <Container maxWidth="xl" sx={{ py: 3 }}>
        <Stack spacing={3}>
          <Grid container spacing={3}>
            <Grid size={{ xs: 12, md: 7 }}>
              <StateCard status={status} act={run} />
            </Grid>
            <Grid size={{ xs: 12, md: 5 }}>
              <Stack spacing={3}>
                <FixturesCard fixtures={fixtures} />
                <LevelsCard levels={status?.levels} act={run} />
                <ActionsCard status={status} act={run} />
              </Stack>
            </Grid>
          </Grid>
          <LogPane lines={log} debug={status?.debug ?? false} />
        </Stack>
      </Container>

      <Snackbar
        open={error !== ""}
        autoHideDuration={5000}
        onClose={() => setError("")}
      >
        <Alert severity="error" variant="filled" onClose={() => setError("")}>
          {error}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default App;
