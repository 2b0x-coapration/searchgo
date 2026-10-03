"""SUPERGO v2ray / xray backend (no GTK, no root).

Parses vless / vmess / trojan / shadowsocks links (or a full v2ray JSON config), writes a core
config with ONE local SOCKS5 inbound on 127.0.0.1, starts `xray` or `v2ray` as the normal user,
and checks that traffic really passes through the remote server.  The browser points WebKit at
that SOCKS port; nothing else on the computer is touched.
"""
import sys, os, re, json, base64, html, shutil, socket, subprocess, threading, time, uuid as _uuid
from urllib.parse import urlsplit, parse_qs, unquote

PROTOS = ('vless', 'vmess', 'trojan', 'ss')
LINK_RE = re.compile(r'(?:vless|vmess|trojan|ss)://[^\s<>"\']+', re.I)
UUID_RE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
PRIVATE_NETS = ['127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16',
                '100.64.0.0/10', '::1/128', 'fc00::/7', 'fe80::/10']

COUNTRIES = {
    'US': 'United States', 'GB': 'United Kingdom', 'DE': 'Germany', 'NL': 'Netherlands', 'FR': 'France',
    'CA': 'Canada', 'SG': 'Singapore', 'JP': 'Japan', 'KR': 'South Korea', 'HK': 'Hong Kong', 'TW': 'Taiwan',
    'IN': 'India', 'RU': 'Russia', 'UA': 'Ukraine', 'TR': 'Turkey', 'IR': 'Iran', 'AE': 'United Arab Emirates',
    'FI': 'Finland', 'SE': 'Sweden', 'NO': 'Norway', 'DK': 'Denmark', 'PL': 'Poland', 'CZ': 'Czechia',
    'AT': 'Austria', 'CH': 'Switzerland', 'IT': 'Italy', 'ES': 'Spain', 'PT': 'Portugal', 'IE': 'Ireland',
    'BE': 'Belgium', 'RO': 'Romania', 'BG': 'Bulgaria', 'HU': 'Hungary', 'GR': 'Greece', 'LT': 'Lithuania',
    'LV': 'Latvia', 'EE': 'Estonia', 'MD': 'Moldova', 'RS': 'Serbia', 'IL': 'Israel', 'SA': 'Saudi Arabia',
    'AU': 'Australia', 'NZ': 'New Zealand', 'BR': 'Brazil', 'AR': 'Argentina', 'MX': 'Mexico', 'CL': 'Chile',
    'ZA': 'South Africa', 'EG': 'Egypt', 'NG': 'Nigeria', 'KZ': 'Kazakhstan', 'TH': 'Thailand', 'VN': 'Vietnam',
    'ID': 'Indonesia', 'MY': 'Malaysia', 'PH': 'Philippines', 'PK': 'Pakistan', 'BD': 'Bangladesh', 'CN': 'China',
    'AM': 'Armenia', 'GE': 'Georgia', 'AZ': 'Azerbaijan', 'IS': 'Iceland', 'LU': 'Luxembourg', 'CY': 'Cyprus',
}
NAME_HINTS = [(v.lower(), k) for k, v in COUNTRIES.items()] + [
    ('usa', 'US'), ('america', 'US'), ('england', 'GB'), ('uk ', 'GB'), ('deutschland', 'DE'), ('holland', 'NL'),
    ('korea', 'KR'), ('emirates', 'AE'), ('uae', 'AE')]


# ------------------------------------------------------------------ helpers
def flag_cc(text):
    """Country code from a flag emoji in the remark, else from a country name, else ''."""
    m = re.search('([\U0001F1E6-\U0001F1FF])([\U0001F1E6-\U0001F1FF])', text or '')
    if m:
        cc = ''.join(chr(ord(c) - 0x1F1E6 + 65) for c in m.groups())
        if cc in COUNTRIES: return cc
    low = ' ' + (text or '').lower() + ' '
    for nm, cc in NAME_HINTS:
        if nm in low: return cc
    m = re.search(r'(?:^|[\s\[\(|_-])([A-Z]{2})(?:[\s\]\)|_-]|$)', text or '')
    if m and m.group(1) in COUNTRIES: return m.group(1)
    return ''


