import { describe, expect, it } from 'vitest';

import {
  MENU_REDO_ITEM_ID,
  MENU_REDO_SHIFT_ITEM_ID,
  MENU_UNDO_ITEM_ID,
  appMenuTemplate,
} from './app-menu';

/**
 * The menu's shape is a packaged-build guarantee, not a preference: the acceptance criterion is
 * that no Reload, Force Reload or Developer Tools reaches a Dealer's build, so the tests walk the
 * template at any depth rather than asserting on one named submenu.
 */

type Item = {
  id?: string;
  label?: string;
  role?: string;
  accelerator?: string;
  enabled?: boolean;
  visible?: boolean;
  submenu?: Item[];
};

const sendCalls: string[] = [];
const send = (command: string): void => {
  sendCalls.push(command);
};

function template(isPackaged: boolean, platform: NodeJS.Platform = 'win32'): Item[] {
  return appMenuTemplate({ isPackaged, platform, send }) as unknown as Item[];
}

function flatten(items: Item[]): Item[] {
  return items.flatMap((item) => [item, ...(item.submenu ? flatten(item.submenu) : [])]);
}

function findById(items: Item[], id: string): Item | undefined {
  return flatten(items).find((item) => item.id === id);
}

const DESTRUCTIVE_ROLES = ['reload', 'forceReload', 'toggleDevTools'] as const;

describe('the packaged application menu', () => {
  it('contains no reload, forceReload or toggleDevTools role at any depth', () => {
    for (const item of flatten(template(true))) {
      expect(DESTRUCTIVE_ROLES).not.toContain(item.role);
    }
  });

  it('still offers fullscreen, the one View behaviour a Dealer may want', () => {
    expect(flatten(template(true)).some((item) => item.role === 'togglefullscreen')).toBe(true);
  });
});

describe('the development application menu', () => {
  it('keeps reload and devtools for development, at no other depth', () => {
    const items = flatten(template(false));
    for (const role of DESTRUCTIVE_ROLES) {
      expect(items.filter((item) => item.role === role)).toHaveLength(1);
    }
  });
});

describe('the Edit menu', () => {
  it('has undo and redo items by id, starting disabled', () => {
    const menu = template(true);
    expect(findById(menu, MENU_UNDO_ITEM_ID)?.enabled).toBe(false);
    expect(findById(menu, MENU_REDO_ITEM_ID)?.enabled).toBe(false);
  });

  it('undoes with CmdOrCtrl+Z', () => {
    expect(findById(template(true), MENU_UNDO_ITEM_ID)?.accelerator).toBe('CmdOrCtrl+Z');
  });

  it('has no Delete item — there is nothing selectable to delete', () => {
    const labels = flatten(template(true))
      .map((item) => item.label)
      .filter((label): label is string => label !== undefined);
    expect(labels).not.toContain('Delete');
  });

  it('keeps the text-editing roles the Catalogue search box needs', () => {
    const roles = flatten(template(true)).map((item) => item.role);
    for (const role of ['cut', 'copy', 'paste', 'selectAll']) {
      expect(roles).toContain(role);
    }
  });

  it('sends undo to the renderer when the Undo item is clicked', () => {
    const menu = template(true);
    const undo = findById(menu, MENU_UNDO_ITEM_ID) as { click?: () => void };
    undo.click?.();
    expect(sendCalls).toContain('undo');
  });
});

describe('the Redo accelerator', () => {
  it('is Ctrl+Y on Windows, with a hidden Ctrl+Shift+Z sibling', () => {
    const menu = template(true, 'win32');
    expect(findById(menu, MENU_REDO_ITEM_ID)?.accelerator).toBe('Ctrl+Y');

    const hidden = findById(menu, MENU_REDO_SHIFT_ITEM_ID);
    expect(hidden?.accelerator).toBe('Ctrl+Shift+Z');
    expect(hidden?.visible).toBe(false);
    // Main enables it alongside Redo via MENU_STATE_CHANNEL; it must start disabled too.
    expect(hidden?.enabled).toBe(false);
  });

  it('is CmdOrCtrl+Shift+Z elsewhere, with no hidden sibling', () => {
    const menu = template(false, 'darwin');
    expect(findById(menu, MENU_REDO_ITEM_ID)?.accelerator).toBe('CmdOrCtrl+Shift+Z');
    expect(findById(menu, MENU_REDO_SHIFT_ITEM_ID)).toBeUndefined();
  });
});
