"""SUPERGO for Windows - internal pages, settings, history (ported from the Linux 1.8.0 source)."""
import os, sys, re, json, time, html, sqlite3, secrets, hashlib, gzip
from urllib.parse import urlparse, parse_qs, quote_plus

VERSION = '1.8.0'
RES = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
APPDATA = os.environ.get('APPDATA') or os.path.expanduser('~')
TOKEN = secrets.token_hex(8)
APP = None
HOOKS = {'settings': lambda: None, 'clear': lambda secs: None}
BL = {'state': 'idle', 'filters': [], 'meta': {}, 'note': ''}

ENGINES = {'Google': 'https://www.google.com/search?q=%s',
           'Bing': 'https://www.bing.com/search?q=%s',
           'DuckDuckGo': 'https://duckduckgo.com/?q=%s',
           'searchgo!': 'https://searchgo.base44.app/?q=%s'}
DEFAULTS = {'engine': 'Google', 'custom_engine': 'https://www.google.com/search?q=%s',
            'homepage': 'supergo://newtab', 'restore': True, 'theme': 'dark',
            'download_dir': '', 'ask_save': False, 'perms': {}, 'disabled_ext': [],
            'adblock': True, 'adblock_off': [], 'vpn': {'sel': 'auto', 'mine': []}, 'anim': True, 'side': True, 'welcome_done': False, 'ui_v': 8}

BL_DIR = RES
ICON = os.path.join(RES, 'supergo.png')
CONF = DATA = CACHE = SPATH = DB = S = None
Win = type('Win', (), {})


def init(profile='Default'):
    """Create the profile folders, settings and database. Must be called once at start-up."""
    global CONF, DATA, CACHE, SPATH, DB, S
    profile = re.sub(r'[^\w.-]', '_', profile)
    CONF = os.path.join(APPDATA, 'SUPERGO', profile)
    DATA, CACHE = os.path.join(CONF, 'data'), os.path.join(CONF, 'cache')
    for d in (CONF, DATA, CACHE): os.makedirs(d, exist_ok=True)
    SPATH = os.path.join(CONF, 'settings.json')
    S = Settings()
    DB = sqlite3.connect(os.path.join(CONF, 'browser.db'), check_same_thread=False, isolation_level=None)
    DB.execute('PRAGMA journal_mode=WAL')
    DB.executescript("""
CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,url TEXT UNIQUE,title TEXT,ts INTEGER,visits INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS bookmarks(id INTEGER PRIMARY KEY,url TEXT UNIQUE,title TEXT,folder TEXT DEFAULT 'Bookmarks',ts INTEGER);
""")


def default_download_dir():
    d = os.path.join(os.path.expanduser('~'), 'Downloads')
    return d if os.path.isdir(d) else os.path.expanduser('~')


def write_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(obj, f); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def anim_on(): return bool(S.get('anim', True))
def apply_theme(): pass
def apply_all_ext(): pass
def bl_init(): pass


def bl_meta():
    try: return json.load(open(os.path.join(BL_DIR, 'blocklist.meta.json')))
    except Exception: return {}


class Settings(dict):
    def __init__(self):
        super().__init__(json.loads(json.dumps(DEFAULTS)))
        try:
            self.update(json.load(open(SPATH)))
        except Exception:
            pass
        if self.get('ui_v', 1) < 5:          # 1.5: VPN is now v2ray/xray with the user's own configs
            self['vpn'] = {'sel': 'auto', 'mine': []}
            self['ui_v'] = 5
        if self.get('ui_v', 1) < 8:          # 1.7: flat dark UI, tabs live in the sidebar (always shown by default)
            self['side'] = True; self['ui_v'] = 8
        for k in ('engine', 'custom_engine', 'homepage', 'download_dir'):     # repair damaged settings.json values
            if not isinstance(self.get(k), str): self[k] = DEFAULTS[k]
        for k in ('restore', 'ask_save', 'adblock', 'anim', 'side', 'welcome_done'): self[k] = bool(self.get(k, DEFAULTS[k]))
        for k, d in (('perms', {}), ('disabled_ext', []), ('adblock_off', [])):
            if not isinstance(self.get(k), type(d)): self[k] = d
        if not isinstance(self.get('vpn'), dict): self['vpn'] = {}
        self['vpn'].setdefault('sel', 'auto'); self['vpn'].setdefault('mine', [])
        self['theme'] = 'dark'               # the app is always dark

    def save(self):
        write_json(SPATH, self)




def engine_url():
    return S['custom_engine'] if S['engine'] == 'Custom' else ENGINES.get(S['engine'], ENGINES['Google'])


def to_url(text):
    t = text.strip()
    if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', t) or t.startswith(('about:', 'data:')):
        return t
    if ' ' not in t and ('.' in t or t.startswith('localhost')):
        return ('http://' if t.startswith(('localhost', '127.')) else 'https://') + t
    return engine_url().replace('%s', quote_plus(t))


def esc(s):
    return html.escape(s or '', quote=True)


