# Changelog

Changes since the port moved from Project Reclaimer (Halo 3) to Project Gravemind (Halo 2).

## 0.8.3
- Problems joining or playing? now has "Play with debug logging": one launch with detailed Wine, DXVK and file-trace logging. When the game closes, the logs and Gravemind's own logs are zipped to the Desktop as `Gravemind-Debug-Logs-<date and time>.zip`. Later launches are normal.
- The installer replaces a Wine stub `d3d11.dll` in the prefix with DXVK, which fixes a crash at startup ("Unimplemented function d3d11.dll.D3D11CreateDeviceAndSwapChain").
- Release notes now come from this file, and releases wait for the checks to pass.

## 0.8.2
- First release. A `v*` tag runs the release workflow: it runs the checks, builds the DMG and publishes a GitHub release.
- Ported the Mac launcher, installer, updater and tools to Project Gravemind (Halo 2).
  - Gravemind comes from `BriRoz1/h2gravemind-releases`; the updater checks its releases and verifies each ZIP's SHA-256.
  - Mac-port updates come from this repo's `VERSION` on `main`.
  - Halo 2 files come from MCC depots 976731 (shared), 976735 (campaign), 976736 and 976737 (multiplayer), checked at `halo2/h2_maps_win64_dx11/ascension.map`.
  - Steam QR sign-in and downloads use DepotDownloader.
  - New Gravemind app icon, branding, README and install guide.
- Launcher rebuilt from the Gravemind source, so the app shows "Project Gravemind" and "Halo 2 on your Mac".
- Removed the Reclaimer loopback LaunchDaemon, which Gravemind doesn't need.
- Fixed Steam sign-in issues in the launcher window.
- A game process counts as this install's only if its working directory is inside the install. Force Quit kills only those processes, and `launch.sh` starts the helper and game from the game folder.
- Stopping a stuck update stops the installer and its downloads. The update watchdog counts from the update's start, and the window blocks App Nap while an update runs.
- The test suite no longer depends on free disk space.
- Added ADR 0001 (Forge builds on 8 GB Macs) and the update-stall spec.
- Installed copies of the old Reclaimer port keep updating from the upstream repo until the installer is re-run once.

## Known issues
- Workshop downloads reach `ready`, but Gravemind logs `MCC's steam_api64.dll not found` and loads 0 Halo 2 mods.
- Main and pause menus run below 10 FPS while gameplay runs at 60 FPS. This is likely a Gravemind/Wine problem, not Mac-only.
