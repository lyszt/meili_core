"""
Standalone portal screencast worker.

Runs as its own process (spawned by PortalCapture). Mirrors the empirically
winning standalone-experiment architecture:

    portal_worker (this process): DBus handshake + serial resolution
        -> spawns streamer subprocess with pass_fds(fd)
    streamer subprocess: GStreamer pipeline + JPEG frames on stdout

Protocol on stdout (relayed from the streamer):
    "MESLY READY <width>x<height>\\n"          stream verified and starting
    MESLYF + 4-byte big-endian length + JPEG   one frame
    "MESLY ERR <message>\\n"                   fatal error, worker exits
"""

import fcntl
import json
import os
import random
import subprocess
import sys
import time

import gi
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gio, Gst

REFUSE_MAX_WIDTH = 640
REFUSE_MAX_HEIGHT = 480

PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"
REQUEST_IFACE = "org.freedesktop.portal.Request"
REQUEST_PATH_FORMAT = "/org/freedesktop/portal/desktop/request/{sender}/{token}"

SOURCE_TYPES_WINDOW_OR_MONITOR = 3
CURSOR_MODE_HIDDEN = 1
RESPONSE_TIMEOUT_SECONDS = 120
DBUS_CALL_TIMEOUT_MS = 30000

# The streamer: runs in its own process with the fd inherited via
# pass_fds - exactly like the standalone attempts that bind reliably.
STREAMER_SOURCE = r'''
import io
import os
import sys
import time

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst
import numpy as np
from PIL import Image

fd = int(sys.argv[1])
serial = sys.argv[2]

Gst.init(None)


def emit_line(msg):
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def emit_frame(jpeg_bytes):
    header = b"MESLYF" + bytes([
        (len(jpeg_bytes) >> 24) & 0xFF,
        (len(jpeg_bytes) >> 16) & 0xFF,
        (len(jpeg_bytes) >> 8) & 0xFF,
        len(jpeg_bytes) & 0xFF,
    ])
    sys.stdout.buffer.write(header + jpeg_bytes)
    sys.stdout.buffer.flush()


desc = (
    f"pipewiresrc name=src fd={fd} keepalive-time=5000 always-copy=true "
    "! videoconvert ! video/x-raw,format=RGB "
    "! appsink name=sink emit-signals=true sync=false max-buffers=1 drop=true")
struct_props, _ = Gst.Structure.from_string(
    f"props, target.object=(string){serial}")

pipeline = Gst.parse_launch(desc)
src = pipeline.get_by_name("src")
src.set_property("stream-properties", struct_props)
src.set_property("target-object", serial)

state = {"frames": 0, "w": 0, "h": 0, "error": None, "ended": False, "latest": None}


def on_sample(sink):
    sample = sink.emit("pull-sample")
    if sample is None:
        return Gst.FlowReturn.OK
    s = sample.get_caps().get_structure(0)
    width = int(s.get_value("width"))
    height = int(s.get_value("height"))
    buf = sample.get_buffer()
    ok, mapinfo = buf.map(Gst.MapFlags.READ)
    if not ok:
        return Gst.FlowReturn.ERROR
    try:
        # Single-plane RGB with row padding: the byte length of the buffer
        # divided by the row count gives the padded stride (e.g. 1366px RGB
        # is 4100 bytes/row, not 4098). Slice off the padding per row, then
        # reshape to real pixels - otherwise the image comes out as a
        # 4098-wide grayscale ghost and nothing downstream (preview aspect,
        # OCR) works.
        stride = len(mapinfo.data) // height
        raw = np.frombuffer(mapinfo.data, dtype=np.uint8)
        rows = raw.reshape(height, stride)[:, :width * 3]
        pixels = np.ascontiguousarray(rows).reshape(height, width, 3)
        image = Image.fromarray(pixels)
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=75)
        state["latest"] = (width, height, out.getvalue())
        state["frames"] += 1
    except Exception as e:
        sys.stderr.write(f"encode failed: {e}\n")
    finally:
        buf.unmap(mapinfo)
    return Gst.FlowReturn.OK


pipeline.get_by_name("sink").connect("new-sample", on_sample)
pipeline.set_state(Gst.State.PLAYING)


def drain_bus():
    message = pipeline.get_bus().pop_filtered(
        Gst.MessageType.ERROR | Gst.MessageType.EOS)
    if message is None:
        return False
    if message.type == Gst.MessageType.ERROR:
        err, dbg = message.parse_error()
        state["error"] = f"{err.message}"
        sys.stderr.write(f"stream error: {err.message} | {dbg[:150]}\n")
    else:
        state["error"] = "end of stream"
        sys.stderr.write("stream EOS\n")
    state["ended"] = True
    return True


# Verification window: wait for real frames; refuse webcam-sized streams
deadline = time.time() + 12
while (time.time() < deadline and state["frames"] == 0
       and state["error"] is None and not state["ended"]):
    drain_bus()
    time.sleep(0.1)

width, height = state.get("latest", (0, 0, b""))[:2]
if state["frames"] > 0 and width <= 640 and height <= 480:
    pipeline.set_state(Gst.State.NULL)
    sys.stderr.write(f"refusing suspicious stream {width}x{height} (possible webcam)\n")
    emit_line("MESLY ERR refused suspiciously small stream (possible webcam)")
    sys.exit(1)

if state["frames"] == 0:
    pipeline.set_state(Gst.State.NULL)
    detail = state["error"] or "no frames within timeout"
    emit_line(f"MESLY ERR stream failed: {detail}")
    sys.exit(1)

emit_line(f"MESLY READY {width}x{height}")

# Stream until error/EOS
while state["error"] is None and not state["ended"]:
    drain_bus()
    latest = state.get("latest")
    if latest is not None:
        state["latest"] = None
        emit_frame(latest[2])
    time.sleep(0.04)

pipeline.set_state(Gst.State.NULL)
emit_line(f"MESLY ERR stream ended: {state['error'] or 'eos'}")
'''


