// Open apps: swipe up from the bottom and pause. Each open app is a card; tap
// one to go back to it, flick it up to close it.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {hbox, label, makePressable, vbox, wallpaperUri} from './util.js';

const CARD_W = 340;
const FLICK = 140;   // px up that closes an app

export class Switcher {
    constructor(isAppWindow) {
        this._isAppWindow = isAppWindow;
        this.isOpen = false;
        this.root = new St.Widget({name: 'heirloomSwitcher', style_class: 'hs-root', reactive: true, visible: false,
            layout_manager: new Clutter.FixedLayout()});
        this.backdrop = new St.Widget({style_class: 'hs-backdrop', reactive: true});
        makePressable(this.backdrop, {onTap: () => this.close()});
        this.root.add_child(this.backdrop);
        this.dim = new St.Widget({style_class: 'hs-dim'});
        this.root.add_child(this.dim);

        this.scroll = new St.ScrollView({style_class: 'hs-scroll', hscrollbar_policy: St.PolicyType.EXTERNAL,
            vscrollbar_policy: St.PolicyType.NEVER, overlay_scrollbars: true});
        this.row = hbox({style_class: 'hs-row', y_align: Clutter.ActorAlign.CENTER,
            x_align: Clutter.ActorAlign.CENTER, x_expand: true});
        this.scroll.set_child(this.row);
        this.root.add_child(this.scroll);

        this.hint = new St.Bin({child: label('Tap an app to go back to it · Flick a card up to close it', 'hs-hint',
            {x_align: Clutter.ActorAlign.CENTER})});
        this.root.add_child(this.hint);
        this.empty = new St.Bin({child: label('No apps are open', 'hs-hint', {x_align: Clutter.ActorAlign.CENTER})});
        this.root.add_child(this.empty);

        this.root.connect('key-press-event', (_a, ev) => {
            if (ev.get_key_symbol() === Clutter.KEY_Escape) {
                this.close();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });

        Main.layoutManager.addTopChrome(this.root);
        Main.layoutManager.uiGroup.set_child_below_sibling(this.root, Main.layoutManager.panelBox);
        this._monitorsId = Main.layoutManager.connect('monitors-changed', () => this._relayout());
        this._relayout();
    }

    destroy() {
        this._popModal();
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
        this.backdrop.set_size(m.width, m.height);
        this.dim.set_size(m.width, m.height);
        this._cardH = Math.round(CARD_W * m.height / m.width);
        const rowH = this._cardH + 200;
        this.scroll.set_position(0, Math.round((m.height - rowH) / 2));
        this.scroll.set_size(m.width, rowH);
        this.hint.set_position(0, Math.round((m.height + rowH) / 2) + 10);
        this.hint.set_width(m.width);
        this.empty.set_position(0, Math.round(m.height / 2 - 12));
        this.empty.set_width(m.width);
    }

    windows() {
        return global.display.get_tab_list(Meta.TabList.NORMAL, null).filter(w => this._isAppWindow(w));
    }

    open() {
        if (this.isOpen)
            return;
        // The desktop wallpaper behind the cards.
        this._wall?.destroy();
        this._wall = null;
        const bg = Main.layoutManager._bgManagers?.[0]?.backgroundActor;
        if (bg) {
            this._wall = new Clutter.Clone({source: bg, reactive: false});
            this.backdrop.add_child(this._wall);
        } else {
            const uri = wallpaperUri();
            this.backdrop.set_style(uri ? `background-image: url("${uri}");` : null);
        }
        this._build();
        this.root.opacity = 0;
        this.root.show();
        this.root.ease({opacity: 255, duration: 160, mode: Clutter.AnimationMode.EASE_OUT_QUAD});
        this.isOpen = true;
        try {
            this._modal = Main.pushModal(this.root, {actionMode: Shell.ActionMode.POPUP});
        } catch (_e) {
            this._modal = null;
        }
        this.root.grab_key_focus();
    }

    close(then) {
        if (!this.isOpen)
            return;
        this.isOpen = false;
        this._popModal();
        this.root.ease({
            opacity: 0, duration: 140, mode: Clutter.AnimationMode.EASE_IN_QUAD,
            onComplete: () => {
                this.root.hide();
                this.row.destroy_all_children();
                then?.();
            },
        });
    }

    _popModal() {
        if (this._modal) {
            Main.popModal(this._modal);
            this._modal = null;
        }
    }

    _build() {
        this.row.destroy_all_children();
        // Oldest on the left, the app you were just in on the right (nearest your thumb).
        const wins = this.windows().reverse();
        this.empty.visible = !wins.length;
        this.hint.visible = wins.length > 0;
        for (const win of wins)
            this.row.add_child(this._card(win));
        GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            const adj = this.scroll.hadjustment;
            adj.value = adj.upper - adj.page_size;
            return GLib.SOURCE_REMOVE;
        });
    }

    _card(win) {
        const app = Shell.WindowTracker.get_default().get_window_app(win);
        const card = vbox({style_class: 'hs-card', reactive: true});
        const title = hbox({style_class: 'hs-title'});
        if (app)
            title.add_child(app.create_icon_texture(24));
        title.add_child(label(app ? app.get_name() : (win.get_title() ?? ''), 'hs-name'));
        const close = new St.Button({style_class: 'hs-close', label: '×', can_focus: true, x_expand: true,
            x_align: Clutter.ActorAlign.END, accessible_name: 'Close'});
        close.connect('clicked', () => this._closeCard(card, win));
        title.add_child(close);
        card.add_child(title);

        const shot = new St.Widget({style_class: 'hs-shot', width: CARD_W, height: this._cardH,
            layout_manager: new Clutter.BinLayout(), clip_to_allocation: true});
        const actor = win.get_compositor_private();
        if (actor) {
            const rect = win.get_frame_rect();
            const scale = Math.min(CARD_W / Math.max(1, rect.width), this._cardH / Math.max(1, rect.height));
            const clone = new Clutter.Clone({source: actor, x_align: Clutter.ActorAlign.CENTER, y_align: Clutter.ActorAlign.CENTER});
            clone.set_scale(scale, scale);
            // The window actor includes its shadow; shift so the frame lines up with the card.
            const bufferRect = win.get_buffer_rect();
            const dx = (rect.x - bufferRect.x) * scale, dy = (rect.y - bufferRect.y) * scale;
            const holder = new St.Widget({width: CARD_W, height: this._cardH, layout_manager: new Clutter.FixedLayout()});
            clone.set_position(-dx + (CARD_W - rect.width * scale) / 2, -dy + (this._cardH - rect.height * scale) / 2);
            holder.add_child(clone);
            shot.add_child(holder);
        }
        card.add_child(shot);
        this._flickable(card, win);
        return card;
    }

    _flickable(card, win) {
        let start = null, moved = false;
        card.connect('event', (_a, ev) => {
            const t = ev.type();
            const E = Clutter.EventType;
            if (t === E.TOUCH_BEGIN || (t === E.BUTTON_PRESS && ev.get_button() === 1)) {
                start = ev.get_coords();
                moved = false;
                return Clutter.EVENT_STOP;
            }
            if ((t === E.TOUCH_UPDATE || t === E.MOTION) && start) {
                const [x, y] = ev.get_coords();
                const dy = y - start[1], dx = x - start[0];
                if (!moved && Math.abs(dx) > 14 && Math.abs(dx) > Math.abs(dy)) {
                    // sideways: scroll the row instead
                    const adj = this.scroll.hadjustment;
                    adj.value -= dx;
                    start = [x, y];
                    return Clutter.EVENT_STOP;
                }
                if (Math.abs(dy) > 10)
                    moved = true;
                if (moved) {
                    card.translation_y = Math.min(0, dy);
                    card.opacity = Math.round(255 * Math.max(0.3, 1 + Math.min(0, dy) / 400));
                }
                return Clutter.EVENT_STOP;
            }
            if ((t === E.TOUCH_END || t === E.BUTTON_RELEASE) && start) {
                start = null;
                if (!moved) {
                    this.close(() => Main.activateWindow(win));
                } else if (card.translation_y < -FLICK) {
                    this._closeCard(card, win);
                } else {
                    card.ease({translation_y: 0, opacity: 255, duration: 160, mode: Clutter.AnimationMode.EASE_OUT_QUAD});
                }
                return Clutter.EVENT_STOP;
            }
            if (t === E.TOUCH_CANCEL && start) {
                start = null;
                card.ease({translation_y: 0, opacity: 255, duration: 160});
            }
            return Clutter.EVENT_PROPAGATE;
        });
    }

    _closeCard(card, win) {
        card.ease({
            translation_y: -this.root.height, opacity: 0, duration: 180, mode: Clutter.AnimationMode.EASE_IN_QUAD,
            onComplete: () => {
                card.destroy();
                if (!this.row.get_n_children())
                    this.close();
            },
        });
        try {
            win.delete(global.get_current_time());
        } catch (_e) { /* already gone */ }
    }
}
