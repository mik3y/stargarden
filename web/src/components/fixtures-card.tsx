import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { CellPreview, FixturePreview } from "@/lib/api";

const ROW_HEIGHT = 14;

const Cell = ({ cell }: { cell: CellPreview }) => (
  <Box
    sx={{
      flex: 1,
      height: ROW_HEIGHT,
      borderRadius: 0.5,
      bgcolor: `rgb(${cell.rgb.join(",")})`,
      // The hardware strobe is engaged: a dashed rim, like the TUI's hatched swatch.
      outline: cell.strobe ? "1px dashed rgba(255,255,255,0.7)" : "none",
      outlineOffset: -1,
      transition: "background-color 80ms linear",
    }}
  />
);

/**
 * The virtual fixtures: each fixture's color cells as swatches, row by row,
 * with its white cells (what lightning flashes) alongside.
 */
const FixturesCard = ({ fixtures }: { fixtures: FixturePreview[] }) => (
  <Card>
    <CardContent>
      <Typography variant="overline" color="text.secondary">
        fixtures
      </Typography>
      <Stack spacing={1.5} sx={{ mt: 1 }}>
        {fixtures.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            no fixtures patched
          </Typography>
        )}
        {fixtures.map((fixture) => {
          const height = fixture.rows.length * (ROW_HEIGHT + 2) - 2;
          return (
            <Stack
              key={fixture.name}
              direction="row"
              spacing={1.5}
              sx={{ alignItems: "center" }}
            >
              <Stack spacing="2px" sx={{ flex: 1 }}>
                {fixture.rows.map((row) => (
                  <Stack
                    key={row.map((cell) => cell.name).join("+")}
                    direction="row"
                    spacing="2px"
                  >
                    {row.map((cell) => (
                      <Cell key={cell.name} cell={cell} />
                    ))}
                  </Stack>
                ))}
              </Stack>
              {fixture.whites.length > 0 && (
                <Stack direction="row" spacing="2px">
                  {fixture.whites.map((white) => (
                    <Box
                      key={white.name}
                      sx={{
                        width: 8,
                        height,
                        borderRadius: 0.5,
                        bgcolor: `rgb(${white.rgb.join(",")})`,
                        border: "1px solid",
                        borderColor: "divider",
                      }}
                    />
                  ))}
                </Stack>
              )}
              <Typography
                variant="caption"
                sx={{ minWidth: "5em", textAlign: "right" }}
              >
                {fixture.name}
              </Typography>
            </Stack>
          );
        })}
      </Stack>
    </CardContent>
  </Card>
);

export default FixturesCard;
