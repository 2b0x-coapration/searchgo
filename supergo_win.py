"""SUPERGO for Windows - flat dark browser, tabs in the sidebar, WebView2 engine (port of the Linux 1.8.0 app)."""
import sys, os, re, json, time, threading, http.server, socketserver, shutil, subprocess, ctypes
from urllib.parse import urlparse, parse_qs

HERE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def parse_args(a):
    prof, priv, urls, i = 'Default', False, [], 0
    while i < len(a):
        if a[i] == '--profile' and i + 1 < len(a): prof = re.sub(r'[^\w.-]', '_', a[i + 1]); i += 1
        elif a[i] in ('--private', '--incognito'): priv = True
        elif a[i] == '--version': print('SUPERGO 1.8.0'); sys.exit(0)
        elif not a[i].startswith('-'): urls.append(a[i])
        i += 1
    return prof, priv, urls


PROFILE, START_PRIVATE, START_URLS = parse_args(sys.argv[1:])

# ---------------------------------------------------------------- .NET / WebView2 (DLLs ship inside pywebview)
import webview                                           # only used for its bundled WebView2 DLLs
LIB = os.path.join(os.path.dirname(webview.__file__), 'lib')
for _d in (LIB, os.path.join(LIB, 'runtimes', 'win-x64', 'native'), os.path.join(LIB, 'win-x64')):
    if os.path.isdir(_d):
        sys.path.append(_d); os.environ['PATH'] = _d + os.pathsep + os.environ['PATH']
        try: os.add_dll_directory(_d)
        except Exception: pass
import clr
for _a in ('System.Windows.Forms', 'System.Drawing'): clr.AddReference(_a)
clr.AddReference(os.path.join(LIB, 'Microsoft.Web.WebView2.Core.dll'))
clr.AddReference(os.path.join(LIB, 'Microsoft.Web.WebView2.WinForms.dll'))
import System
from System import Action
from System.Drawing import Color, Font, FontStyle, Point, Size, Icon, Pen, Rectangle
from System.Drawing.Drawing2D import GraphicsPath
from System.Windows.Forms import (Application, Form, Panel, Button, TextBox, Label, FlowLayoutPanel, FlowDirection, ContextMenuStrip,
                                  ToolStripMenuItem, ToolStripSeparator, DockStyle, FlatStyle, Padding, Keys, Control, MessageBox,
                                  FormWindowState, FormBorderStyle, HorizontalAlignment, Cursors, SaveFileDialog, FolderBrowserDialog,
                                  RichTextBox, ScrollBars, AnchorStyles)
from Microsoft.Web.WebView2.WinForms import WebView2, CoreWebView2CreationProperties
from Microsoft.Web.WebView2.Core import CoreWebView2WebResourceContext, CoreWebView2DownloadState

import sg_pages as P
import sg_vpn
import v2core

P.init(PROFILE)
S, DB = P.S, P.DB
ICON_ICO = os.path.join(HERE, 'supergo.ico')


def C(h):
    h = h.lstrip('#'); return Color.FromArgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


BG_TOP, BG_SIDE, BG_PILL, BD_PILL, BD_SIDE = C('1b1b1b'), C('171717'), C('262626'), C('3a3a3a'), C('2e2e2e')
FG, FG_DIM, HOVER, CUR = C('ececec'), C('9a9a9a'), C('2c2c2c'), C('2e2e2e')
PRIV_TOP, PRIV_HOVER = C('1a1030'), C('2e2150')
UI = 'Segoe UI'
SYM = 'Segoe UI Symbol'

# ---------------------------------------------------------------- ad blocker (host list converted from the uBlock/EasyList build)
BLOCKED = set()


def load_blocklist():
    try:
        with open(os.path.join(P.BL_DIR, 'blocked_hosts.txt'), encoding='utf-8') as f:
            BLOCKED.update(x.strip() for x in f if x.strip())
    except Exception: pass


def host_blocked(host):
    h = (host or '').lower()
    while h:
        if h in BLOCKED: return True
        h = h.partition('.')[2]
    return False


# ---------------------------------------------------------------- supergo:// pages served from 127.0.0.1
_plock = threading.Lock()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        srv = self.server
        if self.headers.get('Host', '') != '127.0.0.1:%d' % srv.server_address[1]:
            self.send_error(403); return
        u = urlparse(self.path)
        name = u.path.strip('/').lower()
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        mime = 'text/html; charset=utf-8'
        with _plock:
            P.CUR_PRIV[0] = srv.private
            try:
                if name == 'logo.png':
                    data, mime = open(P.ICON, 'rb').read(), 'image/png'
                else:
                    fn = {'newtab': lambda: P.newtab_page(), 'history': lambda: P.history_page(q),
                          'bookmarks': lambda: P.bookmarks_page(q), 'settings': lambda: P.settings_page(q),
                          'about': P.about_page, 'welcome': lambda: P.welcome_page(q)}.get(name)
                    html = fn() if fn else P.page('Not found', '<h1>Unknown SUPERGO page: %s</h1>' % P.esc(name))
                    data = html.replace('supergo://', 'http://127.0.0.1:%d/' % srv.server_address[1]).encode('utf-8')
            except Exception as e:
                import traceback
                data = P.page('Error', '<h1>Internal page error</h1><pre>%s</pre>' % P.esc(traceback.format_exc())).encode('utf-8')
            finally:
                P.CUR_PRIV[0] = False
        self.send_response(200)
        self.send_header('Content-Type', mime); self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers(); self.wfile.write(data)


class PageServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def start_server(private):
    s = PageServer(('127.0.0.1', 0), Handler); s.private = private
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


SERVERS = {False: start_server(False), True: start_server(True)}

# ---------------------------------------------------------------- app-wide state
WINDOWS = []
CLOSED = []                          # recently closed tab URLs
DOWNLOADS = []                       # {'name','path','state','done','total'}
PROXY = ['']                         # '--proxy-server=...' while the VPN is on
UI_THREAD = [None]
DWM = ctypes.windll.dwmapi


def on_ui(fn):
    """Run fn on the UI thread (safe to call from any thread)."""
    w = next((w for w in WINDOWS if not w.form.IsDisposed), None)
    if w is None: return
    try: w.form.BeginInvoke(Action(fn))
    except Exception: pass


def pill_text(u):
    if not u: return ''
    if u.startswith('supergo://'): return ''
    h = urlparse(u).hostname
    return (h or u).replace('www.', '') if h else u


def flat_btn(text, tip, cb, dock, w=34, font=SYM, size=11):
    b = Button(); b.Text = text; b.Width = w; b.Dock = dock; b.FlatStyle = FlatStyle.Flat
    b.FlatAppearance.BorderSize = 0; b.FlatAppearance.MouseOverBackColor = HOVER; b.FlatAppearance.MouseDownBackColor = C('383838')
    b.ForeColor = C('d8d8d8'); b.BackColor = Color.Transparent; b.Font = Font(font, size); b.Cursor = Cursors.Hand
    b.TabStop = False; b.Click += lambda s, e: cb()
    from System.Windows.Forms import ToolTip
    tt = ToolTip(); tt.SetToolTip(b, tip); b._tt = tt
    return b


def round_region(ctrl, r):
    def fix(s, e):
        if ctrl.Width < 4 or ctrl.Height < 4: return
        gp = GraphicsPath(); d = r * 2
        gp.AddArc(0, 0, d, d, 180, 90); gp.AddArc(ctrl.Width - d, 0, d, d, 270, 90)
        gp.AddArc(ctrl.Width - d, ctrl.Height - d, d, d, 0, 90); gp.AddArc(0, ctrl.Height - d, d, d, 90, 90)
        gp.CloseFigure()
        ctrl.Region = System.Drawing.Region(gp)
    ctrl.Resize += fix; fix(None, None)


