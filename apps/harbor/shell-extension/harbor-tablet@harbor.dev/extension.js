// Harbor Tablet Mode — a GNOME Shell extension.
//
// Tablet mode (screen folded back, or forced from Quick Settings):
//   * Harbor comes to the front as the home screen, and sits on every desktop
//     (so the first desktop is always Harbor, and any new one starts on it)
//   * apps open full screen: maximized, with GNOME's top bar tucked away
//     (swipe down from the top edge to bring the top bar back for a moment)
//   * a swipe up from the bottom edge closes the app you're in (home bar)
//   * the Super key goes Home instead of opening the Activities overview
//   * three fingers up shows your desktops; up again makes a new desktop
//
// Laptop mode: plain GNOME, and Harbor tucks itself away.
//
// The hinge is read through GNOME's "touch mode", the same signal GNOME uses
// to turn on the on-screen keyboard and screen rotation.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Gio from 'gi://Gio';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {QuickMenuToggle, SystemIndicator} from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const HARBOR_APP_ID = 'dev.harbor.Harbor.desktop';
const HARBOR_WM_CLASS = 'dev.harbor.Harbor';
const MODES = ['auto', 'tablet', 'laptop'];
const SWIPE_DISTANCE = 70; // pixels up from the edge that count as "close the app"
const EDGE_HEIGHT = 14;    // height of the touch strip along the bottom
const TOP_EDGE_HEIGHT = 6; // the strip along the top that pulls down the top bar
const PULL_DISTANCE = 40;
const PANEL_SHOW_SECONDS = 5;
const APP_GRID = 2;        // the overview's third stage (OverviewControls.ControlsState.APP_GRID)

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
        win.maximize(Meta.MaximizeFlags.BOTH);
    } catch (_e) {
        try {
            win.maximize();
        } catch (_e2) { /* leave it as it is */ }
    }
}


// ---- touch strips along the screen edges ---------------------------------
// The bottom one carries the little home bar; swiping up from it closes the app.
// The top one is invisible; pulling down from it shows GNOME's top bar.

