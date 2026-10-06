import os, io, csv, json, random, secrets, sqlite3
from datetime import datetime
from functools import wraps
import qrcode
from flask import Flask, request, session, redirect, url_for, flash, Response, send_from_directory, render_template_string
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix

BASE=os.path.dirname(os.path.abspath(__file__))
DB=os.getenv('DB_NAME',os.path.join(BASE,'sorteador.db'))
UPLOAD=os.getenv('UPLOAD_DIR',os.path.join(BASE,'uploads'))
os.makedirs(UPLOAD,exist_ok=True)
app=Flask(__name__); app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1,x_host=1)
app.secret_key=os.getenv('SECRET_KEY',secrets.token_hex(32))
app.config.update(MAX_CONTENT_LENGTH=8*1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=True)
ALLOWED={'png','jpg','jpeg','webp','gif'}

def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def now(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
def csrf():
 if 'csrf' not in session: session['csrf']=secrets.token_urlsafe(24)
 return session['csrf']
def okcsrf(): return secrets.compare_digest(request.form.get('csrf',''),session.get('csrf',''))
def admin(fn):
 @wraps(fn)
 def w(*a,**k): return fn(*a,**k) if session.get('uid') else redirect(url_for('login'))
 return w

def init():
 c=db(); c.executescript('''
 CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,name TEXT,active INTEGER DEFAULT 1);
 CREATE TABLE IF NOT EXISTS campaigns(id INTEGER PRIMARY KEY,name TEXT,title TEXT,prize TEXT,draw_at TEXT,terms TEXT,image TEXT DEFAULT '',active INTEGER DEFAULT 0,created_at TEXT);
 CREATE TABLE IF NOT EXISTS participants(id INTEGER PRIMARY KEY,campaign_id INTEGER,name TEXT,whatsapp TEXT,email TEXT,company TEXT,created_at TEXT,winner INTEGER DEFAULT 0,allow_again INTEGER DEFAULT 1,blocked INTEGER DEFAULT 0,UNIQUE(campaign_id,email));
 CREATE TABLE IF NOT EXISTS draws(id INTEGER PRIMARY KEY,campaign_id INTEGER,drawn_at TEXT,winner_ids TEXT,operator TEXT);
 ''')
 if not c.execute('select 1 from campaigns limit 1').fetchone():
  c.execute('insert into campaigns(name,title,prize,terms,active,created_at) values(?,?,?,?,1,?)',('Campanha principal','Participe do nosso sorteio','Kit Neos + Brindes','Ao participar, você concorda com as regras da ação.',now()))
 if not c.execute('select 1 from users limit 1').fetchone():
  user=os.getenv('ADMIN_USER','admin'); pwd=os.getenv('ADMIN_PASSWORD') or secrets.token_urlsafe(10)
  c.execute('insert into users(username,password,name) values(?,?,?)',(user,generate_password_hash(pwd),'Administrador'))
  print(f'INITIAL_ADMIN_USER={user}',flush=True); print(f'INITIAL_ADMIN_PASSWORD={pwd}',flush=True)
 c.commit(); c.close()

def camp():
 c=db(); r=c.execute('select * from campaigns where active=1 order by id desc limit 1').fetchone(); c.close(); return r

def saveimg(f):
 if not f or not f.filename: return ''
 n=secure_filename(f.filename); ext=n.rsplit('.',1)[-1].lower() if '.' in n else ''
 if ext not in ALLOWED: return ''
 n=f'{datetime.now().strftime("%Y%m%d%H%M%S")}_{secrets.token_hex(3)}.{ext}'; f.save(os.path.join(UPLOAD,n)); return n

CSS='''
:root{--p:#172554;--a:#14b8a6;--bg:#f6f8fb;--tx:#172033}*{box-sizing:border-box}body{margin:0;font-family:Inter,Arial,sans-serif;background:var(--bg);color:var(--tx)}a{text-decoration:none}.wrap{max-width:1180px;margin:auto;padding:28px}.brand{font-size:25px;font-weight:800;color:var(--p)}.brand b{color:var(--a)}.hero{background:linear-gradient(135deg,#0f1f4b,#18366f);color:#fff;border-radius:26px;padding:48px;display:grid;grid-template-columns:1.4fr 1fr;gap:28px;align-items:center}.hero h1{font-size:48px;margin:12px 0}.btn{display:inline-block;border:0;border-radius:12px;padding:13px 18px;font-weight:750;cursor:pointer;background:var(--p);color:white}.btn.a{background:var(--a);color:#042f2e}.btn.red{background:#b91c1c}.btn.gray{background:#e5e7eb;color:#111827}.card{background:white;border:1px solid #e5e7eb;border-radius:18px;padding:22px;margin:16px 0;box-shadow:0 7px 24px #0f172a0a}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.input,textarea,select{width:100%;padding:12px;border:1px solid #cbd5e1;border-radius:10px;margin:6px 0 13px;background:white}.prizeimg{max-width:100%;max-height:330px;border-radius:18px;object-fit:contain;background:white}.top{display:flex;justify-content:space-between;align-items:center;gap:15px}.muted{color:#64748b}.flash{padding:12px;background:#ecfeff;border:1px solid #99f6e4;border-radius:10px;margin:10px 0}.table{width:100%;border-collapse:collapse;font-size:14px}.table th,.table td{padding:10px;border-bottom:1px solid #e5e7eb;text-align:left}.pill{padding:4px 8px;border-radius:999px;background:#eef2ff}.actions form{display:inline-block;margin:2px}.winner{font-size:56px;font-weight:900;text-align:center;color:var(--p);padding:40px}.login{max-width:430px;margin:70px auto}.qr{max-width:220px}.sectiontitle{margin-top:34px}@media(max-width:800px){.hero,.grid{grid-template-columns:1fr}.hero h1{font-size:36px}.wrap{padding:16px}.table{font-size:12px}}
'''

def layout(title,body):
 msgs=''.join(f'<div class="flash">{m}</div>' for m in __import__('flask').get_flashed_messages())
 return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{CSS}</style></head><body>{msgs}{body}</body></html>'''

@app.route('/health')
def health(): return {'ok':True}
@app.route('/uploads/<path:n>')
def up(n): return send_from_directory(UPLOAD,n)

@app.route('/')
def home():
 x=camp(); img=f'<img class="prizeimg" src="/uploads/{x["image"]}">' if x and x['image'] else '<div style="font-size:120px;text-align:center">🎁</div>'
 body=f'''<div class="wrap"><div class="top"><div class="brand">Zanthus <b>| Neos</b></div><a href="/admin/login">Área administrativa</a></div><div class="hero"><div><div>{x['name']}</div><h1>{x['title']}</h1><p>Cadastre-se e concorra a <b>{x['prize']}</b>.</p><a class="btn a" href="/cadastro">QUERO PARTICIPAR →</a></div><div>{img}</div></div></div>'''; return layout('Sorteio Zanthus | Neos',body)

@app.route('/cadastro',methods=['GET','POST'])
def cadastro():
 x=camp()
 if request.method=='POST':
  if not okcsrf(): flash('Sessão expirada.'); return redirect('/cadastro')
  vals=[request.form.get(k,'').strip() for k in ('name','whatsapp','email','company')]
  if not all(vals) or not request.form.get('consent'): flash('Preencha todos os campos.'); return redirect('/cadastro')
  c=db()
  try:c.execute('insert into participants(campaign_id,name,whatsapp,email,company,created_at) values(?,?,?,?,?,?)',(x['id'],vals[0],vals[1],vals[2].lower(),vals[3],now()));c.commit()
  except sqlite3.IntegrityError: c.close(); flash('Este e-mail já está cadastrado nesta campanha.'); return redirect('/cadastro')
  c.close(); return redirect('/sucesso')
 img=f'<img class="prizeimg" src="/uploads/{x["image"]}">' if x['image'] else ''
 body=f'''<div class="wrap"><div class="card" style="max-width:650px;margin:auto"><div class="brand">Zanthus <b>| Neos</b></div><h1>Faça seu cadastro</h1>{img}<p><b>Prêmio:</b> {x['prize']}</p><form method="post"><input type="hidden" name="csrf" value="{csrf()}"><label>Nome</label><input class="input" name="name" required><label>WhatsApp</label><input class="input" name="whatsapp" required><label>E-mail</label><input class="input" type="email" name="email" required><label>Empresa</label><input class="input" name="company" required><label><input type="checkbox" name="consent" required> {x['terms']}</label><br><br><button class="btn a">CADASTRAR E PARTICIPAR</button></form></div></div>'''; return layout('Cadastro',body)

@app.route('/sucesso')
def sucesso(): return layout('Sucesso','<div class="wrap"><div class="card" style="text-align:center"><h1>✅ Cadastro realizado!</h1><p>Você já está participando. Boa sorte!</p><a class="btn" href="/">Voltar</a></div></div>')

@app.route('/admin/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  c=db(); u=c.execute('select * from users where username=? and active=1',(request.form.get('username',''),)).fetchone(); c.close()
  if u and check_password_hash(u['password'],request.form.get('password','')): session['uid']=u['id'];session['user']=u['username'];return redirect('/admin')
  flash('Usuário ou senha inválidos.')
 body='''<div class="login card"><div class="brand">Zanthus <b>| Neos</b></div><h1>Painel administrativo</h1><form method="post"><input class="input" name="username" placeholder="Usuário" required><input class="input" type="password" name="password" placeholder="Senha" required><button class="btn" style="width:100%">ENTRAR</button></form></div>'''; return layout('Login',body)
@app.route('/admin/logout')
def logout(): session.clear(); return redirect('/')

@app.route('/admin')
@admin
def painel():
 x=camp(); c=db(); ps=c.execute('select * from participants where campaign_id=? order by id desc',(x['id'],)).fetchall(); cs=c.execute('select * from campaigns order by id desc').fetchall(); ds=c.execute('select * from draws where campaign_id=? order by id desc limit 20',(x['id'],)).fetchall(); c.close()
 rows=''.join(f'''<tr><td>{p['name']}</td><td>{p['company']}</td><td>{'🏆' if p['winner'] else '—'}</td><td>{'Bloqueado' if p['blocked'] else ('Elegível' if not p['winner'] else 'Sorteado')}</td><td class="actions"><form method="post" action="/admin/p/{p['id']}/block"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn gray">{'Desbloquear' if p['blocked'] else 'Bloquear'}</button></form><form method="post" action="/admin/p/{p['id']}/again"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn gray">{'Não repetir' if p['allow_again'] else 'Pode repetir'}</button></form><form method="post" action="/admin/p/{p['id']}/reenter"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn a">Recolocar</button></form></td></tr>''' for p in ps)
 camps=''.join(f'<option value="{z["id"]}" {"selected" if z["active"] else ""}>{z["name"]}</option>' for z in cs)
 hist=''.join(f'<li>{d["drawn_at"]} — operador {d["operator"]}</li>' for d in ds) or '<li>Sem sorteios ainda.</li>'
 body=f'''<div class="wrap"><div class="top"><div class="brand">Zanthus <b>| Neos</b></div><div><a href="/qr.png">QR Code</a> · <a href="/admin/export">CSV</a> · <a href="/admin/logout">Sair</a></div></div><h1>Painel do Sorteio</h1><div class="grid"><div class="card"><b>Participantes</b><div style="font-size:38px">{len(ps)}</div></div><div class="card"><b>Campanha ativa</b><div>{x['name']}</div></div><div class="card"><b>Prêmio</b><div>{x['prize']}</div></div></div><div class="card"><h2>Sorteio</h2><form method="post" action="/admin/draw"><input type="hidden" name="csrf" value="{csrf()}"><label>Quantidade de ganhadores</label><input class="input" type="number" min="1" max="20" value="1" name="count"><button class="btn a">🎲 SORTEAR AGORA</button></form><form method="post" action="/admin/reenter-all" style="margin-top:10px"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn gray">↻ Recolocar ganhadores permitidos</button></form></div><div class="card"><h2>Participantes</h2><div style="overflow:auto"><table class="table"><tr><th>Nome</th><th>Empresa</th><th>Ganhou</th><th>Status</th><th>Ações</th></tr>{rows}</table></div></div><div class="card"><h2>Campanhas</h2><form method="post" action="/admin/campaign"><input type="hidden" name="csrf" value="{csrf()}"><input class="input" name="name" placeholder="Nome da campanha" required><input class="input" name="title" placeholder="Título da LP" required><input class="input" name="prize" placeholder="Prêmio" required><input class="input" name="draw_at" placeholder="Data/horário do sorteio"><textarea name="terms" placeholder="Termos"></textarea><input class="input" type="file" name="image" disabled><button class="btn">Criar campanha</button></form><p class="muted">Imagem do prêmio: use a edição da campanha abaixo.</p><form method="post" action="/admin/activate"><input type="hidden" name="csrf" value="{csrf()}"><select name="id">{camps}</select><button class="btn gray">Ativar selecionada</button></form><hr><form method="post" enctype="multipart/form-data" action="/admin/campaign/{x['id']}/image"><input type="hidden" name="csrf" value="{csrf()}"><label>Imagem do prêmio da campanha ativa</label><input class="input" type="file" name="image" accept="image/*" required><button class="btn">Enviar imagem</button></form></div><div class="card"><h2>Histórico</h2><ul>{hist}</ul></div></div>'''; return layout('Painel',body)

@app.post('/admin/campaign')
@admin
def newcamp():
 if not okcsrf(): return redirect('/admin')
 c=db(); c.execute('insert into campaigns(name,title,prize,draw_at,terms,created_at) values(?,?,?,?,?,?)',(request.form['name'],request.form['title'],request.form['prize'],request.form.get('draw_at',''),request.form.get('terms',''),now()));c.commit();c.close();flash('Campanha criada.');return redirect('/admin')
@app.post('/admin/activate')
@admin
def activate():
 if not okcsrf(): return redirect('/admin')
 c=db();c.execute('update campaigns set active=0');c.execute('update campaigns set active=1 where id=?',(request.form['id'],));c.commit();c.close();return redirect('/admin')
@app.post('/admin/campaign/<int:i>/image')
@admin
def image(i):
 if not okcsrf(): return redirect('/admin')
 n=saveimg(request.files.get('image')); c=db(); c.execute('update campaigns set image=? where id=?',(n,i));c.commit();c.close();flash('Imagem atualizada.');return redirect('/admin')
@app.post('/admin/p/<int:i>/block')
@admin
def block(i):
 if not okcsrf(): return redirect('/admin')
 c=db();c.execute('update participants set blocked=case blocked when 1 then 0 else 1 end where id=?',(i,));c.commit();c.close();return redirect('/admin')
@app.post('/admin/p/<int:i>/again')
@admin
def again(i):
 if not okcsrf(): return redirect('/admin')
 c=db();c.execute('update participants set allow_again=case allow_again when 1 then 0 else 1 end where id=?',(i,));c.commit();c.close();return redirect('/admin')
@app.post('/admin/p/<int:i>/reenter')
@admin
def reenter(i):
 if not okcsrf(): return redirect('/admin')
 c=db();p=c.execute('select * from participants where id=?',(i,)).fetchone()
 if p and p['allow_again'] and not p['blocked']: c.execute('update participants set winner=0 where id=?',(i,));c.commit();flash('Participante recolocado.')
 else: flash('Participante não pode voltar ao sorteio.')
 c.close();return redirect('/admin')
@app.post('/admin/reenter-all')
@admin
def reall():
 if not okcsrf(): return redirect('/admin')
 x=camp();c=db();c.execute('update participants set winner=0 where campaign_id=? and allow_again=1 and blocked=0',(x['id'],));c.commit();c.close();flash('Ganhadores permitidos recolocados.');return redirect('/admin')

@app.post('/admin/draw')
@admin
def draw():
 if not okcsrf(): return redirect('/admin')
 x=camp(); n=max(1,min(int(request.form.get('count','1')),20)); c=db(); pool=c.execute('select * from participants where campaign_id=? and winner=0 and blocked=0',(x['id'],)).fetchall()
 if len(pool)<n: c.close();flash('Participantes elegíveis insuficientes.');return redirect('/admin')
 ws=random.SystemRandom().sample(pool,n); ids=[w['id'] for w in ws]
 for i in ids:c.execute('update participants set winner=1 where id=?',(i,))
 c.execute('insert into draws(campaign_id,drawn_at,winner_ids,operator) values(?,?,?,?)',(x['id'],now(),json.dumps(ids),session['user']));c.commit();c.close(); return redirect('/admin/draw-screen?ids='+','.join(map(str,ids)))
@app.route('/admin/draw-screen')
@admin
def screen():
 ids=[int(x) for x in request.args.get('ids','').split(',') if x.isdigit()]; c=db(); q=','.join('?'*len(ids)); ws=c.execute(f'select * from participants where id in ({q})',ids).fetchall() if ids else []; c.close(); cards=''.join(f'<div class="winner">🏆 {w["name"]}<div style="font-size:22px">{w["company"]}</div></div>' for w in ws); return layout('Resultado',f'<div class="wrap"><div class="brand">Zanthus <b>| Neos</b></div><h1 style="text-align:center">RESULTADO DO SORTEIO</h1>{cards}<div style="text-align:center"><a class="btn" href="/admin">Voltar ao painel</a></div></div>')

@app.route('/admin/export')
@admin
def export():
 x=camp();c=db();rs=c.execute('select * from participants where campaign_id=? order by id',(x['id'],)).fetchall();c.close();o=io.StringIO();w=csv.writer(o);w.writerow(['Nome','WhatsApp','Email','Empresa','Ganhador','Pode repetir','Bloqueado']);[w.writerow([r['name'],r['whatsapp'],r['email'],r['company'],r['winner'],r['allow_again'],r['blocked']]) for r in rs];return Response('\ufeff'+o.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=participantes.csv'})
@app.route('/qr.png')
def qr():
 img=qrcode.make(request.url_root.rstrip('/')+'/cadastro'); b=io.BytesIO();img.save(b,format='PNG');b.seek(0);return Response(b.getvalue(),mimetype='image/png')

init()
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT','5000')))
