"""Browser-only VPN for SUPERGO (Windows): runs xray/v2ray as the current user and exposes a local SOCKS5 proxy."""
import os, json, threading, time, random
import v2core

STATE = {'state': 'off', 'msg': '', 'port': 0, 'gen': 0, 'name': '', 'proc': None}
_cb = [lambda: None]          # called (from a worker thread) whenever STATE changes


def on_change(fn): _cb[0] = fn


def _set(gen, **kw):
    if STATE['gen'] != gen: return
    STATE.update(kw)
    try: _cb[0]()
    except Exception: pass


def stop():
    STATE['gen'] += 1
    p, STATE['proc'] = STATE['proc'], None
    v2core.terminate(p)
    STATE.update(state='off', msg='', port=0, name='')
    try: _cb[0]()
    except Exception: pass


def _try(core, n, gen, done, lock, hints, vdir):
    port = v2core.free_port()
    cfgp = os.path.join(vdir, 'cfg-%d.json' % port)
    with open(cfgp, 'w') as f: json.dump(v2core.build_config(n, port, core), f)
    proc, log = None, []
    try:
        proc = v2core.spawn(core, cfgp)

        def reader():
            for ln in proc.stdout:
                log.append(ln.rstrip()); del log[:-120]
        threading.Thread(target=reader, daemon=True).start()
        ms = None
        if v2core.wait_listen(port, proc, 6.0):
            try: os.remove(cfgp)
            except OSError: pass
            ms = v2core.tunnel_check(port, 9.0)
        if ms is not None and STATE['gen'] == gen:
            with lock:
                if done.is_set(): ms = None
                else: done.set()
        else: ms = None
        if ms is None:
            h = v2core.hint_from_log(log)
            if h: hints.append(h)
            v2core.terminate(proc); return False
        STATE['proc'] = proc
        _set(gen, state='on', port=port, name=n['name'][:40], msg='Connected (%d ms)' % ms)
        while proc.poll() is None:
            if STATE['gen'] != gen: v2core.terminate(proc); return True
            time.sleep(0.5)
        _set(gen, state='off', port=0, msg='The tunnel dropped - browsing paused until you reconnect or turn the VPN off')
        return True
    except Exception:
        v2core.terminate(proc); return False
    finally:
        try: os.remove(cfgp)
        except OSError: pass


def connect(conf_dir, mine_nodes=None, builtin_path=None):
    """Start connecting. mine_nodes: nodes from the user's own link/config; None = Automatic (bundled public servers)."""
    stop()
    STATE['gen'] += 1; gen = STATE['gen']
    _set(gen, state='busy', msg='Looking for xray / v2ray…')
    vdir = os.path.join(conf_dir, 'vpn'); os.makedirs(vdir, exist_ok=True)

    def work():
        core = v2core.find_core()
        if not core: return _set(gen, state='off', msg=v2core.install_hint())
        if mine_nodes:
            cands = [n for n in mine_nodes if core.supports(n.get('caps', ''))]
            if not cands: return _set(gen, state='off', msg='That config needs xray (Reality / XHTTP / Vision).')
        else:
            _set(gen, msg='Loading the server list…')
            pool = [x for x in v2core.load_builtin(builtin_path) if core.supports(x['caps'])]
            if not pool: return _set(gen, state='off', msg='No bundled server is compatible with %s - use xray.' % core.kind)
            sec = [x for x in pool if x['sec'] != 'none']; plain = [x for x in pool if x['sec'] == 'none']
            random.shuffle(sec); random.shuffle(plain)
            sample = sec[:280] + plain[:80]; random.shuffle(sample)
            _set(gen, msg='Testing %d servers…' % len(sample))
            reach = v2core.tcp_probe(sample, timeout=2.0, stop=lambda: STATE['gen'] != gen, want=14)
            if STATE['gen'] != gen: return
            if not reach: return _set(gen, state='off', msg='No server answered - check your internet connection.')
            cands = [x for x in (v2core.realize(n) for _ms, n in reach) if x]
        queue, done, lock, hints = list(cands), threading.Event(), threading.Lock(), []
        total = len(cands)

        def attempt():
            while STATE['gen'] == gen and not done.is_set():
                with lock:
                    n = queue.pop(0) if queue else None
                    idx = total - len(queue)
                if n is None: return
                _set(gen, msg='Connecting… (%d/%d) %s' % (idx, total, n['name'][:30]))
                if _try(core, n, gen, done, lock, hints, vdir): return
        ths = [threading.Thread(target=attempt, daemon=True) for _ in range(min(3, total))]
        for t in ths: t.start()
        while STATE['gen'] == gen and not done.is_set() and any(t.is_alive() for t in ths): time.sleep(0.2)
        if STATE['gen'] == gen and not done.is_set():
            _set(gen, state='off', msg=hints[-1] if hints else 'Could not connect - try again or add your own link.')
    threading.Thread(target=work, daemon=True).start()
