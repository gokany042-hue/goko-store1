import os, sqlite3, secrets, json, re
from pathlib import Path
from functools import wraps
from datetime import datetime
from flask import Flask, request, redirect, url_for, session, flash, render_template_string, abort, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from jinja2 import DictLoader

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('DATA_DIR', str(ROOT)))
DATA.mkdir(parents=True, exist_ok=True)
UPLOADS = DATA / 'uploads'
UPLOADS.mkdir(parents=True, exist_ok=True)
DB = DATA / 'store.db'
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
if not ADMIN_PASSWORD:
    raise RuntimeError('Render ortam degiskenlerinde ADMIN_PASSWORD ayarlanmamis.')
PASSWORD_HASH = generate_password_hash(ADMIN_PASSWORD)
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config.update(MAX_CONTENT_LENGTH=5*1024*1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=True)
ALLOWED = {'png','jpg','jpeg','webp','gif'}
TG = 'Denktinee'


def connect():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

# Additive migrations only: existing product records and uploaded images are retained.
with connect() as c:
    c.execute("""CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '', price TEXT NOT NULL, image TEXT NOT NULL DEFAULT '')""")
    cols = {r['name'] for r in c.execute('PRAGMA table_info(products)').fetchall()}
    if 'sale_price' not in cols:
        c.execute("ALTER TABLE products ADD COLUMN sale_price TEXT NOT NULL DEFAULT ''")
    c.execute("""CREATE TABLE IF NOT EXISTS reviews(
        id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
        customer_name TEXT NOT NULL, rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
        comment TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE)""")
    c.execute("""CREATE TABLE IF NOT EXISTS coupons(
        id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL CHECK(kind IN ('percent','fixed')), amount REAL NOT NULL,
        active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE,
        customer_name TEXT NOT NULL, contact TEXT NOT NULL, address TEXT NOT NULL DEFAULT '',
        items_json TEXT NOT NULL, subtotal REAL NOT NULL, discount REAL NOT NULL DEFAULT 0,
        coupon_code TEXT NOT NULL DEFAULT '', total REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'Sipariş alındı', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS support_messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT, visitor_id TEXT NOT NULL,
        sender TEXT NOT NULL CHECK(sender IN ('visitor','admin')), message TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")


def admin(fn):
    @wraps(fn)
    def w(*a, **k):
        if not session.get('admin'):
            return redirect(url_for('login'))
        return fn(*a, **k)
    return w


def csrf():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(24)
    return session['_csrf']


@app.context_processor
def inject_template_globals():
    return {'token': csrf()}


@app.before_request
def protect():
    if request.method == 'POST':
        token = request.form.get('_csrf', '')
        if not session.get('_csrf') or not secrets.compare_digest(token, session['_csrf']):
            abort(400)


def parse_price(value):
    s = str(value or '').replace('TL', '').replace('₺', '').replace(' ', '').replace('.', '').replace(',', '.')
    try:
        return max(0.0, float(s))
    except ValueError:
        return 0.0


def money(value):
    return ('{:,.2f}'.format(float(value))).replace(',', 'X').replace('.', ',').replace('X', '.') + ' TL'

BASE = r'''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#090a10"><title>Gökø Store</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap');
:root{color-scheme:dark;--bg:#090a10;--panel:#121420;--text:#f5f5fb;--muted:#9da1b5;--line:#292c3d;--purple:#9b7cff;--soft:#1d2030}
:root[data-theme="light"]{color-scheme:light;--bg:#f5f5fb;--panel:#fff;--text:#191827;--muted:#65677a;--line:#e2e2ed;--purple:#7653e8;--soft:#efedf8}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 50% -20%,#282044,transparent 48%),var(--bg);color:var(--text);font-family:'DM Sans',Arial,sans-serif;min-height:100vh;transition:background .2s,color .2s}
header{min-height:70px;padding:12px max(calc((100% - 1080px)/2),20px);display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);gap:12px;flex-wrap:wrap}.brand{font-size:22px;font-weight:800;color:var(--text);text-decoration:none}.brand span,h1 span{color:var(--purple)}nav{display:flex;gap:10px;align-items:center;flex-wrap:wrap}nav a{color:var(--muted);text-decoration:none;font-size:14px}
main{max-width:1080px;margin:auto;padding:35px 20px 70px}.hero{padding:45px 0 38px}.eyebrow{color:var(--purple);font-size:11px;font-weight:800;letter-spacing:2px}.hero h1{font-size:clamp(42px,7vw,72px);margin:10px 0;line-height:1}.muted,p{color:var(--muted);line-height:1.65}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:18px}.card,.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;overflow:hidden}.pic,.placeholder{height:210px;width:100%;object-fit:cover;background:linear-gradient(135deg,#282044,#111522)}.placeholder{display:grid;place-items:center;color:var(--purple);font-size:44px;font-weight:800}.info{padding:17px}.info h3{margin:0}.bottom,.head,.actions,.item,.card-tools{display:flex;align-items:center;justify-content:space-between;gap:10px}.bottom{margin-top:15px;flex-wrap:wrap}.btn{display:inline-block;border:0;border-radius:9px;background:var(--purple);color:#100d1b;text-decoration:none;padding:11px 15px;font-weight:800;cursor:pointer;font-size:13px}.secondary{background:var(--soft);color:var(--text)}.danger{background:#542638;color:white}.small{padding:8px 11px}.panel{max-width:650px;margin:25px auto;padding:25px}.panel h1{margin:5px 0 15px}label{display:block;margin:13px 0 6px;font-weight:700;font-size:13px}input,textarea,select{width:100%;padding:12px;border:1px solid var(--line);border-radius:9px;background:var(--bg);color:var(--text);font:inherit}button.full{width:100%;margin-top:18px}.list{border:1px solid var(--line);border-radius:14px;overflow:hidden}.item{padding:13px 16px;background:var(--panel);border-bottom:1px solid var(--line)}.item:last-child{border:0}.item p{margin:3px 0}.actions form{margin:0}.flash{background:var(--soft);border:1px solid var(--line);padding:8px 13px;border-radius:9px}.empty{text-align:center;padding:45px 15px}footer{text-align:center;color:var(--muted);border-top:1px solid var(--line);padding:22px;font-size:12px}.price-old{text-decoration:line-through;color:var(--muted);font-size:13px;margin-right:7px}.price-now{font-size:18px;font-weight:800}.discount{display:inline-block;background:#d83f68;color:white;padding:5px 9px;border-radius:7px;font-size:11px;font-weight:800}.icon-btn{border:1px solid var(--line);background:var(--soft);color:var(--text);border-radius:9px;padding:9px 11px;cursor:pointer}.icon-btn.active{color:#ff668d;border-color:#ff668d}.rating{color:#f5b942;letter-spacing:1px}.review-box{border-top:1px solid var(--line);margin-top:15px;padding-top:12px}.review-box summary{cursor:pointer;color:var(--purple);font-weight:700}.review{border-top:1px solid var(--line);padding:8px 0;font-size:13px}.review p{margin:3px 0}.cart-drawer{position:fixed;z-index:10;right:16px;top:82px;width:min(380px,calc(100vw - 32px));max-height:75vh;overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:0 15px 55px #0007;display:none}.cart-drawer.open{display:block}.cart-row{display:flex;justify-content:space-between;gap:10px;padding:10px 0;border-bottom:1px solid var(--line)}.pill{background:var(--soft);border-radius:20px;padding:4px 8px;font-size:12px}.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:15px 0 20px}.toolbar input{flex:1;min-width:190px}.status{display:inline-block;padding:5px 9px;border-radius:20px;background:var(--soft);font-size:12px}.chatbox{position:fixed;right:16px;bottom:16px;z-index:20;width:min(340px,calc(100vw - 32px));background:var(--panel);border:1px solid var(--line);border-radius:16px;box-shadow:0 10px 45px #0008;overflow:hidden}.chathead{padding:13px 15px;background:var(--soft);display:flex;justify-content:space-between;align-items:center;font-weight:800}.chatbody{height:220px;overflow:auto;padding:12px}.bubble{padding:8px 10px;border-radius:11px;background:var(--soft);margin:7px 0;max-width:90%;font-size:13px;white-space:pre-wrap}.bubble.mine{margin-left:auto;background:var(--purple);color:#100d1b}.chatform{display:flex;gap:7px;padding:10px;border-top:1px solid var(--line)}.chatform input{min-width:0}.chatform button{flex:none}.search-empty{display:none;text-align:center;padding:24px}.admin-links{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}
@media(max-width:600px){.head{align-items:flex-start;flex-direction:column}.item{align-items:flex-start;flex-direction:column}.actions{width:100%}.actions>*{flex:1}.actions .btn{width:100%;text-align:center}.hero{padding-top:30px}}
</style></head><body><header><a class="brand" href="/">Gökø <span>Store</span></a><nav><a href="/">Mağaza</a><a href="/admin">Admin</a><a href="/track">Sipariş takip</a><button class="icon-btn" id="themeToggle" type="button" aria-label="Tema değiştir">🌙</button><button class="icon-btn" id="cartToggle" type="button">🛒 Sepet <span id="cartCount" class="pill">0</span></button></nav></header>
<aside class="cart-drawer" id="cartDrawer"><div class="head"><h3>🛒 Sepetim</h3><button class="icon-btn" id="cartClose">✕</button></div><div id="cartItems"></div><div class="bottom"><b id="cartTotal">Toplam: 0</b><button class="btn" id="checkoutStart" type="button">Siparişi tamamla</button></div><p class="muted">Bu adım ödeme almaz. Sipariş talebin mağazaya iletilir; ödeme ve teslimat ayrıntıları ayrıca netleştirilir.</p></aside>
<main>{% with ms=get_flashed_messages() %}{% if ms %}<div class="flash">{% for m in ms %}{{m}}{% endfor %}</div>{% endif %}{% endwith %}{% block body %}{% endblock %}</main><footer>© Gökø Store · Tarzını keşfet.</footer>
<div class="chatbox" id="supportWidget"><div class="chathead"><span>💬 Canlı destek</span><button class="icon-btn" id="chatToggle" type="button">−</button></div><div id="chatContent"><div class="chatbody" id="chatMessages"><p class="muted">Bize mesaj bırak, buradan cevaplayalım.</p></div><form class="chatform" id="chatForm" data-csrf="{{token}}"><input name="message" maxlength="500" placeholder="Mesajını yaz..." required><button class="btn small">Gönder</button></form></div></div>
<script>
(()=>{
 const root=document.documentElement, saved=localStorage.getItem('goko-theme')||'dark';root.dataset.theme=saved;
 const theme=document.getElementById('themeToggle');if(theme){theme.textContent=saved==='dark'?'☀️':'🌙';theme.onclick=()=>{const n=root.dataset.theme==='dark'?'light':'dark';root.dataset.theme=n;localStorage.setItem('goko-theme',n);theme.textContent=n==='dark'?'☀️':'🌙'}}
 const read=()=>{try{return JSON.parse(localStorage.getItem('goko-cart')||'[]')}catch(e){return []}},write=a=>localStorage.setItem('goko-cart',JSON.stringify(a));
 const money=n=>new Intl.NumberFormat('tr-TR',{maximumFractionDigits:2}).format(n)+' TL';
 function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
 const drawer=document.getElementById('cartDrawer');
 function renderCart(){const a=read(),c=document.getElementById('cartCount'),box=document.getElementById('cartItems');if(c)c.textContent=a.reduce((s,x)=>s+x.qty,0);if(box){box.innerHTML=a.length?a.map(x=>`<div class="cart-row"><span>${esc(x.name)} × ${x.qty}<br><small>${money(x.price)}</small></span><button class="icon-btn" data-remove="${x.id}">Sil</button></div>`).join(''):'<p class="muted">Sepetin henüz boş.</p>';document.getElementById('cartTotal').textContent='Toplam: '+money(a.reduce((s,x)=>s+x.price*x.qty,0))}}
 document.querySelectorAll('[data-add]').forEach(b=>b.onclick=()=>{const id=Number(b.dataset.add),name=b.dataset.name,price=Number(b.dataset.price);let a=read(),x=a.find(z=>z.id===id);if(x)x.qty++;else a.push({id,name,price,qty:1});write(a);renderCart();b.textContent='Eklendi ✓';setTimeout(()=>b.textContent='Sepete ekle',900)});
 document.querySelectorAll('[data-fav]').forEach(b=>{const key='goko-favs',id=Number(b.dataset.fav);let f=JSON.parse(localStorage.getItem(key)||'[]');if(f.includes(id)){b.classList.add('active');b.textContent='♥'}b.onclick=()=>{f=JSON.parse(localStorage.getItem(key)||'[]');f=f.includes(id)?f.filter(x=>x!==id):[...f,id];localStorage.setItem(key,JSON.stringify(f));b.classList.toggle('active',f.includes(id));b.textContent=f.includes(id)?'♥':'♡'}});
 const toggle=document.getElementById('cartToggle'),close=document.getElementById('cartClose');if(toggle)toggle.onclick=()=>drawer.classList.toggle('open');if(close)close.onclick=()=>drawer.classList.remove('open');document.addEventListener('click',e=>{const b=e.target.closest('[data-remove]');if(b){write(read().filter(x=>x.id!==Number(b.dataset.remove)));renderCart()}});renderCart();
 const search=document.getElementById('productSearch');if(search)search.addEventListener('input',()=>{const q=search.value.toLocaleLowerCase('tr');let visible=0;document.querySelectorAll('.product-card').forEach(card=>{const yes=card.dataset.search.includes(q);card.style.display=yes?'':'none';if(yes)visible++});const empty=document.getElementById('searchEmpty');if(empty)empty.style.display=visible?'none':'block'});
 const start=document.getElementById('checkoutStart');if(start)start.onclick=()=>{const a=read();if(!a.length){alert('Sepetin boş.');return}localStorage.setItem('goko-checkout-cart',JSON.stringify(a));location.href='/checkout'};
 const chatToggle=document.getElementById('chatToggle'),chatContent=document.getElementById('chatContent');if(chatToggle)chatToggle.onclick=()=>{chatContent.style.display=chatContent.style.display==='none'?'':'none';chatToggle.textContent=chatContent.style.display==='none'?'+':'−'};
 const chatMessages=document.getElementById('chatMessages');async function loadChat(){if(!chatMessages)return;try{const r=await fetch('/support/messages');const data=await r.json();chatMessages.innerHTML=data.messages.length?data.messages.map(m=>`<div class="bubble ${m.sender==='visitor'?'mine':''}">${esc(m.message)}<br><small>${esc(m.created_at)}</small></div>`).join(''):'<p class="muted">Henüz mesaj yok. Bize yazabilirsin.</p>';chatMessages.scrollTop=chatMessages.scrollHeight}catch(e){}}
 const chatForm=document.getElementById('chatForm');if(chatForm)chatForm.onsubmit=async e=>{e.preventDefault();const input=chatForm.elements.message,body=new URLSearchParams({_csrf:chatForm.dataset.csrf||'',message:input.value});try{const r=await fetch('/support/send',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body});if(r.ok){input.value='';loadChat()}else alert('Mesaj gönderilemedi. Sayfayı yenileyip tekrar dene.')}catch(e){alert('Bağlantı hatası.')}};
 loadChat();setInterval(loadChat,7000);
})();
</script></body></html>'''

TEMPLATES = {
'base': BASE,
'home': r'''{% extends 'base' %}{% block body %}<section class="hero"><div class="eyebrow">ONLINE STORE</div><h1>Tarzını <span>keşfet.</span></h1><p>Gökø Store'a hoş geldin. Ürünleri keşfet, favorilerine ekle ve sepetini oluştur.</p><a class="btn" href="#products">Ürünleri keşfet ↓</a></section>
<div class="head" id="products"><div><div class="eyebrow">KOLEKSİYON</div><h2>Ürünlerimiz</h2></div><p>{{products|length}} ürün</p></div>
<div class="toolbar"><input id="productSearch" type="search" placeholder="🔎 Ürün ara..." aria-label="Ürün ara"></div>
{% if products %}<div class="grid" id="productGrid">{% for p in products %}<article class="card product-card" data-search="{{(p.name ~ ' ' ~ p.description)|lower|e}}">{% if p.image %}<img class="pic" src="/uploads/{{p.image}}" alt="{{p.name}}">{% else %}<div class="placeholder">Gökø</div>{% endif %}<div class="info"><div class="card-tools"><span class="pill">Ürün #{{p.id}}</span>{% if p.sale_price %}<span class="discount">İNDİRİM</span>{% endif %}</div><h3 style="margin-top:10px">{{p.name}}</h3><p>{{p.description}}</p><div><span class="rating">{% for i in range(1,6) %}{{'★' if i <= (p.avg_rating|round|int) else '☆'}}{% endfor %}</span> <small class="muted">{{'%.1f'|format(p.avg_rating)}} / 5 · {{p.review_count}} yorum</small></div><div class="bottom">{% if p.sale_price %}<div><span class="price-old">{{p.price}}</span><span class="price-now">{{p.sale_price}}</span></div>{% else %}<b class="price-now">{{p.price}}</b>{% endif %}<button class="icon-btn" data-fav="{{p.id}}">♡</button></div><div class="bottom"><button class="btn" data-add="{{p.id}}" data-name="{{p.name|e}}" data-price="{{p.numeric_price}}">Sepete ekle</button><a class="btn secondary" href="https://t.me/Denktinee" target="_blank" rel="noopener">Telegram ↗</a></div><details class="review-box"><summary>⭐ Yorumları gör / yorum yap</summary><form method="post" action="/review/{{p.id}}"><input type="hidden" name="_csrf" value="{{token}}"><label>Adın</label><input name="customer_name" maxlength="50" required placeholder="Adın"><label>Puanın</label><select name="rating" required><option value="5">5 - Harika</option><option value="4">4 - Çok iyi</option><option value="3">3 - İyi</option><option value="2">2 - Geliştirilebilir</option><option value="1">1 - Beğenmedim</option></select><label>Yorumun</label><textarea name="comment" maxlength="500" rows="3" required placeholder="Ürün hakkındaki düşüncen..."></textarea><button class="btn small" type="submit">Yorumu gönder</button></form>{% for r in p.reviews %}<div class="review"><b>{{r.customer_name}}</b> <span class="rating">{{'★' * r.rating}}</span><p>{{r.comment}}</p></div>{% else %}<p class="muted">Henüz yorum yok. İlk yorumu sen yap!</p>{% endfor %}</details></div></article>{% endfor %}</div><div id="searchEmpty" class="search-empty muted">Aramana uygun ürün bulunamadı.</div>{% else %}<div class="panel empty"><h3>Henüz ürün eklenmedi</h3><p>İlk ürününü admin panelinden ekleyebilirsin.</p><a class="btn" href="/admin/login">Admin paneli</a></div>{% endif %}{% endblock %}''',
'login': r'''{% extends 'base' %}{% block body %}<div class="panel"><div class="eyebrow">YÖNETİCİ GİRİŞİ</div><h1>Admin Paneli</h1><p>Yönetici şifreni gir.</p><form method="post"><input type="hidden" name="_csrf" value="{{token}}"><label>Şifre</label><input type="password" name="password" required><button class="btn full">Giriş yap</button></form></div>{% endblock %}''',
'dash': r'''{% extends 'base' %}{% block body %}<div class="head"><div><div class="eyebrow">YÖNETİM</div><h1>Admin Paneli</h1><p>Ürünleri, siparişleri, kuponları ve destek mesajlarını yönet.</p></div><div class="actions"><a class="btn" href="/admin/new">+ Ürün ekle</a><form method="post" action="/admin/logout"><input type="hidden" name="_csrf" value="{{token}}"><button class="btn secondary">Çıkış</button></form></div></div><div class="admin-links"><a class="btn secondary" href="/admin/orders">📦 Siparişler ({{order_count}})</a><a class="btn secondary" href="/admin/coupons">🎟️ Kuponlar</a><a class="btn secondary" href="/admin/support">💬 Destek mesajları ({{support_count}})</a></div><h2>Ürünler</h2><div class="list">{% for p in products %}<div class="item"><div><b>{{p.name}}</b><p>{{p.price}} {% if p.sale_price %}→ <b>{{p.sale_price}}</b>{% endif %}</p></div><div class="actions"><a class="btn secondary small" href="/admin/edit/{{p.id}}">Düzenle</a><form method="post" action="/admin/delete/{{p.id}}" onsubmit="return confirm('Ürün silinsin mi?')"><input type="hidden" name="_csrf" value="{{token}}"><button class="btn danger small">Sil</button></form></div></div>{% else %}<div class="empty">Henüz ürün yok.</div>{% endfor %}</div>{% endblock %}''',
'form': r'''{% extends 'base' %}{% block body %}<div class="panel"><div class="eyebrow">ÜRÜN YÖNETİMİ</div><h1>{{'Ürünü düzenle' if product else 'Yeni ürün ekle'}}</h1><form method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{token}}"><label>Ürün adı</label><input name="name" required value="{{product.name if product else ''}}"><label>Normal fiyat</label><input name="price" required value="{{product.price if product else ''}}" placeholder="Örn: 500 TL"><label>İndirimli fiyat (isteğe bağlı)</label><input name="sale_price" value="{{product.sale_price if product else ''}}" placeholder="Örn: 399 TL"><label>Açıklama</label><textarea name="description" rows="4">{{product.description if product else ''}}</textarea><label>Fotoğraf</label><input type="file" name="image" accept=".png,.jpg,.jpeg,.webp,.gif"><p><button class="btn">Kaydet</button> <a class="btn secondary" href="/admin">Vazgeç</a></p></form></div>{% endblock %}''',
'checkout': r'''{% extends 'base' %}{% block body %}<div class="panel"><div class="eyebrow">SİPARİŞ OLUŞTUR</div><h1>Sipariş bilgileri</h1><p>Bu form ödeme almaz; sipariş talebini kaydeder. Ödeme ve teslimat ayrıntıları seninle ayrıca netleştirilir.</p><form method="post" action="/checkout/submit" id="checkoutForm"><input type="hidden" name="_csrf" value="{{token}}"><input type="hidden" name="items" id="orderItems"><label>Ad soyad</label><input name="customer_name" maxlength="80" required><label>İletişim (telefon veya Telegram kullanıcı adı)</label><input name="contact" maxlength="100" required><label>Teslimat bilgisi (gerekliyse)</label><textarea name="address" maxlength="500" rows="2"></textarea><label>Kupon kodu (isteğe bağlı)</label><input name="coupon" maxlength="40" placeholder="Örn: HOSGELDIN10"><div class="flash" id="checkoutSummary">Sepet bilgisi hazırlanıyor...</div><button class="btn full" type="submit">Sipariş talebini gönder</button></form></div><script>try{const a=JSON.parse(localStorage.getItem('goko-checkout-cart')||'[]');document.getElementById('orderItems').value=JSON.stringify(a.map(x=>({id:x.id,qty:x.qty})));document.getElementById('checkoutSummary').textContent=a.length+' ürün siparişe eklenecek.';if(!a.length)document.getElementById('checkoutForm').querySelector('button').disabled=true}catch(e){}</script>{% endblock %}''',
'order_done': r'''{% extends 'base' %}{% block body %}<script>localStorage.removeItem('goko-cart');localStorage.removeItem('goko-checkout-cart');</script><div class="panel"><div class="eyebrow">SİPARİŞİN ALINDI</div><h1>Teşekkürler!</h1><p>Sipariş takip kodun:</p><h2 style="color:var(--purple)">{{code}}</h2><p>Bu kodu sakla. Sipariş durumunu Sipariş Takip sayfasından kontrol edebilirsin.</p><a class="btn" href="/track">Siparişimi takip et</a> <a class="btn secondary" href="/">Mağazaya dön</a></div>{% endblock %}''',
'order_track': r'''{% extends 'base' %}{% block body %}<div class="panel"><div class="eyebrow">SİPARİŞ TAKİBİ</div><h1>Siparişini bul</h1><form method="get"><label>Sipariş takip kodu</label><input name="code" value="{{code}}" placeholder="Örn: GOKO-AB12CD34" required><button class="btn full">Sorgula</button></form>{% if order %}<div class="review-box"><h3>{{order.customer_name}}</h3><p><span class="status">{{order.status}}</span></p><p>Sipariş tarihi: {{order.created_at}}</p><p>Toplam: <b>{{money(order.total)}}</b>{% if order.discount %} · İndirim: {{money(order.discount)}}{% endif %}</p><p>Ürünler: {{items_text}}</p></div>{% elif code %}<p class="muted">Bu kodla eşleşen sipariş bulunamadı. Kodu kontrol et.</p>{% endif %}</div>{% endblock %}''',
'orders': r'''{% extends 'base' %}{% block body %}<div class="head"><div><div class="eyebrow">YÖNETİM</div><h1>Siparişler</h1></div><a class="btn secondary" href="/admin">← Admin</a></div><div class="list">{% for o in orders %}<div class="item"><div><b>{{o.code}} · {{o.customer_name}}</b><p>{{o.contact}} · {{money(o.total)}} · {{o.created_at}}</p>{% if o.address %}<p>Teslimat: {{o.address}}</p>{% endif %}<p>{{o.items_json}}</p></div><form method="post" action="/admin/orders/{{o.id}}"><input type="hidden" name="_csrf" value="{{token}}"><select name="status">{% for s in statuses %}<option {{'selected' if s==o.status else ''}}>{{s}}</option>{% endfor %}</select><button class="btn small">Durumu kaydet</button></form></div>{% else %}<div class="empty">Henüz sipariş yok.</div>{% endfor %}</div>{% endblock %}''',
'coupons': r'''{% extends 'base' %}{% block body %}<div class="head"><div><div class="eyebrow">YÖNETİM</div><h1>Kupon sistemi</h1><p>Yüzde veya sabit tutarlı indirim kodu oluştur.</p></div><a class="btn secondary" href="/admin">← Admin</a></div><div class="panel"><form method="post"><input type="hidden" name="_csrf" value="{{token}}"><label>Kupon kodu</label><input name="code" maxlength="40" required placeholder="GOKO10"><label>İndirim türü</label><select name="kind"><option value="percent">Yüzde (%)</option><option value="fixed">Sabit TL</option></select><label>İndirim miktarı</label><input name="amount" type="number" min="0.01" step="0.01" required><button class="btn full">Kupon oluştur</button></form></div><h2>Mevcut kuponlar</h2><div class="list">{% for c in coupons %}<div class="item"><div><b>{{c.code}}</b><p>{{c.amount:g}} {{'%' if c.kind=='percent' else 'TL'}} · {{'Aktif' if c.active else 'Pasif'}}</p></div><form method="post" action="/admin/coupons/{{c.id}}/toggle"><input type="hidden" name="_csrf" value="{{token}}"><button class="btn secondary small">{{'Pasifleştir' if c.active else 'Etkinleştir'}}</button></form></div>{% else %}<div class="empty">Henüz kupon yok.</div>{% endfor %}</div>{% endblock %}''',
'support_admin': r'''{% extends 'base' %}{% block body %}<div class="head"><div><div class="eyebrow">YÖNETİM</div><h1>Canlı destek mesajları</h1></div><a class="btn secondary" href="/admin">← Admin</a></div><div class="list">{% for v in visitors %}<a class="item" style="text-decoration:none;color:var(--text)" href="/admin/support/{{v.visitor_id}}"><div><b>Ziyaretçi · {{v.visitor_id[:10]}}</b><p>{{v.last_message}} · {{v.created_at}}</p></div><span class="status">{{v.count}} mesaj</span></a>{% else %}<div class="empty">Henüz destek mesajı yok.</div>{% endfor %}</div>{% endblock %}''',
'support_thread': r'''{% extends 'base' %}{% block body %}<div class="head"><div><div class="eyebrow">CANLI DESTEK</div><h1>Ziyaretçi görüşmesi</h1></div><a class="btn secondary" href="/admin/support">← Mesajlar</a></div><div class="panel">{% for m in messages %}<div class="bubble {{'mine' if m.sender=='admin' else ''}}"><b>{{'Sen' if m.sender=='admin' else 'Ziyaretçi'}}</b><br>{{m.message}}<br><small>{{m.created_at}}</small></div>{% endfor %}<form method="post"><input type="hidden" name="_csrf" value="{{token}}"><label>Yanıtın</label><textarea name="message" maxlength="500" required></textarea><button class="btn full">Yanıt gönder</button></form></div>{% endblock %}'''
}
app.jinja_loader = DictLoader(TEMPLATES)


@app.route('/')
def home():
    with connect() as c:
        rows = c.execute('SELECT * FROM products ORDER BY id DESC').fetchall()
        products = []
        for row in rows:
            p = dict(row)
            p['numeric_price'] = parse_price(p.get('sale_price') or p['price'])
            stats = c.execute('SELECT AVG(rating) avg_rating, COUNT(*) review_count FROM reviews WHERE product_id=?', (p['id'],)).fetchone()
            p['avg_rating'] = stats['avg_rating'] or 0
            p['review_count'] = stats['review_count'] or 0
            p['reviews'] = c.execute('SELECT customer_name,rating,comment FROM reviews WHERE product_id=? ORDER BY id DESC LIMIT 10', (p['id'],)).fetchall()
            products.append(p)
    return render_template_string("{% extends 'home' %}", products=products, token=csrf())


@app.route('/uploads/<path:name>')
def uploaded(name):
    from flask import send_from_directory
    return send_from_directory(UPLOADS, name)


@app.route('/review/<int:pid>', methods=['POST'])
def review(pid):
    name = request.form.get('customer_name', '').strip()[:50]
    comment = request.form.get('comment', '').strip()[:500]
    try: rating = int(request.form.get('rating', '5'))
    except ValueError: rating = 0
    with connect() as c:
        if not c.execute('SELECT id FROM products WHERE id=?', (pid,)).fetchone(): abort(404)
        if not name or not comment or rating not in range(1, 6):
            flash('Yorum bilgilerini kontrol et.'); return redirect('/#products')
        c.execute('INSERT INTO reviews(product_id,customer_name,rating,comment) VALUES(?,?,?,?)', (pid, name, rating, comment))
    flash('Yorumun eklendi. Teşekkürler!')
    return redirect('/#products')


@app.route('/checkout')
def checkout():
    return render_template_string("{% extends 'checkout' %}", token=csrf())


@app.route('/checkout/submit', methods=['POST'])
def checkout_submit():
    name = request.form.get('customer_name', '').strip()[:80]
    contact = request.form.get('contact', '').strip()[:100]
    address = request.form.get('address', '').strip()[:500]
    coupon_code = request.form.get('coupon', '').strip().upper()[:40]
    try:
        requested = json.loads(request.form.get('items', '[]'))
    except (ValueError, TypeError):
        requested = []
    if not name or not contact or not isinstance(requested, list) or not requested:
        flash('Ad, iletişim ve en az bir ürün gerekli.'); return redirect('/checkout')
    quantities = {}
    for item in requested[:50]:
        try:
            pid, qty = int(item.get('id')), int(item.get('qty'))
            if qty < 1 or qty > 20: continue
            quantities[pid] = min(20, quantities.get(pid, 0) + qty)
        except (TypeError, ValueError, AttributeError):
            continue
    with connect() as c:
        lines, subtotal = [], 0.0
        for pid, qty in quantities.items():
            product = c.execute('SELECT id,name,price,sale_price FROM products WHERE id=?', (pid,)).fetchone()
            if not product: continue
            unit = parse_price(product['sale_price'] or product['price'])
            subtotal += unit * qty
            lines.append({'id': pid, 'name': product['name'], 'qty': qty, 'unit_price': unit})
        if not lines:
            flash('Sepetindeki ürünler artık mevcut değil. Mağazayı yenile.'); return redirect('/')
        discount = 0.0
        if coupon_code:
            coupon = c.execute('SELECT * FROM coupons WHERE code=? AND active=1', (coupon_code,)).fetchone()
            if not coupon:
                flash('Kupon kodu geçersiz veya pasif.'); return redirect('/checkout')
            discount = subtotal * coupon['amount'] / 100 if coupon['kind'] == 'percent' else coupon['amount']
            discount = min(subtotal, max(0.0, discount))
        total = max(0.0, subtotal - discount)
        code = 'GOKO-' + secrets.token_hex(8).upper()
        c.execute('INSERT INTO orders(code,customer_name,contact,address,items_json,subtotal,discount,coupon_code,total) VALUES(?,?,?,?,?,?,?,?,?)',
                  (code, name, contact, address, json.dumps(lines, ensure_ascii=False), subtotal, discount, coupon_code, total))
    return render_template_string("{% extends 'order_done' %}", code=code)


@app.route('/track')
def track():
    code = request.args.get('code', '').strip().upper()[:30]
    order = None; items_text = ''
    if code:
        with connect() as c: order = c.execute('SELECT * FROM orders WHERE code=?', (code,)).fetchone()
        if order:
            items = json.loads(order['items_json'])
            items_text = ', '.join(f"{x['name']} × {x['qty']}" for x in items)
    return render_template_string("{% extends 'order_track' %}", code=code, order=order, items_text=items_text, money=money)


@app.route('/support/messages')
def support_messages():
    visitor_id = session.setdefault('visitor_id', secrets.token_urlsafe(12))
    with connect() as c:
        rows = c.execute('SELECT sender,message,created_at FROM support_messages WHERE visitor_id=? ORDER BY id ASC LIMIT 100', (visitor_id,)).fetchall()
    return jsonify(messages=[dict(r) for r in rows])


@app.route('/support/send', methods=['POST'])
def support_send():
    visitor_id = session.setdefault('visitor_id', secrets.token_urlsafe(12))
    message = request.form.get('message', '').strip()[:500]
    if not message: return jsonify(ok=False), 400
    with connect() as c:
        c.execute("INSERT INTO support_messages(visitor_id,sender,message) VALUES(?,'visitor',?)", (visitor_id, message))
    return jsonify(ok=True)


@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if check_password_hash(PASSWORD_HASH, request.form.get('password', '')):
            session.clear(); session['admin'] = True
            return redirect('/admin')
        flash('Şifre yanlış.')
    return render_template_string("{% extends 'login' %}", token=csrf())


@app.route('/admin')
@admin
def dashboard():
    with connect() as c:
        products = c.execute('SELECT * FROM products ORDER BY id DESC').fetchall()
        order_count = c.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        support_count = c.execute("SELECT COUNT(DISTINCT visitor_id) FROM support_messages WHERE sender='visitor'").fetchone()[0]
    return render_template_string("{% extends 'dash' %}", products=products, token=csrf(), order_count=order_count, support_count=support_count)


@app.route('/admin/logout', methods=['POST'])
@admin
def logout():
    session.clear(); return redirect('/')


@app.route('/admin/new', methods=['GET', 'POST'])
@admin
def new():
    if request.method == 'POST': return save_product()
    return render_template_string("{% extends 'form' %}", product=None, token=csrf())


@app.route('/admin/edit/<int:pid>', methods=['GET', 'POST'])
@admin
def edit(pid):
    with connect() as c: p = c.execute('SELECT * FROM products WHERE id=?', (pid,)).fetchone()
    if not p: abort(404)
    if request.method == 'POST': return save_product(pid, p)
    return render_template_string("{% extends 'form' %}", product=p, token=csrf())


def save_product(pid=None, old=None):
    name = request.form.get('name', '').strip(); price = request.form.get('price', '').strip()
    sale = request.form.get('sale_price', '').strip(); desc = request.form.get('description', '').strip()
    if not name or not price: flash('Ürün adı ve fiyat zorunlu.'); return redirect(request.path)
    if sale and parse_price(sale) >= parse_price(price): flash('İndirimli fiyat normal fiyattan düşük olmalı.'); return redirect(request.path)
    image = old['image'] if old else ''; f = request.files.get('image')
    if f and f.filename:
        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
        if ext not in ALLOWED: flash('PNG, JPG, WEBP veya GIF görsel yükle.'); return redirect(request.path)
        image = secrets.token_hex(8) + '_' + secure_filename(f.filename); f.save(UPLOADS / image)
    with connect() as c:
        if pid: c.execute('UPDATE products SET name=?,description=?,price=?,image=?,sale_price=? WHERE id=?', (name, desc, price, image, sale, pid))
        else: c.execute('INSERT INTO products(name,description,price,image,sale_price) VALUES(?,?,?,?,?)', (name, desc, price, image, sale))
    flash('Ürün kaydedildi.'); return redirect('/admin')


@app.route('/admin/delete/<int:pid>', methods=['POST'])
@admin
def delete(pid):
    with connect() as c:
        row = c.execute('SELECT image FROM products WHERE id=?', (pid,)).fetchone()
        c.execute('DELETE FROM reviews WHERE product_id=?', (pid,)); c.execute('DELETE FROM products WHERE id=?', (pid,))
    if row and row['image']:
        try: (UPLOADS / row['image']).unlink(missing_ok=True)
        except OSError: pass
    flash('Ürün silindi.'); return redirect('/admin')


ORDER_STATUSES = ['Sipariş alındı', 'Onaylandı', 'Hazırlanıyor', 'Kargoya verildi', 'Teslim edildi', 'İptal edildi']

@app.route('/admin/orders')
@admin
def admin_orders():
    with connect() as c: orders = c.execute('SELECT * FROM orders ORDER BY id DESC').fetchall()
    return render_template_string("{% extends 'orders' %}", orders=orders, statuses=ORDER_STATUSES, token=csrf(), money=money)


@app.route('/admin/orders/<int:oid>', methods=['POST'])
@admin
def admin_order_update(oid):
    status = request.form.get('status', '')
    if status not in ORDER_STATUSES: abort(400)
    with connect() as c: c.execute('UPDATE orders SET status=? WHERE id=?', (status, oid))
    flash('Sipariş durumu güncellendi.'); return redirect('/admin/orders')


@app.route('/admin/coupons', methods=['GET', 'POST'])
@admin
def admin_coupons():
    if request.method == 'POST':
        code = re.sub(r'[^A-Z0-9_-]', '', request.form.get('code', '').strip().upper())[:40]
        kind = request.form.get('kind', 'percent')
        try: amount = float(request.form.get('amount', '0'))
        except ValueError: amount = 0
        if not code or kind not in ('percent', 'fixed') or amount <= 0 or (kind == 'percent' and amount > 100):
            flash('Kupon bilgilerini kontrol et.'); return redirect('/admin/coupons')
        try:
            with connect() as c: c.execute('INSERT INTO coupons(code,kind,amount) VALUES(?,?,?)', (code, kind, amount))
            flash('Kupon oluşturuldu.')
        except sqlite3.IntegrityError: flash('Bu kupon kodu zaten var.')
        return redirect('/admin/coupons')
    with connect() as c: coupons = c.execute('SELECT * FROM coupons ORDER BY id DESC').fetchall()
    return render_template_string("{% extends 'coupons' %}", coupons=coupons, token=csrf())


@app.route('/admin/coupons/<int:cid>/toggle', methods=['POST'])
@admin
def coupon_toggle(cid):
    with connect() as c: c.execute('UPDATE coupons SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?', (cid,))
    return redirect('/admin/coupons')


@app.route('/admin/support')
@admin
def admin_support():
    with connect() as c:
        visitors = c.execute('''SELECT visitor_id, COUNT(*) count, MAX(created_at) created_at,
            (SELECT message FROM support_messages s2 WHERE s2.visitor_id=s.visitor_id ORDER BY id DESC LIMIT 1) last_message
            FROM support_messages s GROUP BY visitor_id ORDER BY MAX(id) DESC''').fetchall()
    return render_template_string("{% extends 'support_admin' %}", visitors=visitors)


@app.route('/admin/support/<visitor_id>', methods=['GET', 'POST'])
@admin
def admin_support_thread(visitor_id):
    if request.method == 'POST':
        message = request.form.get('message', '').strip()[:500]
        if message:
            with connect() as c: c.execute("INSERT INTO support_messages(visitor_id,sender,message) VALUES(?,'admin',?)", (visitor_id, message))
        return redirect(request.path)
    with connect() as c: messages = c.execute('SELECT * FROM support_messages WHERE visitor_id=? ORDER BY id ASC LIMIT 200', (visitor_id,)).fetchall()
    return render_template_string("{% extends 'support_thread' %}", messages=messages, token=csrf())


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '5000')))
