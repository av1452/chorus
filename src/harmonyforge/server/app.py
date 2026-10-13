"""A local web interface -- the part that stands in for MyHarmony's GUI.

Deliberately built on ``http.server`` so that running the editor needs no
dependencies beyond the standard library. It binds to localhost by default;
there is no authentication, so do not expose it to a network.
"""

from __future__ import annotations

import json
import logging
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .. import __version__
from ..config.model import (
    Activity,
    Device,
    DeviceType,
    Function,
    PowerStyle,
    RemoteConfig,
    Step,
)
from ..errors import HarmonyForgeError
from ..ir import pronto, protocols
from ..ir.database import CodeLibrary

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}


class AppState:
    """Shared, mutable state behind the HTTP handlers."""

    def __init__(self, config_path: str | None, library_path: str | None):
        self.lock = threading.Lock()
        self.config_path = Path(config_path) if config_path else None
        self.library = CodeLibrary(library_path)
        if self.config_path and self.config_path.exists():
            self.config = RemoteConfig.load(self.config_path)
        else:
            self.config = RemoteConfig(name="My Harmony")

    def save(self) -> str | None:
        if self.config_path is None:
            return None
        self.config.save(self.config_path)
        return str(self.config_path)


class Handler(BaseHTTPRequestHandler):
    server_version = f"harmonyforge/{__version__}"
    state: AppState

    # -- plumbing ---------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HarmonyForgeError(
                f"request body is not valid JSON: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise HarmonyForgeError("request body must be a JSON object")
        return data

    def _serve_static(self, path: str) -> None:
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC_DIR / name).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._send_error_json("not found", 404)
            return
        if not target.is_file():
            self._send_error_json("not found", 404)
            return

        body = target.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type",
            CONTENT_TYPES.get(target.suffix, "application/octet-stream"),
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- routing ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if not route.startswith("/api/"):
            self._serve_static(route)
            return

        try:
            if route == "/api/status":
                self._send_json(self._status())
            elif route == "/api/config":
                self._send_json(self.state.config.to_dict())
            elif route == "/api/config/validate":
                self._send_json({"warnings": self.state.config.validate()})
            elif route == "/api/codes":
                self._send_json(self._codes(query.get("q", [""])[0]))
            elif route == "/api/codes/detail":
                self._send_json(self._code_detail(query.get("slug", [""])[0]))
            elif route == "/api/models":
                self._send_json(self._models(query.get("q", [""])[0]))
            elif route == "/api/meta":
                self._send_json(self._meta())
            else:
                self._send_error_json("unknown endpoint", 404)
        except HarmonyForgeError as exc:
            self._send_error_json(str(exc))
        except Exception as exc:  # pragma: no cover
            log.exception("GET %s failed", route)
            self._send_error_json(f"internal error: {exc}", 500)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            body = self._read_json()
            if route == "/api/config":
                self._send_json(self._save_config(body))
            elif route == "/api/device":
                self._send_json(self._upsert_device(body))
            elif route == "/api/device/delete":
                self._send_json(self._delete_device(body))
            elif route == "/api/activity":
                self._send_json(self._upsert_activity(body))
            elif route == "/api/activity/delete":
                self._send_json(self._delete_activity(body))
            elif route == "/api/device/import-codes":
                self._send_json(self._import_codes(body))
            elif route == "/api/pronto/decode":
                self._send_json(self._decode_pronto(body))
            elif route == "/api/function":
                self._send_json(self._add_function(body))
            elif route == "/api/learn":
                self._send_json(self._learn(body))
            elif route == "/api/backup":
                self._send_json(self._backup(body))
            else:
                self._send_error_json("unknown endpoint", 404)
        except HarmonyForgeError as exc:
            self._send_error_json(str(exc))
        except Exception as exc:  # pragma: no cover
            log.exception("POST %s failed", route)
            self._send_error_json(f"internal error: {exc}", 500)

    # -- endpoint implementations ----------------------------------------

    def _meta(self) -> dict:
        return {
            "version": __version__,
            "device_types": [t.value for t in DeviceType],
            "power_styles": [s.value for s in PowerStyle],
            "protocols": sorted({p.name for p in protocols.PROTOCOLS}),
            "config_path": str(self.state.config_path or ""),
            "library_path": str(self.state.library.root),
            "buttons": COMMON_BUTTONS,
        }

    def _status(self) -> dict:
        """Report whether a remote is attached, without claiming it."""
        try:
            from ..usb.transport import enumerate_remotes

            found = enumerate_remotes()
        except Exception as exc:
            return {"available": False, "reason": str(exc), "remotes": []}

        return {
            "available": bool(found),
            "remotes": [
                {
                    "vendor_id": f"{info.vendor_id:04x}",
                    "product_id": f"{info.product_id:04x}",
                    "label": str(info),
                    "usbnet": info.is_usbnet,
                }
                for info in found
            ],
        }

    def _codes(self, query: str) -> dict:
        sets = (
            self.state.library.search(query) if query else list(self.state.library)
        )
        return {
            "root": str(self.state.library.root),
            "sets": [
                {
                    "slug": c.slug,
                    "label": c.label,
                    "manufacturer": c.manufacturer,
                    "model": c.model,
                    "device_type": c.device_type,
                    "source": c.source,
                    "function_count": len(c.functions),
                    "functions": sorted(c.functions),
                }
                for c in sets
            ],
        }

    def _code_detail(self, slug: str) -> dict:
        if not slug:
            raise HarmonyForgeError("slug is required")
        code_set = self.state.library.find(slug)
        return {
            "slug": code_set.slug,
            "label": code_set.label,
            "functions": {
                name: {
                    "frequency": signal.frequency,
                    "durations": list(signal.durations),
                    "pronto": pronto.format_signal(signal),
                    "protocol": (
                        str(protocols.identify(signal) or "unrecognised")
                    ),
                }
                for name, signal in sorted(code_set.functions.items())
            },
        }

    def _models(self, query: str) -> dict:
        from .. import devicedb

        hits = (
            devicedb.search_models(query)
            if query
            else [(i, m) for i, m in enumerate(devicedb.MODELS) if m.known]
        )
        return {
            "models": [
                {
                    "skin": skin,
                    "name": model.name,
                    "manufacturer": model.manufacturer,
                }
                for skin, model in hits
            ]
        }

    def _save_config(self, body: dict) -> dict:
        with self.state.lock:
            self.state.config = RemoteConfig.from_dict(body)
            path = self.state.save()
        return {"saved": bool(path), "path": path or ""}

    def _upsert_device(self, body: dict) -> dict:
        name = (body.get("name") or "").strip()
        if not name:
            raise HarmonyForgeError("a device needs a name")

        with self.state.lock:
            config = self.state.config
            original = (body.get("original_name") or name).strip()
            existing = config.devices.pop(original, None)

            device = Device(
                name=name,
                manufacturer=body.get("manufacturer", ""),
                model=body.get("model", ""),
                type=DeviceType(body.get("type", "other")),
                power_style=PowerStyle(body.get("power_style", "toggle")),
                inputs=list(body.get("inputs") or []),
                power_on_delay_ms=int(body.get("power_on_delay_ms", 2000)),
                inter_command_delay_ms=int(
                    body.get("inter_command_delay_ms", 100)
                ),
                repeat_count=int(body.get("repeat_count", 1)),
                notes=body.get("notes", ""),
            )
            if existing is not None:
                device.functions = existing.functions
            config.devices[name] = device

            # Keep activity references pointing at the renamed device.
            if original != name:
                for activity in config.activities.values():
                    for step in (
                        activity.start_sequence + activity.stop_sequence
                    ):
                        if step.device == original:
                            step.device = name
                    activity.buttons = {
                        button: (
                            f"{name}/{target.split('/', 1)[1]}"
                            if target.split("/", 1)[0] == original
                            else target
                        )
                        for button, target in activity.buttons.items()
                    }
                    for attr in (
                        "volume_device",
                        "channel_device",
                        "primary_device",
                    ):
                        if getattr(activity, attr) == original:
                            setattr(activity, attr, name)
            path = self.state.save()
        return {"device": name, "saved": bool(path)}

    def _delete_device(self, body: dict) -> dict:
        name = body.get("name") or ""
        with self.state.lock:
            if name not in self.state.config.devices:
                raise HarmonyForgeError(f"no device named {name!r}")
            del self.state.config.devices[name]
            path = self.state.save()
        return {"deleted": name, "saved": bool(path)}

    def _upsert_activity(self, body: dict) -> dict:
        name = (body.get("name") or "").strip()
        if not name:
            raise HarmonyForgeError("an activity needs a name")
        with self.state.lock:
            config = self.state.config
            original = (body.get("original_name") or name).strip()
            config.activities.pop(original, None)
            activity = Activity(
                name=name,
                label=body.get("label", ""),
                icon=body.get("icon", ""),
                volume_device=body.get("volume_device", ""),
                channel_device=body.get("channel_device", ""),
                primary_device=body.get("primary_device", ""),
                buttons=dict(body.get("buttons") or {}),
                start_sequence=[
                    Step(
                        device=s.get("device", ""),
                        function=s.get("function", ""),
                        delay_ms=int(s.get("delay_ms", 500)),
                        repeat=int(s.get("repeat", 1)),
                    )
                    for s in (body.get("start_sequence") or [])
                ],
                stop_sequence=[
                    Step(
                        device=s.get("device", ""),
                        function=s.get("function", ""),
                        delay_ms=int(s.get("delay_ms", 500)),
                        repeat=int(s.get("repeat", 1)),
                    )
                    for s in (body.get("stop_sequence") or [])
                ],
            )
            config.activities[name] = activity
            path = self.state.save()
        return {"activity": name, "saved": bool(path)}

    def _delete_activity(self, body: dict) -> dict:
        name = body.get("name") or ""
        with self.state.lock:
            if name not in self.state.config.activities:
                raise HarmonyForgeError(f"no activity named {name!r}")
            del self.state.config.activities[name]
            path = self.state.save()
        return {"deleted": name, "saved": bool(path)}

    def _import_codes(self, body: dict) -> dict:
        device_name = body.get("device") or ""
        slug = body.get("slug") or ""
        wanted = body.get("functions")
        with self.state.lock:
            device = self.state.config.device(device_name)
            code_set = self.state.library.find(slug)
            names = wanted if wanted else sorted(code_set.functions)
            added = 0
            for name in names:
                if name not in code_set.functions:
                    continue
                device.add(
                    Function.from_signal(
                        name,
                        code_set.functions[name],
                        source=code_set.source or "library",
                    )
                )
                added += 1
            path = self.state.save()
        return {"added": added, "device": device_name, "saved": bool(path)}

    def _add_function(self, body: dict) -> dict:
        device_name = body.get("device") or ""
        name = (body.get("name") or "").strip()
        if not name:
            raise HarmonyForgeError("a function needs a name")

        with self.state.lock:
            device = self.state.config.device(device_name)
            if body.get("pronto"):
                function = Function.from_pronto(name, body["pronto"])
            elif body.get("protocol"):
                fields = {
                    key: int(value)
                    for key, value in (body.get("fields") or {}).items()
                }
                signal = protocols.encode(body["protocol"], **fields)
                function = Function.from_signal(
                    name, signal, source=f"synthesised:{body['protocol']}"
                )
            else:
                raise HarmonyForgeError(
                    "provide either a Pronto code or a protocol plus fields"
                )
            device.add(function)
            path = self.state.save()
        return {
            "device": device_name,
            "function": name,
            "protocol": function.protocol,
            "saved": bool(path),
        }

    def _decode_pronto(self, body: dict) -> dict:
        code = body.get("code") or ""
        signal = pronto.parse(code)
        decoded = protocols.identify(signal)
        return {
            "frequency": signal.frequency,
            "duration_count": len(signal.durations),
            "total_ms": round(signal.total_us / 1000, 2),
            "protocol": decoded.protocol if decoded else "",
            "fields": decoded.fields if decoded else {},
        }

    def _learn(self, body: dict) -> dict:
        """Learn one code from the attached remote and store it."""
        from ..usb.remote import HarmonyRemote
        from ..usb.transport import open_remote

        name = (body.get("name") or "").strip()
        device_name = body.get("device") or ""
        if not name:
            raise HarmonyForgeError("a function name is required")

        with open_remote() as transport:
            remote = HarmonyRemote(transport)
            remote.identify()
            signal = remote.learn_ir().snapped()

        decoded = protocols.identify(signal)
        with self.state.lock:
            if device_name:
                device = self.state.config.device(device_name)
                device.add(
                    Function.from_signal(name, signal, source="learned")
                )
                self.state.save()
        return {
            "name": name,
            "device": device_name,
            "frequency": signal.frequency,
            "duration_count": len(signal.durations),
            "protocol": decoded.protocol if decoded else "",
            "fields": decoded.fields if decoded else {},
            "pronto": pronto.format_signal(signal),
        }

    def _backup(self, body: dict) -> dict:
        from ..usb.remote import HarmonyRemote
        from ..usb.transport import open_remote

        target = Path(body.get("path") or "harmony-backup.bin")
        with open_remote() as transport:
            remote = HarmonyRemote(transport)
            identity = remote.identify()
            blob = remote.read_config()
        target.write_bytes(blob)
        return {
            "path": str(target),
            "bytes": len(blob),
            "model": identity.name,
        }


#: Button names the Harmony hard keys usually carry, offered in the editor.
COMMON_BUTTONS = [
    "PowerToggle", "PowerOn", "PowerOff",
    "VolumeUp", "VolumeDown", "Mute",
    "ChannelUp", "ChannelDown", "PrevChannel",
    "DirectionUp", "DirectionDown", "DirectionLeft", "DirectionRight",
    "OK", "Menu", "Exit", "Back", "Info", "Guide", "Home",
    "Play", "Pause", "Stop", "Rewind", "FastForward", "Record",
    "SkipBack", "SkipForward",
    "Red", "Green", "Yellow", "Blue",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "Input", "Aspect", "Subtitle", "Audio",
]


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8737,
    config_path: str | None = None,
    library_path: str | None = None,
    open_browser: bool = True,
) -> None:
    """Run the web interface until interrupted."""
    state = AppState(config_path, library_path)

    handler = type("BoundHandler", (Handler,), {"state": state})
    httpd = ThreadingHTTPServer((host, port), handler)

    if open_browser:
        threading.Timer(
            0.6, lambda: webbrowser.open(f"http://{host}:{port}")
        ).start()

    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
