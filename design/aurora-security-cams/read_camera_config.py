"""Read-only: print both Amcrest cams' encoder, image and PTZ settings.

Runs on the Pi 5 (the cameras are only reachable from its eth0). The admin
user and password for cam 0, then cam 1, arrive on stdin (4 lines) and are
never written anywhere or put on a command line. Only GET requests to
``getConfig`` / ``getCaps`` / ``getStatus``-style CGI endpoints are made, so
nothing on the camera changes. Prints only whitelisted, non-identifying fields.

From the runner::

    printf '%s\n%s\n%s\n%s\n' "$AMCREST_CAM_ADMIN_USERNAME_0" "$AMCREST_CAM_ADMIN_PASSWORD_0" \
        "$AMCREST_CAM_ADMIN_USERNAME_1" "$AMCREST_CAM_ADMIN_PASSWORD_1" \
      | ssh <pi5> 'python3 -I /tmp/aurora-cams/read_camera_config.py'
"""
import re, sys, urllib.request, urllib.error

lines = sys.stdin.read().splitlines()
creds = {0: (lines[0], lines[1]), 1: (lines[2], lines[3])}
hosts = {0: "192.168.3.150", 1: "192.168.3.151"}

def opener(host, user, pw):
    pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pm.add_password(None, f"http://{host}/", user, pw)
    return urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(pm))

def get(op, host, path):
    try:
        with op.open(f"http://{host}{path}", timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, type(e).__name__

ENC = re.compile(r"table\.Encode\[0\]\.(MainFormat\[0\]|ExtraFormat\[[01]\])\.("
                 r"VideoEnable|AudioEnable|Video\.(Compression|Width|Height|FPS|GOP|BitRate|"
                 r"BitRateControl|Profile|Quality|Priority)|Audio\.Compression)=(.*)")
VIN = re.compile(r"table\.VideoInOptions\[0\]\.(Flip|Mirror|Rotate90|DayNightColor|ExposureMode|"
                 r"IrisAuto|LightingMode|InfraRed\w*|FlashControl\.\w+)=(.*)")
for n in (0, 1):
    h = hosts[n]
    op = opener(h, *creds[n])
    print(f"\n##### cam {n} ({h})")
    st, t = get(op, h, "/cgi-bin/global.cgi?action=getCurrentTime")
    print("clock:", st, t.strip()[:40])
    st, t = get(op, h, "/cgi-bin/configManager.cgi?action=getConfig&name=ChannelTitle")
    print("ChannelTitle:", st, [l.split("=", 1)[1] for l in t.splitlines() if ".Name=" in l][:2])
    st, t = get(op, h, "/cgi-bin/configManager.cgi?action=getConfig&name=Encode")
    print("Encode:", st)
    for l in t.splitlines():
        m = ENC.match(l.strip())
        if m:
            print(f"   {m.group(1):15} {m.group(2):22} = {m.group(4)}")
    st, t = get(op, h, "/cgi-bin/configManager.cgi?action=getConfig&name=VideoInOptions")
    print("VideoInOptions:", st, "; ".join(f"{m.group(1)}={m.group(2)}" for l in t.splitlines() if (m := VIN.match(l.strip()))))
    for path in ("/cgi-bin/ptz.cgi?action=getCurrentProtocolCaps&channel=1",
                 "/cgi-bin/ptz.cgi?action=getStatus&channel=1",
                 "/cgi-bin/devVideoInput.cgi?action=getCaps&channel=1"):
        st, t = get(op, h, path)
        keep = [l.strip() for l in t.splitlines()
                if re.search(r"(?i)zoom|focus|pan|tilt|ptz|iris|rotate|flip|mirror|error|bad", l)]
        print(path.split("?", 1)[1][:45], "->", st, keep[:14] if keep else t.strip()[:80])
    st, t = get(op, h, "/cgi-bin/userManager.cgi?action=getActiveUserInfoAll")
    users = {}
    for l in t.splitlines():
        m = re.match(r"users\[(\d+)\]\.(Name|ClientType|LoginTime)=(.*)", l.strip())
        if m:
            users.setdefault(m.group(1), {})[m.group(2)] = m.group(3).strip()
    print("active sessions:", st, [f"{u.get('Name')}/{u.get('ClientType')}/{u.get('LoginTime')}" for u in users.values()])