def _b64d(s):
    s = s.strip().replace('-', '+').replace('_', '/')
    s += '=' * (-len(s) % 4)
    return base64.b64decode(s).decode('utf-8', 'replace')


def _q(qs, key, default=''):
    v = qs.get(key) or qs.get(key.lower())
    return (v[0] if v else default).strip()


def _split_hostport(netloc):
    hp = netloc.rsplit('@', 1)[-1]
    if hp.startswith('['):
        h, _, rest = hp[1:].partition(']')
        p = rest.lstrip(':')
    else:
        h, _, p = hp.rpartition(':')
    if not h or not p.isdigit() or not 0 < int(p) < 65536: return None, None
    return h, int(p)


def clean_link(s):
    s = html.unescape(s.strip())
    s = re.split(r'<|\\u200f|\u200f', s)[0]
    return s.strip()


# ------------------------------------------------------------------ parsing
def parse_link(text, own=False):
    """One share link -> node dict, or None when it is malformed."""
    link = clean_link(text)
    m = re.match(r'^(vless|vmess|trojan|ss)://', link, re.I)
    if not m: return None
    proto = m.group(1).lower()
    try:
        node = {'vless': _parse_vless, 'trojan': _parse_vless, 'vmess': _parse_vmess, 'ss': _parse_ss}[proto](link, proto)
    except Exception:
        return None
    if not node: return None
    node.update(proto=proto, own=own, uri=link, cc=node.get('cc') or flag_cc(node.get('name', '')))
    node['name'] = (node.get('name') or '%s:%s' % (node['host'], node['port']))[:70]
    node['caps'] = caps_of(node)
    return node


def _parse_vless(link, proto):
    u = urlsplit(link)
    host, port = _split_hostport(u.netloc)
    if not host or '@' not in u.netloc: return None
    ident = unquote(u.netloc.rsplit('@', 1)[0])
    qs = parse_qs(u.query, keep_blank_values=True)
    if proto == 'vless' and not UUID_RE.match(ident): return None
    net = _q(qs, 'type', 'tcp').lower()
    if net == 'raw': net = 'tcp'
    if net == 'h2': net = 'http'
    if net == 'splithttp': net = 'xhttp'
    sec = _q(qs, 'security', 'tls' if proto == 'trojan' else 'none').lower()
    if sec not in ('none', 'tls', 'reality'): sec = 'none'
    if net not in ('tcp', 'ws', 'grpc', 'http', 'httpupgrade', 'xhttp', 'kcp', 'quic'): return None
    flow = _q(qs, 'flow')
    flow = flow if flow.startswith('xtls-rprx-vision') else ''
    extra = {}
    try:
        e = json.loads(_q(qs, 'extra') or '{}')
        if isinstance(e, dict): extra = e
    except Exception:
        pass
    return dict(name=unquote(u.fragment).strip(), host=host, port=port, id=ident, net=net, sec=sec, flow=flow,
                sni=_q(qs, 'sni') or _q(qs, 'peer'), fp=_q(qs, 'fp'), alpn=_q(qs, 'alpn'), path=unquote(_q(qs, 'path')),
                hosthdr=_q(qs, 'host'), service=unquote(_q(qs, 'serviceName')), mode=_q(qs, 'mode'),
                pbk=_q(qs, 'pbk'), sid=_q(qs, 'sid'), spx=unquote(_q(qs, 'spx')), htype=_q(qs, 'headerType', 'none').lower(),
                seed=_q(qs, 'seed'), insecure=_q(qs, 'allowInsecure') in ('1', 'true') or _q(qs, 'insecure') in ('1', 'true'),
                extra=extra)


def _parse_vmess(link, proto):
    j = json.loads(_b64d(link[8:].split('#')[0]))
    host, port = j.get('add'), int(j.get('port'))
    if not host or not _UUID_OK(j.get('id', '')) or not 0 < port < 65536: return None
    net = (j.get('net') or 'tcp').lower()
    net = {'h2': 'http', 'raw': 'tcp', 'splithttp': 'xhttp'}.get(net, net)
    if net not in ('tcp', 'ws', 'grpc', 'http', 'httpupgrade', 'xhttp', 'kcp', 'quic'): return None
    sec = 'tls' if (j.get('tls') or '').lower() == 'tls' else 'none'
    return dict(name=str(j.get('ps') or ''), host=host, port=port, id=j['id'], aid=int(j.get('aid') or 0),
                scy=j.get('scy') or 'auto', net=net, sec=sec, flow='', sni=j.get('sni') or j.get('host') or '',
                fp=j.get('fp') or '', alpn=j.get('alpn') or '', path=j.get('path') or '', hosthdr=j.get('host') or '',
                service=j.get('path') or '', mode='', pbk='', sid='', spx='', htype=(j.get('type') or 'none').lower(),
                seed=j.get('seed') or '', insecure=False, extra={})


