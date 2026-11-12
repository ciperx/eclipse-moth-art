# Papercut Lighthouse

A single 1024x1024 PNG drawn by `main.py` with nothing but the Python standard
library: a night seascape built from eight flat paper plates, each a solid
colour with a crisp cut edge and a soft drop shadow nudged down-right, so the
picture reads as card stacked in depth.

Navy sky with punched cream stars, a low moon, a wide translucent pale-gold
beam sweeping left from the lantern, three dark teal sea bands with scalloped
crests, a pale cliff on the right, and a white lighthouse with two thin dark
rings and a warm-yellow lantern room.

```bash
mkdir -p out
MAKEFUN_OUTPUT_DIR=out python3 main.py   # writes out/entry.png
```

Edges are anti-aliased from analytic box coverage of each span, so silhouettes
stay clean at 1024 without any dithering. Runs in about one second on a single
CPU and produces a ~100 KB file.

MIT licensed. Built for make.fun's *Make the coolest art* competition.
