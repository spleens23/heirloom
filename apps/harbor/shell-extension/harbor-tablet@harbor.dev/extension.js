// Heirloom Tablet Mode — a GNOME Shell extension.
//
// Tablet mode (screen folded back, or forced from Quick Settings) is a locked-down,
// iPad-like interface:
//   * an app is always in front, full screen (Screenroom after starting up, or
//     when the last app closes)
//   * a slim status bar across the top: the time on the left, Wi-Fi and battery on
//     the right; pull down on the right for the controls, on the left for
//     notifications and the calendar
//   * a quick swipe up from the bottom edge opens the app drawer (search,
//     favorites, every app and folder); the Super key does too
//   * swipe up and pause for your open apps: tap one to switch, flick it up to close
//   * no overview, desktops or window controls
//
// Laptop mode is plain GNOME.
//
// The hinge is read through GNOME's "touch mode", the same signal GNOME uses to
// turn on the on-screen keyboard and screen rotation.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Gio from 'gi://Gio';
import Meta from 'gi://Meta';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {QuickMenuToggle, SystemIndicator} from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {Drawer} from './drawer.js';
import {Switcher} from './switcher.js';
import {DEFAULT_FAVORITES, loadConfig, lookupApp} from './util.js';

const MODES = ['auto', 'tablet', 'laptop'];
const FRONT_APP = 'dev.screenroom.Screenroom.desktop';  // the app in front after starting up
const EDGE_HEIGHT = 14;      // the touch strip along the bottom
const PAUSE_MS = 280;        // holding still this long mid-swipe opens the open-apps view
const PAUSE_MIN_PX = 110;    // ...once the finger is at least this far up
const PULL_PX = 24;          // a pull down on the status bar this far opens its menu

// The mode you pick is remembered in ~/.config/harbor/tablet-mode
function modeFile() {
    return Gio.File.new_for_path(GLib.build_filenamev([GLib.get_user_config_dir(), 'harbor', 'tablet-mode']));
}

function readMode() {
    try {
        const [, bytes] = modeFile().load_contents(null);
        const text = new TextDecoder().decode(bytes).trim();
        return MODES.includes(text) ? text : 'auto';
    } catch (_e) {
        return 'auto';
    }
}

function writeMode(mode) {
    const file = modeFile();
    try {
        file.get_parent().make_directory_with_parents(null);
    } catch (_e) { /* already exists */ }
    file.replace_contents(new TextEncoder().encode(`${mode}\n`), null, false,
        Gio.FileCreateFlags.REPLACE_DESTINATION, null);
}

// Maximize across GNOME versions (the call changed shape in GNOME 49).
function maximize(win) {
    try {
        if (Meta.MaximizeFlags)
            win.maximize(Meta.MaximizeFlags.BOTH);
        else
            win.maximize();
    } catch (_e) {
        try {
            win.maximize();
        } catch (_e2) { /* leave it as it is */ }
    }
}


// ---- the bottom edge: swipe up for the drawer, swipe up and pause for open apps --