# ---------------------------------------------------------------- internal pages
PAGE_CSS = """
:root{--ease:cubic-bezier(.2,.9,.25,1.12);--mx:0;--my:0}
html{background:var(--bg);color-scheme:dark}
body{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;color:var(--fg);padding:0 5vw 80px;
 min-height:100vh;position:relative;-webkit-font-smoothing:antialiased}
/* living background the glass picks its colours from */
body::before,body::after{content:"";position:fixed;inset:-25%;z-index:-1;pointer-events:none}
body::before{background:radial-gradient(30vmax 30vmax at 34% 34%,rgba(255,255,255,.15),transparent 64%),
 radial-gradient(28vmax 28vmax at 68% 32%,rgba(255,255,255,.09),transparent 64%),
 radial-gradient(32vmax 32vmax at 58% 68%,rgba(255,255,255,.07),transparent 64%);
 animation:drift 26s ease-in-out infinite alternate}
body::after{background:radial-gradient(22vmax 22vmax at 36% 66%,rgba(255,255,255,.06),transparent 62%),
 radial-gradient(20vmax 20vmax at 72% 52%,rgba(255,255,255,.04),transparent 62%);
 background-position:calc(var(--mx)*-50px) calc(var(--my)*-50px);animation:drift 34s ease-in-out infinite alternate-reverse}
@keyframes drift{0%{transform:translate3d(-3%,-2%,0) scale(1) rotate(0)}50%{transform:translate3d(3%,2%,0) scale(1.08) rotate(4deg)}
 100%{transform:translate3d(-2%,4%,0) scale(1.03) rotate(-3deg)}}
a{color:inherit;text-decoration:none}
/* glass material: translucent, blurred, rim-lit, rounded */
.nav,.cov,.note,.c,.sf input,input[name=s]{
 background:linear-gradient(135deg,rgba(255,255,255,.14),rgba(255,255,255,.04)),rgba(8,8,8,.62);
 -webkit-backdrop-filter:blur(40px) saturate(110%);backdrop-filter:blur(40px) saturate(110%);
 border:1px solid rgba(255,255,255,.2);
 box-shadow:inset 0 1px 0 rgba(255,255,255,.42),inset 0 -1px 0 rgba(255,255,255,.07),0 14px 44px rgba(0,0,0,.34)}
.nav::after,.cov::after,.note::after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;opacity:0;
 background:radial-gradient(260px circle at var(--cx,50%) var(--cy,0%),rgba(255,255,255,.3),transparent 62%);transition:opacity .35s}
.nav:hover::after,.cov:hover::after,.note:hover::after{opacity:1}
.top{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:26px 0 20px;animation:rise .8s var(--ease) both}
.logo{font:500 34px/1 Georgia,"Times New Roman",serif;letter-spacing:-.6px;text-shadow:0 2px 26px rgba(255,255,255,.30)}
.nav{position:relative;display:flex;gap:4px;font-size:13px;flex-wrap:wrap;padding:5px;border-radius:999px}
.nav a{padding:7px 16px;border-radius:999px;border:0;transition:background .35s var(--ease),box-shadow .35s,transform .35s var(--ease)}
.nav a:hover{background:rgba(255,255,255,.12);transform:scale(1.05)}
.nav a.on{background:linear-gradient(180deg,rgba(255,255,255,.3),rgba(255,255,255,.12));box-shadow:inset 0 1px 0 rgba(255,255,255,.5),0 4px 14px rgba(0,0,0,.25)}
.sf{display:flex;justify-content:center;margin:34px 0 8px;animation:rise .9s var(--ease) .08s both}
.sf input{width:min(620px,92vw);box-sizing:border-box;color:var(--fg);border-radius:999px;padding:15px 26px;font:16px system-ui,sans-serif;
 outline:none;transition:width .5s var(--ease),box-shadow .35s,border-color .35s}
.sf input:focus{width:min(700px,94vw);border-color:rgba(255,255,255,.85);
 box-shadow:inset 0 1px 0 rgba(255,255,255,.45),0 0 0 5px rgba(255,255,255,.16),0 18px 54px rgba(0,0,0,.4)}
.sf input::placeholder{color:var(--mut)}
h1{font:500 30px/1.2 Georgia,"Times New Roman",serif;margin:28px 0 10px;animation:rise .7s var(--ease) both}
h3{font:600 11px/1 system-ui,sans-serif;letter-spacing:.18em;text-transform:uppercase;color:var(--mut);margin:34px 0 8px}
.m{color:var(--mut);font-size:13px}
.sec{display:grid;grid-template-columns:18px 1fr;gap:22px;margin:34px 0 10px;align-items:start}
.lbl{writing-mode:vertical-rl;transform:rotate(180deg);font-size:9px;letter-spacing:.22em;text-transform:uppercase;
 color:var(--fg);white-space:nowrap;justify-self:center}
.g2{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:30px}
.card{display:block;position:relative;animation:rise .85s var(--ease) calc(var(--i,0)*70ms + 120ms) both}
@keyframes rise{from{opacity:0;transform:translateY(26px) scale(.96)}to{opacity:1;transform:none}}
.cov{position:relative;aspect-ratio:1.28;overflow:hidden;display:flex;align-items:center;justify-content:center;border-radius:30px;
 background:linear-gradient(160deg,rgba(255,255,255,.20),rgba(255,255,255,.05)),rgba(8,8,8,.62);
 transition:transform .55s var(--ease),border-radius .55s var(--ease),box-shadow .4s}
.card:hover .cov{transform:translateY(-8px) scale(1.035);border-radius:42px;
 box-shadow:inset 0 1px 0 rgba(255,255,255,.55),inset 0 -1px 0 rgba(255,255,255,.1),0 26px 60px rgba(0,0,0,.45)}
.card:active .cov{transform:scale(.97);transition-duration:.15s}
.ini{font:400 96px/1 Georgia,"Times New Roman",serif;color:rgba(255,255,255,.95);text-shadow:0 4px 30px rgba(0,0,0,.28);
 transition:transform .55s var(--ease)}
.card:hover .ini{transform:scale(1.1)}
.cov .vl{position:absolute;right:12px;bottom:16px;writing-mode:vertical-rl;transform:rotate(180deg);font-size:9px;
 letter-spacing:.22em;text-transform:uppercase;color:rgba(255,255,255,.92)}
.cap{font:600 15px/1.3 Georgia,"Times New Roman",serif;margin:16px 6px 0}
.c{display:block;position:relative;padding:14px 20px;margin:10px 0;border-radius:20px;transition:transform .4s var(--ease),background .3s}
.c:hover{transform:translateX(6px) scale(1.01);background:linear-gradient(135deg,rgba(255,255,255,.24),rgba(255,255,255,.08))}
.c a:hover{text-decoration:underline}
.note{position:relative;overflow:hidden;padding:16px 20px;margin:14px 0;border-radius:24px;animation:rise .8s var(--ease) both}
input[name=s]{border-radius:999px;padding:11px 20px;color:var(--fg);font:15px system-ui,sans-serif;outline:none;width:min(420px,90vw);
 transition:box-shadow .35s,border-color .35s}
input[name=s]:focus{border-color:rgba(255,255,255,.85);box-shadow:0 0 0 4px rgba(255,255,255,.16)}
/* alive: shimmering logo, floating cards, tilt + light sweep, host-coloured covers */
.logo{background:linear-gradient(110deg,#fff 0%,#fff 38%,#9ad0ff 46%,#d9b8ff 54%,#fff 62%,#fff 100%);background-size:260% 100%;
 -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:transparent;text-shadow:none;
 filter:drop-shadow(0 2px 18px rgba(160,190,255,.35));animation:shine 7s linear infinite}
@keyframes shine{from{background-position:130% 0}to{background-position:-130% 0}}
.card{animation:rise .85s var(--ease) calc(var(--i,0)*70ms + 120ms) both,bob 8s ease-in-out calc(var(--i,0)*-1.1s) infinite}
@keyframes bob{0%,100%{translate:0 0}50%{translate:0 -6px}}
.cov{background-image:radial-gradient(120% 120% at 18% 8%,hsla(var(--h,220),85%,62%,.42),transparent 62%),linear-gradient(160deg,rgba(255,255,255,.20),rgba(255,255,255,.05))}
.card:hover .cov{transform:perspective(900px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg)) translateY(-8px) scale(1.035)}
.cov::before{content:"";position:absolute;inset:0;pointer-events:none;border-radius:inherit;opacity:0;transition:opacity .4s;
 background:linear-gradient(115deg,transparent 30%,rgba(255,255,255,.24) 48%,transparent 66%);background-size:250% 100%;background-position:120% 0}
.card:hover .cov::before{opacity:1;animation:sweep 1.1s var(--ease) both}
@keyframes sweep{from{background-position:120% 0}to{background-position:-60% 0}}
.note{animation:rise .8s var(--ease) both,glow 6s ease-in-out infinite}
@keyframes glow{50%{border-color:rgba(190,210,255,.45)}}
@media (max-width:700px){.top{flex-direction:column;align-items:flex-start}.sec{grid-template-columns:1fr}.lbl{display:none}.ini{font-size:72px}}
@media (prefers-contrast:more){.nav,.cov,.note,.c,.sf input{border-color:rgba(255,255,255,.7)}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
@supports not ((-webkit-backdrop-filter:blur(1px)) or (backdrop-filter:blur(1px))){
 .nav,.cov,.note,.c,.sf input,input[name=s]{background:rgba(22,22,22,.92)}}
"""
LIGHT_VARS = DARK_VARS = '--bg:#070707;--fg:#f5f5f5;--mut:rgba(235,235,235,.62);--line:rgba(255,255,255,.16);--card:rgba(255,255,255,.07);--inp:rgba(255,255,255,.08);'
PAGE_JS = r'''(function(){
var R=document.documentElement,D=document,reduce=(window.matchMedia&&matchMedia('(prefers-reduced-motion:reduce)').matches)||window.SG_ANIM===false;
addEventListener('pointermove',function(e){
 R.style.setProperty('--mx',(e.clientX/innerWidth-.5).toFixed(3));R.style.setProperty('--my',(e.clientY/innerHeight-.5).toFixed(3));
 var t=e.target.closest&&e.target.closest('.cov,.nav,.note');
 if(t){var b=t.getBoundingClientRect();t.style.setProperty('--cx',(e.clientX-b.left)+'px');t.style.setProperty('--cy',(e.clientY-b.top)+'px')}
 var c=e.target.closest&&e.target.closest('.card');
 if(c&&!reduce){var v=c.querySelector('.cov'),bb=v.getBoundingClientRect(),px=(e.clientX-bb.left)/bb.width-.5,py=(e.clientY-bb.top)/bb.height-.5;
  v.style.setProperty('--ry',(px*14).toFixed(2)+'deg');v.style.setProperty('--rx',(-py*14).toFixed(2)+'deg')}
},{passive:true});
D.querySelectorAll('.card').forEach(function(c,i){c.style.setProperty('--i',i);
 c.addEventListener('pointerleave',function(){var v=c.querySelector('.cov');v.style.setProperty('--rx','0deg');v.style.setProperty('--ry','0deg')})});
if(reduce)return;
var cv=D.createElement('canvas');cv.style.cssText='position:fixed;left:0;top:0;width:100%;height:100%;z-index:-1;pointer-events:none';
D.body.insertBefore(cv,D.body.firstChild);
var g=cv.getContext('2d'),W=0,H=0,dots=[],rip=[],mx=-1e4,my=-1e4,sx=-1e4,sy=-1e4,last=0;
function size(){W=innerWidth;H=innerHeight;cv.width=W;cv.height=H;var n=Math.max(30,Math.min(80,Math.round(W*H/20000)));dots=[];
 for(var i=0;i<n;i++)dots.push({x:Math.random()*W,y:Math.random()*H,vx:(Math.random()-.5)*.25,vy:(Math.random()-.5)*.25,r:Math.random()*1.4+.5,p:Math.random()*6.28})}
size();addEventListener('resize',size);
addEventListener('pointermove',function(e){mx=e.clientX;my=e.clientY},{passive:true});
R.addEventListener('pointerleave',function(){mx=-1e4;my=-1e4});
addEventListener('pointerdown',function(e){rip.push({x:e.clientX,y:e.clientY,t:performance.now()})},{passive:true});
var B=[[.11,.07,0,1,.62],[.08,.13,2,4,.7],[.13,.09,4,2,.55],[.06,.1,1,5,.8],[.1,.05,3,0,.5]];
function frame(now){requestAnimationFrame(frame);if(D.hidden||now-last<32)return;last=now;var t=now/1000,i,j;
 g.globalAlpha=1;g.globalCompositeOperation='source-over';g.clearRect(0,0,W,H);g.globalCompositeOperation='lighter';
 var big=Math.max(W,H);
 for(i=0;i<B.length;i++){var b=B[i],x=W*(.5+.45*Math.sin(t*b[0]+b[2])),y=H*(.5+.45*Math.cos(t*b[1]+b[3])),r=big*(.30+.25*b[4]),h=window.SG_PRIV?(268+30*Math.sin(t*.25+i*1.3)):(t*7+i*58+215)%360;
  var gr=g.createRadialGradient(x,y,0,x,y,r);gr.addColorStop(0,'hsla('+h+',85%,55%,.20)');gr.addColorStop(1,'hsla('+h+',85%,55%,0)');g.fillStyle=gr;g.fillRect(0,0,W,H)}
 sx+=(mx-sx)*.12;sy+=(my-sy)*.12;
 if(mx>-9999){var gm=g.createRadialGradient(sx,sy,0,sx,sy,220);gm.addColorStop(0,'rgba(190,210,255,.16)');gm.addColorStop(1,'rgba(190,210,255,0)');g.fillStyle=gm;g.fillRect(sx-220,sy-220,440,440)}
 g.fillStyle='#ffffff';g.strokeStyle='#cfe0ff';g.lineWidth=.7;
 for(i=0;i<dots.length;i++){var d=dots[i];d.x+=d.vx;d.y+=d.vy;
  var dx=d.x-mx,dy=d.y-my,q=dx*dx+dy*dy;
  if(q<14400&&q>1){var f=(1-q/14400)*1.4,m=Math.sqrt(q);d.x+=dx/m*f;d.y+=dy/m*f}
  if(d.x<-10)d.x=W+10;else if(d.x>W+10)d.x=-10;if(d.y<-10)d.y=H+10;else if(d.y>H+10)d.y=-10;
  g.globalAlpha=.35+.3*Math.sin(t*1.2+d.p);g.beginPath();g.arc(d.x,d.y,d.r,0,6.283);g.fill();
  for(j=i+1;j<dots.length;j++){var e=dots[j],ax=d.x-e.x,ay=d.y-e.y,s=ax*ax+ay*ay;
   if(s<12100){g.globalAlpha=(1-s/12100)*.22;g.beginPath();g.moveTo(d.x,d.y);g.lineTo(e.x,e.y);g.stroke()}}}
 g.globalAlpha=1;
 for(var k=rip.length-1;k>=0;k--){var a=(now-rip[k].t)/900;if(a>=1){rip.splice(k,1);continue}
  g.strokeStyle='rgba(200,220,255,'+(.45*(1-a)).toFixed(3)+')';g.lineWidth=2;g.beginPath();g.arc(rip[k].x,rip[k].y,10+a*160,0,6.283);g.stroke()}
}
requestAnimationFrame(frame);
var q=D.getElementById('q');
if(q){var ph=['Search or enter website name','Try: duckduckgo.com','Try: how do black holes work?','Try: weather tomorrow'],pi=0;
 setInterval(function(){if(D.activeElement!==q&&!q.value){pi=(pi+1)%ph.length;q.setAttribute('placeholder',ph[pi])}},3200)}
})();
'''


