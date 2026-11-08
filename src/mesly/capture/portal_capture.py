"""
Wayland-compatible live capture via the xdg-desktop-portal ScreenCast API
(the same mechanism OBS uses): the system shows a native window/screen
picker and frames stream over PipeWire.
"""

import random

import numpy as np
from PIL import Image
from PyQt5.QtCore import QThread, pyqtSignal

from ..utils import Logger

try:
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gio
    HAS_GIO = True
except ImportError:
    HAS_GIO = False
try:
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    HAS_GST = True
except ImportError:
    HAS_GST = False

PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"
REQUEST_IFACE = "org.freedesktop.portal.Request"
REQUEST_PATH_FORMAT = "/org/freedesktop/portal/desktop/request/{sender}/{token}"

# SelectSources types bitfield: 1 = monitor, 2 = window
SOURCE_TYPES_WINDOW_OR_MONITOR = 3
# Cursor modes: 0 unspecified, 1 hidden, 2 embedded
CURSOR_MODE_HIDDEN = 1


def portal_available() -> bool:
    """Whether the portal capture stack (PyGObject + GStreamer) is importable."""
    return HAS_GIO and HAS_GST


class PortalCapture(QThread):
    """
    Live capture through the desktop portal: kicks off the native
    window/screen picker dialog, then streams frames from the selected
    source over PipeWire into a GStreamer appsink.
    """

    frame = pyqtSignal(object)  # PIL Image
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self._pipeline = None
        self._pipeline_bus = None

    def stop(self):
        self.running = False

    def run(self):
        if not portal_available():
            self.error.emit(
                "Portal capture unavailable: install PyGObject, GStreamer and the "
                "PipeWire GStreamer plugin (e.g. python-gobject gst-plugin-pipewire)"
            )
            return

        try:
            Gst.init(None)
        except Exception as e:
            self.error.emit(f"GStreamer init failed: {e}")
            return

        try:
            n_frames = self._run_stream()
            Logger.info(f"Portal capture ended ({n_frames} frames)")
        except Exception as e:
            Logger.exception(f"Portal capture failed: {e}")
            self.error.emit(f"Portal capture failed: {e}")
        finally:
            self._teardown()

    def _teardown(self):
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
        if self._pipeline_bus is not None:
            self._pipeline_bus.remove_signal_watch()

    # ------------------------------------------------------------------
    # DBus handshake
    # ------------------------------------------------------------------

    def _call_portal(self, bus, method, signature, values, reply_type=None):
        params = GLib.Variant(signature, values)
        reply = GLib.VariantType(reply_type) if reply_type else None
        return bus.call_sync(
            PORTAL_BUS_NAME, PORTAL_OBJECT_PATH, SCREENCAST_IFACE,
            method, params, reply, Gio.DBusCallFlags.NONE, -1, None
        )

    def _wait_response(self, bus, sender, call_with_token):
        """
        Waits for a portal Response signal for a fresh request.

        Args:
            bus: session DBus connection
            sender: our unique name without the leading ':', dots replaced
            call_with_token: callable(handle_token) that performs the portal
                method call and returns the request path

        Returns:
            (response_code, results_dict), or None if stopped before a
            response arrived.
        """
        token = f"mesly{random.randint(100000, 999999)}"
        request_path = REQUEST_PATH_FORMAT.format(sender=sender, token=token)
        holder = {}
        loop = GLib.MainLoop()

        def on_response(connection, sender_name, object_path, interface_name,
                        signal_name, parameters, user_data):
            code, results = parameters.unpack()
            holder["code"] = code
            holder["results"] = results
            loop.quit()

        subscription = bus.signal_subscribe(
            None, REQUEST_IFACE, "Response", request_path, None,
            Gio.DBusSignalFlags.NONE, on_response, None
        )

        def watch_stop():
            if not self.running:
                loop.quit()
                return False
            return True

        stop_timer = GLib.timeout_add(200, watch_stop)
        try:
            call_with_token(token)
            loop.run()
        finally:
            GLib.source_remove(stop_timer)
            bus.signal_unsubscribe(subscription)

        if "code" not in holder:
            return None
        return holder["code"], holder["results"]

    def _open_session(self):
        """
        Runs the full portal handshake, blocking while the user picks a
        source in the dialog.

        Returns:
            (fd, pipewire_node_id) on success, or (None, error_message).
        """
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception as e:
            return None, f"No session DBus: {e}"

        sender = bus.get_unique_name()[1:].replace(".", "_")

        # 1. CreateSession
        response = self._wait_response(bus, sender, lambda token: self._call_portal(
            bus, "CreateSession", "(a{sv})",
            ({
                "handle_token": GLib.Variant("s", token),
                "session_handle_token": GLib.Variant("s", "mesly_session"),
            },),
            "(o)"
        ))
        if response is None:
            return None, "Cancelled"
        code, results = response
        if code != 0:
            return None, f"CreateSession rejected (code {code})"
        session_path = results.get("session_handle")
        if not session_path:
            return None, "Portal did not return a session handle"
        Logger.info(f"Portal session created: {session_path}")

        # 2. SelectSources (opens the native picker dialog)
        response = self._wait_response(bus, sender, lambda token: self._call_portal(
            bus, "SelectSources", "(oa{sv})",
            (session_path, {
                "handle_token": GLib.Variant("s", token),
                "types": GLib.Variant("u", SOURCE_TYPES_WINDOW_OR_MONITOR),
                "multiple": GLib.Variant("b", False),
                "cursor_mode": GLib.Variant("u", CURSOR_MODE_HIDDEN),
            }),
            "(o)"
        ))
        if response is None:
            return None, "Cancelled"
        code, results = response
        if code != 0:
            return None, "Source selection cancelled or rejected"
        Logger.info("Portal source selected")

        # 3. Start the session
        response = self._wait_response(bus, sender, lambda token: self._call_portal(
            bus, "Start", "(osa{sv})",
            (session_path, "", {
                "handle_token": GLib.Variant("s", token),
            }),
            "(o)"
        ))
        if response is None:
            return None, "Cancelled"
        code, results = response
        if code != 0:
            return None, "Session start rejected by portal"
        streams = results.get("streams")
        if not streams:
            return None, "Portal returned no streams"
        node_id = streams[0][0]
        Logger.info(f"Portal stream ready (PipeWire node {node_id})")

        # 4. OpenPipeWireRemote
        try:
            result = self._call_portal(
                bus, "OpenPipeWireRemote", "(oa{sv})",
                (session_path, {}), "(h)"
            )
            fd = result.unpack()[0]
        except Exception as e:
            return None, f"OpenPipeWireRemote failed: {e}"

        return fd, node_id

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def _run_stream(self):
        handle = self._open_session()
        fd, node_id = handle
        if fd is None:
            # node_id holds the error message on failure
            self.error.emit(node_id)
            return 0

        pipeline = Gst.parse_launch(
            f"pipewiresrc fd={fd} path={node_id} keepalive-time=5 "
            "! video/x-raw "
            "! videoconvert "
            "! video/x-raw,format=RGB "
            "! appsink name=sink emit-signals=true sync=false max-buffers=1 drop=true"
        )
        appsink = pipeline.get_by_name("sink")
        appsink.connect("new-sample", self._on_new_sample)

        self._pipeline_bus = pipeline.get_bus()
        self._pipeline_bus.add_signal_watch()
        self._pipeline_bus.connect("message", self._on_gst_message)

        self._pipeline = pipeline
        pipeline.set_state(Gst.State.PLAYING)
        Logger.info("Portal pipeline playing")

        n_frames = 0
        while self.running:
            self.msleep(100)
        return n_frames

    def _on_new_sample(self, sink):
        """Appsink callback running on a GStreamer streaming thread."""
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.ERROR

        caps = sample.get_caps()
        if caps is None or caps.get_size() == 0:
            return Gst.FlowReturn.ERROR
        structure = caps.get_structure(0)
        width = int(structure.get_value("width"))
        height = int(structure.get_value("height"))

        buffer = sample.get_buffer()
        ok, mapinfo = buffer.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.ERROR

        try:
            array = np.frombuffer(mapinfo.data, dtype=np.uint8)
            image = Image.fromarray(array.reshape(height, width, 3).copy())
            self.frame.emit(image)
        except Exception as e:
            Logger.error(f"Portal frame conversion failed: {e}")
        finally:
            buffer.unmap(mapinfo)

        return Gst.FlowReturn.OK

    def _on_gst_message(self, bus, message):
        if message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            Logger.error(f"Portal pipeline error: {err} ({debug})")
            self.error.emit(f"Stream error: {err}")
            self.running = False
        elif message.type == Gst.MessageType.EOS:
            Logger.info("Portal stream ended")
            self.running = False
