// The app drawer: a glass sheet that slides up over the app you're in, with
// search, a row of favorites, and every app (and folder) in alphabetical order.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {
    DEFAULT_FAVORITES, appMatches, folderNameFor, hbox, installedApps, label,
    loadConfig, lookupApp, makePressable, saveConfig, touchScroll, vbox,
} from './util.js';

const SIDE = 40;          // gap either side of the sheet
const TOP = 96;           // where the open sheet's top edge sits
const CELL = 104;         // one icon's column
const ANIM = 220;

export class Drawer {
    constructor() {
        this.progress = 0;
        this.isOpen = false;
        this._modal = null;
        this._dirty = true;
        this._installedId = Shell.AppSystem.get_default().connect('installed-changed', () => (this._dirty = true));

        this.root = new St.Widget({name: 'heirloomDrawer', reactive: true, visible: false, layout_manager: new Clutter.FixedLayout()});
        this.veil = new St.Widget({style_class: 'hd-veil', reactive: true, opacity: 0});
        makePressable(this.veil, {onTap: () => this.close()});
        this.root.add_child(this.veil);

        this.sheet = vbox({style_class: 'hd-sheet', reactive: true});
        this.root.add_child(this.sheet);

        const grab = new St.Widget({style_class: 'hd-grabber', x_align: Clutter.ActorAlign.CENTER, reactive: true});
        this._grabArea = new St.Bin({child: grab, x_expand: true, reactive: true, style_class: 'hd-grab-area'});
        this._watchSwipeDown(this._grabArea);
        this.sheet.add_child(this._grabArea);

        this.search = new St.Entry({style_class: 'hd-search', hint_text: 'Search apps', can_focus: true,
            x_align: Clutter.ActorAlign.CENTER});
        this.search.clutter_text.connect('text-changed', () => this._fill());
        this.search.clutter_text.connect('activate', () => this._openFirstMatch());
        this.search.clutter_text.connect('key-press-event', (_a, ev) => {
            if (ev.get_key_symbol() === Clutter.KEY_Escape) {
                this.close();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
        this.sheet.add_child(this.search);

        this.favTitle = label('FAVORITES', 'hd-section');
        this.favRow = hbox({style_class: 'hd-favs', x_align: Clutter.ActorAlign.FILL});
        this.allTitle = label('ALL APPS', 'hd-section');
        this.sheet.add_child(this.favTitle);
        this.sheet.add_child(this.favRow);
        this.sheet.add_child(this.allTitle);

        this.scroll = new St.ScrollView({style_class: 'hd-scroll', x_expand: true, y_expand: true,
            hscrollbar_policy: St.PolicyType.NEVER, vscrollbar_policy: St.PolicyType.AUTOMATIC, overlay_scrollbars: true});
        this.grid = vbox({style_class: 'hd-grid', x_expand: true});
        this.scroll.set_child(this.grid);
        touchScroll(this.scroll);
        this.sheet.add_child(this.scroll);

        this.root.connect('key-press-event', (_a, ev) => {
            if (ev.get_key_symbol() === Clutter.KEY_Escape) {
                this.close();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });

        Main.layoutManager.addTopChrome(this.root);
        // Keep the status bar above the drawer.
        Main.layoutManager.uiGroup.set_child_below_sibling(this.root, Main.layoutManager.panelBox);
        this._monitorsId = Main.layoutManager.connect('monitors-changed', () => this._relayout());
        this._relayout();
    }

    destroy() {
        this._popModal();
        if (this._installedId)
            Shell.AppSystem.get_default().disconnect(this._installedId);
        if (this._monitorsId)
            Main.layoutManager.disconnect(this._monitorsId);
        Main.layoutManager.removeChrome(this.root);
        this.root.destroy();
    }

    _relayout() {
        const m = Main.layoutManager.primaryMonitor;
        if (!m)
            return;
        this.root.set_position(m.x, m.y);
        this.root.set_size(m.width, m.height);
        this.veil.set_size(m.width, m.height);
        this._sheetH = m.height - TOP;
        this.sheet.set_position(SIDE, TOP);
        this.sheet.set_size(m.width - 2 * SIDE, this._sheetH);
        this._cols = Math.max(4, Math.floor((m.width - 2 * SIDE - 88) / CELL));
        this._dirty = true;
        this._apply();
    }

    // ---- following the finger ---------------------------------------------------
    beginDrag() {
        this._prepare();
        this.root.show();
    }

    dragTo(px) {
        this.progress = Math.max(0, Math.min(1, px / this._sheetH));
        this._apply();
    }

    endDrag(velocity) {
        // velocity: px per ms upward
        if (this.progress > 0.25 || velocity > 0.45)
            this.open();
        else
            this.close();
    }

    _apply() {
        this.sheet.translation_y = this._sheetH * (1 - this.progress);
        this.veil.opacity = Math.round(255 * this.progress);
    }

    _animateTo(target, done) {
        const from = this.progress;
        const start = GLib.get_monotonic_time();
        if (this._anim)
            GLib.source_remove(this._anim);
        this._anim = GLib.timeout_add(GLib.PRIORITY_HIGH, 16, () => {
            const t = Math.min(1, (GLib.get_monotonic_time() - start) / 1000 / ANIM);
            const eased = 1 - Math.pow(1 - t, 3);
            this.progress = from + (target - from) * eased;
            this._apply();
            if (t < 1)
                return GLib.SOURCE_CONTINUE;
            this._anim = 0;
            done?.();
            return GLib.SOURCE_REMOVE;
        });
    }

    toggle() {
        if (this.isOpen)
            this.close();
        else
            this.open();
    }

    open() {
        if (!this.root.visible)
            this.beginDrag();
        this.isOpen = true;
        this._animateTo(1, () => {
            this._pushModal();
            this.search.grab_key_focus();
        });
    }

    close() {
        this._popModal();
        this._closeMenu();
        this._closeFolder();
        this.isOpen = false;
        this._animateTo(0, () => {
            this.root.hide();
            this.search.set_text('');
        });
    }

    hideNow() {
        if (this._anim) {
            GLib.source_remove(this._anim);
            this._anim = 0;
        }
        this._popModal();
        this._closeMenu();
        this._closeFolder();
        this.isOpen = false;
        this.progress = 0;
        this._apply();
        this.root.hide();
    }

    _pushModal() {
        if (this._modal)
            return;
        try {
            this._modal = Main.pushModal(this.root, {actionMode: Shell.ActionMode.POPUP});
        } catch (_e) {
            this._modal = null;
        }
    }

    _popModal() {
        if (this._modal) {
            Main.popModal(this._modal);
            this._modal = null;
        }
    }

    _watchSwipeDown(actor) {
        let start = null;
        actor.connect('event', (_a, ev) => {
            const t = ev.type();
            const E = Clutter.EventType;
            if (t === E.TOUCH_BEGIN || (t === E.BUTTON_PRESS && ev.get_button() === 1)) {
                start = ev.get_coords()[1];
                return Clutter.EVENT_STOP;
            }
            if ((t === E.TOUCH_UPDATE || t === E.MOTION) && start !== null) {
                const dy = ev.get_coords()[1] - start;
                this.progress = Math.max(0, Math.min(1, 1 - dy / this._sheetH));
                this._apply();
                return Clutter.EVENT_STOP;
            }
            if ((t === E.TOUCH_END || t === E.BUTTON_RELEASE) && start !== null) {
                const dy = ev.get_coords()[1] - start;
                start = null;
                if (dy > 80 || Math.abs(dy) < 6)
                    this.close();  // a pull down, or a tap on the grabber
                else
                    this.open();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
    }

    // ---- what's in it ---------------------------------------------------------------
    _prepare() {
        if (this._dirty || !this._built) {
            this._config = loadConfig();
            this._apps = installedApps();
            this._byId = new Map(this._apps.map(a => [a.get_id(), a]));
            if (this._config.dock === null) {
                this._config.dock = DEFAULT_FAVORITES.filter(id => this._byId.has(id)).slice(0, 8);
                this._save();
            }
            this._dirty = false;
            this._built = true;
        }
        this._fill();
    }

    _save() {
        try {
            saveConfig(this._config);
        } catch (e) {
            console.warn(`Heirloom drawer: couldn't save: ${e}`);
        }
    }

    _query() {
        return this.search.get_text().trim().toLowerCase();
    }

    _fill() {
        if (!this._apps)
            return;
        const q = this._query();
        const hidden = new Set(this._config.hidden);
        this.favRow.destroy_all_children();
        this.grid.destroy_all_children();

        const showFavs = !q;
        this.favTitle.visible = this.favRow.visible = showFavs;
        if (showFavs) {
            for (const id of this._config.dock) {
                const app = this._byId.get(id);
                if (app)
                    this.favRow.add_child(this._appIcon(app, {fav: true}));
            }
            if (!this.favRow.get_n_children())
                this.favRow.add_child(label('Tap and hold an app to add it to Favorites.', 'hd-empty'));
        }

        let items;
        if (q) {
            this.allTitle.text = 'RESULTS';
            items = this._apps.filter(a => !hidden.has(a.get_id()) && appMatches(a, q)).map(a => ({app: a}));
            if (!items.length) {
                this.grid.add_child(label(`No apps match “${this.search.get_text().trim()}”`, 'hd-empty'));
                return;
            }
        } else {
            this.allTitle.text = 'ALL APPS';
            const inFolder = new Set(Object.values(this._config.folders).flatMap(f => f.apps));
            items = this._apps.filter(a => !hidden.has(a.get_id()) && !inFolder.has(a.get_id()))
                .map(a => ({app: a, name: a.get_name()}));
            for (const [fid, f] of Object.entries(this._config.folders)) {
                const apps = f.apps.map(id => this._byId.get(id)).filter(Boolean);
                if (apps.length)
                    items.push({folder: fid, name: f.name, apps});
            }
            items.sort((a, b) => a.name.localeCompare(b.name));
        }

        let row = null;
        items.forEach((item, n) => {
            if (n % this._cols === 0) {
                row = hbox({style_class: 'hd-row'});
                this.grid.add_child(row);
            }
            row.add_child(item.folder ? this._folderIcon(item) : this._appIcon(item.app, {}));
        });
    }

    _openFirstMatch() {
        const q = this._query();
        if (!q)
            return;
        const hit = this._apps.find(a => appMatches(a, q));
        if (hit)
            this._launch(hit);
    }

    _launch(app) {
        this.hideNow();
        app.activate();
    }

    _tile(child, extra = '') {
        const tile = new St.Bin({style_class: `hd-tile ${extra}`, child, x_align: Clutter.ActorAlign.CENTER});
        return tile;
    }

    _appIcon(app, {fav = false, folder = null}) {
        const cell = vbox({style_class: 'hd-app', x_align: Clutter.ActorAlign.CENTER});
        cell.add_child(this._tile(app.create_icon_texture(48)));
        cell.add_child(label(app.get_name(), 'hd-app-label', {x_align: Clutter.ActorAlign.CENTER}));
        cell.get_last_child().clutter_text.ellipsize = 3; // Pango.EllipsizeMode.END
        makePressable(cell, {
            onTap: () => this._launch(app),
            onLongPress: () => this._appMenu(cell, app, {fav, folder}),
        });
        return cell;
    }

    _folderIcon(item) {
        const cell = vbox({style_class: 'hd-app', x_align: Clutter.ActorAlign.CENTER});
        const minis = new St.Widget({layout_manager: new Clutter.GridLayout({row_spacing: 4, column_spacing: 4}),
            x_align: Clutter.ActorAlign.CENTER, y_align: Clutter.ActorAlign.CENTER});
        const lm = minis.layout_manager;
        item.apps.slice(0, 4).forEach((app, i) => lm.attach(app.create_icon_texture(22), i % 2, Math.floor(i / 2), 1, 1));
        cell.add_child(this._tile(minis, 'hd-folder-tile'));
        cell.add_child(label(item.name, 'hd-app-label', {x_align: Clutter.ActorAlign.CENTER}));
        makePressable(cell, {
            onTap: () => this._openFolder(item.folder),
            onLongPress: () => this._menu(cell, [
                ['Rename', () => this._openFolder(item.folder, true)],
                ['Remove Folder (keep the apps)', () => this._removeFolder(item.folder)],
            ]),
        });
        return cell;
    }

    // ---- tap-and-hold menus -------------------------------------------------------------
    _appMenu(cell, app, {fav, folder}) {
        const id = app.get_id();
        const isFav = this._config.dock.includes(id);
        const items = [[isFav ? 'Remove from Favorites' : 'Add to Favorites', () => this._toggleFav(id)]];
        const inFolder = folder ?? Object.keys(this._config.folders).find(f => this._config.folders[f].apps.includes(id));
        if (inFolder)
            items.push(['Take Out of Folder', () => this._takeOut(id)]);
        else if (!fav)
            items.push(['Add to Folder…', () => this._folderPicker(cell, id)]);
        items.push(['Open', () => this._launch(app)]);
        this._menu(cell, items);
    }

    _folderPicker(cell, id) {
        const items = Object.entries(this._config.folders).map(([fid, f]) => [`Into “${f.name}”`, () => {
            this._config.folders[fid].apps.push(id);
            this._save();
            this._fill();
        }]);
        items.push(['New Folder', () => this._newFolder(id)]);
        this._menu(cell, items);
    }

    _menu(cell, items) {
        this._closeMenu();
        const menu = vbox({style_class: 'hd-menu', reactive: true});
        for (const [text, fn] of items) {
            const b = new St.Button({style_class: 'hd-menu-item', label: text, x_align: Clutter.ActorAlign.FILL, can_focus: true});
            b.connect('clicked', () => {
                this._closeMenu();
                fn();
            });
            menu.add_child(b);
        }
        // A catcher behind the menu closes it on a tap elsewhere.
        this._catcher = new St.Widget({reactive: true, width: this.root.width, height: this.root.height});
        makePressable(this._catcher, {onTap: () => this._closeMenu()});
        this.root.add_child(this._catcher);
        this.root.add_child(menu);
        this._menuActor = menu;
        const [cx, cy] = cell.get_transformed_position();
        const [rx, ry] = this.root.get_transformed_position();
        const [, natW] = menu.get_preferred_width(-1);
        const [, natH] = menu.get_preferred_height(natW);
        let x = cx - rx + cell.width / 2 - natW / 2;
        let y = cy - ry - natH - 6;
        if (y < TOP)
            y = cy - ry + cell.height + 6;
        x = Math.max(8, Math.min(this.root.width - natW - 8, x));
        menu.set_position(Math.round(x), Math.round(y));
    }

    _closeMenu() {
        this._menuActor?.destroy();
        this._menuActor = null;
        this._catcher?.destroy();
        this._catcher = null;
    }

    _toggleFav(id) {
        const d = this._config.dock;
        if (d.includes(id))
            this._config.dock = d.filter(x => x !== id);
        else
            d.push(id);
        this._save();
        this._fill();
    }

    _takeOut(id) {
        for (const [fid, f] of Object.entries(this._config.folders)) {
            f.apps = f.apps.filter(a => a !== id);
            if (!f.apps.length)
                delete this._config.folders[fid];
        }
        this._save();
        this._closeFolder();
        this._fill();
    }

    _newFolder(id) {
        let n = 1;
        while (`folder:${n}` in this._config.folders)
            n++;
        const fid = `folder:${n}`;
        this._config.folders[fid] = {name: folderNameFor(this._byId.get(id)), apps: [id]};
        this._save();
        this._fill();
        this._openFolder(fid, true);
    }

    _removeFolder(fid) {
        delete this._config.folders[fid];
        this._save();
        this._closeFolder();
        this._fill();
    }

    // ---- an open folder ------------------------------------------------------------------
    _openFolder(fid, rename = false) {
        this._closeFolder();
        const f = this._config.folders[fid];
        if (!f)
            return;
        const veil = new St.Widget({style_class: 'hd-folder-veil', reactive: true,
            width: this.root.width, height: this.root.height, layout_manager: new Clutter.BinLayout()});
        makePressable(veil, {onTap: () => this._closeFolder()});
        const card = vbox({style_class: 'hd-folder-card', reactive: true,
            x_align: Clutter.ActorAlign.CENTER, y_align: Clutter.ActorAlign.CENTER});
        const name = new St.Entry({style_class: 'hd-folder-name', text: f.name, can_focus: true, x_align: Clutter.ActorAlign.CENTER});
        name.clutter_text.connect('text-changed', () => {
            f.name = name.get_text().trim() || 'Folder';
            this._save();
        });
        name.clutter_text.connect('activate', () => this._closeFolder());
        card.add_child(name);
        let row = null;
        f.apps.map(id => this._byId.get(id)).filter(Boolean).forEach((app, i) => {
            if (i % 4 === 0) {
                row = hbox({style_class: 'hd-row'});
                card.add_child(row);
            }
            row.add_child(this._appIcon(app, {folder: fid}));
        });
        veil.add_child(card);
        this.root.add_child(veil);
        this._folderVeil = veil;
        if (rename) {
            name.grab_key_focus();
            name.clutter_text.set_selection(0, -1);
        }
    }

    _closeFolder() {
        if (!this._folderVeil)
            return;
        this._folderVeil.destroy();
        this._folderVeil = null;
        this._fill();
    }
}