CUR_PRIV = [False]          # True while a supergo:// page is being served to a private window
PRIV_CSS = """
:root{--bg:#0b0714;--card:rgba(167,139,250,.10);--inp:rgba(167,139,250,.12);--line:rgba(190,170,255,.24)}
body::before{background:radial-gradient(30vmax 30vmax at 34% 34%,rgba(150,100,255,.30),transparent 64%),
 radial-gradient(28vmax 28vmax at 68% 32%,rgba(110,70,220,.24),transparent 64%),
 radial-gradient(32vmax 32vmax at 58% 68%,rgba(200,120,255,.16),transparent 64%)}
.logo{background-image:linear-gradient(110deg,#fff 0%,#fff 38%,#c4a8ff 46%,#ff9be8 54%,#fff 62%,#fff 100%);filter:drop-shadow(0 2px 18px rgba(170,120,255,.5))}
.logo::after{content:"  PRIVATE";font:700 10px system-ui,sans-serif;letter-spacing:.24em;vertical-align:middle;margin-left:8px;
 -webkit-text-fill-color:#d6c2ff;padding:4px 9px;border-radius:999px;border:1px solid rgba(190,160,255,.5);background:rgba(150,110,255,.2)}
.nav a.on{background:linear-gradient(180deg,rgba(190,160,255,.45),rgba(150,110,255,.18))}
.sf input:focus,input[name=s]:focus{border-color:#b79cff;box-shadow:0 0 0 5px rgba(170,130,255,.2),0 18px 54px rgba(0,0,0,.4)}
.note,.c,.cov{border-color:rgba(190,170,255,.26)}
"""
SEARCH_JS = r"""var T=__T__;function go(e){e.preventDefault();var v=document.getElementById('q').value.trim();if(!v)return;
if(/^[a-z][a-z0-9+.-]*:\/\//i.test(v))location.href=v;else if(!/\s/.test(v)&&/\./.test(v))location.href='https://'+v;
else location.href=T.replace('%s',encodeURIComponent(v));}"""
PRIV_NEWTAB = r"""
<style>
.pv{max-width:780px;margin:6px auto 0;text-align:center}
.pv svg{width:170px;height:140px;overflow:visible}
.pv h1{margin:2px 0 8px;font-size:34px}
.gh{fill:rgba(255,255,255,.95);filter:drop-shadow(0 0 18px rgba(170,120,255,.85))}
.ey{fill:#2a1b4d;transform-box:fill-box;transform-origin:center;animation:blk 4.2s infinite}
.gt{animation:fl 3.6s ease-in-out infinite}
.sh2{fill:rgba(0,0,0,.35);transform-box:fill-box;transform-origin:center;animation:shd 3.6s ease-in-out infinite}
.sp{fill:#e4d6ff;transform-box:fill-box;transform-origin:center;opacity:0;animation:tw 2.8s ease-in-out infinite}
@keyframes fl{50%{transform:translateY(-9px)}}
@keyframes shd{50%{transform:scale(.8);opacity:.5}}
@keyframes blk{0%,92%,100%{transform:scaleY(1)}95%{transform:scaleY(.1)}}
@keyframes tw{0%,100%{opacity:0;transform:scale(.2)}50%{opacity:1;transform:scale(1.15)}}
.pg{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;max-width:860px;margin:30px auto 0;text-align:left}
.pg .note h4{margin:0 0 8px;font:600 11px system-ui,sans-serif;letter-spacing:.18em;text-transform:uppercase;color:#cdb8ff}
.pg ul{margin:0;padding-left:18px}.pg li{margin:3px 0;font-size:14px}
.pg .note{animation:rise .8s var(--ease) calc(var(--i,0)*120ms + 300ms) both}
.pt{max-width:700px;margin:22px auto 0;text-align:center}
</style>
<div class=pv>
<svg viewBox="0 0 240 170"><ellipse class=sh2 cx=110 cy=160 rx=40 ry=6 />
<circle class=sp cx=40 cy=44 r=5 style="animation-delay:0s"/><circle class=sp cx=196 cy=60 r=4 style="animation-delay:.9s"/><circle class=sp cx=178 cy=128 r=3.5 style="animation-delay:1.8s"/>
<g class=gt><path class=gh d="M70 70 A40 40 0 0 1 150 70 V128 L137 118 L123 128 L110 118 L97 128 L83 118 L70 128 Z"/>
<ellipse class=ey cx=96 cy=70 rx=5 ry=7 /><ellipse class=ey cx=124 cy=70 rx=5 ry=7 /><ellipse cx=110 cy=88 rx=6 ry=4 fill="#2a1b4d"/></g></svg>
<h1>You are in a private window</h1>
<p class=m>Nothing you do here is saved to your history, and everything is wiped when you close the window.</p>
</div>
<form class=sf onsubmit="go(event)"><input id=q autofocus placeholder="Search privately or enter website name"></form>
<script>__JS__</script>
<div class=pg>
<div class=note style="--i:0"><h4>SUPERGO will not keep</h4><ul><li>Browsing history</li><li>Cookies and site data</li><li>Cache and form data</li><li>Site permission choices</li></ul></div>
<div class=note style="--i:1"><h4>Still visible to</h4><ul><li>The websites you open</li><li>Your network, school or employer</li><li>Your internet provider</li><li>Files you download and bookmarks you add stay</li></ul></div>
</div>
<p class="m pt">Want more privacy? Turn on the built-in VPN from the top bar - it works in private windows too.</p>
"""