def _UUID_OK(s):
    return bool(UUID_RE.match(s or ''))


def _parse_ss(link, proto):
    body, _, frag = link[5:].partition('#')
    body, _, query = body.partition('?')
    if '@' in body:
        cred, _, hp = body.rpartition('@')
        try: cred = _b64d(cred) if ':' not in cred else unquote(cred)
        except Exception: return None
    else:
        dec = _b64d(body)
        cred, _, hp = dec.rpartition('@')
    method, _, pw = cred.partition(':')
    host, port = _split_hostport('x@' + hp)
    if not (host and port and method and pw): return None
    if 'plugin' in parse_qs(query): return None          # plugins (obfs, v2ray-plugin) are not supported
    return dict(name=unquote(frag).strip(), host=host, port=port, id=pw, method=method, net='tcp', sec='none', flow='',
                sni='', fp='', alpn='', path='', hosthdr='', service='', mode='', pbk='', sid='', spx='', htype='none',
                seed='', insecure=False, extra={})


def caps_of(n):
    """What the core must support to run this node: r=reality, x=xhttp, v=vision flow, q=quic."""
    c = ''
    if n.get('sec') == 'reality': c += 'r'
    if n.get('net') == 'xhttp': c += 'x'
    if n.get('flow'): c += 'v'
    if n.get('net') == 'quic': c += 'q'
    return c


def parse_json_config(text, own=True, name=None):
    try: j = json.loads(text)
    except Exception: return None
    if not isinstance(j, dict) or not isinstance(j.get('outbounds') or j.get('outbound'), (list, dict)): return None
    obs = j.get('outbounds') or [j.get('outbound')]
    ob = obs[0] if obs and isinstance(obs[0], dict) else {}
    host = ''
    try:
        st = ob.get('settings', {})
        v = (st.get('vnext') or st.get('servers') or [{}])[0]
        host = '%s:%s' % (v.get('address', ''), v.get('port', ''))
    except Exception:
        pass
    return dict(proto='json', raw=j, own=own, name=(name or j.get('remarks') or ob.get('protocol', 'JSON') + ' config ' + host)[:70],
                host=host, port=0, uri='', cc=flag_cc(j.get('remarks', '')), caps='', net='tcp', sec='none')


def parse_many(text, own=True):
    """Accepts pasted links, a base64 subscription body, or a v2ray JSON config. Returns nodes (deduplicated)."""
    text = (text or '').strip()
    if not text: return []
    if text.startswith('{'):
        n = parse_json_config(text, own)
        return [n] if n else []
    if not LINK_RE.search(text):
        try:
            dec = _b64d(re.sub(r'\s+', '', text))
            if LINK_RE.search(dec): text = dec
        except Exception:
            pass
    out, seen = [], set()
    for raw in LINK_RE.findall(text):
        n = parse_link(raw, own)
        if not n: continue
        key = (n['host'], n['port'], n.get('id'), n.get('net'), n.get('path'), n.get('sni'))
        if key in seen: continue
        seen.add(key); out.append(n)
    return out


# ------------------------------------------------------------------ core detection
class Core:
    def __init__(self, path, kind, ver):
        self.path, self.kind, self.ver = path, kind, ver      # kind: 'xray' | 'v2ray'

    def supports(self, caps):
        if self.kind == 'xray': return 'q' not in caps
        return not set(caps) & set('rxv')                     # v2ray-core has no reality / xhttp / vision

    def argv(self, cfg):
        if self.kind == 'v2ray' and self.ver and self.ver[0] < 5: return [self.path, '-config', cfg]
        return [self.path, 'run', '-c', cfg]

    def label(self):
        return '%s %s' % (self.kind, '.'.join(map(str, self.ver)) if self.ver else '')

    def use_xhttp_name(self):
        if self.kind != 'xray' or not self.ver: return True
        return self.ver >= (1, 8, 24) if self.ver[0] == 1 else True