const HomeEdge = GObject.registerClass(
class HomeEdge extends St.Widget {
    _init(ext) {
        super._init({name: 'harborHomeEdge', reactive: true, layout_manager: new Clutter.BinLayout()});
        this._ext = ext;
        this._bar = new St.Widget({style_class: 'harbor-home-bar', x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER});
        this.add_child(this._bar);
        this._start = null;
        this.connect('event', (_a, ev) => this._event(ev));
        this._relayout();
        this._monitorsId = Main.layoutManager.connect('monitors-changed', () => this._relayout());
    }

    _relayout() {
        const m = Main.layoutManager.primaryMonitor;
        if (!m)
            return;
        this.set_position(m.x, m.y + m.height - EDGE_HEIGHT);
        this.set_size(m.width, EDGE_HEIGHT);
    }

    _clearPause() {
        if (this._pause) {
            GLib.source_remove(this._pause);
            this._pause = 0;
        }
    }

    _armPause() {
        this._clearPause();
        this._pause = GLib.timeout_add(GLib.PRIORITY_DEFAULT, PAUSE_MS, () => {
            this._pause = 0;
            if (this._start !== null && this._mode === 'drawer' && this._dy > PAUSE_MIN_PX) {
                this._mode = 'switcher';
                this._ext.drawer.hideNow();
                this._ext.switcher.open();
            }
            return GLib.SOURCE_REMOVE;
        });
    }

    _event(ev) {
        const t = ev.type();
        const E = Clutter.EventType;
        const [, y] = ev.get_coords();
        const now = GLib.get_monotonic_time() / 1000;

        // Mouse: click the home bar for the drawer, hold it for open apps.
        if (t === E.BUTTON_PRESS && ev.get_button() === 1) {
            this._clearPause();
            this._mouseHeld = false;
            this._pause = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
                this._pause = 0;
                this._mouseHeld = true;
                this._ext.switcher.open();
                return GLib.SOURCE_REMOVE;
            });
            return Clutter.EVENT_STOP;
        }
        if (t === E.BUTTON_RELEASE && ev.get_button() === 1) {
            this._clearPause();
            if (!this._mouseHeld)
                this._ext.drawer.toggle();
            return Clutter.EVENT_STOP;
        }

        if (t === E.TOUCH_BEGIN) {
            if (this._ext.switcher.isOpen || this._ext.drawer.isOpen)
                return Clutter.EVENT_STOP;
            this._start = y;
            this._dy = 0;
            this._lastY = y;
            this._lastT = now;
            this._v = 0;
            this._mode = 'drawer';
            this._bar.add_style_pseudo_class('active');
            this._ext.drawer.beginDrag();
            this._armPause();
            return Clutter.EVENT_STOP;
        }
        if (this._start === null)
            return Clutter.EVENT_PROPAGATE;
        if (t === E.TOUCH_UPDATE) {
            this._dy = this._start - y;
            const dt = Math.max(1, now - this._lastT);
            this._v = 0.7 * this._v + 0.3 * ((this._lastY - y) / dt);
            if (Math.abs(this._lastY - y) > 4)
                this._armPause();  // still moving: wait for a pause again
            this._lastY = y;
            this._lastT = now;
            if (this._mode === 'drawer')
                this._ext.drawer.dragTo(this._dy);
            return Clutter.EVENT_STOP;
        }
        if (t === E.TOUCH_END || t === E.TOUCH_CANCEL) {
            this._clearPause();
            this._bar.remove_style_pseudo_class('active');
            if (this._mode === 'drawer') {
                if (t === E.TOUCH_CANCEL)
                    this._ext.drawer.close();
                else
                    this._ext.drawer.endDrag(this._v);
            }
            this._start = null;
            return Clutter.EVENT_STOP;
        }
        return Clutter.EVENT_STOP;
    }

    destroy() {
        this._clearPause();
        if (this._monitorsId) {
            Main.layoutManager.disconnect(this._monitorsId);
            this._monitorsId = 0;
        }
        super.destroy();
    }
});


// ---- Quick Settings toggle --------------------------------------------------

const TabletToggle = GObject.registerClass(
class TabletToggle extends QuickMenuToggle {
    _init(ext) {
        super._init({title: 'Tablet Mode', iconName: 'input-tablet-symbolic', toggleMode: false});
        this._ext = ext;
        this.menu.setHeader('input-tablet-symbolic', 'Tablet Mode', 'Heirloom');

        this._items = {};
        for (const [mode, text] of [
            ['auto', 'Automatic (follow the hinge)'],
            ['tablet', 'Always Tablet'],
            ['laptop', 'Always Laptop'],
        ]) {
            const item = new PopupMenu.PopupMenuItem(text);
            item.connect('activate', () => ext.setMode(mode));
            this.menu.addMenuItem(item);
            this._items[mode] = item;
        }
        // Tapping the toggle itself flips to the other mode.
        this.connect('clicked', () => ext.setMode(ext.isTablet() ? 'laptop' : 'tablet'));
        this.sync();
    }

    sync() {
        const ext = this._ext;
        this.checked = ext.isTablet();
        this.subtitle = ext.mode === 'auto'
            ? (ext.isTablet() ? 'Automatic · Tablet' : 'Automatic · Laptop')
            : (ext.mode === 'tablet' ? 'Always Tablet' : 'Always Laptop');
        for (const [mode, item] of Object.entries(this._items)) {
            item.setOrnament(mode === ext.mode
                ? PopupMenu.Ornament.CHECK : PopupMenu.Ornament.NONE);
        }
    }
});

