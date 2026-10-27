// Harbor Tablet Mode — a GNOME Shell extension.
//
// Tablet mode (screen folded back, or forced from Quick Settings):
//   * Harbor comes to the front as the home screen
//   * the Super key goes Home instead of opening the Activities overview
//   * a swipe up from the bottom edge goes Home (with a little home bar)
//   * newly opened apps fill the screen
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
const SWIPE_DISTANCE = 70; // pixels up from the edge that count as "go home"
const EDGE_HEIGHT = 14;    // height of the touch strip along the bottom

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


// ---- the bottom-edge strip with its little home bar ------------------------

const HomeEdge = GObject.registerClass(
class HomeEdge extends St.Widget {
    _init(onHome) {
        super._init({
            name: 'harborHomeEdge',
            reactive: true,
            layout_manager: new Clutter.BinLayout(),
        });
        this._onHome = onHome;
        this._startY = null;

        this._bar = new St.Widget({
            style_class: 'harbor-home-bar',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this.add_child(this._bar);

        this.connect('touch-event', (_a, event) => this._touch(event));
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

    _touch(event) {
        const type = event.type();
        const [, y] = event.get_coords();
        if (type === Clutter.EventType.TOUCH_BEGIN) {
            this._startY = y;
            this._bar.add_style_pseudo_class('active');
            return Clutter.EVENT_STOP;
        }
        if (this._startY === null)
            return Clutter.EVENT_PROPAGATE;
        if (type === Clutter.EventType.TOUCH_UPDATE) {
            if (this._startY - y > SWIPE_DISTANCE) {
                this._finish();
                this._onHome();
            }
            return Clutter.EVENT_STOP;
        }
        if (type === Clutter.EventType.TOUCH_END || type === Clutter.EventType.TOUCH_CANCEL)
            this._finish();
        return Clutter.EVENT_STOP;
    }

    _finish() {
        this._startY = null;
        this._bar.remove_style_pseudo_class('active');
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
            this._edge = new HomeEdge(() => this.goHome());
            Main.layoutManager.addTopChrome(this._edge, {affectsInputRegion: true, trackFullscreen: false});
        }

        if (!this._windowId) {
            this._windowId = global.display.connect('window-created', (_d, win) => {
                // Let the window finish appearing, then fill the screen.
                GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                    if (win.get_window_type() === Meta.WindowType.NORMAL &&
                        win.get_wm_class() !== HARBOR_WM_CLASS &&
                        win.can_maximize())
                        maximize(win);
                    return GLib.SOURCE_REMOVE;
                });
            });
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
        if (this._edge) {
            Main.layoutManager.removeChrome(this._edge);
            this._edge.destroy();
            this._edge = null;
        }
        if (this._windowId) {
            global.display.disconnect(this._windowId);
            this._windowId = 0;
        }
        if (tuckHarborAway) {
            for (const win of this._harborWindows())
                win.minimize();
        }
    }

    // ---- going home -----------------------------------------------------------
    _harborWindows() {
        return global.get_window_actors()
            .map(a => a.meta_window)
            .filter(w => w && w.get_wm_class() === HARBOR_WM_CLASS);
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