def _version(path):
    try:
        out = subprocess.run([path, 'version'], capture_output=True, text=True, timeout=6).stdout
    except Exception:
        return None, None
    m = re.search(r'(Xray|V2Ray)\s+v?(\d+)\.(\d+)\.(\d+)', out, re.I)
    if not m: return None, None
    return m.group(1).lower().replace('v2ray', 'v2ray'), (int(m.group(2)), int(m.group(3)), int(m.group(4)))


def find_core(extra_dirs=(), preferred=''):
    """First usable core: a user-chosen path, then xray (Reality/XHTTP capable), then v2ray."""
    cands = []
    if preferred and os.access(preferred, os.X_OK): cands.append(preferred)
    dirs = list(extra_dirs) + [os.path.dirname(os.path.abspath(sys.argv[0])), os.getcwd(),
                                os.path.join(os.environ.get('LOCALAPPDATA', ''), 'SUPERGO'),
                                os.path.join(os.environ.get('APPDATA', ''), 'SUPERGO')]
    for name in ('xray', 'v2ray'):
        p = shutil.which(name)
        if p: cands.append(p)
        for d in dirs:
            q = os.path.join(d, name + '.exe')
            if os.access(q, os.X_OK): cands.append(q)
    seen = set()
    for p in cands:
        rp = os.path.realpath(p)
        if rp in seen: continue
        seen.add(rp)
        kind, ver = _version(p)
        if kind: return Core(p, kind, ver)
    return None


# ------------------------------------------------------------------ core config
def _tls_block(n, sec):
    sni = n.get('sni') or n.get('hosthdr') or ''
    if sec == 'reality':
        return 'realitySettings', {'serverName': sni, 'fingerprint': n.get('fp') or 'chrome', 'publicKey': n.get('pbk', ''),
                                   'shortId': n.get('sid', ''), 'spiderX': n.get('spx') or ''}
    t = {'allowInsecure': bool(n.get('insecure') and n.get('own'))}
    if sni: t['serverName'] = sni
    if n.get('alpn'): t['alpn'] = [a for a in n['alpn'].split(',') if a]
    if n.get('fp'): t['fingerprint'] = n['fp']
    return 'tlsSettings', t


def stream_settings(n, core):
    net, sec = n['net'], n['sec']
    s = {'network': net, 'security': sec}
    hosthdr, path = n.get('hosthdr', ''), n.get('path', '') or '/'
    if net == 'tcp':
        if n.get('htype') == 'http':
            hdr = {'type': 'http', 'request': {'version': '1.1', 'method': 'GET', 'path': [p for p in path.split(',') if p] or ['/'],
                                               'headers': {'Host': [h for h in hosthdr.split(',') if h]}}}
            s['tcpSettings'] = {'header': hdr}
    elif net == 'ws':
        ws = {'path': path}
        if hosthdr: ws['headers'] = {'Host': hosthdr}; ws['host'] = hosthdr
        s['wsSettings'] = ws
    elif net == 'grpc':
        s['grpcSettings'] = {'serviceName': n.get('service', ''), 'multiMode': n.get('mode') == 'multi'}
    elif net == 'http':
        s['httpSettings'] = {'path': path, 'host': [h for h in hosthdr.split(',') if h]}
    elif net == 'httpupgrade':
        s['httpupgradeSettings'] = {'path': path, 'host': hosthdr}
    elif net == 'xhttp':
        x = {'path': path, 'host': hosthdr, 'mode': n.get('mode') or 'auto'}
        if n.get('extra'): x['extra'] = n['extra']
        if core.use_xhttp_name(): s['xhttpSettings'] = x
        else: s['network'] = 'splithttp'; s['splithttpSettings'] = x
    elif net == 'kcp':
        s['kcpSettings'] = {'header': {'type': n.get('htype') or 'none'}, 'seed': n.get('seed', '')}
    elif net == 'quic':
        s['quicSettings'] = {'security': 'none', 'header': {'type': n.get('htype') or 'none'}}
    if sec in ('tls', 'reality'):
        k, v = _tls_block(n, sec); s[k] = v
    return s


