# Chorus

A browser app for setting up universal remotes. It's an independent, open-source take on the
discontinued desktop setup software for USB universal remotes, and it runs entirely in your
browser with nothing to install.

## What it does

- **Devices**: list the TVs, receivers, streaming boxes and other things you control, each with its commands.
- **Activities**: build activities like "Watch TV" that power on the right devices and switch inputs.
- **Buttons**: choose what every button sends during each activity, with automatic suggestions
  based on which device handles volume and which handles playback.
- **USB remote**: plug a supported remote or hub in over USB and read its model, firmware
  version and serial number (Chrome or Edge, via WebHID). A live packet log shows the raw traffic.
- **Backup**: export and import your setup as JSON. Everything is stored locally in your browser.
- Works offline and can be installed as an app (PWA).

## What it doesn't do (yet)

- **Write a configuration to the remote.** The original software compiled the remote's
  configuration on the vendor's servers from their device and IR-code database. Chorus doesn't
  have that database, so syncing a remote isn't possible yet.
- Talk to older remotes that use the earlier per-model USB protocol (they're marked "not yet"
  on the USB remote screen).

See [docs/PROTOCOL.md](docs/PROTOCOL.md) for what is known about the USB protocol and how it was worked out.

## Run it

Any static file server works. WebHID needs HTTPS or `localhost`.

```bash
npm start
```

Then open http://localhost:8080.

## Test

```bash
npm test
```

## Deploy

The included GitHub Actions workflow runs the tests and publishes the app to GitHub Pages
on every push to `main`. Turn on Pages in the repository settings with **Source: GitHub Actions**.

## Legal

Chorus is not affiliated with or endorsed by Logitech. "Harmony" is a trademark of its owner
and is used here only to describe compatibility. This repository contains no code, data files
or artwork from the original software; protocol details were documented from the publicly
available application for interoperability.

## License

MIT
