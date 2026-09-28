import CssBaseline from "@mui/material/CssBaseline";
import { ThemeProvider } from "@mui/material/styles";
import { createRoot } from "react-dom/client";

import App from "@/components/app";
import theme from "@/theme";

const container = document.getElementById("react-app");
if (!container) {
  throw new Error("Missing #react-app mount point");
}
createRoot(container).render(
  <ThemeProvider theme={theme}>
    <CssBaseline />
    <App />
  </ThemeProvider>,
);
