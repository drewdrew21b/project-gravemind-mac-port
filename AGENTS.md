# AGENTS.md

Pointers for contributors and coding agents. The README is for players; this file is for changing the port.

## Layout
- `install.sh`: installs and updates Project Gravemind and its Halo 2 files (also re-run by the app on every Mac port update).
- `scripts/`: what lands in `~/Games/ProjectGravemind/game/`: `run.sh` (starts Gravemind under Wine), `launch.sh` (starts the game and Workshop helper), `updater.py` (checks Gravemind GitHub releases), `tools.py` (game files and diagnostics), `game_process.py` (identifies this install's running game), and `workshop_helper.py` (Steam QR sign-in and MCC game downloads).
- `launcher/*.swift`: the app window (SwiftUI). Pure, tested logic lives in `LauncherCore.swift`; tests in `launcher/Tests/main.swift`.
- `docs/specs/` (plans), `docs/adr/` (decisions, including things that don't work).

## Checks (CI runs the same: `.github/workflows/checks.yml`)

- `/usr/bin/python3 -I -m unittest discover -s tests`
- `swiftc -typecheck -target arm64-apple-macos14.0 -swift-version 5 -parse-as-library launcher/*.swift`
- `scripts/make_launcher.sh test`

## Rules

- **Don't commit `launcher/ProjectReclaimer` or change `LAUNCHER_SHA` in a PR.** The maintainer rebuilds the launcher from source at release time (`scripts/make_launcher.sh` builds it and pins its checksum). Same for any other prebuilt binary: commit its source and build script.
- Players get a change only when `VERSION` on main goes up; the maintainer bumps it.
- Record every player-visible change in `CHANGELOG.md` under the upcoming version's `## X.Y.Z` heading (newest first, above `## Known issues`) in the same PR. The release workflow publishes that section as the release notes and fails if the tagged version has none.
- Tests and experiments never touch a real install (`~/Games/ProjectGravemind`, `~/Applications`): use a throwaway `RECLAIMER_HOME` / `RECLAIMER_APPS_DIR`.
- Process matches (`pgrep`/`pkill`) name this install or a test path, never a bare script or app name.
- Merge `main` and re-run the checks before asking for review: `main` moves, and a green run from before the move proves nothing about the merge. Merge, don't rebuild: never re-pin `LAUNCHER_SHA`, commit `launcher/ProjectReclaimer` or change `VERSION` to make the checks pass.
- Tickets that touch the same files do not run in parallel, whatever the dependency graph says: independent in the plan, conflicting on disk.

## Gravemind notes

- This is the public `drewdrew21b/project-gravemind-mac-port` fork; `origin` is this repo and `upstream` is Matt Romano's Reclaimer Mac port. Preserve the README credit to the original project.
- `VERSION` is the Mac-port version (currently 0.8.0), separate from Gravemind's version (for example, 0.18.380). The updater compares versions numerically, so an existing 1.4.7 Reclaimer install will not auto-downgrade to 0.8.0.
- Gravemind is the closed-source Windows `h2gravemind.exe` from `BriRoz1/h2gravemind-releases`; its release ZIP contains the executable. Do not assume Reclaimer executable names, CLI options, logs, mod behavior, or loopback requirements apply.
- MCC depots: shared files `976731`, Halo 2 campaign `976735`, multiplayer `976736` and `976737`. Verify multiplayer at `halo2/h2_maps_win64_dx11/ascension.map`; `976734` is not Halo 2 multiplayer.
- Steam QR sign-in and downloads use DepotDownloader; the Steam desktop client is not installed in Wine. The launcher has a manual Workshop-link download control. The background `workshop_helper.py` watcher still recognizes legacy Reclaimer log patterns, so `ready` means downloaded, not necessarily loaded by Gravemind.
- Workshop remains unresolved. On 2026-10-22, Steam login succeeded, Workshop item `3541781365` reached `ready`, and the `appworkshop_976730.acf` manifest existed. Gravemind nevertheless logged `MCC's steam_api64.dll not found, no Workshop downloads` and `0 Halo 2 mod(s)`. The DLL exists at `MCC/Binaries/Win64/steam_api64.dll`; a Wine `+file` trace showed `bink2w64.dll` opened there but no `steam_api64.dll` lookup. Do not install Steam in Wine or copy the DLL without confirmation from the Gravemind maintainers. Revisit the README Workshop caveat when this is resolved.
- Menu performance is unresolved: gameplay was reported at 60 FPS while main and pause menus fell below 10 FPS at low and high settings. The user reports Linux/Wine users see similar behavior; treat this as a Gravemind/Wine compatibility issue, not a proven Mac-only issue.
- Reclaimer's deleted loopback LaunchDaemon assigned extra `127.x` aliases for Reclaimer-specific binds. Do not restore it for Gravemind without evidence from Gravemind logs or maintainers.
- Logs: the source `scripts/launch.sh` captures Wine output in `~/Games/ProjectGravemind/logs/client-wine.log`; the repo scripts support `GRAVEMIND_DEBUG=1` for Wine/DXVK logs. Verify which wrapper is running: the installed `game/launch.sh` was stale and hardcoded the normal log. For file tracing, use the repo wrapper with `RECLAIMER_HOME` set to the install and explicit `WINEDEBUG=+timestamp,+pid,+tid,+file,err+all,+seh,+winsock,+winhttp,+wininet`; reproduce once because file logs grow quickly. Gravemind's own logs are in the Wine user's `AppData/Local/Project Gravemind/logs/`; **Tools > Make Report** includes recent logs and redacts account names and the Mac home path.
- `.github/workflows/checks.yml` runs tests on standard `macos-15` for pushes to `main`, pull requests, and manual dispatch. Standard hosted-runner minutes are free for this public repo; runner queue time is separate from job runtime.

## Traps

- The helper scripts run as `/usr/bin/python3 -I`: their own folder isn't on `sys.path`, so importing a sibling script needs `sys.path.insert(0, <its folder>)` (see `presets.py`).
- Wine is x86_64 (Rosetta). An arm64 library in `DYLD_INSERT_LIBRARIES` (e.g. from `~/.zshenv`) kills it at launch: `run.sh` and `tools.py` unset it.
- Wine reads `SDL_*` controller variables only when its device process starts: a Wine process started earlier without them (e.g. by `tools.py`) keeps the old setting until Wine restarts.
