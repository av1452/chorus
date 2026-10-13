# Chorus (harmonyforge web app)

The in-browser part of [harmonyforge](../README.md): set up devices, activities and buttons,
and read newer remotes and hubs over USB, with nothing to install.

**Use it now:** https://av1452.github.io/harmonyforge/

## What it does

- **Devices**: list the TVs, receivers, streaming boxes and other things you control, each with its commands.
- **Activities**: build activities like "Watch TV" that power on the right devices and switch inputs.
- **Buttons**: choose what every button sends during each activity, with automatic suggestions
  based on which device handles volume and which handles playback.
- **USB remote**: plug a supported remote or hub in over USB and read its model, firmware
  version and serial number. A live packet log shows the raw traffic.
- **Setup file**: download and open your setup as a JSON file in the **same format as the
  harmonyforge command-line tool**, so you can plan in the browser and add IR codes with the CLI
  (or the other way round). It also runs the same checks as `harmonyforge config validate`.
- Works offline and can be installed as an app.

## What it doesn't do (yet)

- **Write a configuration to the remote.** The original software built the remote's
  configuration on the vendor's servers from their device and IR-code database. Chorus doesn't
  have that database, so syncing a remote isn't possible yet.
- Talk to older USB remotes (650, 665, 700, One, 880 and similar). Those use a different protocol
  that the [harmonyforge Python tool](../README.md) already supports, including backup and
  IR learning. They're marked "use Python tool" on the USB remote screen.

See [docs/protocol-packet-hid.md](../docs/protocol-packet-hid.md) for what is known about the USB protocol and how it was worked out.

---

## How to use it

You don't need to download or install anything. Open the link and start using it:

**https://av1452.github.io/harmonyforge/**

### Which browser?

| Browser | Setup screens | USB remote screen |
|---|---|---|
| Chrome or Edge on Windows, Mac, Linux or ChromeOS | ✅ | ✅ |
| Chrome on Android | ✅ | ❌ |
| Firefox, Safari, any iPhone/iPad browser | ✅ | ❌ (no WebHID support) |

### Install it as an app (optional)

In Chrome or Edge, open the link, then click the install icon at the right end of the address
bar (a monitor with a down arrow), or open the **⋮** menu → **Cast, save and share** →
**Install page as app**. It then opens in its own window and works offline.

### First-time walkthrough

1. **Devices** → **Add device**. Give it a name (for example "Living room TV") and pick its type.
   Choose how its power works: separate **Power On / Power Off** buttons are the most reliable.
   Leave **Commands** empty to start with common commands for that type, or type your own
   (one per line). Repeat for each device.
2. **Activities** → **Add activity**. Name it ("Watch TV"), tick the devices it uses, choose
   each device's input, and pick which device controls volume, channels, and menus/playback.
   The card then lists the start-up and turn-off steps.
3. **Buttons** → choose an activity, click a button on the on-screen remote, and choose what
   it sends. **Fill in suggestions** maps the obvious ones for you.
4. **Setup file** → **Download setup file** saves it as JSON. Your setup lives only in this
   browser, so download it if you clear your browser data or switch computers.

Commands start as names only. To give them real IR codes, use the command-line tool on the
downloaded file (`harmonyforge learn` to learn from your old remote, or `harmonyforge codes`
to import a database), then open the file here again with **Open setup file**.

### Reading a remote over USB

1. Use Chrome or Edge on a computer.
2. Connect the remote or hub with a **data** USB cable. Some cables only charge; if nothing
   shows up, try another cable.
3. Close any other program that might be using the remote, such as the old desktop software.
4. Go to **USB remote** → **Connect remote**. The browser lists matching devices. Pick yours and click **Connect**.
5. Click **Read remote info**.

If the list is empty, the remote isn't a model Chorus knows, or the cable or port isn't
passing data. On Linux you may also need a udev rule that gives your user access to the device.

---

## Running it on your own computer (optional)

Only do this if you want to change the code. Otherwise use the link above.

### 1. Install the tools (once)

- **Node.js**: download the **LTS** version from https://nodejs.org and install it with the
  default options. To check it worked, open a *new* terminal and run `node --version`. It
  should print something like `v22.x.x`.
- **Git** (optional): https://git-scm.com. You can download a ZIP instead (see below).

### 2. Get the code

**With Git:**

```bash
git clone https://github.com/av1452/harmonyforge.git
```

```bash
cd harmonyforge/web
```

**Without Git:** on the [repository page](https://github.com/av1452/harmonyforge), click the
green **Code** button → **Download ZIP**. Right-click the ZIP → **Extract All**, then open the
`web` folder inside the extracted `harmonyforge-main` folder.

### 3. Start it

**Windows, easiest:** double-click **`start.cmd`** in the `web` folder. A black window opens
and your browser opens the app. Leave the black window open while you use the app; close it
to stop.

**Any system, from a terminal in the `web` folder:**

```bash
node serve.mjs
```

The app opens at **http://localhost:8080**. Press **Ctrl+C** in the terminal to stop it.

> Open the app through `http://localhost:8080`. Double-clicking `index.html` won't work: browsers
> block the app's code on `file://` pages, so you'll only see a "Chorus didn't start" message.

### Run the tests

```bash
node --test "test/*.test.js"
```

(`npm test` does the same thing.)

### Troubleshooting

| What you see | What to do |
|---|---|
| `'node' is not recognized…` / `command not found: node` | Node.js isn't installed, or the terminal was opened before you installed it. Install it, then open a **new** terminal. |
| `npm : File …\npm.ps1 cannot be loaded because running scripts is disabled` | That's a PowerShell setting. Use `node serve.mjs` instead of `npm start`, or type `npm.cmd start`. |
| `Cannot find module …serve.mjs` or `ENOENT … package.json` | The terminal isn't in the `web` folder. `cd` into the folder that contains `index.html` and try again. |
| `Port 8080 is already in use` | Something else is using that port. Run `node serve.mjs 8081` and open http://localhost:8081. |
| Blank page or "Chorus didn't start" | Make sure the address starts with `http://localhost`, not `file://`. |
| Old version still showing after an update | Press **Ctrl+Shift+R** to reload without the cache. |
| USB remote screen says the browser can't talk to USB devices | Use Chrome or Edge on a computer, opened at `localhost` or the `https://` link. |

## Deploy your own copy

The `Web app` GitHub Actions workflow (`.github/workflows/web.yml`) runs these tests and
publishes this folder to GitHub Pages whenever `web/` changes on `main`. In a fork, go to **Settings → Pages** and set **Source** to **GitHub Actions**.

## Legal

harmonyforge and Chorus are not affiliated with or endorsed by Logitech. "Harmony" is a trademark of its owner
and is used here only to describe compatibility. This repository contains no code, data files
or artwork from the original software; protocol details were documented from the publicly
available application for interoperability.

## License

GPL-3.0-or-later, like the rest of harmonyforge. See [LICENSE](../LICENSE).
