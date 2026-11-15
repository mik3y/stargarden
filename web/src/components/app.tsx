import Alert from "@mui/material/Alert";
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Container from "@mui/material/Container";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import { useCallback, useEffect, useState } from "react";

import FixturesCard from "@/components/fixtures-card";
import LogPane from "@/components/log-pane";
import SettingsCard from "@/components/settings-card";
import SunsetCard from "@/components/sunset-card";
import { type Act, act } from "@/lib/api";
import { useConsole } from "@/lib/hooks";

/**
 * The console on one page, sized for a phone: the sunset and its controls,
 * the bars as the program is driving them, the settings, the log. One stream
 * feeds it and named actions drive the program.
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

  const site = status?.site;
  useEffect(() => {
    document.title = site ?? "Stargarden";
  }, [site]);

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppBar position="sticky">
        <Toolbar variant="dense">
          <Typography variant="h6" component="h1">
            {site ?? "Stargarden"}
          </Typography>
          <Box sx={{ flex: 1 }} />
          <Chip
            size="small"
            variant="outlined"
            color={connected ? "success" : "default"}
            label={connected ? "live" : "reconnecting…"}
          />
        </Toolbar>
      </AppBar>

      <Container maxWidth="sm" sx={{ py: 3 }}>
        <Stack spacing={3}>
          <SunsetCard status={status} act={run} />
          <FixturesCard fixtures={fixtures} />
          <SettingsCard status={status} act={run} />
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