class Tab:
    def __init__(self, win, url):
        self.win, self.url, self.title, self.blocked, self.loading, self.zoom = win, url, 'New Tab', 0, False, 1.0
        self.wv = WebView2(); self.wv.Dock = DockStyle.Fill; self.wv.Visible = False
        self.wv.DefaultBackgroundColor = C('070707')
        cp = CoreWebView2CreationProperties()
        cp.UserDataFolder = win.udf
        if PROXY[0]: cp.AdditionalBrowserArguments = PROXY[0]
        self.wv.CreationProperties = cp
        self.ready, self.pending = False, url
        self.wv.CoreWebView2InitializationCompleted += self.on_init
        win.content.Controls.Add(self.wv)
        self.wv.EnsureCoreWebView2Async(None)

    # -- engine events
    def on_init(self, s, e):
        if not e.IsSuccess:
            MessageBox.Show('SUPERGO needs the Microsoft Edge WebView2 Runtime.\nInstall it from https://go.microsoft.com/fwlink/p/?LinkId=2124703\n\n' + str(e.InitializationException),
                            'SUPERGO'); return
        c = self.wv.CoreWebView2
        c.Settings.AreDefaultContextMenusEnabled = True
        c.Settings.IsStatusBarEnabled = False
        c.Settings.AreBrowserAcceleratorKeysEnabled = True
        c.SourceChanged += lambda s, e: self.win.sync(self)
        c.DocumentTitleChanged += self.on_title
        c.NavigationStarting += self.on_nav
        c.NavigationCompleted += self.on_done
        c.NewWindowRequested += self.on_newwin
        c.DownloadStarting += self.on_download
        c.PermissionRequested += self.on_perm
        c.AddWebResourceRequestedFilter('*', CoreWebView2WebResourceContext.All)
        c.WebResourceRequested += self.on_res
        try:
            ctl = getattr(self.wv, 'CoreWebView2Controller', None)
            if ctl is not None: ctl.AcceleratorKeyPressed += self.on_accel
        except Exception: pass
        self.ready = True
        if self.pending: self.go(self.pending); self.pending = None

    def go(self, url):
        url = self.win.internal(url)
        if not self.ready: self.pending = url; return
        try: self.wv.CoreWebView2.Navigate(url)
        except Exception: pass

    def real_url(self):
        try: return self.win.display(self.wv.CoreWebView2.Source) if self.ready else self.win.display(self.pending or self.url)
        except Exception: return self.url

    def on_title(self, s, e):
        try: self.title = self.wv.CoreWebView2.DocumentTitle or 'New Tab'
        except Exception: pass
        self.win.sync(self, side=True)

    def on_nav(self, s, e):
        u = e.Uri
        if u.startswith('supergo://'):
            e.Cancel = True; self.go(u); return
        self.loading = True; self.blocked = 0
        self.win.sync(self)

    def on_done(self, s, e):
        self.loading = False
        u = self.real_url()
        try:
            if not self.win.private and u.startswith('http'):
                DB.execute('INSERT INTO history(url,title,ts) VALUES(?,?,?) ON CONFLICT(url) DO UPDATE SET title=excluded.title,ts=excluded.ts,visits=visits+1',
                           (u, self.title, int(time.time())))
        except Exception: pass
        self.win.sync(self)

    def on_newwin(self, s, e):
        e.Handled = True
        self.win.new_tab(e.Uri)

    def on_perm(self, s, e):
        pass                                         # WebView2 shows its own permission prompt

    def on_res(self, s, e):
        try:
            if not S['adblock'] or not BLOCKED: return
            pu = urlparse(self.real_url() or '').hostname
            if pu and (pu in S['adblock_off'] or any(pu.endswith('.' + o) for o in S['adblock_off'])): return
            host = urlparse(e.Request.Uri).hostname
            if host in ('127.0.0.1', 'localhost') or not host_blocked(host): return
            e.Response = self.wv.CoreWebView2.Environment.CreateWebResourceResponse(None, 403, 'Blocked', '')
            self.blocked += 1
        except Exception: pass

    def on_download(self, s, e):
        try:
            d = S.get('download_dir') or P.default_download_dir()
            os.makedirs(d, exist_ok=True)
            name = os.path.basename(e.ResultFilePath) or 'download'
            base, ext = os.path.splitext(name); path, n = os.path.join(d, name), 1
            while os.path.exists(path): path = os.path.join(d, '%s (%d)%s' % (base, n, ext)); n += 1
            if S.get('ask_save'):
                dlg = SaveFileDialog(); dlg.FileName = name; dlg.InitialDirectory = d
                if int(dlg.ShowDialog()) != 1: e.Cancel = True; return
                path = dlg.FileName
            e.ResultFilePath = path; e.Handled = True
            ent = {'name': os.path.basename(path), 'path': path, 'state': 'downloading', 'done': 0, 'total': 0}
            DOWNLOADS.insert(0, ent)
            op = e.DownloadOperation

            def prog(s2, e2):
                try:
                    ent['done'] = int(op.BytesReceived); ent['total'] = int(op.TotalBytesToReceive or 0)
                except Exception: pass
                self.win.refresh_side()

            def st(s2, e2):
                ent['state'] = {1: 'done', 2: 'failed'}.get(int(op.State), 'downloading')
                self.win.refresh_side()
            op.BytesReceivedChanged += prog; op.StateChanged += st
            self.win.refresh_side()
        except Exception: pass

    def on_accel(self, s, e):
        try:
            if int(e.KeyEventKind) not in (0, 2): return           # key down / system key down
            vk = int(e.VirtualKey)
            if self.win.hotkey(vk, int(Control.ModifierKeys)): e.Handled = True
        except Exception: pass

    def dispose(self):
        try: self.win.content.Controls.Remove(self.wv); self.wv.Dispose()
        except Exception: pass


