#!/usr/bin/env python3
"""
Read-only reconnaissance of the camera Ethernet link on a relay Pi.

This is the tool used to find and identify the Amcrest security cameras that
share an Ethernet switch with the Aurora "cataloging stage overhead" Pi 5
(the ex-OT-2 HQ camera). It is deliberately passive / non-intrusive:

  * It never sends or tries credentials, and never attempts to guess a
    password. Credential guessing can lock out camera accounts and is not
    what this tool is for.
  * It only reads: it listens, it ARP-probes (RFC 5227, sender 0.0.0.0, no
    state changed on any host), and it opens TCP sockets to well-known camera
    ports to read banners. The one UDP it can emit is a WS-Discovery probe
    (``discover``), which is the standard ONVIF multicast and changes nothing.
  * Output is redacted: MAC addresses are reduced to their vendor OUI,
    and serial / UUID / token / RTSP-realm strings are replaced with
    ``<redacted>`` so nothing identifying lands in a log or a public repo.

It does NOT touch the Pi's own streaming. Run the active modes behind a
throw-away, in-memory NetworkManager profile that you delete afterwards, e.g.::

    sudo nmcli connection add type ethernet ifname eth0 con-name cam-probe \\
      ipv4.method manual ipv4.addresses 192.168.3.199/24 \\
      ipv4.never-default yes ipv6.method disabled \\
      connection.autoconnect no save no
    sudo nmcli -w 20 connection up cam-probe
    sudo python3 -I probe_camera_link.py probe 192.168.3.150 192.168.3.151
    sudo nmcli connection down cam-probe && sudo nmcli connection delete cam-probe

``ipv4.never-default yes`` keeps the Pi's default route on Wi-Fi, and
``save no`` means a reboot wipes the profile even if you forget to delete it.

Modes:
  sniff [IFACE] [SECONDS]   Passive listen: who is on the link (vendor OUI),
                            their IPs, ARP targets, and discovery chatter.
                            Needs an interface that is up; no IP required.
  sweep IFACE [CIDR]        ARP-probe every host in CIDR (default the /24 of
                            the interface's address); list which are present.
  probe HOST [HOST ...]     TCP port check + HTTP/RTSP banner + the one ONVIF
                            call (GetSystemDateAndTime) that needs no auth.
  discover [IFACE]          WS-Discovery multicast probe for ONVIF devices.

Raw-socket modes (sniff/sweep) need root. Pass ``python3 -I`` so nothing is
imported from the working directory.
"""
import argparse
import collections
import re
import socket
import struct
import sys
import time

# --- redaction ---------------------------------------------------------------
_RED = re.compile(
    r'(?i)(serial\w*|sn|mac\w*|uuid|usn|token|realm|hardware\w*id|deviceid|p2p\w*)'
    r'(["\s:=>]+)([^\s<>"&,]{3,})'
)


def redact(text):
    text = _RED.sub(lambda m: m.group(1) + m.group(2) + "<redacted>", text)
    text = re.sub(r'(?i)uuid:[0-9a-f-]{8,}', 'uuid:<redacted>', text)
    return text


def oui(mac):
    return mac[:8]


def _mac(b):
    return ":".join(f"{x:02x}" for x in b)