def outbound(n, core):
    p = n['proto']
    if p == 'vless':
        user = {'id': n['id'], 'encryption': 'none'}
        if n.get('flow') and core.kind == 'xray': user['flow'] = n['flow']
        st = {'vnext': [{'address': n['host'], 'port': n['port'], 'users': [user]}]}
    elif p == 'vmess':
        st = {'vnext': [{'address': n['host'], 'port': n['port'],
                         'users': [{'id': n['id'], 'alterId': n.get('aid', 0), 'security': n.get('scy') or 'auto'}]}]}
    elif p == 'trojan':
        st = {'servers': [{'address': n['host'], 'port': n['port'], 'password': n['id']}]}
    else:
        st = {'servers': [{'address': n['host'], 'port': n['port'], 'method': n['method'], 'password': n['id']}]}
    ob = {'tag': 'proxy', 'protocol': 'shadowsocks' if p == 'ss' else p, 'settings': st}
    if p != 'ss': ob['streamSettings'] = stream_settings(n, core)
    return ob


def build_config(n, port, core):
    """Core config: one SOCKS5 inbound on 127.0.0.1:port, traffic goes out through the node only."""
    inbound = {'tag': 'in', 'listen': '127.0.0.1', 'port': port, 'protocol': 'socks',
               'settings': {'auth': 'noauth', 'udp': False}}
    block = {'tag': 'block', 'protocol': 'blackhole', 'settings': {}}
    rules = [{'type': 'field', 'ip': PRIVATE_NETS, 'outboundTag': 'block'}]
    if n['proto'] == 'json':                      # the user's own full config: keep outbounds/routing, replace inbounds
        j = json.loads(json.dumps(n['raw']))
        obs = j.get('outbounds') or [j.get('outbound')]
        if not any(o.get('tag') == 'block' for o in obs): obs = obs + [block]
        cfg = {'log': {'loglevel': 'warning'}, 'inbounds': [inbound], 'outbounds': obs}
        if j.get('dns'): cfg['dns'] = j['dns']
        r = j.get('routing') or {}
        cfg['routing'] = {'domainStrategy': r.get('domainStrategy', 'AsIs'), 'rules': rules + [x for x in r.get('rules', []) if isinstance(x, dict)]}
        return cfg
    return {'log': {'loglevel': 'warning'}, 'inbounds': [inbound], 'outbounds': [outbound(n, core), block],
            'routing': {'domainStrategy': 'AsIs', 'rules': rules}}


# ------------------------------------------------------------------ network checks
def free_port():
    k = socket.socket(); k.bind(('127.0.0.1', 0)); p = k.getsockname()[1]; k.close(); return p


def tcp_probe(nodes, timeout=2.5, workers=64, stop=None, want=0):
    """TCP connect time (ms) to every node's server, in parallel. Returns [(ms, node)] fastest first."""
    res, lock, it = [], threading.Lock(), iter(list(nodes))

    def work():
        while not (stop and stop()) and not (want and len(res) >= want):
            with lock:
                n = next(it, None)
            if n is None: return
            if n.get('net') in ('kcp', 'quic') or not n.get('port'): continue
            t0 = time.time()
            try:
                s = socket.create_connection((n['host'], n['port']), timeout=timeout); s.close()
                res.append((int((time.time() - t0) * 1000), n))
            except Exception:
                pass
    ths = [threading.Thread(target=work, daemon=True) for _ in range(min(workers, max(1, len(nodes))))]
    for t in ths: t.start()
    for t in ths: t.join()
    return sorted(res, key=lambda x: x[0])


def wait_listen(port, proc, secs=5.0):
    t0 = time.time()
    while time.time() - t0 < secs:
        if proc.poll() is not None: return False
        try:
            socket.create_connection(('127.0.0.1', port), timeout=0.4).close(); return True
        except OSError:
            time.sleep(0.12)
    return False


