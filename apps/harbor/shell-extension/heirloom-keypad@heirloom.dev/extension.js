// Heirloom Passcode Keypad — a GNOME Shell extension that runs on the login screen
// (GDM), the lock screen and in your session.
//
//   * Where a person has a passcode (its length is in /var/lib/heirloom/passcode/<user>,
//     written by Heirloom's passcode helper), the password box becomes a keypad
//     with 4 or 6 dots. It unlocks by itself when the last digit is in. Typing the
//     digits on a keyboard works too. "Use Password" brings back the normal box.
//   * The lock screen is iPad-style: the clock over a sharp wallpaper; the keypad
//     over the same wallpaper, blurred.
//   * The login screen shows the lock-screen wallpaper
//     (/var/lib/heirloom/lock-wallpaper.png) and, when only one person has an
//     account, goes straight to their passcode.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as AuthPrompt from 'resource:///org/gnome/shell/gdm/authPrompt.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const PASSCODE_DIR = '/var/lib/heirloom/passcode';
const LOCK_WALLPAPER = '/var/lib/heirloom/lock-wallpaper.png';
const BLUR_RADIUS = 90;
const BLUR_BRIGHTNESS = 0.65;
const LETTERS = ['', 'ABC', 'DEF', 'GHI', 'JKL', 'MNO', 'PQRS', 'TUV', 'WXYZ'];

function passcodeLength(user) {
    if (!user || /[/\0]/.test(user))
        return 0;
    try {
        const [, bytes] = Gio.File.new_for_path(`${PASSCODE_DIR}/${user}`).load_contents(null);
        const n = parseInt(new TextDecoder().decode(bytes).trim(), 10);
        return n === 4 || n === 6 ? n : 0;
    } catch (_e) {
        return 0;
    }
}

// St.BoxLayout swapped `vertical` for `orientation` in GNOME 48.
function box(vertical, params = {}) {
    try {
        return new St.BoxLayout({...params, orientation: vertical ? Clutter.Orientation.VERTICAL : Clutter.Orientation.HORIZONTAL});
    } catch (_e) {
        return new St.BoxLayout({...params, vertical});
    }
}


// ---- the keypad, inside GNOME's own password prompt --------------------------------

class Keypad {
    constructor(prompt) {
        this.prompt = prompt;
        this.length = 0;
        this.active = false;
        this._submitted = false;

        this.actor = box(true, {style_class: 'hk-keypad', x_align: Clutter.ActorAlign.CENTER, visible: false});
        this.title = new St.Label({style_class: 'hk-title', text: 'Enter Passcode', x_align: Clutter.ActorAlign.CENTER});
        this.actor.add_child(this.title);
        this.dots = box(false, {style_class: 'hk-dots', x_align: Clutter.ActorAlign.CENTER});
        this.actor.add_child(this.dots);

        const grid = new St.Widget({style_class: 'hk-grid', x_align: Clutter.ActorAlign.CENTER,
            layout_manager: new Clutter.GridLayout({row_spacing: 16, column_spacing: 28})});
        const lm = grid.layout_manager;
        const key = (digit, letters) => {
            const b = new St.Button({style_class: 'hk-key', can_focus: false, accessible_name: digit});
            const inner = box(true, {x_align: Clutter.ActorAlign.CENTER, y_align: Clutter.ActorAlign.CENTER});
            inner.add_child(new St.Label({style_class: 'hk-digit', text: digit, x_align: Clutter.ActorAlign.CENTER}));
            const l = new St.Label({style_class: 'hk-letters', text: letters, x_align: Clutter.ActorAlign.CENTER});
            l.clutter_text.ellipsize = 0; // Pango.EllipsizeMode.NONE
            inner.add_child(l);
            b.set_child(inner);
            b.connect('clicked', () => this.type(digit));
            return b;
        };
        for (let n = 1; n <= 9; n++)
            lm.attach(key(String(n), LETTERS[n - 1]), (n - 1) % 3, Math.floor((n - 1) / 3), 1, 1);
        lm.attach(key('0', ''), 1, 3, 1, 1);
        this.actor.add_child(grid);

        const bottom = box(false, {style_class: 'hk-bottom', x_expand: true});
        this.cancelBtn = new St.Button({style_class: 'hk-text-button', label: 'Cancel', can_focus: true});
        this.cancelBtn.connect('clicked', () => this.prompt.cancel());
        this.passwordBtn = new St.Button({style_class: 'hk-text-button hk-small', label: 'Use Password', can_focus: true,
            x_expand: true, x_align: Clutter.ActorAlign.CENTER});
        this.passwordBtn.connect('clicked', () => this.deactivate(true));
        this.deleteBtn = new St.Button({style_class: 'hk-text-button', label: 'Delete', can_focus: true});
        this.deleteBtn.connect('clicked', () => this.erase());
        bottom.add_child(this.cancelBtn);
        bottom.add_child(this.passwordBtn);
        bottom.add_child(this.deleteBtn);
        this.actor.add_child(bottom);
    }