# --- sniff -------------------------------------------------------------------
def sniff(iface="eth0", seconds=45.0):
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(0x0003))
    s.bind((iface, 0))
    s.settimeout(1.0)
    dev = collections.OrderedDict()
    printed = collections.Counter()
    seen_ports = (1900, 3702, 5353, 37810, 5050, 67, 68, 123, 53)

    def d(src):
        if src not in dev:
            dev[src] = {
                "id": f"dev{len(dev)+1}", "oui": oui(src), "ips": set(),
                "who_has": collections.Counter(), "proto": collections.Counter(),
            }
        return dev[src]

    t0 = time.time()
    n = 0
    while time.time() - t0 < seconds:
        try:
            pkt = s.recv(65535)
        except socket.timeout:
            continue
        n += 1
        src = _mac(pkt[6:12])
        et = struct.unpack("!H", pkt[12:14])[0]
        off = 14
        info = d(src)
        while et in (0x8100, 0x88A8):
            et = struct.unpack("!H", pkt[off + 2:off + 4])[0]
            off += 4
        p = pkt[off:]
        if et == 0x0806 and len(p) >= 28:  # ARP
            op = struct.unpack("!H", p[6:8])[0]
            spa, tpa = socket.inet_ntoa(p[14:18]), socket.inet_ntoa(p[24:28])
            if spa != "0.0.0.0":
                info["ips"].add(spa)
            info["proto"]["arp-" + ("req" if op == 1 else "rep")] += 1
            if op == 1:
                info["who_has"][tpa] += 1
        elif et == 0x0800 and len(p) >= 20:  # IPv4
            ihl = (p[0] & 15) * 4
            proto = p[9]
            sip = socket.inet_ntoa(p[12:16])
            if sip != "0.0.0.0":
                info["ips"].add(sip)
            if proto == 17 and len(p) >= ihl + 8:
                sp, dp = struct.unpack("!HH", p[ihl:ihl + 4])
                port = dp if dp < 49152 else sp
                info["proto"][f"udp/{port}"] += 1
                if port in seen_ports and printed[(info["id"], port)] < 1:
                    printed[(info["id"], port)] += 1
                    txt = re.sub(r'[^\x20-\x7e]', '.', p[ihl + 8:].decode("latin1"))
                    print(f"  [{info['id']} udp/{port}] {redact(txt)[:200]}")
            elif proto == 6:
                sp, dp = struct.unpack("!HH", p[ihl:ihl + 4])
                info["proto"][f"tcp/{min(sp, dp)}"] += 1
            elif proto == 2:
                info["proto"]["igmp"] += 1
        elif et == 0x86DD:  # IPv6
            info["proto"]["ipv6"] += 1

    print(f"=== {n} frames in {seconds:.0f} s on {iface}")
    for info in dev.values():
        print(f"{info['id']} oui={info['oui']} ips={sorted(info['ips'])}")
        print(f"    proto={dict(info['proto'].most_common(10))}")
        if info["who_has"]:
            print(f"    arp who-has={dict(info['who_has'].most_common(6))}")


# --- sweep -------------------------------------------------------------------
def sweep(iface, cidr=None):
    with open(f"/sys/class/net/{iface}/address") as fh:
        mm = bytes.fromhex(fh.read().strip().replace(":", ""))
    if cidr is None:
        import subprocess
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", iface],
                             capture_output=True, text=True).stdout
        m = re.search(r'inet (\d+\.\d+\.\d+)\.\d+/', out)
        if not m:
            print(f"{iface} has no IPv4 address; pass a CIDR explicitly.")
            return
        base = m.group(1)
    else:
        base = cidr.rsplit(".", 1)[0]
    cands = [f"{base}.{i}" for i in range(1, 255)]
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(0x0806))
    s.bind((iface, 0))
    s.settimeout(0.2)
    taken = {}
    for _ in range(2):
        for c in cands:
            arp = struct.pack("!HHBBH6s4s6s4s", 1, 0x0800, 6, 4, 1, mm,
                              b"\0" * 4, b"\0" * 6, socket.inet_aton(c))
            s.send(b"\xff" * 6 + mm + b"\x08\x06" + arp)
        t = time.time()
        while time.time() - t < 1.2:
            try:
                p = s.recv(100)
            except socket.timeout:
                continue
            a = p[14:42]
            if len(a) < 28:
                continue
            spa = socket.inet_ntoa(a[14:18])
            if spa in cands:
                taken[spa] = oui(_mac(a[8:14]))
    for c in sorted(taken, key=lambda x: int(x.rsplit(".", 1)[1])):
        print(f"{c}\tpresent\toui={taken[c]}")
    print(f"=== {len(taken)} hosts present on {base}.0/24")


# --- probe -------------------------------------------------------------------
PORTS = [80, 554, 443, 37777, 37778, 8000, 8899, 9000, 22, 23]


def _tcp(host, port, tmo=2.0):
    try:
        s = socket.create_connection((host, port), tmo)
        s.settimeout(tmo)
        return s
    except Exception:
        return None


def _http_head(host, port=80):
    c = _tcp(host, port)
    if not c:
        return "(no connect)"
    try:
        c.sendall(f"GET / HTTP/1.0\r\nHost: {host}\r\nUser-Agent: aurora-probe\r\n\r\n".encode())
        data = b""
        while len(data) < 4096:
            ch = c.recv(2048)
            if not ch:
                break
            data += ch
        c.close()
        head = data.split(b"\r\n\r\n", 1)[0].decode("latin1")
        keep = [l for l in head.splitlines()
                if re.match(r'(?i)^(HTTP|Server|WWW-Authenticate|Content-Type)', l)]
        return redact("\n      ".join(keep))
    except Exception as e:
        return f"({type(e).__name__})"