const EdgeSwipe = GObject.registerClass(
class EdgeSwipe extends St.Widget {
    _init(where, onSwipe) {
        super._init({
            name: where === 'bottom' ? 'harborHomeEdge' : 'harborTopEdge',
            reactive: true,
            layout_manager: new Clutter.BinLayout(),
        });
        this._where = where;
        this._onSwipe = onSwipe;
        this._startY = null;

        if (where === 'bottom') {
            this._bar = new St.Widget({
                style_class: 'harbor-home-bar',
                x_align: Clutter.ActorAlign.CENTER,
                y_align: Clutter.ActorAlign.CENTER,
            });
            this.add_child(this._bar);
        }

        this.connect('touch-event', (_a, event) => this._touch(event));
        this._relayout();
        this._monitorsId = Main.layoutManager.connect('monitors-changed', () => this._relayout());
    }

    _relayout() {
        const m = Main.layoutManager.primaryMonitor;
        if (!m)
            return;
        const h = this._where === 'bottom' ? EDGE_HEIGHT : TOP_EDGE_HEIGHT;
        this.set_position(m.x, this._where === 'bottom' ? m.y + m.height - h : m.y);
        this.set_size(m.width, h);
    }

    _touch(event) {
        const type = event.type();
        const [, y] = event.get_coords();
        if (type === Clutter.EventType.TOUCH_BEGIN) {
            this._startY = y;
            this._bar?.add_style_pseudo_class('active');
            return Clutter.EVENT_STOP;
        }
        if (this._startY === null)
            return Clutter.EVENT_PROPAGATE;
        if (type === Clutter.EventType.TOUCH_UPDATE) {
            const moved = this._where === 'bottom' ? this._startY - y : y - this._startY;
            if (moved > (this._where === 'bottom' ? SWIPE_DISTANCE : PULL_DISTANCE)) {
                this._finish();
                this._onSwipe();
            }
            return Clutter.EVENT_STOP;
        }
        if (type === Clutter.EventType.TOUCH_END || type === Clutter.EventType.TOUCH_CANCEL)
            this._finish();
        return Clutter.EVENT_STOP;
    }

    _finish() {
        this._startY = null;
        this._bar?.remove_style_pseudo_class('active');
    }

    destroy() {
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
        this.menu.setHeader('input-tablet-symbolic', 'Tablet Mode', 'Harbor home screen');

        this._items = {};
        for (const [mode, label] of [
            ['auto', 'Automatic (follow the hinge)'],
            ['tablet', 'Always Tablet'],
            ['laptop', 'Always Laptop'],
        ]) {
            const item = new PopupMenu.PopupMenuItem(label);
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
        this._seat = Clutter.get_default_backend().get_default_seat();
        this._touchId = this._seat.connect('notify::touch-mode', () => this._update());

        this._indicator = new TabletIndicator(this);
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);

        this._update();
    }

    disable() {
        // Always hand GNOME back exactly as we found it.
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
            console.warn(`Harbor: couldn't save mode: ${e}`);
        }
        this._update();
    }

    _update() {
        const tablet = this.isTablet();
        if (tablet !== this._tablet) {
            this._tablet = tablet;
            if (tablet)
                this._enterTablet();
            else
                this._leaveTablet(true);
        }
        this._indicator?.toggle.sync();
    }

    // ---- tablet mode ------------------------------------------------------
    _enterTablet() {
        // The Super key (and the Activities button) go Home instead.
        if (!this._origToggle) {
            this._origToggle = Main.overview.toggle;
            Main.overview.toggle = () => this.goHome();
        }

        if (!this._edge) {
            this._edge = new EdgeSwipe('bottom', () => this.closeApp());
            Main.layoutManager.addTopChrome(this._edge, {affectsInputRegion: true, trackFullscreen: false});
        }
        if (!this._topEdge) {
            this._topEdge = new EdgeSwipe('top', () => this._revealPanel());
            Main.layoutManager.addTopChrome(this._topEdge, {affectsInputRegion: true, trackFullscreen: false});
        }
        this._tuckPanel();
        this._hookOverviewGesture();

        if (!this._windowId) {
            this._windowId = global.display.connect('window-created', (_d, win) => this._placeNewWindow(win));
        }
        // Windows that were already open fill the screen too, and Harbor goes on every desktop.
        for (const actor of global.get_window_actors()) {
            const win = actor.meta_window;
            if (!win)
                continue;
            if (this._isHarbor(win))
                this._pinHarbor(win);
            else
                this._fill(win);
        }

        if (Main.layoutManager._startingUp) {
            // Right after login GNOME shows its overview; wait until it has
            // finished starting up, then go Home.
            this._startupId = Main.layoutManager.connect('startup-complete', () => {
                Main.layoutManager.disconnect(this._startupId);
                this._startupId = 0;
                if (this._tablet)
                    this.goHome();
            });
        } else {
            this.goHome();
        }
    }

    _leaveTablet(tuckHarborAway = false) {
        if (this._startupId) {
            Main.layoutManager.disconnect(this._startupId);
            this._startupId = 0;
        }
        if (this._origToggle) {
            Main.overview.toggle = this._origToggle;
            this._origToggle = null;
        }
        for (const key of ['_edge', '_topEdge']) {
            if (this[key]) {
                Main.layoutManager.removeChrome(this[key]);
                this[key].destroy();
                this[key] = null;
            }
        }
        this._restorePanel();
        this._unhookOverviewGesture();
        if (this._windowId) {
            global.display.disconnect(this._windowId);
            this._windowId = 0;
        }
        for (const win of this._harborWindows()) {
            try {
                win.unstick();
            } catch (_e) { /* fine */ }
            if (tuckHarborAway)
                win.minimize();
        }
    }

    // ---- windows: full screen, and Harbor on every desktop -------------------
    _isHarbor(win) {
        return win.get_wm_class() === HARBOR_WM_CLASS;
    }

    _pinHarbor(win) {
        try {
            if (!win.is_on_all_workspaces())
                win.stick();
        } catch (_e) { /* fine */ }
    }

    _fill(win) {
        if (!this._tablet || !win || win.get_window_type() !== Meta.WindowType.NORMAL)
            return;
        if (this._isHarbor(win) || win.get_transient_for() || !win.can_maximize())
            return;
        maximize(win);
    }

    _placeNewWindow(win) {
        // Apps often set their own size as they appear, so fill the screen at
        // a few moments: once GNOME is idle, at the first frame, and a bit later.
        GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            if (this._isHarbor(win))
                this._pinHarbor(win);
            else
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

    // ---- GNOME's top bar: tucked away, pulled down from the top edge ---------
    _tuckPanel() {
        if (this._panelTucked)
            return;
        const box = Main.layoutManager.panelBox;
        try {
            // Stop it reserving space at the top, so apps use the whole screen.
            Main.layoutManager.untrackChrome(box);
            Main.layoutManager.trackChrome(box, {affectsStruts: false, affectsInputRegion: true, trackFullscreen: false});
        } catch (e) {
            console.warn(`Harbor: couldn't free the top bar's space: ${e}`);
        }
        box.translation_y = -box.height;
        box.hide();
        this._panelTucked = true;
    }

    _restorePanel() {
        if (!this._panelTucked)
            return;
        if (this._panelTimer) {
            GLib.source_remove(this._panelTimer);
            this._panelTimer = 0;
        }
        const box = Main.layoutManager.panelBox;
        box.remove_all_transitions();
        try {
            Main.layoutManager.untrackChrome(box);
            Main.layoutManager.trackChrome(box, {affectsStruts: true, trackFullscreen: true});
        } catch (e) {
            console.warn(`Harbor: couldn't restore the top bar: ${e}`);
        }
        box.translation_y = 0;
        box.show();
        this._panelTucked = false;
    }

    _revealPanel() {
        if (!this._panelTucked)
            return;
        const box = Main.layoutManager.panelBox;
        box.show();
        box.ease({translation_y: 0, duration: 180, mode: Clutter.AnimationMode.EASE_OUT_QUAD});
        if (this._panelTimer)
            GLib.source_remove(this._panelTimer);
        let idle = 0;
        this._panelTimer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            // Stay while a menu from the top bar (Quick Settings, the calendar) is open.
            idle = Main.panel.menuManager.activeMenu ? 0 : idle + 1;
            if (idle < PANEL_SHOW_SECONDS)
                return GLib.SOURCE_CONTINUE;
            this._panelTimer = 0;
            this._hidePanel();
            return GLib.SOURCE_REMOVE;
        });
    }

    _hidePanel() {
        if (!this._panelTucked)
            return;
        const box = Main.layoutManager.panelBox;
        box.ease({
            translation_y: -box.height,
            duration: 180,
            mode: Clutter.AnimationMode.EASE_IN_QUAD,
            onComplete: () => {
                if (this._panelTucked)
                    box.hide();
            },
        });
    }

    // ---- three fingers up, then up again: a new desktop ----------------------
    _hookOverviewGesture() {
        const controls = Main.overview._overview?.controls;
        if (!controls || this._origGestureEnd)
            return;
        this._origGestureEnd = controls.gestureEnd;
        const orig = this._origGestureEnd;
        controls.gestureEnd = (target, duration, onComplete) => {
            if (target < APP_GRID || !this._tablet) {
                orig.call(controls, target, duration, onComplete);
                return;
            }
            // Instead of GNOME's app grid (Harbor is the app grid), settle on the
            // desktops view, then go to a fresh desktop with Harbor on it.
            orig.call(controls, 1, duration, onComplete);
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, duration + 60, () => {
                this.newDesktop();
                return GLib.SOURCE_REMOVE;
            });
        };
    }

    _unhookOverviewGesture() {
        const controls = Main.overview._overview?.controls;
        if (controls && this._origGestureEnd)
            controls.gestureEnd = this._origGestureEnd;
        this._origGestureEnd = null;
    }

    newDesktop() {
        const wm = global.workspace_manager;
        const time = global.get_current_time();
        // With GNOME's automatic desktops the last one is always empty: use it,
        // or add one if it isn't.
        let target = wm.get_workspace_by_index(wm.get_n_workspaces() - 1);
        const busy = target.list_windows().some(w => !w.is_on_all_workspaces() &&
            w.get_window_type() === Meta.WindowType.NORMAL);
        if (busy || target === wm.get_active_workspace())
            target = wm.append_new_workspace(false, time);
        target.activate(time);
        this.goHome();
    }

    // ---- the swipe up: close the app you're in -------------------------------
    closeApp() {
        if (Main.overview.visible) {
            Main.overview.hide();
            return;
        }
        const win = global.display.get_focus_window();
        if (win && !this._isHarbor(win) && win.get_window_type() !== Meta.WindowType.DESKTOP) {
            if (win.can_close())
                win.delete(global.get_current_time());
            else
                win.minimize();
        }
        this.goHome();
    }

    // ---- going home -----------------------------------------------------------
    _harborWindows() {
        return global.get_window_actors()
            .map(a => a.meta_window)
            .filter(w => w && this._isHarbor(w));
    }

    goHome() {
        if (Main.overview.visible)
            Main.overview.hide();
        const app = Shell.AppSystem.get_default().lookup_app(HARBOR_APP_ID);
        if (!app) {
            Main.notify('Harbor isn’t installed', 'Run Harbor’s install.sh to set up the home screen.');
            return;
        }
        const wins = this._harborWindows();
        if (wins.length) {
            // Raise Home and ask it to return to its first page.
            Main.activateWindow(wins[0]);
            app.activate();
        } else {
            app.activate();
        }
    }
}
