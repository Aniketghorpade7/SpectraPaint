# desktop — Electron shell

The main process owns everything the renderer must not:

- Spawning and supervising the Python sidecar, restarting it quietly on death and logging each restart
- Holding the service port and the per-launch secret
- Native dialogs: opening a Room Photo, choosing an export destination, the system share sheet
- Reporting disk space for the low-disk warning

The preload script uses `contextBridge` to expose a narrow HTTP client that injects the secret.
`contextIsolation` stays on and `nodeIntegration` stays off, so the renderer never holds the raw secret.