def private_newtab_page():
    tmpl = json.dumps(engine_url()).replace('<', '\\u003c')
    return page('Private window', PRIV_NEWTAB.replace('__JS__', SEARCH_JS.replace('__T__', tmpl)), 'newtab')


def welcome_page(q):
    if q.get('done') and q.get('t') == TOKEN:
        S['welcome_done'] = True; S.save()
        home = json.dumps(S['homepage'] if S['homepage'].startswith(('http://', 'https://', 'supergo://')) else 'supergo://newtab').replace('<', '\\u003c')
        return '<!doctype html><meta charset=utf-8><title>SUPERGO</title><body style="background:#07060d"><script>location.replace(%s)</script>' % home
    return WELCOME_HTML.replace('__TOKEN__', TOKEN).replace('__ANIM__', 'true' if anim_on() else 'false')


def settings_extras():
    chips = ''.join('<a class="btn%s" href="supergo://settings?quick=%s&t=%s">%s%s</a>'
                    % (' on' if S['engine'] == n else '', quote_plus(n), TOKEN, esc(n), ' &#10003;' if S['engine'] == n else '')
                    for n in ENGINES)
    return ('<style>.btn{display:inline-block;margin:4px 10px 4px 0;padding:10px 22px;border-radius:999px;border:1px solid var(--line);'
            'background:var(--card);color:var(--fg);font-size:14px;transition:transform .3s var(--ease),background .3s}'
            '.btn:hover{background:rgba(255,255,255,.2);transform:scale(1.05)}.btn.on{border-color:#fff;background:rgba(255,255,255,.16)}'
            '.btn.pri{background:linear-gradient(135deg,rgba(120,170,255,.5),rgba(190,130,255,.45));border-color:rgba(255,255,255,.5)}</style>'
            '<h3>Quick search engine</h3><p class=m>Tap one to switch right away.</p><p>' + chips + '</p>'
            '<h3>Welcome tour</h3><p class=m>Replay the 8-step introduction to how SUPERGO works.</p>'
            '<p><a class="btn pri" href="supergo://welcome">&#9654;&nbsp; Start welcome tour</a></p>')