    setUser(user) {
        this.length = passcodeLength(user);
    }

    entry() {
        return this.prompt._entry;
    }

    activate() {
        if (!this.length || this._usePassword)
            return;
        this.active = true;
        this._submitted = false;
        this.title.text = 'Enter Passcode';
        this.actor.show();
        // GNOME's own row (with the real, focused password box) stays, unseen.
        const row = this.prompt._mainBox;
        if (row) {
            row.opacity = 0;
            row.set_height(1);
        }
        this.prompt._userWell?.hide();
        this._watchEntry();
        this.draw();
    }

    deactivate(forGood = false) {
        if (forGood)
            this._usePassword = true;
        this.active = false;
        this.actor.hide();
        const row = this.prompt._mainBox;
        if (row) {
            row.opacity = 255;
            row.set_height(-1);
        }
        this.prompt._userWell?.show();
        this.entry()?.grab_key_focus();
    }

    _watchEntry() {
        for (const e of [this.prompt._passwordEntry, this.prompt._textEntry]) {
            if (!e || e._hkWatched)
                continue;
            e._hkWatched = true;
            e.clutter_text.connect('text-changed', () => {
                if (!this.active)
                    return;
                // digits only
                const text = e.get_text();
                const clean = text.replace(/\D/g, '').slice(0, this.length);
                if (clean !== text) {
                    e.set_text(clean);
                    return;
                }
                this.draw();
                if (clean.length === this.length && !this._submitted)
                    GLib.idle_add(GLib.PRIORITY_DEFAULT, () => (this._submit(), GLib.SOURCE_REMOVE));
            });
        }
    }

    type(digit) {
        const e = this.entry();
        if (!e || this._submitted)
            return;
        if (e.get_text().length < this.length)
            e.set_text(e.get_text() + digit);
        e.grab_key_focus();
    }

    erase() {
        const e = this.entry();
        if (!e || this._submitted)
            return;
        e.set_text(e.get_text().slice(0, -1));
        e.grab_key_focus();
    }

    _submit() {
        const e = this.entry();
        if (!this.active || this._submitted || !e || e.get_text().length !== this.length)
            return;
        this._submitted = true;
        this.title.text = 'Unlocking…';
        this.prompt._activateNext(true);
    }

    failed() {
        this._submitted = false;
        if (!this.active)
            return;
        this.title.text = 'Wrong Passcode';
        this.dots.remove_all_transitions();
        // a little shake
        this.dots.translation_x = 0;
        const shake = [-14, 12, -9, 6, -3, 0];
        let i = 0;
        const step = () => {
            if (i >= shake.length)
                return;
            this.dots.ease({translation_x: shake[i++], duration: 45, mode: Clutter.AnimationMode.EASE_OUT_QUAD, onComplete: step});
        };
        step();
        this.draw();
    }

    reset() {
        this._submitted = false;
        if (this.active)
            this.title.text = 'Enter Passcode';
        this.draw();
    }

    draw() {
        const filled = this.entry()?.get_text().length ?? 0;
        this.dots.destroy_all_children();
        for (let i = 0; i < this.length; i++)
            this.dots.add_child(new St.Widget({style_class: i < filled ? 'hk-dot hk-dot-on' : 'hk-dot'}));
    }
}


// ---- the extension ------------------------------------------------------------------