class BrowserWin:
    def __init__(self, private=False):
        self.private, self.tabs, self.cur, self.edit = private, [], None, False
        self.srv = SERVERS[private]; self.base = 'http://127.0.0.1:%d/' % self.srv.server_address[1]
        self.udf = os.path.join(P.CONF, 'webview-private-%d' % os.getpid()) if private else os.path.join(P.CONF, 'webview')
        os.makedirs(self.udf, exist_ok=True)
        f = self.form = Form(); f.Text = 'SUPERGO' + (' (Private)' if private else ''); f.Size = Size(1280, 820)
        f.BackColor = C('070707'); f.KeyPreview = True; f.StartPosition = System.Windows.Forms.FormStartPosition.CenterScreen
        try: f.Icon = Icon(ICON_ICO)
        except Exception: pass
        self.dark_titlebar()
        top_bg = PRIV_TOP if private else BG_TOP

        # content area + thin load bar
        self.content = Panel(); self.content.Dock = DockStyle.Fill; self.content.BackColor = C('070707')
        self.bar = Panel(); self.bar.Height = 2; self.bar.Dock = DockStyle.Top; self.bar.BackColor = C('8ab4ff'); self.bar.Visible = False
        self.content.Controls.Add(self.bar)

        # sidebar
        self.side = Panel(); self.side.Width = 250; self.side.Dock = DockStyle.Left; self.side.BackColor = BG_SIDE
        edge = Panel(); edge.Width = 1; edge.Dock = DockStyle.Right; edge.BackColor = BD_SIDE; self.side.Controls.Add(edge)
        self.flow = FlowLayoutPanel(); self.flow.Dock = DockStyle.Fill; self.flow.FlowDirection = FlowDirection.TopDown
        self.flow.WrapContents = False; self.flow.AutoScroll = True; self.flow.Padding = Padding(10, 8, 0, 8); self.flow.BackColor = BG_SIDE
        self.side.Controls.Add(self.flow); self.flow.BringToFront()
        self.side.Visible = bool(S.get('side', True))

        # top bar
        top = Panel(); top.Height = 48; top.Dock = DockStyle.Top; top.BackColor = top_bg; top.Padding = Padding(8, 0, 8, 0)
        self.b_vpn = flat_btn('VPN', 'VPN', self.show_vpn, DockStyle.Right, 44, UI, 9)
        self.b_ubo = flat_btn('\U0001F6E1', 'uBlock - ad & tracker blocker', self.show_ubo, DockStyle.Right, 36)
        self.b_new = flat_btn('+', 'New tab (Ctrl+T)', lambda: self.new_tab(), DockStyle.Right, 36, UI, 14)
        self.b_side = flat_btn('\u25AF', 'Sidebar (Ctrl+Shift+L)', self.toggle_side, DockStyle.Left, 36)
        self.b_back = flat_btn('\u2039', 'Back (Alt+Left)', lambda: self.back(), DockStyle.Left, 32, UI, 16)
        self.b_fwd = flat_btn('\u203A', 'Forward (Alt+Right)', lambda: self.fwd(), DockStyle.Left, 32, UI, 16)
        wrap = Panel(); wrap.Dock = DockStyle.Fill; wrap.Padding = Padding(8, 8, 8, 8); wrap.BackColor = top_bg
        self.pill = Panel(); self.pill.Dock = DockStyle.Fill; self.pill.BackColor = BG_PILL; self.pill.Padding = Padding(8, 0, 4, 0)
        round_region(self.pill, 8)
        self.pill.Paint += lambda s, e: e.Graphics.DrawRectangle(Pen(BD_PILL), 0, 0, s.Width - 1, s.Height - 1)
        self.b_menu = flat_btn('\u2022\u2022\u2022', 'Menu', lambda: self.show_menu(), DockStyle.Right, 34, UI, 8)
        self.b_rel = flat_btn('\u27F3', 'Reload / Stop', lambda: self.reload_stop(), DockStyle.Right, 28)
        self.b_star = flat_btn('\u2606', 'Bookmark (Ctrl+D)', lambda: self.bookmark(), DockStyle.Right, 28)
        self.addr = TextBox(); self.addr.BorderStyle = getattr(System.Windows.Forms.BorderStyle, 'None'); self.addr.BackColor = BG_PILL; self.addr.ForeColor = FG
        self.addr.Font = Font(UI, 10); self.addr.TextAlign = HorizontalAlignment.Center
        self.addr.Anchor = AnchorStyles.Left | AnchorStyles.Right
        self.addr_holder = Panel(); self.addr_holder.Dock = DockStyle.Fill; self.addr_holder.BackColor = BG_PILL
        self.addr_holder.Controls.Add(self.addr)
        self.addr_holder.Resize += lambda s, e: self.layout_addr()
        self.addr.KeyDown += self.on_addr_key
        self.addr.Enter += lambda s, e: self.begin_edit()
        self.addr.Leave += lambda s, e: self.end_edit()
        for w in (self.addr_holder, self.b_star, self.b_rel, self.b_menu): self.pill.Controls.Add(w)
        self.addr_holder.BringToFront()
        wrap.Controls.Add(self.pill)
        for w in (wrap, self.b_new, self.b_ubo, self.b_vpn, self.b_fwd, self.b_back, self.b_side): top.Controls.Add(w)
        wrap.BringToFront()
        self.top = top

        f.Controls.Add(self.content); f.Controls.Add(self.side); f.Controls.Add(top)
        f.KeyDown += lambda s, e: self.on_key(e)
        f.FormClosing += lambda s, e: self.on_closing()
        f.FormClosed += lambda s, e: self.on_closed()
        WINDOWS.append(self)
        self.layout_addr()

    # -- helpers
    def dark_titlebar(self):
        try:
            h = self.form.Handle.ToInt64()
            v = ctypes.c_int(1)
            DWM.DwmSetWindowAttribute(ctypes.c_void_p(h), 20, ctypes.byref(v), 4)                 # immersive dark mode
            col = ctypes.c_int(0x1a1a1a if not self.private else 0x30101a)                          # BGR caption colour
            DWM.DwmSetWindowAttribute(ctypes.c_void_p(h), 35, ctypes.byref(col), 4)
        except Exception: pass

    def layout_addr(self):
        h = self.addr_holder.Height
        self.addr.Height = self.addr.PreferredHeight
        self.addr.Location = Point(6, max(0, (h - self.addr.Height) // 2)); self.addr.Width = max(20, self.addr_holder.Width - 12)

    def internal(self, u):
        m = re.match(r'^supergo://([^/?#]*)(.*)$', u or '')
        return self.base + m.group(1) + m.group(2) if m else u

    def display(self, u):
        return 'supergo://' + u[len(self.base):] if (u or '').startswith(self.base) else (u or '')

    def cur_url(self): return self.cur.real_url() if self.cur else ''

    # -- tabs
    def new_tab(self, url=None, switch=True):
        t = Tab(self, url or S.get('homepage') or 'supergo://newtab')
        self.tabs.append(t)
        if switch or self.cur is None: self.select(t)
        self.refresh_side()
        return t

    def select(self, t):
        self.cur = t
        for x in self.tabs: x.wv.Visible = (x is t)
        t.wv.BringToFront(); self.bar.BringToFront()
        self.sync(t, force=True); self.refresh_side()
        if t.real_url().startswith('supergo://newtab'): self.addr.Focus()
        else: t.wv.Focus()

    def close_tab(self, t):
        if t.real_url().startswith('http') and not self.private: CLOSED.append(t.real_url())
        i = self.tabs.index(t); self.tabs.remove(t); t.dispose()
        if not self.tabs:
            self.form.Close(); return
        if t is self.cur: self.select(self.tabs[min(i, len(self.tabs) - 1)])
        self.refresh_side()

    def restore_closed(self):
        if CLOSED: self.new_tab(CLOSED.pop())

    def back(self):
        try:
            if self.cur.wv.CoreWebView2.CanGoBack: self.cur.wv.CoreWebView2.GoBack()
        except Exception: pass

    def fwd(self):
        try:
            if self.cur.wv.CoreWebView2.CanGoForward: self.cur.wv.CoreWebView2.GoForward()
        except Exception: pass

    def reload_stop(self):
        try:
            c = self.cur.wv.CoreWebView2
            c.Stop() if self.cur.loading else c.Reload()
        except Exception: pass

    # -- address bar
    def begin_edit(self):
        self.edit = True; self.addr.TextAlign = HorizontalAlignment.Left
        u = self.cur_url(); self.addr.Text = '' if u == 'supergo://newtab' else u
        self.addr.SelectAll()

    def end_edit(self):
        self.edit = False; self.addr.TextAlign = HorizontalAlignment.Center; self.sync(self.cur, force=True)

    def on_addr_key(self, s, e):
        if e.KeyCode == Keys.Return:
            e.SuppressKeyPress = True
            txt = self.addr.Text.strip()
            if txt and self.cur:
                self.cur.go(txt if txt.startswith('supergo://') else P.to_url(txt))
                self.cur.wv.Focus()
        elif e.KeyCode == Keys.Escape:
            self.cur.wv.Focus()

    def sync(self, t, force=False, side=False):
        if t is None or t is not self.cur and not side: 
            if side: self.refresh_side()
            return
        u = self.cur_url()
        if not self.edit:
            self.addr.Text = pill_text(u)
        loading = t.loading
        self.b_rel.Text = '\u2715' if loading else '\u27F3'
        self.bar.Visible = loading
        try:
            c = t.wv.CoreWebView2
            self.b_back.Enabled = bool(c.CanGoBack); self.b_fwd.Visible = bool(c.CanGoForward)
        except Exception: pass
        marked = bool(u) and DB.execute('SELECT 1 FROM bookmarks WHERE url=?', (u,)).fetchone() is not None
        self.b_star.Text = '\u2605' if marked else '\u2606'; self.b_star.ForeColor = C('ffd24a') if marked else C('d8d8d8')
        self.b_ubo.ForeColor = Color.White if S['adblock'] else C('777777')
        sel = sg_vpn.STATE['state']
        self.b_vpn.ForeColor = {'on': C('37e06a'), 'busy': C('ffb340')}.get(sel, C('d8d8d8'))
        t_title = t.title if t.title and not u.startswith('supergo://newtab') else 'New Tab'
        self.form.Text = (t_title + ' - SUPERGO') + (' (Private)' if self.private else '')
        self.refresh_side()

    # -- sidebar
    def refresh_side(self):
        try: self.form.BeginInvoke(Action(self._refresh_side))
        except Exception: pass

    def _refresh_side(self):
        if self.form.IsDisposed or not self.side.Visible: return
        fl = self.flow
        fl.SuspendLayout()
        for c in list(fl.Controls): fl.Controls.Remove(c); c.Dispose()
        W = 232

        def head(t):
            l = Label(); l.Text = t.upper(); l.ForeColor = FG_DIM; l.Font = Font(UI, 7.5, FontStyle.Bold); l.AutoSize = False
            l.Size = Size(W, 24); l.TextAlign = System.Drawing.ContentAlignment.BottomLeft; l.Padding = Padding(6, 0, 0, 3)
            fl.Controls.Add(l)

        def item(text, cb, close=None, cur=False):
            r = Panel(); r.Size = Size(W, 32); r.Margin = Padding(0, 1, 0, 1); r.BackColor = CUR if cur else BG_SIDE
            round_region(r, 8)
            lb = Label(); lb.Text = text; lb.ForeColor = FG; lb.Font = Font(UI, 9.5); lb.Dock = DockStyle.Fill
            lb.TextAlign = System.Drawing.ContentAlignment.MiddleLeft; lb.Padding = Padding(8, 0, 0, 0); lb.AutoEllipsis = True; lb.Cursor = Cursors.Hand
            lb.BackColor = Color.Transparent
            lb.Click += lambda s, e: cb()
            if close:
                x = flat_btn('\u2715', 'Close tab', close, DockStyle.Right, 28, SYM, 8); r.Controls.Add(x)
            r.Controls.Add(lb); lb.BringToFront()
            if not cur:
                lb.MouseEnter += lambda s, e: setattr(r, 'BackColor', C('242424'))
                lb.MouseLeave += lambda s, e: setattr(r, 'BackColor', BG_SIDE)
            fl.Controls.Add(r)

        head('Tabs')
        item('\uFF0B  New tab', lambda: self.new_tab())
        for t in list(self.tabs):
            name = t.title if t.title and t.real_url() != 'supergo://newtab' else 'New Tab'
            item(name, lambda t=t: self.select(t), lambda t=t: self.close_tab(t), t is self.cur)
        item('\u2699  Settings', lambda: self.new_tab('supergo://settings'))
        if DOWNLOADS:
            head('Downloads')
            for d in DOWNLOADS[:6]:
                pct = ' %d%%' % (100 * d['done'] // d['total']) if d['state'] == 'downloading' and d['total'] else ''
                mark = {'done': '\u2713 ', 'failed': '\u2717 '}.get(d['state'], '\u2193 ')
                item(mark + d['name'] + pct, lambda d=d: (os.startfile(d['path']) if d['state'] == 'done' and os.path.exists(d['path']) else None))
        rows = DB.execute('SELECT url,title FROM bookmarks ORDER BY ts DESC LIMIT 30').fetchall()
        if rows:
            head('Bookmarks')
            for u, t in rows: item(t or u, lambda u=u: self.cur.go(u))
        fl.ResumeLayout()

    def toggle_side(self):
        self.side.Visible = not self.side.Visible
        S['side'] = self.side.Visible; S.save(); self.refresh_side()

    # -- bookmarks
    def bookmark(self):
        u = self.cur_url()
        if not u.startswith('http'): return
        if DB.execute('SELECT 1 FROM bookmarks WHERE url=?', (u,)).fetchone(): DB.execute('DELETE FROM bookmarks WHERE url=?', (u,))
        else: DB.execute('INSERT OR REPLACE INTO bookmarks(url,title,folder,ts) VALUES(?,?,?,?)', (u, self.cur.title or u, 'Bookmarks', int(time.time())))
        self.sync(self.cur, force=True)

    # -- menu
    def show_menu(self):
        m = ContextMenuStrip(); m.BackColor = C('1f1f1f'); m.ForeColor = FG; m.ShowImageMargin = False
        def add(text, cb, key=''):
            it = ToolStripMenuItem(text); it.ShortcutKeyDisplayString = key
            it.Click += lambda s, e: cb(); m.Items.Add(it)
        add('New tab', lambda: self.new_tab(), 'Ctrl+T')
        add('New window', lambda: open_window(), 'Ctrl+N')
        add('New private window', lambda: open_window(True), 'Ctrl+Shift+N')
        m.Items.Add(ToolStripSeparator())
        add('Bookmarks', lambda: self.new_tab('supergo://bookmarks'))
        add('History', lambda: self.new_tab('supergo://history'), 'Ctrl+H')
        add('Downloads folder', lambda: os.startfile(S.get('download_dir') or P.default_download_dir()))
        m.Items.Add(ToolStripSeparator())
        add('Zoom in', lambda: self.zoom(.1), 'Ctrl++'); add('Zoom out', lambda: self.zoom(-.1), 'Ctrl+-'); add('Reset zoom', lambda: self.zoom(0), 'Ctrl+0')
        add('Print…', lambda: self.print_page(), 'Ctrl+P')
        add('Full screen', lambda: self.fullscreen(), 'F11')
        m.Items.Add(ToolStripSeparator())
        add('Settings', lambda: self.new_tab('supergo://settings'))
        add('Welcome tour', lambda: self.new_tab('supergo://welcome'))
        add('About SUPERGO', lambda: self.new_tab('supergo://about'))
        m.Show(self.b_menu, Point(self.b_menu.Width - 200, self.b_menu.Height))

    def zoom(self, d):
        try:
            t = self.cur; t.zoom = 1.0 if d == 0 else max(.3, min(5.0, t.zoom + d)); t.wv.ZoomFactor = t.zoom
        except Exception: pass

    def print_page(self):
        try: self.cur.wv.CoreWebView2.ShowPrintUI()
        except Exception: pass

    def fullscreen(self):
        f = self.form
        if f.FormBorderStyle == getattr(FormBorderStyle, 'None'):
            f.FormBorderStyle = FormBorderStyle.Sizable; f.WindowState = FormWindowState.Normal; self.top.Visible = True
        else:
            f.FormBorderStyle = getattr(FormBorderStyle, 'None'); f.WindowState = FormWindowState.Maximized; self.top.Visible = False

    # -- uBlock + VPN panels
    def show_ubo(self):
        host = urlparse(self.cur_url()).hostname or ''
        off = host in S['adblock_off']
        m = ContextMenuStrip(); m.BackColor = C('1f1f1f'); m.ForeColor = FG
        def add(t, cb):
            it = ToolStripMenuItem(t); it.Click += lambda s, e: cb(); m.Items.Add(it)
        add('uBlock is %s (%d rules)' % ('ON' if S['adblock'] else 'OFF', len(BLOCKED)),
            lambda: (S.update(adblock=not S['adblock']), S.save(), self.sync(self.cur, force=True)))
        add('Blocked on this page: %d' % (self.cur.blocked if self.cur else 0), lambda: None)
        if host and not host.startswith('127.'):
            def flip():
                lst = S['adblock_off']
                (lst.remove(host) if off else lst.append(host)); S.save(); self.cur.wv.CoreWebView2.Reload()
            add(('Turn blocking ON for %s' if off else 'Turn blocking OFF for %s') % host, flip)
        m.Show(self.b_ubo, Point(0, self.b_ubo.Height))

    def show_vpn(self):
        VpnDialog(self).show()

    # -- keys
    def hotkey(self, vk, mods):
        m = int(mods); ctrl, shift, alt = bool(m & int(Keys.Control)), bool(m & int(Keys.Shift)), bool(m & int(Keys.Alt))
        if ctrl and shift and vk == int(Keys.T): self.restore_closed()
        elif ctrl and shift and vk == int(Keys.N): open_window(True)
        elif ctrl and shift and vk == int(Keys.L): self.toggle_side()
        elif ctrl and vk == int(Keys.T): self.new_tab()
        elif ctrl and vk == int(Keys.N): open_window()
        elif ctrl and vk == int(Keys.W): self.close_tab(self.cur)
        elif ctrl and vk in (int(Keys.L),): self.addr.Focus()
        elif vk == int(Keys.F6): self.addr.Focus()
        elif (ctrl and vk == int(Keys.R)) or vk == int(Keys.F5): self.reload_stop() if self.cur.loading else self.cur.wv.CoreWebView2.Reload()
        elif ctrl and vk == int(Keys.D): self.bookmark()
        elif ctrl and vk == int(Keys.H): self.new_tab('supergo://history')
        elif ctrl and vk == int(Keys.P): self.print_page()
        elif ctrl and vk == int(Keys.Tab):
            i = (self.tabs.index(self.cur) + (-1 if shift else 1)) % len(self.tabs); self.select(self.tabs[i])
        elif ctrl and vk in (int(Keys.Oemplus), int(Keys.Add)): self.zoom(.1)
        elif ctrl and vk in (int(Keys.OemMinus), int(Keys.Subtract)): self.zoom(-.1)
        elif ctrl and vk == int(Keys.D0): self.zoom(0)
        elif alt and vk == int(Keys.Left): self.back()
        elif alt and vk == int(Keys.Right): self.fwd()
        elif vk == int(Keys.F11): self.fullscreen()
        else: return False
        return True

    def on_key(self, e):
        if self.hotkey(int(e.KeyCode), int(e.Modifiers)): e.Handled = True; e.SuppressKeyPress = True

    # -- lifecycle
    def on_closing(self):
        if not self.private: save_session()

    def on_closed(self):
        if self in WINDOWS: WINDOWS.remove(self)
        for t in list(self.tabs): t.dispose()
        if self.private:
            threading.Thread(target=lambda: (time.sleep(2), shutil.rmtree(self.udf, ignore_errors=True)), daemon=True).start()
        if not WINDOWS:
            sg_vpn.stop(); Application.ExitThread()

    def rebuild_engines(self):
        """The VPN proxy is a browser argument, so every tab's engine is recreated with the new proxy."""
        urls = [t.real_url() for t in self.tabs]; idx = self.tabs.index(self.cur) if self.cur in self.tabs else 0
        for t in list(self.tabs): t.dispose()
        self.tabs, self.cur = [], None
        for u in urls: self.new_tab(u, switch=False)
        self.select(self.tabs[min(idx, len(self.tabs) - 1)])

    def show(self):
        self.form.Show()


class VpnDialog:
    def __init__(self, win): self.win = win

    def show(self):
        f = Form(); f.Text = 'SUPERGO VPN'; f.Size = Size(520, 470); f.BackColor = C('171717'); f.ForeColor = FG
        f.StartPosition = System.Windows.Forms.FormStartPosition.CenterParent; f.FormBorderStyle = FormBorderStyle.FixedDialog; f.MaximizeBox = False
        try: f.Icon = Icon(ICON_ICO)
        except Exception: pass
        self.f = f
        t = Label(); t.Text = 'Browser-only VPN'; t.Font = Font(UI, 14, FontStyle.Bold); t.Location = Point(18, 14); t.AutoSize = True; f.Controls.Add(t)
        self.st = Label(); self.st.Location = Point(20, 50); self.st.Size = Size(470, 44); self.st.ForeColor = C('bdbdbd'); f.Controls.Add(self.st)
        a = Label(); a.Text = 'Paste a vless / vmess / trojan / ss link, a subscription, or a v2ray JSON config:'
        a.Location = Point(20, 100); a.Size = Size(470, 20); f.Controls.Add(a)
        self.box = TextBox(); self.box.Multiline = True; self.box.ScrollBars = ScrollBars.Vertical; self.box.Location = Point(20, 124); self.box.Size = Size(470, 150)
        self.box.BackColor = C('262626'); self.box.ForeColor = FG; self.box.BorderStyle = System.Windows.Forms.BorderStyle.FixedSingle; f.Controls.Add(self.box)

        def mk(text, x, w, cb, accent=False):
            b = Button(); b.Text = text; b.Location = Point(x, 290); b.Size = Size(w, 36); b.FlatStyle = FlatStyle.Flat
            b.FlatAppearance.BorderColor = C('444444'); b.BackColor = C('2e5d3a') if accent else C('262626'); b.ForeColor = FG
            b.Click += lambda s, e: cb(); f.Controls.Add(b)
        mk('Connect with my link', 20, 170, self.mine, True); mk('Automatic', 198, 120, self.auto); mk('Turn off', 326, 100, self.off)
        n = Label(); n.Location = Point(20, 340); n.Size = Size(470, 70); n.ForeColor = C('8a8a8a')
        n.Text = ('Needs xray.exe (or v2ray.exe) next to SUPERGO.exe - get it from github.com/XTLS/Xray-core/releases. '
                  'Only SUPERGO goes through the VPN; the rest of the PC is untouched. If the tunnel drops, SUPERGO pauses instead of leaking.')
        f.Controls.Add(n)
        f.FormClosed += lambda s, e: sg_vpn.on_change(on_vpn_change)
        sg_vpn.on_change(lambda: (on_vpn_change(), on_ui(self.upd)))
        self.upd(); f.Show(self.win.form)

    def upd(self):
        try:
            s = sg_vpn.STATE
            self.st.Text = {'on': 'ON - ' + s['name'], 'busy': 'Working…', 'off': 'OFF'}[s['state']] + ('\n' + s['msg'] if s['msg'] else '')
        except Exception: pass

    def mine(self):
        nodes = v2core.parse_many(self.box.Text, own=True)
        if not nodes: self.st.Text = 'OFF\nThat is not a valid link, subscription or config.'; return
        sg_vpn.connect(P.CONF, nodes)

    def auto(self): sg_vpn.connect(P.CONF, None, os.path.join(HERE, 'servers.tsv.gz'))
    def off(self): sg_vpn.stop()


_last_proxy = ['']


def on_vpn_change():
    """VPN state changed: restart the web engines when the proxy port changes."""
    s = sg_vpn.STATE
    arg = '--proxy-server=socks5://127.0.0.1:%d' % s['port'] if s['state'] == 'on' and s['port'] else ''
    def apply():
        for w in list(WINDOWS):
            w.sync(w.cur, force=True)
        if arg != _last_proxy[0]:
            _last_proxy[0] = arg; PROXY[0] = arg
            for w in list(WINDOWS):
                if w.tabs: w.rebuild_engines()
    on_ui(apply)


# ---------------------------------------------------------------- session / windows
SESSION = lambda: os.path.join(P.CONF, 'session.json')


def save_session():
    try:
        wins = [[t.real_url() for t in w.tabs if t.real_url()] for w in WINDOWS if not w.private]
        P.write_json(SESSION(), {'wins': [w for w in wins if w]})
    except Exception: pass


def clear_site_data(secs):
    try:
        w = WINDOWS[0]; c = w.cur.wv.CoreWebView2
        c.Profile.ClearBrowsingDataAsync()
    except Exception: pass


def open_window(private=False, urls=None):
    w = BrowserWin(private)
    w.show()
    for u in (urls or ['supergo://newtab']): w.new_tab(u)
    if private and not urls: w.cur.go('supergo://newtab')
    return w


def main():
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('SUPERGO.Browser')     # taskbar uses our icon, not python's
    Application.EnableVisualStyles()
    threading.Thread(target=load_blocklist, daemon=True).start()
    P.HOOKS['clear'] = clear_site_data
    sg_vpn.on_change(on_vpn_change)
    P.HOOKS['settings'] = lambda: on_ui(lambda: [w.sync(w.cur, force=True) for w in WINDOWS])
    first = True
    if not START_PRIVATE and not START_URLS and S.get('restore'):
        try:
            sess = json.load(open(SESSION()))
            for urls in sess.get('wins', []):
                open_window(False, urls); first = False
        except Exception: pass
    if first:
        open_window(START_PRIVATE, START_URLS or None)
    if not S.get('welcome_done') and not START_PRIVATE:
        WINDOWS[0].new_tab('supergo://welcome')
    Application.Run()


if __name__ == '__main__':
    main()