const TabletIndicator = GObject.registerClass(
class TabletIndicator extends SystemIndicator {
    _init(ext) {
        super._init();
        this.toggle = new TabletToggle(ext);
        this.quickSettingsItems.push(this.toggle);
    }
});


// ---- the extension ---------------------------------------------------------

export default class HarborTabletExtension extends Extension {
    enable() {
        this.mode = readMode();
        this._tablet = null;
        this._launchedAt = 0;
        this._seat = Clutter.get_default_backend().get_default_seat();
        this._touchId = this._seat.connect('notify::touch-mode', () => this._update());

        // The passcode keypad for the lock screen lives in its own extension; make
        // sure it's on (it's off if extensions were ever switched by hand).
        const KEYPAD = 'heirloom-keypad@heirloom.dev';
        this._keypadId = GLib.idle_add(GLib.PRIORITY_LOW, () => {
            this._keypadId = 0;
            const list = global.settings.get_strv('enabled-extensions');
            if (Main.extensionManager.lookup(KEYPAD) && !list.includes(KEYPAD))
                global.settings.set_strv('enabled-extensions', [...new Set([...list, this.uuid, KEYPAD])]);
            return GLib.SOURCE_REMOVE;
        });

        this._indicator = new TabletIndicator(this);
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);

        this._update();
    }

    disable() {
        if (this._keypadId) {
            GLib.source_remove(this._keypadId);
            this._keypadId = 0;
        }
        // Always hand GNOME back exactly as we found it.
        if (this._tablet)
            this._leaveTablet();
        if (this._touchId) {
            this._seat.disconnect(this._touchId);
            this._touchId = 0;
        }
        this._indicator?.quickSettingsItems.forEach(i => i.destroy());
        this._indicator?.destroy();
        this._indicator = null;
        this._seat = null;
        this._tablet = null;
    }

    // ---- state ------------------------------------------------------------
    isTablet() {
        if (this.mode === 'tablet')
            return true;
        if (this.mode === 'laptop')
            return false;
        return Boolean(this._seat?.touch_mode);
    }

    setMode(mode) {
        this.mode = mode;
        try {
            writeMode(mode);
        } catch (e) {
            console.warn(`Heirloom: couldn't save mode: ${e}`);
        }
        this._update();
    }

    _update() {
        const tablet = this.isTablet();
        if (tablet !== this._tablet) {
            const was = this._tablet;
            this._tablet = tablet;
            if (tablet)
                this._enterTablet();
            else if (was)
                this._leaveTablet();
            else
                this._oneDesktop(false);  // starting in laptop mode: undo anything left over
        }
        this._indicator?.toggle.sync();
    }

    // ---- tablet mode ------------------------------------------------------
    _enterTablet() {
        Main.layoutManager.uiGroup.add_style_class_name('heirloom-tablet');

        this.drawer = new Drawer();
        this.switcher = new Switcher(w => this._isAppWindow(w));
        this._edge = new HomeEdge(this);
        Main.layoutManager.addTopChrome(this._edge, {affectsInputRegion: true, trackFullscreen: false});

        // The Super key, the hot corner and "show apps" open the drawer; the
        // overview, desktops and their gestures are off.
        this._origToggle = Main.overview.toggle;
        Main.overview.toggle = () => this.drawer.toggle();
        this._origShowApps = Main.overview.showApps;
        Main.overview.showApps = () => this.drawer.open();
        if (Main.overview._swipeTracker) {
            this._overviewSwipe = Main.overview._swipeTracker.enabled;
            Main.overview._swipeTracker.enabled = false;
        }
        this._oneDesktop(true);
        this._statusBar(true);

        this._windowId = global.display.connect('window-created', (_d, win) => this._placeNewWindow(win));
        for (const actor of global.get_window_actors()) {
            if (actor.meta_window) {
                this._watchWindow(actor.meta_window);
                this._fill(actor.meta_window);
            }
        }

        if (Main.layoutManager._startingUp) {
            this._startupId = Main.layoutManager.connect('startup-complete', () => {
                Main.layoutManager.disconnect(this._startupId);
                this._startupId = 0;
                if (Main.overview.visible)
                    Main.overview.hide();
                this._ensureAnApp();
            });
        } else {
            if (Main.overview.visible)
                Main.overview.hide();
            this._ensureAnApp();
        }
    }

    _leaveTablet() {
        Main.layoutManager.uiGroup.remove_style_class_name('heirloom-tablet');
        if (this._startupId) {
            Main.layoutManager.disconnect(this._startupId);
            this._startupId = 0;
        }
        if (this._origToggle) {
            Main.overview.toggle = this._origToggle;
            this._origToggle = null;
        }
        if (this._origShowApps) {
            Main.overview.showApps = this._origShowApps;
            this._origShowApps = null;
        }
        if (this._overviewSwipe !== undefined && Main.overview._swipeTracker) {
            Main.overview._swipeTracker.enabled = this._overviewSwipe;
            this._overviewSwipe = undefined;
        }
        this._oneDesktop(false);
        this._statusBar(false);
        if (this._edge) {
            Main.layoutManager.removeChrome(this._edge);
            this._edge.destroy();
            this._edge = null;
        }
        this.drawer?.destroy();
        this.drawer = null;
        this.switcher?.destroy();
        this.switcher = null;
        if (this._windowId) {
            global.display.disconnect(this._windowId);
            this._windowId = 0;
        }
        if (this._ensureId) {
            GLib.source_remove(this._ensureId);
            this._ensureId = 0;
        }
    }

    // ---- one desktop while in tablet mode ------------------------------------------
    // (Your desktop settings are put back when you leave tablet mode, even after a
    //  restart in between: what they were is kept in ~/.config/harbor/desktops.json.)
    _desktopsFile() {
        return Gio.File.new_for_path(GLib.build_filenamev([GLib.get_user_config_dir(), 'harbor', 'desktops.json']));
    }

    _oneDesktop(on) {
        let mutter, wm;
        try {
            mutter = new Gio.Settings({schema_id: 'org.gnome.mutter'});
            wm = new Gio.Settings({schema_id: 'org.gnome.desktop.wm.preferences'});
        } catch (_e) {
            return;
        }
        const file = this._desktopsFile();
        let saved = null;
        try {
            saved = JSON.parse(new TextDecoder().decode(file.load_contents(null)[1]));
        } catch (_e) { /* none */ }
        if (on) {
            if (!saved) {
                saved = {dynamic: mutter.get_boolean('dynamic-workspaces'), num: wm.get_int('num-workspaces')};
                try {
                    file.get_parent().make_directory_with_parents(null);
                } catch (_e) { /* there */ }
                try {
                    file.replace_contents(new TextEncoder().encode(JSON.stringify(saved)), null, false,
                        Gio.FileCreateFlags.REPLACE_DESTINATION, null);
                } catch (_e) { /* fine */ }
            }
            mutter.set_boolean('dynamic-workspaces', false);
            wm.set_int('num-workspaces', 1);
            // Bring every window onto the one desktop.
            const ws = global.workspace_manager.get_workspace_by_index(0);
            for (const a of global.get_window_actors()) {
                const w = a.meta_window;
                if (w && !w.is_on_all_workspaces() && w.get_workspace() !== ws)
                    w.change_workspace(ws);
            }
        } else if (saved) {
            mutter.set_boolean('dynamic-workspaces', saved.dynamic ?? true);
            wm.set_int('num-workspaces', saved.num || 4);
            try {
                file.delete(null);
            } catch (_e) { /* fine */ }
        }
    }

    // ---- the status bar ---------------------------------------------------------------
    _statusBar(on) {
        const panel = Main.panel;
        const date = panel.statusArea.dateMenu;
        const activities = panel.statusArea.activities;
        if (on) {
            activities?.container.hide();
            if (date && !this._dateParent) {
                this._dateParent = date.container.get_parent();
                this._dateIndex = this._dateParent.get_children().indexOf(date.container);
                this._dateParent.remove_child(date.container);
                panel._leftBox.insert_child_at_index(date.container, 0);
            }
            if (!this._pullId)
                this._pullId = panel.connect('captured-event', (_a, ev) => this._pullDown(ev));
        } else {
            activities?.container.show();
            if (date && this._dateParent) {
                date.container.get_parent()?.remove_child(date.container);
                this._dateParent.insert_child_at_index(date.container, Math.max(0, this._dateIndex));
                this._dateParent = null;
            }
            if (this._pullId) {
                panel.disconnect(this._pullId);
                this._pullId = 0;
            }
        }
    }

    _pullDown(ev) {
        const t = ev.type();
        const E = Clutter.EventType;
        if (t === E.TOUCH_BEGIN) {
            this._pull = ev.get_coords();
            this._pulled = false;
        } else if (t === E.TOUCH_UPDATE && this._pull && !this._pulled) {
            const [, y] = ev.get_coords();
            if (y - this._pull[1] > PULL_PX) {
                this._pulled = true;
                const right = this._pull[0] > Main.panel.get_transformed_position()[0] + Main.panel.width / 2;
                const menu = right ? Main.panel.statusArea.quickSettings.menu : Main.panel.statusArea.dateMenu.menu;
                if (!menu.isOpen)
                    menu.open();
            }
        } else if (t === E.TOUCH_END || t === E.TOUCH_CANCEL) {
            this._pull = null;
        }
        return Clutter.EVENT_PROPAGATE;
    }

    // ---- windows: full screen, and always one in front ------------------------------
    _isAppWindow(win) {
        return Boolean(win) && win.get_window_type() === Meta.WindowType.NORMAL &&
            !win.get_transient_for() && !win.is_skip_taskbar();
    }

    _fill(win) {
        if (!this._tablet || !this._isAppWindow(win) || !win.can_maximize())
            return;
        maximize(win);
    }

    _watchWindow(win) {
        if (win._heirloomWatched)
            return;
        win._heirloomWatched = true;
        win.connect('unmanaged', () => {
            if (this._tablet)
                this._queueEnsure();
        });
    }

    _placeNewWindow(win) {
        this._watchWindow(win);
        if (this.drawer?.isOpen)
            this.drawer.hideNow();
        // Apps often set their own size as they appear, so fill the screen at a
        // few moments: once GNOME is idle, at the first frame, and a bit later.
        GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._fill(win);
            return GLib.SOURCE_REMOVE;
        });
        const actor = win.get_compositor_private();
        if (actor) {
            const id = actor.connect('first-frame', () => {
                actor.disconnect(id);
                this._fill(win);
            });
        }
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 600, () => {
            this._fill(win);
            return GLib.SOURCE_REMOVE;
        });
    }

    _appWindows() {
        return global.get_window_actors().map(a => a.meta_window).filter(w => this._isAppWindow(w));
    }

    _queueEnsure() {
        if (this._ensureId)
            GLib.source_remove(this._ensureId);
        this._ensureId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 700, () => {
            this._ensureId = 0;
            this._ensureAnApp();
            return GLib.SOURCE_REMOVE;
        });
    }

    // There's always an app in front: after starting up, and when the last one closes.
    _ensureAnApp() {
        if (!this._tablet || this._appWindows().length)
            return;
        const now = GLib.get_monotonic_time() / 1e6;
        if (now - this._launchedAt < 15)
            return;  // one is on its way
        const favorites = loadConfig().dock ?? DEFAULT_FAVORITES;
        const app = [FRONT_APP, ...favorites].map(id => lookupApp(id)).find(Boolean);
        if (!app)
            return;
        this._launchedAt = now;
        app.activate();
    }
}