WELCOME_HTML = r'''<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Welcome to SUPERGO</title>
<script>window.SG_ANIM=__ANIM__;if(!window.SG_ANIM||(window.matchMedia&&matchMedia('(prefers-reduced-motion:reduce)').matches))document.documentElement.classList.add('na')</script>
<style>
*{box-sizing:border-box}
:root{--ac:215;--ease:cubic-bezier(.2,.9,.25,1.1)}
html,body{height:100%;margin:0}
body{background:#07060d;color:#f5f5f7;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;overflow:hidden;-webkit-font-smoothing:antialiased}
.bg i{position:fixed;border-radius:50%;filter:blur(110px);opacity:.4;pointer-events:none;background-color:hsl(var(--ac),85%,52%);transition:background-color 1s}
.bg i:nth-child(1){width:46vmax;height:46vmax;left:-12vmax;top:-14vmax;animation:d1 18s ease-in-out infinite alternate}
.bg i:nth-child(2){width:40vmax;height:40vmax;right:-12vmax;bottom:-16vmax;background-color:hsl(calc(var(--ac) + 60),85%,50%);animation:d2 22s ease-in-out infinite alternate}
@keyframes d1{to{transform:translate(8vmax,6vmax) scale(1.15)}}
@keyframes d2{to{transform:translate(-7vmax,-5vmax) scale(1.1)}}
.wrap{position:relative;z-index:1;height:100%;display:flex;flex-direction:column;max-width:880px;margin:0 auto;padding:20px 24px 24px}
.top{display:flex;justify-content:space-between;align-items:center}
.brand{font:500 22px Georgia,"Times New Roman",serif;letter-spacing:-.4px}
.top span{color:rgba(255,255,255,.55);font-size:13px;margin-left:12px}
.skip{background:none;border:0;color:rgba(255,255,255,.62);font:inherit;cursor:pointer;padding:8px 14px;border-radius:999px;transition:background .3s}
.skip:hover{background:rgba(255,255,255,.12);color:#fff}
.card{flex:1;min-height:0;margin:14px 0;display:grid;border-radius:32px;border:1px solid rgba(255,255,255,.16);position:relative;overflow:hidden;
 background:linear-gradient(145deg,rgba(255,255,255,.12),rgba(255,255,255,.03)),rgba(10,10,16,.62);
 -webkit-backdrop-filter:blur(30px);backdrop-filter:blur(30px);box-shadow:inset 0 1px 0 rgba(255,255,255,.3),0 24px 70px rgba(0,0,0,.5)}
.step{grid-area:1/1;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:22px 7%;overflow-y:auto;
 opacity:0;visibility:hidden;transform:translateX(60px);transition:opacity .45s,transform .55s var(--ease),visibility 0s .55s}
.step.prev{transform:translateX(-60px)}
.step.on{opacity:1;visibility:visible;transform:none;transition:opacity .5s .1s,transform .6s var(--ease) .1s,visibility 0s}
.ico{width:240px;height:170px;position:relative;margin-bottom:8px;flex:none;display:flex;align-items:center;justify-content:center}
.sv{width:100%;height:100%;overflow:visible}
h2{font:500 clamp(26px,4.4vw,38px)/1.15 Georgia,"Times New Roman",serif;margin:6px 0 12px;text-shadow:0 2px 30px hsla(var(--ac),90%,70%,.5)}
p{max-width:580px;margin:0 auto;color:rgba(240,240,245,.8);font-size:16px}
.w{display:inline-block;opacity:0}
.step.on .w{animation:wr .7s var(--ease) both;animation-delay:var(--d)}
@keyframes wr{from{opacity:0;transform:translateY(14px);filter:blur(6px)}to{opacity:1;transform:none;filter:none}}
.chips{list-style:none;display:flex;flex-wrap:wrap;gap:8px;justify-content:center;padding:0;margin:18px 0 0}
.chips li{padding:6px 14px;border-radius:999px;font-size:12.5px;border:1px solid hsla(var(--ac),90%,75%,.4);background:hsla(var(--ac),90%,60%,.15);opacity:0}
.step.on .chips li{animation:pop .55s var(--ease) both;animation-delay:calc(1s + var(--k)*.13s)}
@keyframes pop{from{opacity:0;transform:scale(.6) translateY(10px)}to{opacity:1;transform:none}}
kbd{font:600 11px ui-monospace,Menlo,Consolas,monospace;padding:2px 7px;border-radius:6px;border:1px solid rgba(255,255,255,.35);background:rgba(255,255,255,.1);margin-left:4px}
.nav{display:flex;align-items:center;justify-content:space-between;gap:14px;min-height:46px}
.btn{font:600 15px system-ui,sans-serif;border-radius:999px;padding:12px 28px;border:1px solid rgba(255,255,255,.25);background:rgba(255,255,255,.08);color:#fff;cursor:pointer;transition:transform .3s var(--ease),background .3s,opacity .3s;min-width:110px}
.btn:hover{background:rgba(255,255,255,.18);transform:scale(1.06)}
.btn:active{transform:scale(.96)}
.btn.pri{border-color:transparent;background:linear-gradient(135deg,hsl(var(--ac),85%,58%),hsl(calc(var(--ac) + 50),85%,55%));box-shadow:0 8px 28px hsla(var(--ac),90%,55%,.45)}
.btn[disabled]{opacity:0;pointer-events:none}
.dots{display:flex;gap:8px;align-items:center}
.dots button{width:9px;height:9px;padding:0;border:0;border-radius:9px;background:rgba(255,255,255,.26);cursor:pointer;transition:width .4s var(--ease),background .3s}
.dots button.seen{background:rgba(255,255,255,.6)}
.dots button.on{width:30px;background:hsl(var(--ac),90%,72%)}
/* 1 welcome */
.i1 img{width:96px;height:96px;border-radius:22px;position:relative;z-index:2;box-shadow:0 10px 40px hsla(var(--ac),90%,60%,.5)}
.step.on .i1 img{animation:bob 4s ease-in-out infinite}
@keyframes bob{50%{transform:translateY(-8px)}}
.i1 .ring{position:absolute;left:50%;top:50%;width:100px;height:100px;margin:-50px 0 0 -50px;border-radius:50%;border:2px solid hsl(var(--ac),90%,70%);opacity:0}
.step.on .i1 .ring{animation:rip 3.3s ease-out infinite;animation-delay:calc(var(--r)*1.1s)}
@keyframes rip{0%{transform:scale(.7);opacity:.7}100%{transform:scale(2.4);opacity:0}}
.orb{position:absolute;left:35px;top:0;width:170px;height:170px}
.orb.rv{left:55px;top:20px;width:130px;height:130px}
.orb u{position:absolute;left:50%;top:-4px;width:8px;height:8px;margin-left:-4px;border-radius:50%;background:#fff;box-shadow:0 0 14px #fff}
.orb.rv u{background:hsl(calc(var(--ac) + 60),95%,75%);box-shadow:0 0 14px hsl(calc(var(--ac) + 60),95%,70%)}
.step.on .orb{animation:spin 9s linear infinite}
.step.on .orb.rv{animation-duration:13s;animation-direction:reverse}
@keyframes spin{to{transform:rotate(360deg)}}
/* 2 address pill */
.i2{flex-direction:column;gap:18px}
.pl{display:flex;align-items:center;gap:10px;width:300px;max-width:100%;padding:12px 18px;border-radius:999px;background:rgba(255,255,255,.1);
 border:1px solid hsla(var(--ac),90%,75%,.6);box-shadow:0 0 0 5px hsla(var(--ac),90%,60%,.14);font:15px ui-monospace,Menlo,Consolas,monospace;text-align:left}
.ty{display:inline-block;overflow:hidden;white-space:nowrap;width:0}
.step.on .ty{animation:typ 5.5s steps(23) infinite}
@keyframes typ{0%{width:0}50%,88%{width:23ch}100%{width:0}}
.cr{width:2px;height:1.2em;background:#fff;margin-left:-6px}
.step.on .cr{animation:blink 1s steps(2) infinite}
@keyframes blink{50%{opacity:0}}
.go{padding:5px 14px;border-radius:9px;border:1px solid rgba(255,255,255,.4);font:600 12px ui-monospace,monospace;opacity:0;background:rgba(255,255,255,.1)}
.step.on .go{animation:key 5.5s infinite}
@keyframes key{0%,48%{opacity:0;transform:none}52%{opacity:1;transform:none}58%{opacity:1;transform:translateY(3px) scale(.92)}64%,86%{opacity:1;transform:none}100%{opacity:0}}
/* 3 sidebar */
.i3 .fr{fill:rgba(255,255,255,.06);stroke:rgba(255,255,255,.35);stroke-width:1.5}
.i3 .pb{fill:rgba(255,255,255,.18)}
.i3 .sb{fill:hsla(var(--ac),60%,45%,.3)}
.i3 .tb{fill:rgba(255,255,255,.22)}
.i3 .tb.cu{fill:hsla(var(--ac),95%,72%,.8)}
.i3 .ct{fill:rgba(255,255,255,.14)}
.step.on .i3 .sd{animation:sin 5.5s var(--ease) infinite}
@keyframes sin{0%{transform:translateX(-76px)}14%,88%{transform:none}100%{transform:translateX(-76px)}}
.step.on .i3 .tb{animation:tpop 5.5s infinite;animation-delay:calc(var(--k)*.16s)}
@keyframes tpop{0%,14%{opacity:0;transform:translateX(-16px)}26%,88%{opacity:1;transform:none}100%{opacity:0}}
/* 4 home / bookmarks */
.i4 .cd rect{fill:hsla(var(--ac),70%,55%,.3);stroke:hsla(var(--ac),90%,80%,.6);stroke-width:1.2}
.i4 .cd text{fill:#fff;font:400 26px Georgia,serif;text-anchor:middle}
.step.on .i4 .cd{animation:flt 4.5s ease-in-out infinite;animation-delay:calc(var(--k)*-1.4s)}
@keyframes flt{50%{transform:translateY(-9px)}}
.i4 .st{fill:#ffd24a;transform-origin:120px 36px;filter:drop-shadow(0 0 8px rgba(255,210,74,.8))}
.step.on .i4 .st{animation:star 3s ease-in-out infinite}
@keyframes star{0%,100%{transform:scale(1) rotate(0)}40%{transform:scale(1.35) rotate(18deg)}60%{transform:scale(1.2) rotate(-10deg)}}
.i4 .cl{fill:none;stroke:rgba(255,255,255,.7);stroke-width:2}
.i4 .hd{stroke:#fff;stroke-width:2.2;stroke-linecap:round;transform-origin:195px 148px}
.step.on .i4 .hd{animation:spin 4s linear infinite}
/* 5 shield */
.i5 .ad rect{fill:hsla(0,80%,60%,.75)}
.i5 .ad text{fill:#fff;font:700 11px system-ui,sans-serif;text-anchor:middle}
.i5 .ad{transform-box:fill-box;transform-origin:center}
.step.on .i5 .ad{animation:fly 3.4s ease-in infinite;animation-delay:calc(var(--k)*.55s)}
@keyframes fly{0%{transform:translateX(0);opacity:0}10%{opacity:1}58%{transform:translateX(68px) scale(1);opacity:1}72%{transform:translateX(78px) scale(.3);opacity:0}100%{opacity:0}}
.i5 .sh{fill:hsla(var(--ac),70%,50%,.28);stroke:hsl(var(--ac),90%,72%);stroke-width:3;transform-box:fill-box;transform-origin:center}
.step.on .i5 .sh{animation:shp 3.4s ease-in-out infinite}
@keyframes shp{50%{transform:scale(1.05);filter:drop-shadow(0 0 14px hsl(var(--ac),90%,65%))}}
.i5 .ck{fill:none;stroke:#fff;stroke-width:7;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:80;stroke-dashoffset:80}
.step.on .i5 .ck{animation:draw 3.4s ease-in-out infinite}
@keyframes draw{0%,10%{stroke-dashoffset:80}35%,90%{stroke-dashoffset:0}100%{stroke-dashoffset:80}}
/* 6 vpn */
.i6 .gl{fill:hsla(var(--ac),60%,45%,.22);stroke:hsl(var(--ac),90%,72%);stroke-width:2}
.i6 .ln{fill:none;stroke:rgba(255,255,255,.35);stroke-width:1.2}
.i6 .mr{fill:none;stroke:rgba(255,255,255,.55);stroke-width:1.4;transform-box:fill-box;transform-origin:center}
.step.on .i6 .mr{animation:mer 4s linear infinite;animation-delay:calc(var(--k)*-1.33s)}
@keyframes mer{0%,100%{transform:scaleX(1)}50%{transform:scaleX(.04)}}
.i6 .rg{fill:none;stroke:hsl(var(--ac),90%,70%);stroke-width:2;opacity:0;transform-box:fill-box;transform-origin:center}
.step.on .i6 .rg{animation:rip 3.3s ease-out infinite;animation-delay:calc(var(--k)*1.1s)}
.i6 .ob{transform-box:fill-box;transform-origin:center}
.step.on .i6 .ob{animation:spin 6s linear infinite}
.i6 .bd{fill:#1fa74f;stroke:#fff;stroke-width:2}
.i6 .lk{fill:#fff}
.i6 .sk{fill:none;stroke:#fff;stroke-width:2.4}
.step.on .i6 .bg2{animation:bob 2.4s ease-in-out infinite}
/* 7 private */
.i7 .gh{fill:rgba(255,255,255,.95);filter:drop-shadow(0 0 16px hsla(var(--ac),90%,65%,.8))}
.i7 .ey{fill:#2a1b4d;transform-box:fill-box;transform-origin:center}
.step.on .i7 .gt{animation:bob 3.4s ease-in-out infinite}
.step.on .i7 .ey{animation:blk 4s infinite}
@keyframes blk{0%,90%,100%{transform:scaleY(1)}94%{transform:scaleY(.1)}}
.i7 .tr{fill:none;stroke:rgba(255,255,255,.65);stroke-width:4;stroke-linecap:round;stroke-dasharray:50}
.step.on .i7 .tr{animation:ers 4s ease-in-out infinite;animation-delay:calc(var(--k)*.3s)}
@keyframes ers{0%,15%{stroke-dashoffset:0;opacity:1}60%,100%{stroke-dashoffset:50;opacity:0}}
.i7 .sp{fill:#fff;transform-box:fill-box;transform-origin:center;opacity:0}
.step.on .i7 .sp{animation:twk 2.6s ease-in-out infinite;animation-delay:calc(var(--k)*.8s)}
@keyframes twk{0%,100%{opacity:0;transform:scale(.2)}50%{opacity:1;transform:scale(1.1)}}
/* 8 ready */
.i8 svg{width:120px;height:120px;position:relative;z-index:2}
.i8 .cc{fill:hsla(var(--ac),70%,45%,.25);stroke:hsl(var(--ac),90%,70%);stroke-width:4;stroke-dasharray:315;stroke-dashoffset:315}
.i8 .cm{fill:none;stroke:#fff;stroke-width:8;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:80;stroke-dashoffset:80}
.step.on .i8 .cc{animation:dr 1s ease-out .2s forwards}
.step.on .i8 .cm{animation:dr .6s ease-out 1s forwards}
@keyframes dr{to{stroke-dashoffset:0}}
.cf{position:absolute;left:50%;top:50%;width:7px;height:12px;margin:-6px 0 0 -3px;border-radius:2px;background:hsl(var(--h),90%,65%);opacity:0}
.step.on .cf{animation:cft 2.8s ease-out infinite}
@keyframes cft{0%{opacity:0;transform:translate(0,0) rotate(0)}8%{opacity:1}100%{opacity:0;transform:translate(var(--x),var(--y)) rotate(var(--r))}}
/* no-motion */
.na *,.na *::before,.na *::after{animation:none!important;transition:none!important}
.na .w,.na .chips li{opacity:1!important}
.na .ty{width:23ch}.na .go{opacity:1}.na .cc,.na .cm,.na .ck{stroke-dashoffset:0}
@media (max-height:620px){.ico{transform:scale(.7);height:120px;margin-bottom:0}}
</style>
<div class=bg><i></i><i></i></div>
<div class=wrap>
 <div class=top><div><b class=brand>SUPERGO</b><span id=cnt>1 / 8</span></div><button class=skip id=skip>Skip tour</button></div>
 <div class=card>

 <section class="step on" data-ac=215>
  <div class="ico i1"><span class=ring style="--r:0"></span><span class=ring style="--r:1"></span><span class=ring style="--r:2"></span>
   <div class=orb><u></u></div><div class="orb rv"><u></u></div><img src="supergo://logo.png" alt=""></div>
  <h2>Welcome to SUPERGO</h2>
  <p>A light, fast web browser built on Microsoft's Edge WebView2 engine. It runs as your own user - no account, no root, nothing to sign in to. Here is a one minute tour of how everything works.</p>
  <ul class=chips><li style="--k:0">Flat dark design</li><li style="--k:1">Tabs in a sidebar</li><li style="--k:2">Ad blocker and VPN built in</li></ul>
 </section>

 <section class=step data-ac=190>
  <div class="ico i2"><div class=pl><svg width=18 height=18 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=2.4 stroke-linecap=round><circle cx=10 cy=10 r=6.5 /><path d="M15 15l6 6"/></svg><span class=ty>how do black holes work</span><i class=cr></i></div><div class=go>Enter &#8629;</div></div>
  <h2>One pill does it all</h2>
  <p>The rounded bar at the top is your address bar. Click it, type a website or just a question, and press Enter. Anything that looks like a site opens directly; everything else goes to your search engine.</p>
  <ul class=chips><li style="--k:0">Focus the bar<kbd>Ctrl+L</kbd></li><li style="--k:1">Reload / stop<kbd>F5</kbd></li><li style="--k:2">Back<kbd>Alt+&#8592;</kbd></li></ul>
 </section>

 <section class=step data-ac=265>
  <div class="ico i3"><svg class=sv viewBox="0 0 240 170"><clipPath id=c3><rect x=14 y=10 width=212 height=150 rx=14 /></clipPath>
   <rect class=fr x=14 y=10 width=212 height=150 rx=14 /><circle cx=30 cy=26 r=4 fill="#ff5f57"/><circle cx=43 cy=26 r=4 fill="#febc2e"/><circle cx=56 cy=26 r=4 fill="#28c840"/>
   <rect class=pb x=78 y=19 width=130 height=14 rx=7 />
   <g clip-path="url(#c3)"><rect class=ct x=96 y=52 width=118 height=44 rx=8 /><rect class=ct x=96 y=104 width=84 height=8 rx=4 /><rect class=ct x=96 y=120 width=104 height=8 rx=4 />
    <g class=sd><rect class=sb x=14 y=42 width=72 height=118 />
     <rect class=tb x=22 y=52 width=56 height=16 rx=5 style="--k:0"/><rect class="tb cu" x=22 y=74 width=56 height=16 rx=5 style="--k:1"/>
     <rect class=tb x=22 y=96 width=56 height=16 rx=5 style="--k:2"/><rect class=tb x=22 y=118 width=56 height=16 rx=5 style="--k:3"/></g></g></svg></div>
  <h2>Your tabs live in the sidebar</h2>
  <p>Open tabs, a new tab button and your bookmarks sit in a slide-out sidebar. Toggle it with the sidebar button at the top left. Middle-click a tab to close it, right-click for more.</p>
  <ul class=chips><li style="--k:0">Sidebar<kbd>Ctrl+Shift+L</kbd></li><li style="--k:1">New tab<kbd>Ctrl+T</kbd></li><li style="--k:2">Reopen closed tab<kbd>Ctrl+Shift+T</kbd></li></ul>
 </section>

 <section class=step data-ac=330>
  <div class="ico i4"><svg class=sv viewBox="0 0 240 170">
   <g class=cd style="--k:0"><rect x=22 y=76 width=62 height=48 rx=11 /><text x=53 y=110>G</text></g>
   <g class=cd style="--k:1"><rect x=89 y=64 width=62 height=48 rx=11 /><text x=120 y=98>W</text></g>
   <g class=cd style="--k:2"><rect x=156 y=76 width=62 height=48 rx=11 /><text x=187 y=110>N</text></g>
   <polygon class=st points="120,14 125.29,28.72 140.92,29.2 128.56,38.78 132.93,53.8 120,45 107.07,53.8 111.44,38.78 99.08,29.2 114.71,28.72"/>
   <circle class=cl cx=195 cy=148 r=15 /><line class=hd x1=195 y1=148 x2=195 y2=137 /></svg></div>
  <h2>Home, bookmarks and history</h2>
  <p>The new tab page shows your most visited, bookmarked and recent sites as floating cards. Star a page to save it into a folder, and search your history any time. You can clear history by hour, day, week or everything.</p>
  <ul class=chips><li style="--k:0">Bookmark<kbd>Ctrl+D</kbd></li><li style="--k:1">History<kbd>Ctrl+H</kbd></li><li style="--k:2">Downloads<kbd>Ctrl+J</kbd></li></ul>
 </section>

 <section class=step data-ac=150>
  <div class="ico i5"><svg class=sv viewBox="0 0 240 170">
   <g class=ad style="--k:0"><rect x=8 y=26 width=46 height=26 rx=6 /><text x=31 y=43>AD</text></g>
   <g class=ad style="--k:1"><rect x=8 y=72 width=46 height=26 rx=6 /><text x=31 y=89>AD</text></g>
   <g class=ad style="--k:2"><rect x=8 y=118 width=46 height=26 rx=6 /><text x=31 y=135>AD</text></g>
   <path class=sh d="M155 18 L196 32 V82 C196 112 178 134 155 146 C132 134 114 112 114 82 V32 Z"/>
   <path class=ck d="M136 82 L151 97 L176 64"/></svg></div>
  <h2>Ads and trackers, stopped early</h2>
  <p>Filter lists from uBlock Origin and EasyList are applied by the browser's request filter, so ads and trackers never load - YouTube ads included. If a page breaks, the shield button lets you switch blocking off for just that site.</p>
  <ul class=chips><li style="--k:0">Shield button in the top bar</li><li style="--k:1">Per-site switch</li><li style="--k:2">Filters compile on first launch only</li></ul>
 </section>

 <section class=step data-ac=35>
  <div class="ico i6"><svg class=sv viewBox="0 0 240 170"><g transform="translate(120 85)">
   <circle class=rg r=58 style="--k:0"/><circle class=rg r=58 style="--k:1"/>
   <g class=ob><circle r=76 fill=none /><circle r=72 fill=none stroke="rgba(255,255,255,.3)" stroke-width=1.5 stroke-dasharray="3 9"/><circle cx=72 r=5 fill="#fff"/></g>
   <circle class=gl r=58 />
   <path class=ln d="M-58 0H58M-49.6 -30H49.6M-49.6 30H49.6"/>
   <ellipse class=mr rx=58 ry=58 style="--k:0"/><ellipse class=mr rx=58 ry=58 style="--k:1"/><ellipse class=mr rx=58 ry=58 style="--k:2"/>
   <g class=bg2><circle class=bd cx=46 cy=44 r=18 /><rect class=lk x=38 y=44 width=16 height=12 rx=3 /><path class=sk d="M41 44v-4a5 5 0 0 1 10 0v4"/></g></g></svg></div>
  <h2>A VPN just for the browser</h2>
  <p>Open the VPN button and tap the glowing orb. SUPERGO runs a v2ray or xray core as your own user and sends only the browser through it - the rest of your computer is untouched. Paste your own vless, vmess, trojan or ss link for real privacy, or try Automatic. If the tunnel drops, browsing pauses so nothing leaks.</p>
  <ul class=chips><li style="--k:0">Needs v2ray or xray</li><li style="--k:1">Your own configs</li><li style="--k:2">Fails closed</li></ul>
 </section>

 <section class=step data-ac=285>
  <div class="ico i7"><svg class=sv viewBox="0 0 240 170">
   <path class=tr d="M168 52H214" style="--k:0"/><path class=tr d="M168 74H206" style="--k:1"/><path class=tr d="M168 96H218" style="--k:2"/>
   <circle class=sp cx=44 cy=40 r=5 style="--k:0"/><circle class=sp cx=60 cy=118 r=3.5 style="--k:1"/><circle class=sp cx=176 cy=132 r=4 style="--k:2"/>
   <g class=gt><path class=gh d="M70 70 A40 40 0 0 1 150 70 V128 L137 118 L123 128 L110 118 L97 128 L83 118 L70 128 Z"/>
   <ellipse class=ey cx=96 cy=70 rx=5 ry=7 /><ellipse class=ey cx=124 cy=70 rx=5 ry=7 /><ellipse cx=110 cy=88 rx=6 ry=4 fill="#2a1b4d"/></g></svg></div>
  <h2>Private windows</h2>
  <p>Open one from the menu. It wears its own purple look so you never mix it up with a normal window. History, cookies and site data are not saved and vanish when you close it. Files you download and bookmarks you add are kept, and websites or your network can still see you - add the VPN for more.</p>
  <ul class=chips><li style="--k:0">New private window<kbd>Ctrl+Shift+P</kbd></li><li style="--k:1">No history saved</li><li style="--k:2">Purple theme</li></ul>
 </section>

 <section class=step data-ac=140>
  <div class="ico i8"><svg viewBox="0 0 120 120"><circle class=cc cx=60 cy=60 r=50 transform="rotate(-90 60 60)"/><path class=cm d="M36 62L54 80L86 42"/></svg></div>
  <h2>You are ready to browse</h2>
  <p>Add Chrome extension content scripts (.zip or .crx) from the menu, change the search engine, homepage and downloads folder in Settings, and press F12 for developer tools. You can replay this tour any time from Settings.</p>
  <ul class=chips><li style="--k:0">Settings<kbd>Ctrl+,</kbd></li><li style="--k:1">Dev tools<kbd>F12</kbd></li><li style="--k:2">Fullscreen<kbd>F11</kbd></li></ul>
 </section>

 </div>
 <div class=nav><button class=btn id=back>Back</button><div class=dots id=dots></div><button class="btn pri" id=next>Next</button></div>
</div>
<script>
(function(){
var D=document,steps=[].slice.call(D.querySelectorAll('.step')),N=steps.length,cur=0,seen={0:1},
 dotsEl=D.getElementById('dots'),back=D.getElementById('back'),next=D.getElementById('next'),cnt=D.getElementById('cnt');
steps.forEach(function(s,si){
 [].forEach.call(s.querySelectorAll('h2,p'),function(el,ei){
  var words=el.textContent.trim().split(/\s+/);el.textContent='';
  words.forEach(function(w,i){var sp=D.createElement('span');sp.className='w';sp.style.setProperty('--d',(ei*0.15+i*0.028+0.1).toFixed(3)+'s');sp.textContent=w;
   el.appendChild(sp);el.appendChild(D.createTextNode(' '))});
 });
 var b=D.createElement('button');b.setAttribute('aria-label','Step '+(si+1));b.onclick=function(){go(si)};dotsEl.appendChild(b);
});
var i8=D.querySelector('.i8');
for(var k=0;k<18;k++){var c=D.createElement('i'),a=k/18*6.283+.2,d=78+(k*37)%46;c.className='cf';
 c.style.cssText='--x:'+Math.round(Math.cos(a)*d)+'px;--y:'+Math.round(Math.sin(a)*d*.8)+'px;--r:'+(k*47%360)+'deg;--h:'+(k*23%360)+';animation-delay:'+(1.2+(k%4)*.1)+'s';i8.appendChild(c)}
function finish(){location.href='supergo://welcome?done=1&t=__TOKEN__'}
function go(n){
 n=Math.max(0,Math.min(N-1,n));cur=n;seen[n]=1;
 steps.forEach(function(s,i){s.classList.toggle('on',i===n);s.classList.toggle('prev',i<n)});
 D.documentElement.style.setProperty('--ac',steps[n].getAttribute('data-ac'));
 [].forEach.call(dotsEl.children,function(b,i){b.classList.toggle('on',i===n);b.classList.toggle('seen',!!seen[i]&&i!==n)});
 back.disabled=(n===0);next.textContent=(n===N-1)?'Start browsing':'Next';cnt.textContent=(n+1)+' / '+N;
}
next.onclick=function(){cur>=N-1?finish():go(cur+1)};
back.onclick=function(){go(cur-1)};
D.getElementById('skip').onclick=finish;
addEventListener('keydown',function(e){if(e.key==='ArrowRight')go(cur+1);else if(e.key==='ArrowLeft')go(cur-1)});
go(0);next.focus();
})();
</script>
'''