def _rtsp(host, port=554):
    s = _tcp(host, port)
    if not s:
        return "(no connect)"
    try:
        s.sendall(f"OPTIONS rtsp://{host}:{port}/ RTSP/1.0\r\nCSeq: 1\r\n\r\n".encode())
        d = s.recv(2048).decode("latin1")
        s.close()
        lines = d.splitlines()
        first = lines[0] if lines else "(empty)"
        auth = [l for l in lines if re.match(r'(?i)^(WWW-Authenticate|Public|Server)', l)]
        return redact(first + (("\n      " + "\n      ".join(auth)) if auth else ""))
    except Exception as e:
        return f"({type(e).__name__})"


def _onvif_datetime(host, port=80):
    """GetSystemDateAndTime requires no authentication per the ONVIF Core spec."""
    body = ('<?xml version="1.0"?><s:Envelope '
            'xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body>'
            '<GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/>'
            '</s:Body></s:Envelope>')
    s = _tcp(host, port)
    if not s:
        return "(no connect)"
    try:
        s.sendall((f"POST /onvif/device_service HTTP/1.0\r\nHost: {host}\r\n"
                   f"Content-Type: application/soap+xml; charset=utf-8\r\n"
                   f"Content-Length: {len(body)}\r\n\r\n{body}").encode())
        d = b""
        while len(d) < 8000:
            ch = s.recv(2048)
            if not ch:
                break
            d += ch
        s.close()
        txt = d.decode("latin1")
        status = txt.splitlines()[0] if txt else "(empty)"
        dt = re.search(r'(?:UTC|Local)DateTime.*?Year>(\d+)<.*?Month>(\d+)<.*?Day>(\d+)<', txt, re.S)
        if "GetSystemDateAndTimeResponse" in txt or dt:
            return f"{status}  ONVIF OK; device clock {'-'.join(dt.group(1, 2, 3)) if dt else '?'}"
        return status
    except Exception as e:
        return f"({type(e).__name__})"


def probe(hosts):
    for h in hosts:
        print(f"\n### {h}")
        up = [p for p in PORTS if (_c := _tcp(h, p, 1.2)) and (_c.close() or True)]
        print("  open tcp:", up)
        if 80 in up:
            print("  http/80:", _http_head(h, 80))
        if 554 in up:
            print("  rtsp/554 OPTIONS:", _rtsp(h, 554))
        if 80 in up:
            print("  onvif:", _onvif_datetime(h, 80))


# --- discover ----------------------------------------------------------------
def discover(iface="eth0", seconds=4.0):
    probe_msg = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
        'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
        'xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
        '<e:Header><w:MessageID>uuid:probe</w:MessageID>'
        '<w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
        '<w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>'
        '</e:Header><e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types>'
        '</d:Probe></e:Body></e:Envelope>'
    ).encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.settimeout(0.5)
    s.sendto(probe_msg, ("239.255.255.250", 3702))
    t = time.time()
    found = set()
    while time.time() - t < seconds:
        try:
            data, addr = s.recvfrom(8192)
        except socket.timeout:
            continue
        if addr[0] in found:
            continue
        found.add(addr[0])
        xaddr = re.search(r'(http://[^\s<]+/onvif/\S+)', data.decode("latin1"))
        x = re.sub(r'//[^/]+', '//<cam>', xaddr.group(1)) if xaddr else "(no XAddr)"
        print(f"  ONVIF device at {addr[0]}  {x}")
    print(f"=== {len(found)} ONVIF responders")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    a = sub.add_parser("sniff"); a.add_argument("iface", nargs="?", default="eth0"); a.add_argument("seconds", nargs="?", type=float, default=45.0)
    a = sub.add_parser("sweep"); a.add_argument("iface"); a.add_argument("cidr", nargs="?")
    a = sub.add_parser("probe"); a.add_argument("hosts", nargs="+")
    a = sub.add_parser("discover"); a.add_argument("iface", nargs="?", default="eth0")
    args = ap.parse_args()
    if args.mode == "sniff":
        sniff(args.iface, args.seconds)
    elif args.mode == "sweep":
        sweep(args.iface, args.cidr)
    elif args.mode == "probe":
        probe(args.hosts)
    elif args.mode == "discover":
        discover(args.iface)


if __name__ == "__main__":
    sys.exit(main())
