# Spectacle

A light, glossy video app for your Linux tablet: your subscriptions, channel
pages, Watch Later, offline downloads and a full-screen player. No account,
no ads, and everything is stored on your own device.

## Install (Fedora)

1. Unzip the folder anywhere (your Downloads folder is fine).
2. Open **Terminal**, then type `cd ` (with a space), drag the `spectacle`
   folder into the window, and press Enter.
3. Run `bash install.sh` and type your password when asked.

Spectacle then appears in your app grid. Running the installer again updates it.

## First steps

- **Bring your subscriptions over:** on another device, go to
  takeout.google.com, deselect everything, select **YouTube and YouTube Music**,
  and under its options choose only **subscriptions**. In the downloaded zip,
  find `subscriptions.csv`, then in Spectacle tap **Import Subscriptions**.
- **Or add channels one by one:** search for them, or use **+** on the
  Channels tab and type an `@handle`.

## Using it

| Where | What it does |
|---|---|
| Subscriptions | Newest videos from your channels. Refresh with the button at top right. |
| Search | Videos and channels. Tap a channel to open its page and subscribe. |
| Channels | Your subscriptions. **Edit** to unsubscribe, **+** to add or import. |
| Watch Later | Tap the clock on any video to save it here. |
| Downloads | Tap the arrow on any video to keep it offline. Files are in `~/Videos/Spectacle`. |

**Player:** tap the video to show or hide controls, double-tap for full screen.
On a keyboard: Space plays/pauses, ←/→ jumps 10 seconds, F toggles full
screen, Esc closes. Spectacle remembers where you stopped and resumes there.

## When something breaks

YouTube changes things now and then, which can stop videos or search from
loading. The fix is almost always:

```
spectacle update
```

To see error messages, start Spectacle from Terminal by typing `spectacle`.

## Making it yours

All the code is yours to change. Good places to start:

- `spectacle/style.css` — every color, gradient, shadow and corner radius.
  The light-blue palette is defined at the top.
- `spectacle/player.py` — `STREAM_FORMAT` sets video quality (720p by default,
  which suits the Latitude's screen).
- `spectacle/icons/hicolor/scalable/actions/` — the app's icon set (simple 16×16 SVGs).

After editing, run `bash install.sh` again to apply your changes. To preview
the design without internet, run `SPECTACLE_DEMO=1 spectacle`.

## Good to know

- Watching through a third-party app without ads goes against YouTube's terms
  of service. Spectacle never signs into your Google account.
- Your library lives in `~/.local/share/spectacle/library.json`.
- To remove Spectacle, run `bash uninstall.sh`. Downloaded videos are kept.