def css():
    extra = '' if anim_on() else '*,*::before,*::after{animation:none!important;transition:none!important}'
    return ':root{%s}' % DARK_VARS + PAGE_CSS + extra + (PRIV_CSS if CUR_PRIV[0] else '')


def page(title, body, active=''):
    nav = ''.join('<a href="supergo://%s"%s>%s</a>' % (k, ' class=on' if k == active else '', n)
                  for k, n in (('newtab', 'Home'), ('bookmarks', 'Bookmarks'), ('history', 'History'), ('settings', 'Settings'), ('about', 'About')))
    return ('<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">'
            '<title>%s</title><style>%s</style><div class=top><a class=logo href="supergo://newtab">SUPERGO</a>'
            '<div class=nav>%s</div></div>%s<script>window.SG_ANIM=%s;window.SG_PRIV=%s;</script><script>%s</script>'
            % (esc(title), css(), nav, body, 'true' if anim_on() else 'false', 'true' if CUR_PRIV[0] else 'false', PAGE_JS))


def card(u, t):
    host = (urlparse(u).hostname or '').replace('www.', '')
    h = int(hashlib.md5(host.encode()).hexdigest()[:4], 16) % 360
    return ('<a class=card href="%s"><div class=cov style="--h:%d">'
            '<span class=ini>%s</span><span class=vl>%s</span></div><div class=cap>%s</div></a>'
            % (esc(u), h, esc((host[:1] or '?').upper()), esc(host), esc((t or host)[:46])))


