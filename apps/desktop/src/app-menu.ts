/**
 * The application menu, as a pure template (issue #50).
 *
 * Electron ships a default menu whose Edit items are text-editing *roles* — they act on the
 * focused text field and do nothing to the Consultation — and whose View menu carries Reload and
 * Toggle Developer Tools even in a packaged build, where a Reload throws away the live
 * Consultation's renderer state mid-counter-session. Building the template here, without Electron,
 * is the pattern boot-messages.ts uses so the shell's decisions stay testable without launching
 * the app (docs/conventions.md §6).
 *
 * What the menu means, per grilling decision 6 (docs/bugs/06-edit-menu-does-nothing.md):
 *
 * - **Undo/Redo are SpectraPaint commands, not roles.** They cover Shade and wall-choice changes
 *   within the open Consultation. The click sends the command to the renderer on
 *   `MENU_COMMAND_CHANNEL`; the renderer decides whether it is paint (undo/redo a snapshot in
 *   `useConsultation`) or text (the Catalogue search box, whose editing stays browser-native).
 * - **Cut/Copy/Paste/Select All stay roles** — the search box is the one real text field, and the
 *   browser already implements them correctly there.
 * - **No Delete.** There is nothing selectable on the photo or the render to delete, and a menu
 *   item that never does anything is the dead control this ticket exists to remove.
 *
 * The menu is *set* with enabled flags for the state the Consultation reports; main flips
 * `undo`/`redo` live via `MENU_STATE_CHANNEL`. They start disabled because at launch there is
 * nothing to undo.
 */

import type { MenuItemConstructorOptions } from 'electron';

import type { MenuCommand } from './bridge-types';

/** The ids of the two items whose enabled state the renderer may drive (issue #50). */
export const MENU_UNDO_ITEM_ID = 'undo';
export const MENU_REDO_ITEM_ID = 'redo';
/** Hidden Windows-only sibling carrying Ctrl+Shift+Z so both Redo habits work (issue #50). */
export const MENU_REDO_SHIFT_ITEM_ID = `${MENU_REDO_ITEM_ID}-shift`;

/**
 * On Windows (the target — design-decisions.md §9c) Redo is `Ctrl+Y` on the item itself, and a
 * second *hidden* item carries `Ctrl+Shift+Z` so both habits work without a duplicated menu row.
 * Everywhere else one `CmdOrCtrl+Shift+Z` item does the job.
 */
export function redoAcceleratorFor(platform: NodeJS.Platform): string {
  return platform === 'win32' ? 'Ctrl+Y' : 'CmdOrCtrl+Shift+Z';
}

export function appMenuTemplate(opts: {
  isPackaged: boolean;
  platform: NodeJS.Platform;
  send: (command: MenuCommand) => void;
}): MenuItemConstructorOptions[] {
  const edit: MenuItemConstructorOptions = {
    label: 'Edit',
    submenu: [
      {
        id: MENU_UNDO_ITEM_ID,
        label: 'Undo',
        accelerator: 'CmdOrCtrl+Z',
        enabled: false,
        click: () => opts.send('undo'),
      },
      {
        id: MENU_REDO_ITEM_ID,
        label: 'Redo',
        accelerator: redoAcceleratorFor(opts.platform),
        enabled: false,
        click: () => opts.send('redo'),
      },
      // Windows muscle memory for Redo is Ctrl+Shift+Z; a hidden item registers the accelerator
      // without showing a second Redo row.
      ...(opts.platform === 'win32'
        ? [
            {
              id: MENU_REDO_SHIFT_ITEM_ID,
              label: 'Redo (Shift)',
              accelerator: 'Ctrl+Shift+Z',
              visible: false,
              enabled: false,
              click: () => opts.send('redo'),
            },
          ]
        : []),
      { type: 'separator' },
      { role: 'cut' },
      { role: 'copy' },
      { role: 'paste' },
      { type: 'separator' },
      { role: 'selectAll' },
    ],
  };

  // Reload and DevTools are development conveniences that must never ship: Reload wipes the live
  // Consultation mid-session, and DevTools is not a Dealer feature. A packaged build gets
  // fullscreen only — no reload, no forceReload, no toggleDevTools, at any depth.
  const view: MenuItemConstructorOptions = {
    label: 'View',
    submenu: opts.isPackaged
      ? [{ role: 'togglefullscreen' }]
      : [
          { role: 'reload' },
          { role: 'forceReload' },
          { role: 'toggleDevTools' },
          { type: 'separator' },
          { role: 'togglefullscreen' },
        ],
  };

  return [{ label: 'File', submenu: [{ role: 'quit' }] }, edit, view, { role: 'windowMenu' }];
}
