// Small helpers shared by the tablet pieces: boxes that work on every GNOME
// version we support, the saved favorites/folders, and the installed apps.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import St from 'gi://St';

// St.BoxLayout swapped `vertical` for `orientation` in GNOME 48.
let _hasOrientation = null;
export function box(vertical, params = {}) {
    if (_hasOrientation === null) {
        try {
            new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL}).destroy();
            _hasOrientation = true;
        } catch (_e) {
            _hasOrientation = false;
        }
    }
    if (_hasOrientation)
        return new St.BoxLayout({...params, orientation: vertical ? Clutter.Orientation.VERTICAL : Clutter.Orientation.HORIZONTAL});
    return new St.BoxLayout({...params, vertical});
}

export const vbox = params => box(true, params);
export const hbox = params => box(false, params);

export function label(text, styleClass, params = {}) {
    return new St.Label({text, style_class: styleClass ?? '', ...params});
}

// ---- favorites and folders: ~/.config/harbor/config.json ---------------------
// (Harbor's file, so favorites and folders made before carry over.)

function configFile() {
    return Gio.File.new_for_path(GLib.build_filenamev([GLib.get_user_config_dir(), 'harbor', 'config.json']));
}

export function loadConfig() {
    let data = {};
    try {
        const [, bytes] = configFile().load_contents(null);
        data = JSON.parse(new TextDecoder().decode(bytes));
    } catch (_e) { /* first run */ }
    data.dock ??= null;
    data.hidden ??= [];
    data.folders ??= {};
    return data;
}

export function saveConfig(data) {
    const file = configFile();
    try {
        file.get_parent().make_directory_with_parents(null);
    } catch (_e) { /* there already */ }
    file.replace_contents(new TextEncoder().encode(JSON.stringify(data, null, 1)), null, false,
        Gio.FileCreateFlags.REPLACE_DESTINATION, null);
}

export const DEFAULT_FAVORITES = [
    'dev.screenroom.Screenroom.desktop', 'dev.screenroom.Parlor.desktop', 'dev.spectacle.Spectacle.desktop',
    'org.mozilla.firefox.desktop', 'firefox.desktop', 'org.gnome.Nautilus.desktop', 'dev.heirloom.Weather.desktop',
];

// ---- apps ----------------------------------------------------------------------------
export const HARBOR_ID = 'dev.harbor.Harbor.desktop';

export function installedApps() {
    const seen = new Set();
    const out = [];
    for (const app of Shell.AppSystem.get_default().get_installed()) {
        if (!app.should_show())
            continue;
        const id = app.get_id();
        if (!id || seen.has(id))
            continue;
        seen.add(id);
        const shellApp = Shell.AppSystem.get_default().lookup_app(id);
        if (shellApp)
            out.push(shellApp);
    }
    out.sort((a, b) => a.get_name().localeCompare(b.get_name()));
    return out;
}

export function lookupApp(id) {
    return Shell.AppSystem.get_default().lookup_app(id);
}

export function appMatches(app, q) {
    const info = app.get_app_info();
    const hay = [app.get_name(), info?.get_description?.() ?? '', (info?.get_keywords?.() ?? []).join(' ')]
        .join(' ').toLowerCase();
    return hay.includes(q);
}

export function folderNameFor(app) {
    const cats = (app?.get_app_info()?.get_categories?.() ?? '').split(';');
    for (const [cat, name] of [
        ['Game', 'Games'], ['Education', 'School'], ['Office', 'Office'],
        ['AudioVideo', 'Watch & Listen'], ['Audio', 'Watch & Listen'], ['Video', 'Watch & Listen'],
        ['Graphics', 'Photos'], ['Network', 'Internet'], ['Development', 'Developer'],
        ['Settings', 'System'], ['System', 'System'], ['Utility', 'Utilities'],
    ]) {
        if (cats.includes(cat))
            return name;
    }
    return 'Folder';
}

// The desktop wallpaper, for backdrops (the app switcher).
export function wallpaperUri() {
    try {
        return new Gio.Settings({schema_id: 'org.gnome.desktop.background'}).get_string('picture-uri');
    } catch (_e) {
        return '';
    }
}

// ---- tap and tap-and-hold, for mouse and touch alike ---------------------------------
// (GNOME changed its gesture classes in version 48, so this is done by hand.)
const _pressing = new Set();

export function cancelPresses() {
    for (const p of [..._pressing])
        p.cancel();
}

export function makePressable(actor, {onTap, onLongPress, holdMs = 550}) {
    actor.reactive = true;
    const p = {timer: 0, pressed: false, longFired: false, sx: 0, sy: 0};
    p.cancel = () => {
        if (p.timer) {
            GLib.source_remove(p.timer);
            p.timer = 0;
        }
        p.pressed = false;
        _pressing.delete(p);
        actor.remove_style_pseudo_class('active');
    };
    actor.connect('destroy', () => p.cancel());
    actor.connect('event', (_a, ev) => {
        const t = ev.type();
        const E = Clutter.EventType;
        if (t === E.BUTTON_PRESS && ev.get_button() === 3) {
            onLongPress?.();
            return Clutter.EVENT_STOP;
        }
        if ((t === E.BUTTON_PRESS && ev.get_button() === 1) || t === E.TOUCH_BEGIN) {
            [p.sx, p.sy] = ev.get_coords();
            p.pressed = true;
            p.longFired = false;
            _pressing.add(p);
            actor.add_style_pseudo_class('active');
            if (onLongPress) {
                p.timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, holdMs, () => {
                    p.timer = 0;
                    p.longFired = true;
                    p.cancel();
                    onLongPress();
                    return GLib.SOURCE_REMOVE;
                });
            }
            return Clutter.EVENT_STOP;
        }
        if ((t === E.MOTION || t === E.TOUCH_UPDATE) && p.pressed) {
            const [x, y] = ev.get_coords();
            if (Math.hypot(x - p.sx, y - p.sy) > 14)
                p.cancel();
            return Clutter.EVENT_PROPAGATE;
        }
        if ((t === E.BUTTON_RELEASE && ev.get_button() === 1) || t === E.TOUCH_END) {
            const tap = p.pressed && !p.longFired;
            p.cancel();
            if (tap)
                onTap?.();
            return Clutter.EVENT_STOP;
        }
        if (t === E.TOUCH_CANCEL)
            p.cancel();
        return Clutter.EVENT_PROPAGATE;
    });
}

// Drag-to-scroll for a St.ScrollView on touch screens (taps still reach the icons).
export function touchScroll(scroll) {
    const s = {start: null, value: 0, dragging: false};
    scroll.connect('captured-event', (_a, ev) => {
        const t = ev.type();
        const E = Clutter.EventType;
        if (t === E.TOUCH_BEGIN) {
            s.start = ev.get_coords()[1];
            s.value = scroll.vadjustment.value;
            s.dragging = false;
            return Clutter.EVENT_PROPAGATE;
        }
        if (t === E.TOUCH_UPDATE && s.start !== null) {
            const dy = ev.get_coords()[1] - s.start;
            if (!s.dragging && Math.abs(dy) > 14) {
                s.dragging = true;
                cancelPresses();
            }
            if (s.dragging) {
                scroll.vadjustment.value = s.value - dy;
                return Clutter.EVENT_STOP;
            }
        }
        if ((t === E.TOUCH_END || t === E.TOUCH_CANCEL) && s.start !== null) {
            const was = s.dragging;
            s.start = null;
            s.dragging = false;
            if (was)
                return Clutter.EVENT_STOP;
        }
        return Clutter.EVENT_PROPAGATE;
    });
}
