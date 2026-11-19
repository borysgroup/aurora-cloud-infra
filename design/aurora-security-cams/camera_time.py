"""Read, or set, both Amcrest cams' clock settings: time zone, DST rule and NTP.

Runs on the Pi 5 (the cameras are only reachable from its eth0). The admin user
and password for cam 0, then cam 1, arrive on stdin (4 lines) and are never
written anywhere or put on a command line.

    read   GETs only: camera time, NTP.*, Locales.* (nothing changes)
    ntp    point both cameras at an NTP server on the camera segment (the Pi's
           chrony at 192.168.3.199 by default, polled every 10 min), set the
           time zone to GMT-07:00 with the US DST rule (2nd Sunday of March
           02:00 to 1st Sunday of November 02:00), then read everything back

From the runner::

    printf '%s\\n%s\\n%s\\n%s\\n' "$AMCREST_CAM_ADMIN_USERNAME_0" "$AMCREST_CAM_ADMIN_PASSWORD_0" \\
        "$AMCREST_CAM_ADMIN_USERNAME_1" "$AMCREST_CAM_ADMIN_PASSWORD_1" \\
      | ssh <pi5> 'python3 -I /tmp/aurora-cams/camera_time.py read'

`ntp [SERVER [CAMS]]`, e.g. `ntp 192.168.3.199 0` changes cam 0 only (both are read back).
"""
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HOSTS = {0: "192.168.3.150", 1: "192.168.3.151"}
# Dahua/Amcrest DST rule fields: Week 1-5 (or -1 = last), Day 0 = Sunday.
US_DST = {"Locales.DSTEnable": "true",
          "Locales.DSTStart.Month": "3", "Locales.DSTStart.Week": "2", "Locales.DSTStart.Day": "0",
          "Locales.DSTStart.Hour": "2", "Locales.DSTStart.Minute": "0",
          "Locales.DSTEnd.Month": "11", "Locales.DSTEnd.Week": "1", "Locales.DSTEnd.Day": "0",
          "Locales.DSTEnd.Hour": "2", "Locales.DSTEnd.Minute": "0"}
SHOW = re.compile(r"table\.(NTP\.\w+|Locales\.(DSTEnable|DSTStart\.\w+|DSTEnd\.\w+|TimeFormat))=(.*)")


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
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__


def show(op, host):
    st, t = get(op, host, "/cgi-bin/global.cgi?action=getCurrentTime")
    print(f"  camera time: {t.strip()[:40]} (HTTP {st}); Pi UTC {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}")
    for name in ("NTP", "Locales"):
        st, t = get(op, host, f"/cgi-bin/configManager.cgi?action=getConfig&name={name}")
        rows = [f"{m.group(1)}={m.group(3).strip()}" for l in t.splitlines() if (m := SHOW.match(l.strip()))]
        print(f"  {name} (HTTP {st}): " + "; ".join(rows))


def set_config(op, host, kv):
    q = "&".join(f"{k}={urllib.parse.quote(v, safe='')}" for k, v in kv.items())
    st, t = get(op, host, f"/cgi-bin/configManager.cgi?action=setConfig&{q}")
    print(f"  setConfig {sorted(kv)} -> HTTP {st} {t.strip()[:20]}")
    return st == 200 and t.strip().startswith("OK")


def main():
    mode = sys.argv[1]
    server = sys.argv[2] if len(sys.argv) > 2 else "192.168.3.199"
    only = {int(c) for c in sys.argv[3].split(",")} if len(sys.argv) > 3 else set(HOSTS)
    lines = sys.stdin.read().splitlines()
    creds = {0: (lines[0], lines[1]), 1: (lines[2], lines[3])}
    ok = True
    for n, host in HOSTS.items():
        op = opener(host, *creds[n])
        print(f"cam {n} ({host})")
        if mode == "ntp" and n in only:
            # TimeZone 27 is GMT-07:00 in Dahua's zone table (26, the old value, reads back as
            # "CentralAmerica", GMT-06:00); TimeZoneDesc is checked on the read-back.
            ok &= set_config(op, host, {"NTP.Enable": "true", "NTP.Address": server, "NTP.Port": "123",
                                        "NTP.UpdatePeriod": "10", "NTP.TimeZone": "27"})
            ok &= set_config(op, host, US_DST)
            time.sleep(5)
        show(op, host)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
