# The Harmony Hub local API

Hub-based remotes keep their configuration on the hub, and the hub exposes a
local API — so unlike the USB remotes, these were never truly dependent on
the cloud once set up. No Logitech account is needed.

Applies to: Harmony Hub, Elite, Companion, Ultimate, Ultimate One, Smart
Control. Requires firmware 4.15.206 or newer, which is the release that
replaced the old XMPP interface (port 5222) with the WebSocket one.

## Discovery

The hub answers SSDP searches for `urn:myharmony-com:device:harmony:1`:

```bash
chorus hub discover
```

```python
from chorus.hub.discovery import discover

for hub in discover(timeout=4.0):
    print(hub.address, hub.friendly_name)
```

Discovery fails on networks with client isolation and across VLANs, because
SSDP is multicast. That is not a bug in the hub — just pass the IP directly.

## Connecting

Two steps. First, a plain HTTP POST to learn the hub's own identifier:

```http
POST / HTTP/1.1
Host: <hub-ip>:8088
Origin: http://sleekxmpp
Content-Type: application/json

{"id": 1, "cmd": "setup.account?getProvisionInfo", "params": {}}
```

The reply carries `data.activeRemoteId`. Then open a WebSocket:

```
ws://<hub-ip>:8088/?domain=svcs.myharmony.com&hubId=<activeRemoteId>
```

The `Origin: http://sleekxmpp` header is checked. It is a legacy value from
the XMPP days, and the hub still expects it.

```python
from chorus.hub.client import HarmonyHub

with HarmonyHub("192.168.1.50") as hub:
    print(hub.remote_id)
```

## Message shape

Every request is JSON wrapped in an envelope:

```json
{
  "hubId": "<remote id>",
  "timeout": 60,
  "hbus": {
    "cmd": "<command>",
    "id": "<your correlation id>",
    "params": { }
  }
}
```

The hub also pushes unsolicited state notifications down the same socket, so
a client has to correlate replies by `id` and ignore the rest. Chorus
does this in `HarmonyHub._call`.

`vnd.logitech.harmony/vnd.logitech.harmony.engine` appears so often it is
abbreviated `ENGINE` below.

| Purpose | Command | Params |
|---|---|---|
| Full configuration | `ENGINE?config` | `{"verb": "get", "format": "json"}` |
| Current activity | `ENGINE?getCurrentActivity` | as above |
| Start activity | `harmony.activityengine?runactivity` | `{"activityId": "<id>", "async": "true", "args": {"rule": "start"}}` |
| Send a command | `ENGINE?holdAction` | see below |

### Sending a command

`holdAction` is sent twice — once to press, once to release:

```json
{
  "status": "press",
  "timestamp": "0",
  "verb": "render",
  "action": "{\"command\":\"VolumeUp\",\"type\":\"IRCommand\",\"deviceId\":\"12345\"}"
}
```

Note that `action` is a JSON *string* containing JSON, not a nested object.
The hub rejects it otherwise.

Press then immediately release is a tap. Hold the gap open and the device
sees a held key, which is what volume ramps need:

```bash
chorus hub -a 192.168.1.50 send 12345 VolumeUp --hold 400
```

### Powering everything off

"Off" is just activity `-1`:

```bash
chorus hub -a 192.168.1.50 off
```

## Reading the configuration

```bash
chorus hub -a 192.168.1.50 activities
chorus hub -a 192.168.1.50 devices --verbose
```

```python
with HarmonyHub("192.168.1.50") as hub:
    for device in hub.devices():
        print(device)
        print("  ", ", ".join(sorted(device.commands)))
```

## Exporting to Chorus

```bash
chorus hub -a 192.168.1.50 export -o hub-config.json
```

This pulls the hub's device and activity structure into Chorus's own
format.

**One important limitation:** the hub exposes command *names*, not IR
waveforms. The codes stay inside the hub. So the exported configuration has
the full structure — every device, every activity, every command name — with
empty waveforms you then fill in by learning or importing. That is still most
of the tedious work done, and it means a working hub config can seed a USB
remote config.

## Why this still works

The hub's API was always local; the cloud was only ever used for the
configuration *editor* and the device database. Shutting the cloud down
removed the ability to change a hub's configuration through Logitech's tools,
but not the ability to read or drive the configuration already on it.

That is also why `hub export` is worth running even if you do not plan to use
Chorus to control things: it gets your configuration out of a device
whose vendor has stopped supporting it, into a file you keep.
