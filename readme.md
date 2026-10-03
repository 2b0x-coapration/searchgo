# SUPERGO

A light, fast Linux web browser built on **WebKitGTK + GTK3**, written in Python.
Flat dark interface, tabs in a sidebar, a built-in ad blocker, a browser-only VPN, and no account or root access needed.

![version](https://img.shields.io/badge/version-1.8.0-blue)
![platform](https://img.shields.io/badge/platform-Debian%20%2F%20Ubuntu-orange)
![engine](https://img.shields.io/badge/engine-WebKitGTK-lightgrey)
![license](https://img.shields.io/badge/license-MIT-green)

---

## Screenshots

![New-tab page with the sidebar](screenshots/home.png)

The new-tab page: tabs in the sidebar, one address pill, and floating cards for frequently visited sites.

### Welcome tour

| | |
| --- | --- |
| ![Welcome](screenshots/welcome-1.png) | ![Ad blocker](screenshots/welcome-5-adblock.png) |
| ![VPN](screenshots/welcome-6-vpn.png) | ![Private windows](screenshots/welcome-7-private.png) |

---

## Features

- **Sidebar tabs**: open tabs and bookmarks live in a slide-out sidebar, with a single address pill at the top.
- **Animated new-tab page**: a live background with floating cards for frequently visited, bookmarked and recent sites.
- **Built-in ad and tracker blocker**: uBlock Origin / EasyList filter lists compiled into WebKit's content blocker, plus YouTube ad pruning and a per-site on/off switch.
- **Browser-only VPN**: runs a v2ray / xray core as your own user (no root). Only SUPERGO's traffic goes through it, and browsing pauses if the tunnel drops so nothing leaks.
- **Private windows**: ephemeral session with its own purple theme and a dedicated private new-tab page.
- **Welcome tour**: an animated 8-step introduction shown on first launch (replayable from Settings).
- **Search engines**: Google, Bing, DuckDuckGo, **searchgo!**, or any custom URL.
- **Bookmarks, history, downloads, profiles** and permission prompts for camera, microphone, location and notifications.
- **Chrome extension support (v1)**: runs the *content scripts* of `.zip` / `.crx` extensions.

## Install

Requires a Debian-based system (Ubuntu, Linux Mint, Debian, Pop!_OS, etc.).

```bash
sudo apt install ./supergo-browser_1_8_0_all.deb
```

Then launch **SUPERGO** from your app menu, or run:

```bash
supergo
```

Upgrading from an older version keeps your bookmarks, history and settings.

**Uninstall:**

```bash
sudo apt remove supergo-browser
```

### Dependencies

Installed automatically by `apt`:

`python3 (>= 3.8)`, `python3-gi`, `python3-gi-cairo`, `python3-cairo`, `gir1.2-gtk-3.0`, `gir1.2-webkit2-4.1` (or `4.0`)

Recommended:

| Package | Needed for |
| --- | --- |
| `v2ray` or `xray` | The built-in VPN (xray adds Reality / XHTTP / Vision support) |
| `gstreamer1.0-plugins-good`, `-bad`, `-libav` | Video and audio playback on websites |

```bash
sudo apt install v2ray
```

## Usage

```
supergo [--profile NAME] [--private] [URL...]
```

| Option | Description |
| --- | --- |
| `--profile NAME` | Use a separate profile (own settings, bookmarks, history, cookies) |
| `--private`, `--incognito` | Open a private window |
| `--version` | Print the version |
| `-h`, `--help` | Show help |

## Keyboard shortcuts

| Action | Shortcut |
| --- | --- |
| New tab / close tab | `Ctrl+T` / `Ctrl+W` |
| Reopen closed tab | `Ctrl+Shift+T` |
| Next / previous tab | `Ctrl+Tab` / `Ctrl+Shift+Tab` |
| Focus address bar | `Ctrl+L` |
| Show / hide sidebar | `Ctrl+Shift+L` |
| Back / forward | `Alt+←` / `Alt+→` |
| Reload / hard reload | `F5` or `Ctrl+R` / `Ctrl+Shift+R` |
| Bookmark page | `Ctrl+D` |
| History / downloads | `Ctrl+H` / `Ctrl+J` |
| Settings | `Ctrl+,` |
| New window / private window | `Ctrl+N` / `Ctrl+Shift+P` |
| Zoom in / out / reset | `Ctrl++` / `Ctrl+-` / `Ctrl+0` |
| Print | `Ctrl+P` |
| Fullscreen | `F11` |
| Developer tools | `F12` |

## Private windows

Open one with `Ctrl+Shift+P`, from the menu, or with `supergo --private`.

- Uses an ephemeral WebKit session: no history, cookies, cache or site data are kept, and site permission choices are not stored.
- Has its own purple window theme, a **Private** badge, and a private new-tab page.
- Files you download and bookmarks you add are still kept.
- Websites, your network and your internet provider can still see your activity. Turn on the built-in VPN for more privacy.

## Welcome tour

On the very first launch, SUPERGO opens an animated 8-step tour:

1. Welcome
2. The address pill
3. Tabs in the sidebar
4. Home, bookmarks and history
5. Ad and tracker blocker
6. Browser-only VPN
7. Private windows
8. Ready to browse

Replay it any time: **Settings → Start welcome tour**, or **menu (•••) → Welcome tour**.

## Search engines

Go to **Settings → Quick search engine** and tap an engine to switch instantly, or use the dropdown plus **Save settings**.

| Engine | URL template |
| --- | --- |
| Google (default) | `https://www.google.com/search?q=%s` |
| Bing | `https://www.bing.com/search?q=%s` |
| DuckDuckGo | `https://duckduckgo.com/?q=%s` |
| **searchgo!** | `https://searchgo.base44.app/?q=%s` |
| Custom | Any URL containing `%s` where the query goes |

> **Note:** searchgo! is a single-page app. SUPERGO sends your query as `?q=`. If the site reads a different parameter, change the `searchgo!` entry in the `ENGINES` dictionary in `usr/bin/supergo`.

## VPN

1. Click the **VPN** button in the top bar and tap the orb.
2. Pick **Automatic** (tests the bundled public servers) or **Add your own config**: paste `vless://`, `vmess://`, `trojan://` or `ss://` links, a subscription URL, or a v2ray / xray JSON config.

The bundled public servers are run by strangers and can see anything that is not HTTPS. For real privacy, use your own server.

## Ad blocker

Click the **shield** button in the top bar to turn blocking on or off globally or for just the current site. Filter lists are compiled on first launch (this can take up to a minute) and cached afterwards. Scriptlets, redirects and `removeparam` rules are not supported by WebKit and are skipped.

## Extensions

SUPERGO v1 runs the **content scripts** (JS and CSS, URL matching, `run_at`) of Chrome extensions. Install from **menu → Extensions → Install extension…** (`.zip` or `.crx`). `chrome.*` APIs, popups and background workers are **not** available, and CRX signatures are not verified.

## Files and data

| Location | Contents |
| --- | --- |
| `~/.config/supergo/<profile>/` | Settings, session, bookmarks and history database, extensions |
| `~/.local/share/supergo/<profile>/` | Cookies, favicons, VPN runtime files |
| `~/.cache/supergo/<profile>/` | Compiled filter lists, web cache |

## Project layout

```
DEBIAN/                         package metadata (control, postinst, postrm)
usr/bin/supergo                 the browser (Python / GTK / WebKitGTK)
usr/lib/supergo/v2core.py       v2ray / xray config parsing and core control
usr/share/supergo/filters/      compiled uBlock filter lists
usr/share/supergo/vpn/          bundled public server list
usr/share/applications/         desktop entry
usr/share/icons/hicolor/        app icons
```

## Build the .deb

From the root of this repository (the folder containing `DEBIAN/` and `usr/`):

```bash
chmod 755 usr/bin/supergo DEBIAN/postinst DEBIAN/postrm
dpkg-deb --root-owner-group -Zxz -b . ../supergo-browser_1_8_0_all.deb
```

Run directly from source without installing:

```bash
python3 usr/bin/supergo
```

## Changelog

### 1.8.0
- Private windows now have a custom purple UI, a Private badge and a dedicated private new-tab page.
- New animated 8-step welcome tour, shown on first launch and replayable from Settings or the menu.
- New **searchgo!** search engine with quick-tap buttons in Settings.

## License

MIT. Components: WebKitGTK (LGPL/BSD), GTK (LGPL), PyGObject (LGPL), SQLite (public domain). Filter lists are converted from uBlock Origin / EasyList sources (GPLv3, CC BY-SA 3.0, CC0).
