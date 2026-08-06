#!/bin/sh
#
# Container entrypoint.
#
# With KLEINANZEIGEN_VNC=true it brings up a virtual screen and streams it to
# the host, so the browser the agent drives can actually be watched — during
# the manual kleinanzeigen.de login (captcha and 2FA included, which no script
# can solve) and later while an ad is being filled in.
#
#   Xvfb       virtual X server; the browser needs a display to draw on
#   fluxbox    minimal window manager, otherwise windows have no size or focus
#   x11vnc     exports that display over the VNC protocol on 5900
#   websockify serves noVNC on 6080 and bridges it to 5900 for the browser
#
# Without the variable none of this starts. The frontend container runs from
# the same image and has no use for a browser.
set -e

if [ "${KLEINANZEIGEN_VNC}" = "true" ]; then
    DISPLAY="${DISPLAY:-:99}"
    export DISPLAY

    echo "[vnc] starting Xvfb on ${DISPLAY} (${VNC_GEOMETRY:-1440x1000x24})"
    Xvfb "${DISPLAY}" -screen 0 "${VNC_GEOMETRY:-1440x1000x24}" -nolisten tcp &

    # x11vnc fails outright if the display is not up yet, so wait for it
    # instead of guessing with a fixed sleep.
    i=0
    until xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; do
        i=$((i + 1))
        if [ "$i" -gt 50 ]; then
            echo "[vnc] Xvfb did not come up within 10s" >&2
            exit 1
        fi
        sleep 0.2
    done
    echo "[vnc] display ready"

    fluxbox >/dev/null 2>&1 &

    # -nopw: no VNC password. Acceptable only because compose publishes the
    # port on 127.0.0.1 — see docker-compose.yml. Anyone who can reach it
    # controls a logged-in browser.
    x11vnc -display "${DISPLAY}" -forever -shared -nopw -quiet -rfbport 5900 &

    websockify --web=/usr/share/novnc 6080 localhost:5900 &
    echo "[vnc] noVNC on http://localhost:6080/vnc.html"
fi

exec "$@"