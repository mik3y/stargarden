import { createTheme } from "@mui/material/styles";

/**
 * Night in a forest: a near-black blue canvas, ember amber for the primary
 * (the ambient program's palette) and orbit blue-violet for the secondary
 * (the show's). Anything data-like is set in mono, like the TUI. Dark only:
 * this is a control panel read in the dark.
 *
 * No web fonts: the program runs offline in the field.
 */
export const colors = {
  canvas: "#0b0e14",
  paper: "#131a24",
  ember: "#f5a524",
  orbit: "#8b95ff",
  moss: "#5fbf7a",
  text: "#e6e9ef",
  muted: "#8a94a6",
};

export const FONT_MONO =
  'ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace';

const theme = createTheme({
  palette: {
    mode: "dark",
    primary: { main: colors.ember, contrastText: colors.canvas },
    secondary: { main: colors.orbit, contrastText: colors.canvas },
    success: { main: colors.moss },
    background: { default: colors.canvas, paper: colors.paper },
    text: { primary: colors.text, secondary: colors.muted },
  },
  shape: {
    borderRadius: 8,
  },
  typography: {
    fontFamily: "system-ui, -apple-system, sans-serif",
    fontWeightMedium: 600,
    h6: { fontWeight: 700, letterSpacing: "-0.01em" },
    button: {
      fontFamily: FONT_MONO,
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.06em",
    },
    overline: { fontFamily: FONT_MONO, letterSpacing: "0.1em" },
    caption: { fontFamily: FONT_MONO, letterSpacing: "0.02em" },
  },
  components: {
    // Flat surfaces with a hairline rule; no elevation glow on the dark canvas.
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: { root: { backgroundImage: "none" } },
    },
    MuiCard: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        root: ({ theme: t }) => ({
          border: `1px solid ${t.palette.divider}`,
        }),
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
    },
    MuiAppBar: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        root: ({ theme: t }) => ({
          backgroundColor: t.palette.background.default,
          borderBottom: `1px solid ${t.palette.divider}`,
          backgroundImage: "none",
        }),
      },
    },
  },
});

export { theme as default };
