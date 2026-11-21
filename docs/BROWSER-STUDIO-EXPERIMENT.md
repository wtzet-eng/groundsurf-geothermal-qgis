# Local-browser Studio, experimental QGIS integration (21 November 2026)

**Not an official QGIS plugin release.** Branch:
`feat/local-browser-studio-experiment`.

This is the first small step toward **3D GeoTherm — Studio by GroundSurf**
as a single QGIS plugin installation with a browser-based Three.js view.
The full independently installed **GroundSurf AI Studio** remains optional.

## What is implemented

- **More tools → Open Studio in browser (preview)** opens the existing
  GroundSurf Studio React/Three.js UI in the system browser via a small
  Python HTTP server bound exclusively to **127.0.0.1**.
- Assets are served from a locally bundled `web_studio/` directory,
  not from `groundsurf.net`, an external CDN or a running Electron app.
- Every browser session uses a random ephemeral URL token.
- HTTP requests with spoofed Host headers or unknown token paths are denied.
- Only static web assets may be served. No model JSON, GeoPackage, QGIS
  layer or source directory is exposed through this server.
- Any POST request is refused; there is no upload API.
- The server is started on demand and stopped when the QGIS plugin unloads.
- The browser file picker opens only **files explicitly selected by the user**,
  such as `model.json`, `surface-*.vtp`, `unit-*.vtu` and observation VTPs.

The existing QGIS modeller, installed GeoPackage schema, desktop Studio
launcher, independent Current View to ParaView and SGeMS Workbench plugins
are unchanged.

## Demonstrated

- Four Python tests: static file allow-list, token protection, Host
  restrictions / forbidden uploads, and server lifecycle **PASS**.
- Headless QGIS 3.34.4 test: **Open Studio in browser** button uses a
  local address; plugin unload closes the server **PASS**.
- Firefox test on the Ubuntu workstation: served Studio UI, explicitly
  imported a QGIS-exported synthetic 4-well model, and displayed all **7
  surfaces/volumes/borehole/contact layers** in an actual Three.js canvas
  **PASS**.
- Screenshot on Ubuntu:
  `/home/toma/surveyland-sandbox/studio-qgis-browser-preview-20261121.png`.

## Current limitation: manual project selection

The local browser interface currently needs the user to **select the
exported geometry files manually**. It does not automatically inspect the
active GeoPackage, read arbitrary directories or pass data from QGIS into
JavaScript. This is deliberate until a narrowly scoped read-only local
project bridge is designed, reviewed, and tested.

The bundled Studio build still contains some demonstration web-only
features; the official edition must hide or safely disable workflows that
cannot run offline.

## Building the local experimental ZIP

The Studio UI source currently comes from the private development checkout
`wtzet-eng/GroundSurf-Studio`. Build it locally first:

```bash
cd /home/toma/groundsurf-studio-pr3-20261121
npm run build
cd /home/toma/surveyland-sandbox/groundsurf-geothermal-qgis-public-20261119
python3 tools/build_browser_preview_zip.py \
  --studio-dist /home/toma/groundsurf-studio-pr3-20261121/dist
```

The preview ZIP includes static JS/CSS assets but **does not download or
execute any runtime installers**. The UI files are under 1 MB extracted;
the resulting ZIP remains far below the QGIS official 25 MB package cap.

**Do not submit this package to the official QGIS Plugin Repository yet.**
The private Studio source and third-party asset licences have not been
audited for a public distributable built into a GPL QGIS plugin. The
reproducible source-to-bundle build must be disclosed and retained for
review. Do not silently commit minified third-party bundles into the
public QGIS repository.

## Next

1. Make the shared Studio UI source/distribution auditable with licences.
2. Implement a session-bound, read-only API for the **active** QGIS project:
   project inventory, observations and only indexed exported model files.
   Deny arbitrary filesystem paths, require same-origin requests,
   enforce size limits and read-only SQLite.
3. Add a safe `Open in ParaView` handoff that uses original `model.vtm`
   geometry and never automatically executes untrusted scripts.
4. Match visual design/naming of the two Studio editions.
5. Re-test on Firefox and Chromium, Ubuntu first, then Windows/macOS.
6. Review and release a QGIS-catalogue-compatible version separately
   from the full desktop installation.