export default class HeirloomKeypadExtension extends Extension {
    enable() {
        this._patches = [];
        const P = AuthPrompt.AuthPrompt.prototype;

        this._patch(P, '_initInputRow', function (orig, ...args) {
            const res = orig.apply(this, args);
            const parent = this._mainBox?.get_parent();
            if (!this._heirloomKeypad && parent) {
                // (Right below GNOME's password row, wherever this version puts it.)
                this._heirloomKeypad = new Keypad(this);
                parent.insert_child_above(this._heirloomKeypad.actor, this._mainBox);
            }
            return res;
        });
        this._patch(P, 'begin', function (orig, params = {}) {
            this._heirloomKeypad?.setUser(params?.userName ?? (this._mode === AuthPrompt.AuthPromptMode.UNLOCK_ONLY ? GLib.get_user_name() : null));
            return orig.call(this, params);
        });
        this._patch(P, '_onAskQuestion', function (orig, verifier, serviceName, question, secret, ...rest) {
            const res = orig.call(this, verifier, serviceName, question, secret, ...rest);
            const kp = this._heirloomKeypad;
            if (kp) {
                if (!kp.length && this._mode === AuthPrompt.AuthPromptMode.UNLOCK_ONLY)
                    kp.setUser(GLib.get_user_name());
                if (secret)
                    kp.activate();
                else if (kp.active)
                    kp.deactivate();
            }
            return res;
        });
        this._patch(P, '_onVerificationFailed', function (orig, ...args) {
            const res = orig.apply(this, args);
            this._heirloomKeypad?.failed();
            return res;
        });
        this._patch(P, 'reset', function (orig, ...args) {
            const res = orig.apply(this, args);
            this._heirloomKeypad?.reset();
            return res;
        });

        // The lock screen: a sharp clock, a blurred background behind the keypad.
        this._patchUnlockDialog();

        // The login screen.
        if (Main.sessionMode.isGreeter)
            this._greeter();
    }

    disable() {
        for (const [obj, name, orig] of this._patches.reverse())
            obj[name] = orig;
        this._patches = [];
        if (this._wallSet) {
            Main.screenShield?._lockDialogGroup?.set_style(null);
            this._wallSet = false;
        }
    }

    _patch(obj, name, fn) {
        const orig = obj[name];
        if (typeof orig !== 'function')
            return;
        this._patches.push([obj, name, orig]);
        // If anything here goes wrong, GNOME's own code still runs: the login and
        // lock screens must never break because of the keypad.
        obj[name] = function (...args) {
            let called = false;
            const once = (...a) => {
                called = true;
                return orig.apply(this, a);
            };
            try {
                return fn.call(this, once, ...args);
            } catch (e) {
                console.error(`Heirloom keypad (${name}): ${e}`);
                if (!called)
                    return orig.apply(this, args);
                return undefined;
            }
        };
    }

    async _patchUnlockDialog() {
        let mod;
        try {
            mod = await import('resource:///org/gnome/shell/ui/unlockDialog.js');
        } catch (_e) {
            return;
        }
        const U = mod.UnlockDialog?.prototype;
        if (!U)
            return;
        const blur = (dialog, progress) => {
            const scale = St.ThemeContext.get_for_stage(global.stage).scale_factor;
            for (const widget of dialog._backgroundGroup ?? []) {
                const effect = widget.get_effect('blur');
                effect?.set({
                    brightness: 1 - (1 - BLUR_BRIGHTNESS) * progress,
                    radius: Math.round(BLUR_RADIUS * scale * progress),
                });
            }
        };
        this._patch(U, '_setTransitionProgress', function (orig, progress) {
            const res = orig.call(this, progress);
            blur(this, progress);
            return res;
        });
        this._patch(U, '_updateBackgroundEffects', function (orig, ...args) {
            const res = orig.apply(this, args);
            blur(this, this._adjustment?.value ?? 0);
            return res;
        });
    }

    async _greeter() {
        // The lock-screen wallpaper behind the login screen.
        if (GLib.file_test(LOCK_WALLPAPER, GLib.FileTest.EXISTS)) {
            const group = Main.screenShield?._lockDialogGroup;
            if (group) {
                group.set_style(`background-image: url("file://${LOCK_WALLPAPER}"); background-size: cover; background-position: center;`);
                this._wallSet = true;
            }
        }
        // One person: straight to their passcode.
        let mod;
        try {
            mod = await import('resource:///org/gnome/shell/gdm/loginDialog.js');
        } catch (_e) {
            return;
        }
        const L = mod.LoginDialog?.prototype;
        if (!L)
            return;
        this._patch(L, '_showUserList', function (orig, ...args) {
            const res = orig.apply(this, args);
            const items = Object.values(this._userList?._items ?? {});
            if (items.length === 1 && !this._heirloomPicked) {
                this._heirloomPicked = true;
                GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
                    try {
                        this._onUserListActivated(items[0]);
                    } catch (e) {
                        console.warn(`Heirloom keypad: couldn't pick the user: ${e}`);
                    }
                    return GLib.SOURCE_REMOVE;
                });
            }
            return res;
        });
        // If the list is already up, pick now.
        const dialog = Main.screenShield?._dialog;
        if (dialog?._userList && dialog._authPrompt && !dialog._authPrompt.visible)
            dialog._showUserList();
    }
}