def tunnel_check(port, timeout=9.0):
    """Real end-to-end test: HTTP request through the SOCKS proxy. Returns round-trip ms, or None."""
    host = b'cp.cloudflare.com'
    t0 = time.time()
    try:
        sk = socket.create_connection(('127.0.0.1', port), timeout=timeout); sk.settimeout(timeout)
        sk.sendall(b'\x05\x01\x00')
        if sk.recv(2) != b'\x05\x00': return None
        sk.sendall(b'\x05\x01\x00\x03' + bytes([len(host)]) + host + (80).to_bytes(2, 'big'))
        r = sk.recv(10)
        if len(r) < 2 or r[1] != 0: return None
        sk.sendall(b'GET /generate_204 HTTP/1.1\r\nHost: cp.cloudflare.com\r\nConnection: close\r\n\r\n')
        data = sk.recv(64); sk.close()
        return int((time.time() - t0) * 1000) if data.startswith(b'HTTP/') else None
    except Exception:
        return None


def hint_from_log(lines):
    """Short human reason from the core's own log output."""
    t = '\n'.join(lines[-40:]).lower()
    for k, v in (('reality', 'this core cannot run Reality - install xray'), ('unknown config id', 'the core does not know this setting'),
                 ('failed to parse', 'the core rejected the config'), ('invalid', 'the config has an invalid value'),
                 ('address already in use', 'local port clash'), ('connection refused', 'the server refused the connection'),
                 ('i/o timeout', 'the server did not answer'), ('tls', 'TLS handshake failed'),
                 ('no such host', 'the server name does not resolve'), ('geoip', 'geoip.dat is missing')):
        if k in t: return v
    return ''


def spawn(core, cfg_path):
    """Start the core as the current user. It is tied to the caller (dies with it) when `setpriv` exists."""
    argv = core.argv(cfg_path)
    env = dict(os.environ)
    return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            text=True, bufsize=1, env=env, creationflags=0x08000000)  # CREATE_NO_WINDOW


def terminate(p, grace=1.5):
    if p is None or p.poll() is not None: return
    try: p.terminate()
    except Exception: return
    t0 = time.time()
    while p.poll() is None and time.time() - t0 < grace: time.sleep(0.05)
    if p.poll() is None:
        try: p.kill()
        except Exception: pass


def install_hint():
    return ('No xray/v2ray core found. Download xray-core for Windows from https://github.com/XTLS/Xray-core/releases '
            'and put xray.exe next to SUPERGO.exe (Reality / XHTTP configs need xray).')


def exit_info(port, timeout=8.0):
    """Where the tunnel exits: (country_code, country_name, ip) via a plain HTTP lookup through the proxy, or None."""
    host = b'ip-api.com'
    try:
        sk = socket.create_connection(('127.0.0.1', port), timeout=timeout); sk.settimeout(timeout)
        sk.sendall(b'\x05\x01\x00')
        if sk.recv(2) != b'\x05\x00': return None
        sk.sendall(b'\x05\x01\x00\x03' + bytes([len(host)]) + host + (80).to_bytes(2, 'big'))
        r = sk.recv(10)
        if len(r) < 2 or r[1] != 0: return None
        sk.sendall(b'GET /json/?fields=status,country,countryCode,query HTTP/1.1\r\nHost: ip-api.com\r\n'
                   b'Connection: close\r\n\r\n')
        buf = b''
        while len(buf) < 4096:
            d = sk.recv(2048)
            if not d: break
            buf += d
        sk.close()
        j = json.loads(buf.split(b'\r\n\r\n', 1)[1].decode('utf-8', 'replace').strip().split('\n')[-1])
        if j.get('status') == 'success': return j.get('countryCode', ''), j.get('country', ''), j.get('query', '')
    except Exception:
        pass
    return None


def load_builtin(path):
    """Bundled list: caps, host, port, security, uri per line -> light dicts (parsed fully only when used)."""
    import gzip
    out = []
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            for ln in f:
                p = ln.rstrip('\n').split('\t')
                if len(p) == 5:
                    out.append({'caps': '' if p[0] == '-' else p[0], 'host': p[1], 'port': int(p[2]), 'sec': p[3], 'uri': p[4],
                                'own': False, 'net': 'tcp'})
    except Exception:
        pass
    return out


def realize(light):
    """Light bundled entry -> full node (parses the stored link)."""
    n = parse_link(light['uri'], own=False)
    return n
