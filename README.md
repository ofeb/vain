# bleed-bot

## Layout

- `core/` contains the runtime, database, patches, helpers, and shared Discord abstractions.
- `ext/` contains the bot feature surface grouped by domain.
- `lib/` contains targeted compatibility shims for legacy import paths still used by ported code.
- `__exec__.py`, `main.py`, and `launcher.py` are the repo-root entrypoints.

The repo no longer nests the runtime under a leftover `bleed/` folder. The repo
root is the runtime root.
