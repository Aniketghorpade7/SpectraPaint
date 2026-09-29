# Bug 6: the Edit menu (Undo, Redo, Cut, Copy, Paste, Delete, Select All) does nothing

| | |
|---|---|
| **Area** | Desktop shell (`apps/desktop`) + Consultation state (`apps/ui`) |
| **Severity** | Medium: dead controls, and the same default menu ships Reload, which wipes the live Consultation |
| **Confidence** | Confirmed |
| **Source** | [SpectrapaintBugs.pdf](./SpectrapaintBugs.pdf), page 3, item 6 |
| **Proposed issue** | Issue 3, "App menu and Shade undo" ([README](./README.md#proposed-issues)) |

## What it is

The menu bar shows File / Edit / View / Window. Under Edit, Undo (Ctrl+Z), Redo (Ctrl+Shift+Z), Cut,
Copy, Paste, Delete and Select All do nothing on the Consultation surface.

## Root cause

1. **It is Electron's default menu.** `apps/desktop/src/main.ts:1` imports only
   `app, BrowserWindow, WebContents, ipcMain`. `Menu` is never imported, and there's no
   `Menu.setApplicationMenu` anywhere in `apps/desktop/src`, so Electron installs its built-in menu.
2. **The default Edit items are text-editing roles.** `role: 'undo'`, `'cut'` and the rest act on the
   focused text field. The only text field in the app is the Catalogue search box. On the photo and
   render they do nothing, because nothing there is text.
3. **The app has no undo history to call anyway.** `useConsultation.ts` holds `target` and
   `assignments` as plain state (`:161-162`), with no history. The only undo in the app is the
   Bundle-delete Toast (`apps/ui/src/library/useLibrary.ts:232`). Wall corrections overwrite the planes
   on the service and keep no history (`services/inference/spectrapaint/api/preparation.py`,
   `replace_planes`).
4. **The default View menu is a hazard.** It includes **Reload / Force Reload** (which throws away the
   live Consultation's renderer state mid-counter-session) and **Toggle Developer Tools**, in
   packaged builds too.

## Decision (grilling decision 6)

**A custom app menu with real Undo/Redo for Shade and wall-choice changes** within the open
Consultation. Cut/Copy/Paste/Select All stay, for the search box. Reload and DevTools are removed from
packaged builds. **Wall corrections (Add/Split/Merge) aren't undoable in V1.** That would need a
plane-history stack on the service and a REST contract change. The Dealer can re-run a correction.
This matches ui-guidelines' "act, and let it be undone".

## Method of fixing

### Step 1: an app-menu module (desktop)

New file `apps/desktop/src/app-menu.ts`, exporting a **pure** template builder so it can be tested
without Electron (the pattern `boot-messages.ts` / `boot-messages.test.ts` already uses):

```ts
export type MenuCommand = 'undo' | 'redo';

export function appMenuTemplate(opts: {
  isPackaged: boolean;
  platform: NodeJS.Platform;
  send: (command: MenuCommand) => void;
}): MenuItemConstructorOptions[] {
  const edit: MenuItemConstructorOptions = {
    label: 'Edit',
    submenu: [
      { id: 'undo', label: 'Undo', accelerator: 'CmdOrCtrl+Z', enabled: false, click: () => opts.send('undo') },
      { id: 'redo', label: 'Redo',
        accelerator: opts.platform === 'win32' ? 'Ctrl+Y' : 'CmdOrCtrl+Shift+Z',
        enabled: false, click: () => opts.send('redo') },
      { type: 'separator' },
      { role: 'cut' }, { role: 'copy' }, { role: 'paste' },
      { type: 'separator' },
      { role: 'selectAll' },
    ],
  };
  const view: MenuItemConstructorOptions = {
    label: 'View',
    submenu: opts.isPackaged
      ? [{ role: 'togglefullscreen' }]
      : [{ role: 'reload' }, { role: 'toggleDevTools' }, { type: 'separator' }, { role: 'togglefullscreen' }],
  };
  return [{ label: 'File', submenu: [{ role: 'quit' }] }, edit, view, { role: 'windowMenu' }];
}
```

- "Delete" is dropped. There's nothing selectable to delete.
- On Windows (the target, design-decisions §9c), also register `Ctrl+Shift+Z` for Redo, via a second
  hidden item (`visible: false`) with the same click, so both habits work.

In `main.ts`, after `app.whenReady()` (`:122`):

```ts
Menu.setApplicationMenu(Menu.buildFromTemplate(appMenuTemplate({
  isPackaged: app.isPackaged,
  platform: process.platform,
  send: (command) => mainWindow?.webContents.send(MENU_COMMAND_CHANNEL, command),
})));
ipcMain.on(MENU_STATE_CHANNEL, (_e, state: { canUndo: boolean; canRedo: boolean }) => {
  const menu = Menu.getApplicationMenu();
  if (menu?.getMenuItemById('undo')) menu.getMenuItemById('undo')!.enabled = state.canUndo;
  if (menu?.getMenuItemById('redo')) menu.getMenuItemById('redo')!.enabled = state.canRedo;
});
```

### Step 2: the bridge

- `apps/desktop/src/channels.ts`: `MENU_COMMAND_CHANNEL = 'spectrapaint:menu:command'` and
  `MENU_STATE_CHANNEL = 'spectrapaint:menu:state'`.
- `apps/desktop/src/preload.ts`: `onMenuCommand(listener)` (the same subscribe/unsubscribe shape as
  `onBootStatus`, `preload.ts:77-83`) and `setMenuState(state)` (`ipcRenderer.send`).
- `apps/desktop/src/bridge-types.ts`: add both to `SpectraPaintBridge`. The sandbox and
  contextIsolation posture (`main.ts:69-74`) is unchanged.

### Step 3: Shade history (UI)

New pure module `apps/ui/src/consultation/history.ts`:

```ts
export type PaintSnapshot = { target: PaintTarget; assignments: Assignments };
export type History = { past: PaintSnapshot[]; future: PaintSnapshot[] };
export const HISTORY_LIMIT = 50;
export function record(h: History, before: PaintSnapshot): History;       // push, cap, clear future
export function undo(h: History, now: PaintSnapshot): [History, PaintSnapshot] | null;
export function redo(h: History, now: PaintSnapshot): [History, PaintSnapshot] | null;
```

In `useConsultation.ts`:

1. `applyShade` (`:318`) and the wall-choice setter call `record(history, { target, assignments })`
   before changing state.
2. `undoPaint()` / `redoPaint()` restore a snapshot, then re-render with the existing path: the same
   `renderPayload(assignments, walls.planes)` → `window.spectrapaint.render(...)` sequence as the
   render-mode effect (`:394-435`). A snapshot with empty `assignments` returns to the original photo
   (`showingRender = false`). Factor that sequence out of `applyShade` into one `repaint(assignments)`
   helper so three callers share it.
3. **Corrections clear the history.** A split or merge can retire plane ids (`useConsultation.ts:477`),
   and a snapshot pointing at a retired plane can't be replayed honestly. Discarding the photo clears it too.
4. Publish `canUndo`/`canRedo` with `window.spectrapaint.setMenuState` from an effect whenever they change.

### Step 4: route the command in the renderer

```ts
useEffect(() => window.spectrapaint.onMenuCommand((command) => {
  const el = document.activeElement;
  const editing = el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement;
  if (editing) { document.execCommand(command); return; }   // text undo in the search box
  if (command === 'undo') undoPaint(); else redoPaint();
}), [undoPaint, redoPaint]);
```

A menu accelerator fires before the page sees the key, so without this branch Ctrl+Z in the search box
would undo a Shade instead of the typing.

## Docs to amend

- `docs/ui-guidelines.md`: what Undo covers (Shades and wall choice, within one open Consultation) and
  what it doesn't (corrections, across saves).
- `docs/implementation-decisions.md`: the menu contents, and why Reload/DevTools are dev-only.
- `docs/specs/v1-spectrapaint.md:270` ("whether the shop PC is touchscreen") is still open. Note that
  Undo also needs an on-screen affordance if the answer is touchscreen. The Toast pattern from
  `useLibrary.ts` is the candidate.

## Tests

- `apps/desktop/src/app-menu.test.ts`: the packaged template has no `reload`/`forceReload`/`toggleDevTools`
  roles; the dev template has them; Undo/Redo items exist with ids and start disabled; the Windows Redo
  accelerator is `Ctrl+Y`, plus the hidden `Ctrl+Shift+Z`.
- `apps/ui/src/consultation/history.test.ts`: record/undo/redo round-trip; `HISTORY_LIMIT` cap; a new
  record clears `future`; undo on empty history returns `null`.
- Hook-level: two Shades applied, then undo → assignments equal the first snapshot and one render is
  requested; a correction clears history.

## Acceptance criteria

- [ ] Ctrl+Z after applying a Shade restores the previous Shade(s) and re-renders; Ctrl+Y /
      Ctrl+Shift+Z redoes.
- [ ] Undo/Redo menu items are disabled when there's nothing to undo or redo.
- [ ] In the Catalogue search box, Ctrl+Z/Ctrl+C/Ctrl+V act on the text, not on the Shades.
- [ ] A packaged build has no Reload, Force Reload or Developer Tools in any menu or shortcut.
- [ ] After Split/Merge/Add, Undo is disabled (history cleared), with no crash and no wrong-plane replay.
