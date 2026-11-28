# Studio Connector 0.6.0 preview

Extract the entire preview kit into Downloads. In QGIS install the inner GroundSurf-Studio-Connector-0.6.0-dev.zip and enable the plugin. The separate browser application is in Downloads/GroundSurf-Connector-0.6. Open the Connector and select an area. Discover boreholes and choose Transfer to Studio, or request terrain and imagery with a Studio handoff. The browser opens a new evidence scene. Existing project files are preserved. No AI account is required.

Automatic mode prefers a compatible installed desktop. Under Advanced tools choose Automatic, Always use browser Studio, or Always use desktop Studio. Desktop-only mode offers the browser if a compatible installation cannot be found. Installers are matched to the OS and architecture from links on the official site. The current public trial has no installer links. The existing separate file import in compatible Studio remains available.

## Exchange and privacy

The plugin transmits no geological content over HTTP. It reads only the fixed terrain inventory or boreholes.geojson, refuses linked members and applies a 64 MiB total limit (8 MiB for borehole headers). For a browser handoff it creates a private local launch document from a SHA-256-pinned portable application and an inert JSON block of base64 file bytes. An opaque temporary directory contains the launch document; QGIS cleans its session directory on normal unload. Original evidence stays in Documents/GroundSurf Transfers. Studio validates evidence through the same scientific readers as the file picker. Terrain import verifies package hashes and spatial frame. Borehole headers and profile references retain their evidence status. Studio displays the accepted evidence or a validation error. A Connector launch message confirms only handoff.

The browser edition runs locally even with networking disabled. The app CSP forbids network connections. This design avoids a localhost listener, tokens and browser local-network permission prompts. If the verified receiver is absent, the plugin requests only the separately published application bytes from https://studio.groundsurf.net/connector/060/GroundSurf-Studio-Connector-Receiver.html. The digest check is mandatory. The private preview supplies that file in the kit. The public site currently advertises 0.10.1 and has no compatible receiver at this path. Publishing a reviewed receiver is a separate release decision.

Desktop Studio accepts --groundsurf-transfer followed by an absolute path to evidence.gstransfer. Only the packaged renderer can consume it, once, through its preload bridge. Each launch starts a separate scene; adding to an already open project is deferred. Detection checks the packaged renderer and launch interface at standard Linux, Windows and macOS installation locations. A recognised filename alone is insufficient.

## Verification

50 Connector tests passed on Ubuntu. The installable plugin passed the QGIS responsive-dock smoke test in an isolated profile. The Studio production build and TypeScript checks passed. Chromium and Firefox loaded the Neuschwanstein textured terrain offline and displayed a synthetic Berlin borehole record. Electron on Ubuntu imported both through the launch argument using the development Studio build. The installed older desktop application was preserved. Native Windows and macOS launches are unverified.

The GPL plugin archive excludes Studio code. The separate proprietary application, its notice and third-party notices are supplied alongside it in the private preview kit.
