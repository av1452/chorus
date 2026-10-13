"""Harmony Hub local API client.

Hub-based remotes keep their configuration on the hub and expose it over a
local WebSocket on port 8088 -- no cloud account needed. Logitech removed the
old XMPP interface in firmware 4.15.206; this client uses the WebSocket API
that replaced it.

The flow is:

1. ``POST /`` to discover the hub's "remote id" (its own identifier).
2. Open ``ws://<ip>:8088/?domain=svcs.myharmony.com&hubId=<remote id>``.
3. Exchange JSON-RPC-ish messages.

What you can do with it: read the full device and activity configuration,
start and stop activities, and send individual IR commands. That makes it
useful both as a replacement controller and as a way to *export* the codes
from a working hub config into chorus's own format.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..errors import HubError
from .websocket import WebSocket

DEFAULT_PORT = 8088
#: The hub validates Origin but accepts this legacy value.
ORIGIN = "http://sleekxmpp"
ENGINE = "vnd.logitech.harmony/vnd.logitech.harmony.engine"


@dataclass
class HubActivity:
    """An activity defined on the hub."""

    id: str
    label: str
    type: str = ""

    def __str__(self) -> str:
        return f"{self.label} [{self.id}]"


@dataclass
class HubDevice:
    """A device defined on the hub."""

    id: str
    label: str
    manufacturer: str = ""
    model: str = ""
    type: str = ""
    #: Function name -> the opaque action blob the hub wants echoed back.
    commands: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        maker = " ".join(x for x in (self.manufacturer, self.model) if x)
        return f"{self.label} ({maker or self.type}) [{self.id}]"


class HarmonyHub:
    """A connection to one Harmony Hub."""

    def __init__(self, address: str, *, port: int = DEFAULT_PORT, timeout: float = 10.0):
        self.address = address
        self.port = port
        self.timeout = timeout
        self._remote_id: str | None = None
        self._ws: WebSocket | None = None
        self._config: dict[str, Any] | None = None

    # -- connection -------------------------------------------------------

    @property
    def remote_id(self) -> str:
        """The hub's own identifier, fetched over plain HTTP."""
        if self._remote_id is None:
            self._remote_id = self._fetch_remote_id()
        return self._remote_id

    def _fetch_remote_id(self) -> str:
        url = f"http://{self.address}:{self.port}/"
        body = json.dumps(
            {
                "id": 1,
                "cmd": "setup.account?getProvisionInfo",
                "params": {},
            }
        ).encode()
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Origin": ORIGIN,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Charset": "utf-8",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode())
        except urllib.error.URLError as exc:
            raise HubError(
                f"could not reach a Harmony Hub at {self.address}:{self.port} "
                f"({exc.reason}). Check the IP address, and that the hub is "
                "powered and on this network."
            ) from exc
        except json.JSONDecodeError as exc:
            raise HubError(
                f"{self.address} answered but not with JSON -- is it really a "
                "Harmony Hub?"
            ) from exc

        data = payload.get("data") or {}
        remote_id = data.get("activeRemoteId") or data.get("remoteId")
        if not remote_id:
            raise HubError(
                f"hub at {self.address} did not report a remote id; response "
                f"was {payload!r}"
            )
        return str(remote_id)

    def connect(self) -> HarmonyHub:
        """Open the WebSocket. Safe to call more than once."""
        if self._ws is not None:
            return self
        url = (
            f"ws://{self.address}:{self.port}/?domain=svcs.myharmony.com"
            f"&hubId={self.remote_id}"
        )
        self._ws = WebSocket(url, origin=ORIGIN, timeout=self.timeout)
        return self

    def close(self) -> None:
        if self._ws is not None:
            self._ws.close()
            self._ws = None

    def __enter__(self) -> HarmonyHub:
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    # -- messaging --------------------------------------------------------

    def _call(
        self,
        command: str,
        params: dict[str, Any] | None = None,
        *,
        expect_reply: bool = True,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        self.connect()
        assert self._ws is not None

        message_id = str(uuid.uuid4())
        envelope = {
            "hubId": self.remote_id,
            "timeout": 60,
            "hbus": {
                "cmd": command,
                "id": message_id,
                "params": params or {"verb": "get", "format": "json"},
            },
        }
        self._ws.send(json.dumps(envelope))

        if not expect_reply:
            return {}

        deadline = time.monotonic() + (timeout or self.timeout * 3)
        while time.monotonic() < deadline:
            raw = self._ws.recv(timeout=max(1.0, deadline - time.monotonic()))
            if raw is None:
                raise HubError("hub closed the connection")
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            # The hub emits unsolicited state notifications; ignore anything
            # that is not the reply we are waiting for.
            if message.get("id") not in (message_id, None):
                continue
            if message.get("cmd") and message.get("id") != message_id:
                continue
            if "data" in message or message.get("id") == message_id:
                return message
        raise HubError(f"hub did not answer {command!r} in time")

    # -- configuration ----------------------------------------------------

    def config(self, *, refresh: bool = False) -> dict[str, Any]:
        """Fetch the hub's full configuration."""
        if self._config is None or refresh:
            reply = self._call(f"{ENGINE}?config")
            data = reply.get("data")
            if not isinstance(data, dict):
                raise HubError(f"unexpected config reply: {reply!r}")
            self._config = data
        return self._config

    def activities(self) -> list[HubActivity]:
        """List the activities defined on the hub."""
        out = []
        for raw in self.config().get("activity", []) or []:
            out.append(
                HubActivity(
                    id=str(raw.get("id", "")),
                    label=raw.get("label") or raw.get("name") or "",
                    type=raw.get("type", ""),
                )
            )
        return out

    def devices(self) -> list[HubDevice]:
        """List the devices defined on the hub, with their IR command names."""
        out = []
        for raw in self.config().get("device", []) or []:
            device = HubDevice(
                id=str(raw.get("id", "")),
                label=raw.get("label") or "",
                manufacturer=raw.get("manufacturer", ""),
                model=raw.get("model", ""),
                type=raw.get("type", ""),
            )
            for group in raw.get("controlGroup", []) or []:
                for function in group.get("function", []) or []:
                    name = function.get("name")
                    action = function.get("action")
                    if name and action:
                        device.commands[name] = action
            out.append(device)
        return out

    def current_activity(self) -> str:
        """The id of the running activity, or ``"-1"`` when off."""
        reply = self._call(f"{ENGINE}?getCurrentActivity")
        return str((reply.get("data") or {}).get("result", "-1"))

    # -- control ----------------------------------------------------------

    def start_activity(self, activity_id: str) -> None:
        """Start an activity by id."""
        self._call(
            "harmony.activityengine?runactivity",
            {
                "async": "true",
                "timestamp": 0,
                "args": {"rule": "start"},
                "activityId": str(activity_id),
            },
            expect_reply=False,
        )

    def power_off(self) -> None:
        """Stop whatever activity is running."""
        self.start_activity("-1")

    def send_command(
        self,
        device_id: str,
        command: str,
        *,
        hold_ms: int = 0,
    ) -> None:
        """Send one IR command through the hub.

        ``hold_ms`` emulates holding the button, which some devices need for
        volume ramps.
        """
        action = json.dumps(
            {"command": command, "type": "IRCommand", "deviceId": str(device_id)}
        )
        self._call(
            f"{ENGINE}?holdAction",
            {
                "status": "press",
                "timestamp": "0",
                "verb": "render",
                "action": action,
            },
            expect_reply=False,
        )
        if hold_ms > 0:
            time.sleep(hold_ms / 1000)
        self._call(
            f"{ENGINE}?holdAction",
            {
                "status": "release",
                "timestamp": str(hold_ms),
                "verb": "render",
                "action": action,
            },
            expect_reply=False,
        )

    # -- export -----------------------------------------------------------

    def to_config(self, name: str = "Imported from Hub"):
        """Convert the hub's configuration into a :class:`RemoteConfig`.

        The hub exposes *command names*, not IR waveforms -- the codes stay
        inside the hub. So the exported config has the full device and
        activity structure with empty function waveforms, which you then fill
        in by learning or importing. That is still most of the tedious work
        done for you.
        """
        from ..config.model import (
            Activity,
            Device,
            DeviceType,
            Function,
            RemoteConfig,
            Step,
        )

        type_map = {
            "Television": DeviceType.TELEVISION,
            "AVReceiver": DeviceType.AV_RECEIVER,
            "StereoReceiver": DeviceType.AV_RECEIVER,
            "SoundBar": DeviceType.SOUNDBAR,
            "Cable": DeviceType.CABLE_SATELLITE,
            "Satellite": DeviceType.CABLE_SATELLITE,
            "Pvr": DeviceType.CABLE_SATELLITE,
            "BlurayDvd": DeviceType.BLURAY_DVD,
            "DvdPlayer": DeviceType.BLURAY_DVD,
            "GameConsole": DeviceType.GAME_CONSOLE,
            "Projector": DeviceType.PROJECTOR,
            "Amplifier": DeviceType.AMPLIFIER,
        }

        config = RemoteConfig(name=name, remote_model="Harmony Hub")
        raw_config = self.config()

        for raw in raw_config.get("device", []) or []:
            device = Device(
                name=raw.get("label") or f"device-{raw.get('id')}",
                manufacturer=raw.get("manufacturer", ""),
                model=raw.get("model", ""),
                type=type_map.get(raw.get("type", ""), DeviceType.OTHER),
            )
            for group in raw.get("controlGroup", []) or []:
                for function in group.get("function", []) or []:
                    fname = function.get("name")
                    if not fname:
                        continue
                    device.functions[fname] = Function(
                        name=fname,
                        label=function.get("label", ""),
                        durations=(),
                        source="hub (waveform not available)",
                    )
            if device.name not in config.devices:
                config.devices[device.name] = device

        by_id = {
            str(raw.get("id")): (raw.get("label") or "")
            for raw in raw_config.get("device", []) or []
        }

        for raw in raw_config.get("activity", []) or []:
            label = raw.get("label") or raw.get("id")
            if str(raw.get("id")) == "-1":
                continue
            activity = Activity(name=str(label), label=str(label))
            for fix in raw.get("fixit", {}).values() if isinstance(raw.get("fixit"), dict) else []:
                device_name = by_id.get(str(fix.get("id", "")), "")
                if not device_name:
                    continue
                if fix.get("Power") == "On":
                    activity.start_sequence.append(
                        Step(device_name, "PowerOn", 2000)
                    )
                if fix.get("Input"):
                    activity.start_sequence.append(
                        Step(device_name, str(fix["Input"]), 500)
                    )
            if activity.name not in config.activities:
                config.activities[activity.name] = activity

        return config