def newtab_page():
    if CUR_PRIV[0]: return private_newtab_page()
    top = DB.execute('SELECT url,title FROM history ORDER BY visits DESC,ts DESC LIMIT 6').fetchall()
    rec = DB.execute('SELECT url,title FROM history ORDER BY ts DESC LIMIT 6').fetchall()
    bms = DB.execute('SELECT url,title FROM bookmarks ORDER BY ts DESC LIMIT 6').fetchall()

    def section(label, rows):
        return ('<div class=sec><div class=lbl>%s</div><div class=g2>%s</div></div>'
                % (label, ''.join(card(u, t) for u, t in rows)))
    tmpl = json.dumps(engine_url()).replace('<', '\\u003c')
    js = ("var T=%s;function go(e){e.preventDefault();var v=document.getElementById('q').value.trim();"
          "if(!v)return;if(/^[a-z][a-z0-9+.-]*:\\/\\//i.test(v))location.href=v;"
          "else if(!/\\s/.test(v)&&/\\./.test(v))location.href='https://'+v;"
          "else location.href=T.replace('%%s',encodeURIComponent(v));}" % tmpl)
    body = ('<form class=sf onsubmit="go(event)"><input id=q autofocus placeholder="Search or enter website name"></form>'
            '<script>' + js + '</script>')
    if top: body += section('Frequently visited', top)
    if bms: body += section('Bookmarks', bms)
    if rec: body += section('Recently visited', rec)
    if not (top or bms or rec):
        body += ('<div class=sec><div class=lbl>Getting started</div><div class=g2>'
                 '<a class=card href="supergo://about"><div class=cov style="--h:160">'
                 '<span class=ini>u</span><span class=vl>Built in</span></div><div class=cap>Ads &amp; trackers blocked with uBlock filter lists</div></a>'
                 '<a class=card href="supergo://about"><div class=cov style="--h:215">'
                 '<span class=ini>S</span><span class=vl>Built in</span></div><div class=cap>VPN built in - bring your own v2ray config</div></a>'
                 '</div></div>')
    return page('New Tab', body, 'newtab')