def emit_line(msg: str) -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def log(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def wait_response(dbus, sender, call_with_token):
    token = f"mesly{random.randint(100000, 999999)}"
    path = REQUEST_PATH_FORMAT.format(sender=sender, token=token)
    holder = {}
    loop = GLib.MainLoop()

    def on_response(connection, sender_name, object_path, interface_name,
                    signal_name, parameters, user_data):
        code, results = parameters.unpack()
        holder["code"] = code
        holder["results"] = results
        loop.quit()

    dbus.signal_subscribe(None, REQUEST_IFACE, "Response", path, None,
                          Gio.DBusSignalFlags.NONE, on_response, None)
    GLib.timeout_add_seconds(RESPONSE_TIMEOUT_SECONDS, loop.quit)
    call_with_token(token)
    loop.run()
    return (holder.get("code"), holder.get("results", {}))


def portal_call(dbus, method, signature, values, reply_type=None):
    params = GLib.Variant(signature, values)
    reply = GLib.VariantType(reply_type) if reply_type else None
    return dbus.call_sync(PORTAL_BUS_NAME, PORTAL_OBJECT_PATH, SCREENCAST_IFACE,
                          method, params, reply, Gio.DBusCallFlags.NONE,
                          DBUS_CALL_TIMEOUT_MS, None)


def resolve_node_serial(node_id, portal_serial):
    """Ground truth from the daemon via pw-dump; portal serial as fallback."""
    try:
        dump = json.loads(subprocess.run(
            ["pw-dump"], capture_output=True, text=True, timeout=10).stdout)
        for obj in dump:
            if (obj.get("id") == node_id
                    and obj.get("type") == "PipeWire:Interface:Node"):
                serial = (obj.get("info", {}).get("props", {}) or {}).get("object.serial")
                if serial is not None:
                    return str(serial), "pw-dump"
        if portal_serial is not None:
            for obj in dump:
                if obj.get("type") != "PipeWire:Interface:Node":
                    continue
                serial = (obj.get("info", {}).get("props", {}) or {}).get("object.serial")
                if str(serial) == str(portal_serial):
                    return str(portal_serial), "serial-scan"
    except Exception as e:
        log(f"pw-dump failed: {e}")
    if portal_serial is not None:
        return str(portal_serial), "portal-fallback"
    return None, "none"


def main():
    Gst.init(None)

    try:
        dbus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except Exception as e:
        emit_line(f"MESLY ERR no session bus: {e}")
        return 1
    sender = dbus.get_unique_name()[1:].replace(".", "_")

    # 1. CreateSession
    code, results = wait_response(dbus, sender, lambda token: portal_call(
        dbus, "CreateSession", "(a{sv})", ({
            "handle_token": GLib.Variant("s", token),
            "session_handle_token": GLib.Variant(
                "s", f"mesly_session_{random.randint(100000, 999999)}"),
        },), "(o)"))
    session_path = results.get("session_handle")
    if code != 0 or not session_path:
        emit_line(f"MESLY ERR CreateSession rejected (code {code})")
        return 1

    # 2. SelectSources
    code, _ = wait_response(dbus, sender, lambda token: portal_call(
        dbus, "SelectSources", "(oa{sv})", (session_path, {
            "handle_token": GLib.Variant("s", token),
            "types": GLib.Variant("u", SOURCE_TYPES_WINDOW_OR_MONITOR),
            "multiple": GLib.Variant("b", False),
            "cursor_mode": GLib.Variant("u", CURSOR_MODE_HIDDEN),
        }), "(o)"))
    if code != 0:
        emit_line(f"MESLY ERR SelectSources rejected (code {code})")
        return 1
    emit_line("MESLY PICKER waiting for your selection")

    # 3. Start (shows the picker dialog)
    code, results = wait_response(dbus, sender, lambda token: portal_call(
        dbus, "Start", "(osa{sv})", (session_path, "", {
            "handle_token": GLib.Variant("s", token),
        }), "(o)"))
    streams = results.get("streams") or []
    if code != 0 or not streams:
        emit_line(f"MESLY ERR Start rejected or cancelled (code {code})")
        return 1

    # KDE portal bug workaround (see OBS screencast-portal.c): only the LAST
    # stream is the real one when more than one is attached.
    log(f"received {len(streams)} stream(s)")
    for index, entry in enumerate(streams):
        entry_props = dict(entry[1]) if len(entry) > 1 else {}
        log(f"  stream[{index}] node={entry[0]} props={entry_props}")

    last_stream = streams[-1]
    node_id = last_stream[0]
    stream_props = dict(last_stream[1]) if len(last_stream) > 1 else {}
    portal_serial = stream_props.get("pipewire-serial") or stream_props.get("id")
    serial, source = resolve_node_serial(node_id, portal_serial)
    if not serial:
        emit_line("MESLY ERR could not resolve the stream node serial; refusing")
        return 1
    log(f"binding via target.object={serial} ({source})")

    # 4. OpenPipeWireRemote
    try:
        result_variant, fd_list = dbus.call_with_unix_fd_list_sync(
            PORTAL_BUS_NAME, PORTAL_OBJECT_PATH, SCREENCAST_IFACE,
            "OpenPipeWireRemote",
            GLib.Variant("(oa{sv})", (session_path, {})),
            GLib.VariantType("(h)"), Gio.DBusCallFlags.NONE,
            DBUS_CALL_TIMEOUT_MS, None, None)
        fd = fd_list.get(result_variant.unpack()[0])
    except Exception as e:
        emit_line(f"MESLY ERR OpenPipeWireRemote failed: {e}")
        return 1

    try:
        flags = fcntl.fcntl(fd, fcntl.F_GETFD)
        log(f"portal fd {fd} open (flags {flags})")
    except Exception as e:
        log(f"portal fd {fd} unusable: {e}")
        emit_line(f"MESLY ERR portal fd unusable: {e}")
        return 1

    # 5. Spawn the streamer with the fd inherited at exec time
    streamer_proc = subprocess.Popen(
        [sys.executable, "-c", STREAMER_SOURCE, str(fd), serial],
        pass_fds=(fd,),
        stdout=subprocess.PIPE,
        stderr=None,  # streamer diagnostics go to our own stderr
    )

    # Relay the streamer's stdout to ours until it exits
    exited_cleanly = False
    while True:
        chunk = streamer_proc.stdout.read1(65536)
        if not chunk:
            break
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        if b"MESLY ERR" in chunk:
            exited_cleanly = False
            break
        if b"MESLY READY" in chunk:
            exited_cleanly = True

    streamer_proc.stdout.close()
    try:
        streamer_proc.wait(timeout=5)
    except Exception:
        streamer_proc.kill()

    return 0 if exited_cleanly else 1


if __name__ == "__main__":
    sys.exit(main())
