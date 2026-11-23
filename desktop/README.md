# Sartor desktop

A native Tauri v2 shell around the Python core and the existing
`sartor serve` web UI. It adds no second UI or document model.

## How it works

1. First launch finds `uv` (offering the standard one-time install if it
   is missing) and creates a private Python venv in the OS app-data
   directory.
2. It installs the pinned `sartor[all]==0.3.0` release from PyPI.
3. It uses `Documents/Sartor` by default, or the project folder chosen
   in **Project & Settings**, initializing that folder if needed.
4. It runs `sartor serve` on a free `127.0.0.1` port with a per-launch
   token, waits for `/api/health`, and shows the existing Sartor UI.
5. Quitting the app stops the sidecar. Its output is appended to
   `logs/sidecar.log` inside the app-data directory.

Provider settings write the selected project's `sartor.yaml`. An API
key entered in the desktop settings is stored in the OS keychain and
passed only to the sidecar as `SARTOR_API_KEY`; the project contains
`${SARTOR_API_KEY}`, never the key value.

## Develop

```bash
cd desktop
npm install
SARTOR_DEV_PATH="/Volumes/Crucial X9/Projects/sartor" npx tauri dev
```

`SARTOR_DEV_PATH` installs the editable local package with the `all`
extra instead of the pinned PyPI release. On this exFAT volume, keep
Cargo output on an internal disk, for example:

```bash
export CARGO_TARGET_DIR="$HOME/.cache/sartor-tauri-target"
```

## Self-test

The desktop binary has a headless self-test that exercises temporary
project/settings handling and, when `SARTOR_BIN` points at a Sartor
executable, starts the real sidecar and waits for its health endpoint:

```bash
SARTOR_BIN="$HOME/Library/Application Support/org.borck.sartor/runtime/bin/sartor" \
  ./src-tauri/target/release/sartor-desktop --selftest
```

It uses `/tmp/sartor-desktop-selftest` by default (or
`SARTOR_SELFTEST_DIR`) and removes that folder unless
`SARTOR_SELFTEST_KEEP=1` is set.

## Release

Releases use the shared app-hq Tauri workflow. Manual dispatch runs the
macOS `notarize-check` only. An annotated `v<version>` tag builds macOS
Apple Silicon and Intel, Windows, and Linux, then stable asset aliases
are attached for direct `releases/latest/download/<asset>` links.

Python, Cargo, npm, and Tauri config versions must match before tagging.
The Tauri updater public key is in `src-tauri/tauri.conf.json`; its
private key and password are per-app GitHub secrets and are never
committed.