def apply_settings_changes():
    try: HOOKS['settings']()
    except Exception as e: print('SUPERGO: settings apply error:', e, file=sys.stderr)
    return False


def settings_page(q):
    note = ''
    if q.get('t') == TOKEN:
        try:
            if q.get('save'):
                eng = q.get('engine', 'Google')
                if eng not in ENGINES and eng != 'Custom': eng = 'Google'
                cust = (q.get('custom') or '').strip()
                if '%s' not in cust: cust = DEFAULTS['custom_engine']
                home = (q.get('home') or '').strip()
                S.update(engine=eng, custom_engine=cust, homepage=to_url(home) if home else 'supergo://newtab',
                         restore=bool(q.get('restore')), adblock=bool(q.get('adblock')), anim=bool(q.get('anim')),
                         ask_save=bool(q.get('ask')), download_dir=(q.get('ddir') or '').strip())
                S.save(); apply_settings_changes()
                note = 'Saved.'
            elif q.get('quick') in ENGINES:
                S['engine'] = q['quick']; S.save(); note = 'Search engine set to %s.' % q['quick']
            elif q.get('clear'):
                secs = {'hour': 3600, 'day': 86400, 'week': 604800}.get(q['clear'])
                if secs: DB.execute('DELETE FROM history WHERE ts>=?', (int(time.time() - secs),))
                else: DB.execute('DELETE FROM history')
                HOOKS['clear'](secs)
                note = 'Cleared history and site data.'
            elif q.get('resetperms'):
                S['perms'].clear(); S.save(); note = 'Site permissions reset.'
        except Exception as e:
            note = 'Error: %s' % e
    def chk(k): return ' checked' if S.get(k) else ''
    opts = ''.join('<option%s>%s</option>' % (' selected' if n == S['engine'] else '', n) for n in list(ENGINES) + ['Custom'])
    ddir = S['download_dir'] or default_download_dir()
    b = ('<h1>Settings</h1>' + ('<div class=note>%s</div>' % esc(note) if note else '') +
         '<style>.st{max-width:680px}.st .r{display:flex;align-items:center;justify-content:space-between;gap:16px;'
         'padding:12px 0;border-bottom:1px solid var(--line)}.st input[type=text],.st select{background:var(--inp);color:var(--fg);'
         'border:1px solid var(--line);border-radius:12px;padding:8px 12px;font:inherit;min-width:300px}'
         '.st input[type=checkbox]{width:20px;height:20px}.st button{background:var(--card);color:var(--fg);'
         'border:1px solid var(--line);border-radius:999px;padding:9px 22px;font:inherit;cursor:pointer;margin-top:18px}'
         '.st button:hover{background:rgba(255,255,255,.18)}</style>'
         '<form class=st action="supergo://settings"><input type=hidden name=t value="%s"><input type=hidden name=save value=1>'
         '<div class=r><span>Search engine</span><select name=engine>%s</select></div>'
         '<div class=r><span>Custom engine URL <span class=m>(use %%s for the query)</span></span>'
         '<input type=text name=custom value="%s"></div>'
         '<div class=r><span>Homepage</span><input type=text name=home value="%s"></div>'
         '<div class=r><span>Restore tabs on start</span><input type=checkbox name=restore value=1%s></div>'
         '<div class=r><span>uBlock ad blocker</span><input type=checkbox name=adblock value=1%s></div>'
         '<div class=r><span>Live background &amp; animations</span><input type=checkbox name=anim value=1%s></div>'
         '<div class=r><span>Download folder</span><input type=text name=ddir value="%s"></div>'
         '<div class=r><span>Ask where to save</span><input type=checkbox name=ask value=1%s></div>'
         '<button type=submit>Save settings</button></form>'
         % (TOKEN, opts, esc(S['custom_engine']), esc(S['homepage']), chk('restore'), chk('adblock'), chk('anim'),
            esc(ddir), chk('ask_save')) +
         settings_extras() + '<h3>Privacy</h3><p class=m>Clear history &amp; site data: ' +
         ' · '.join('<a href="supergo://settings?clear=%s&t=%s">%s</a>' % (k, TOKEN, n) for k, n in
                    (('hour', 'last hour'), ('day', 'last 24 hours'), ('week', 'last 7 days'), ('all', 'all time'))) +
         ' &nbsp;|&nbsp; <a href="supergo://settings?resetperms=1&t=%s">Reset site permissions</a></p>' % TOKEN)
    return page('Settings', b, 'settings')


def history_page(q):
    if q.get('t') == TOKEN:
        if 'del' in q:
            DB.execute('DELETE FROM history WHERE id=?', (int(q['del']),))
        if 'clear' in q:
            secs = {'hour': 3600, 'day': 86400, 'week': 604800}.get(q['clear'])
            if secs: DB.execute('DELETE FROM history WHERE ts>=?', (int(time.time() - secs),))
            else: DB.execute('DELETE FROM history')
    s = q.get('s', '')
    rows = DB.execute('SELECT id,url,title,ts FROM history WHERE url LIKE ? OR title LIKE ? '
                      'ORDER BY ts DESC LIMIT 500', ('%' + s + '%',) * 2).fetchall()
    b = ('<h1>History</h1><form><input name=s value="%s" placeholder="Search history"></form><p class=m>Clear: '
         % esc(s))
    b += ' · '.join('<a href="supergo://history?clear=%s&t=%s">%s</a>' % (k, TOKEN, n) for k, n in
                    (('hour', 'last hour'), ('day', 'last 24 hours'), ('week', 'last 7 days'), ('all', 'all time')))
    b += '</p>'
    for i, u, t, ts in rows:
        b += ('<div class=c><a href="%s">%s</a> <span class=m>%s · %s</span> '
              '<a class=m style="float:right" href="supergo://history?del=%d&t=%s&s=%s">delete</a></div>'
              % (esc(u), esc(t or u), esc(urlparse(u).hostname or ''),
                 time.strftime('%Y-%m-%d %H:%M', time.localtime(ts)), i, TOKEN, esc(quote_plus(s))))
    return page('History', b if rows else b + '<p class=m>No history.</p>', 'history')


def bookmarks_page(q):
    if q.get('t') == TOKEN and 'del' in q:
        DB.execute('DELETE FROM bookmarks WHERE id=?', (int(q['del']),))
    rows = DB.execute('SELECT id,url,title,folder FROM bookmarks ORDER BY folder,title').fetchall()
    b, cur = '<h1>Bookmarks</h1>', None
    for i, u, t, f in rows:
        if f != cur:
            b += '<h3>%s</h3>' % esc(f); cur = f
        b += ('<div class=c><a href="%s">%s</a> <span class=m>%s</span><a class=m style="float:right" '
              'href="supergo://bookmarks?del=%d&t=%s">remove</a></div>'
              % (esc(u), esc(t or u), esc(urlparse(u).hostname or ''), i, TOKEN))
    return page('Bookmarks', b if rows else b + '<p class=m>No bookmarks yet. Press Ctrl+D on a page.</p>', 'bookmarks')


def about_page():
    wk = 'Microsoft Edge WebView2'
    gt = 'WinForms'
    m = bl_meta()
    lists = ', '.join(m.get('lists', [])) or 'not installed'
    return page('About SUPERGO', (
        '<h1>SUPERGO %s</h1>'
        '<div class=note>%s<br>%s<br>Python %s<br>Extension support: content scripts only (v1)</div>'
        '<div class=note><b>uBlock (built in)</b> - %s network and cosmetic rules, built %s, from: %s.<br>'
        '<span class=m>Filter lists are converted from uBlock Origin / EasyList sources (GPLv3, CC BY-SA 3.0, CC0). '
        'Scriptlets, redirects and removeparam rules are not supported and are skipped.</span></div>'
        '<div class=note><b>VPN (built in)</b> - runs the v2ray / xray core as your own user (no root, no password prompt). '
        'Add your own vless / vmess / trojan / ss link, subscription or JSON config, or use Automatic to test the bundled public servers. '
        'Only the SUPERGO browser goes through the VPN - the rest of the computer is untouched.</div>'
        '<div class=note>License: MIT. Components: Microsoft Edge WebView2, pythonnet, SQLite (public domain).</div>'
        % (VERSION, wk, gt, sys.version.split()[0], m.get('rules', 0), m.get('built', '-'), esc(lists))), 'about')

