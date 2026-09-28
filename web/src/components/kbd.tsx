import Box from "@mui/material/Box";

import { FONT_MONO } from "@/theme";

/** A keyboard hint beside a control's label, e.g. the TUI's key for the same action. */
const Kbd = ({ children }: { children?: string }) => {
  if (!children) {
    return null;
  }
  return (
    <Box
      component="kbd"
      sx={{
        ml: 1,
        px: 0.6,
        border: "1px solid",
        borderColor: "divider",
        borderRadius: 0.5,
        fontFamily: FONT_MONO,
        fontSize: "0.75em",
        lineHeight: 1.6,
        opacity: 0.7,
      }}
    >
      {children}
    </Box>
  );
};

export default Kbd;
