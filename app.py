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
def admin_only(fn):
 @wraps(fn)
 def w(*a,**k):
  if not session.get('uid'): return redirect(url_for('login'))
  if session.get('role')!='admin': flash('Acesso restrito a administradores.'); return redirect('/admin')
  return fn(*a,**k)
 return w

def init():
 c=db(); c.executescript('''
 CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,name TEXT,active INTEGER DEFAULT 1);
 CREATE TABLE IF NOT EXISTS campaigns(id INTEGER PRIMARY KEY,name TEXT,title TEXT,prize TEXT,draw_at TEXT,terms TEXT,image TEXT DEFAULT '',active INTEGER DEFAULT 0,created_at TEXT);
 CREATE TABLE IF NOT EXISTS participants(id INTEGER PRIMARY KEY,campaign_id INTEGER,name TEXT,whatsapp TEXT,email TEXT,company TEXT,created_at TEXT,winner INTEGER DEFAULT 0,allow_again INTEGER DEFAULT 1,blocked INTEGER DEFAULT 0,UNIQUE(campaign_id,email));
 CREATE TABLE IF NOT EXISTS draws(id INTEGER PRIMARY KEY,campaign_id INTEGER,drawn_at TEXT,winner_ids TEXT,operator TEXT);\n CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY,user_id INTEGER,username TEXT,action TEXT,details TEXT,created_at TEXT);
 ''')
 if not c.execute('select 1 from campaigns limit 1').fetchone():
  c.execute('insert into campaigns(name,title,prize,terms,active,created_at) values(?,?,?,?,1,?)',('Campanha principal','Participe do nosso sorteio','Kit Neos + Brindes','Ao participar, você concorda com as regras da ação.',now()))
 if not c.execute('select 1 from users limit 1').fetchone():
  user=os.getenv('ADMIN_USER','admin'); pwd=os.getenv('ADMIN_PASSWORD') or secrets.token_urlsafe(10)
  c.execute('insert into users(username,password,name) values(?,?,?)',(user,generate_password_hash(pwd),'Administrador'))
  print(f'INITIAL_ADMIN_USER={user}',flush=True); print(f'INITIAL_ADMIN_PASSWORD={pwd}',flush=True)
 cols=[r['name'] for r in c.execute('pragma table_info(users)').fetchall()]
 if 'force_password_change' not in cols:
  c.execute('alter table users add column force_password_change INTEGER DEFAULT 0')
 if 'role' not in cols:
  c.execute("alter table users add column role TEXT DEFAULT 'user'")
 c.execute("update users set role='admin' where username='admin'")
 c.commit(); c.close()

def audit(action,details='',conn=None):
 own=conn is None; c=conn or db()
 c.execute('insert into audit_logs(user_id,username,action,details,created_at) values(?,?,?,?,?)',(session.get('uid'),session.get('user','sistema'),action,details,now()))
 if own: c.commit(); c.close()

def camp(cid=None,active_only=False):
 c=db()
 if cid:
  sql='select * from campaigns where id=?'+(' and active=1' if active_only else ''); r=c.execute(sql,(cid,)).fetchone()
 else: r=c.execute('select * from campaigns where active=1 order by id desc limit 1').fetchone()
 c.close(); return r

def saveimg(f):
 if not f or not f.filename: return ''
 n=secure_filename(f.filename); ext=n.rsplit('.',1)[-1].lower() if '.' in n else ''
 if ext not in ALLOWED: return ''
 n=f'{datetime.now().strftime("%Y%m%d%H%M%S")}_{secrets.token_hex(3)}.{ext}'; f.save(os.path.join(UPLOAD,n)); return n

CSS='''
:root{--p:#172554;--a:#14b8a6;--bg:#f6f8fb;--tx:#172033}*{box-sizing:border-box}body{margin:0;font-family:Inter,Arial,sans-serif;background:var(--bg);color:var(--tx)}a{text-decoration:none}.wrap{max-width:1180px;margin:auto;padding:28px}.brand{font-size:25px;font-weight:800;color:var(--p)}.brand b{color:var(--a)}.hero{background:linear-gradient(135deg,#0f1f4b,#18366f);color:#fff;border-radius:26px;padding:48px;display:grid;grid-template-columns:1.4fr 1fr;gap:28px;align-items:center}.hero h1{font-size:48px;margin:12px 0}.btn{display:inline-block;border:0;border-radius:12px;padding:13px 18px;font-weight:750;cursor:pointer;background:var(--p);color:white}.btn.a{background:var(--a);color:#042f2e}.btn.red{background:#b91c1c}.btn.gray{background:#e5e7eb;color:#111827}.card{background:white;border:1px solid #e5e7eb;border-radius:18px;padding:22px;margin:16px 0;box-shadow:0 7px 24px #0f172a0a}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.input,textarea,select{width:100%;padding:12px;border:1px solid #cbd5e1;border-radius:10px;margin:6px 0 13px;background:white}.prizeimg{max-width:100%;max-height:330px;border-radius:18px;object-fit:contain;background:white}.top{display:flex;justify-content:space-between;align-items:center;gap:15px}.muted{color:#64748b}.flash{padding:12px;background:#ecfeff;border:1px solid #99f6e4;border-radius:10px;margin:10px 0}.table{width:100%;border-collapse:collapse;font-size:14px}.table th,.table td{padding:10px;border-bottom:1px solid #e5e7eb;text-align:left}.pill{padding:4px 8px;border-radius:999px;background:#eef2ff}.actions form{display:inline-block;margin:2px}.winner{font-size:56px;font-weight:900;text-align:center;color:var(--p);padding:40px}.login{max-width:430px;margin:70px auto}.qr{max-width:220px}.sectiontitle{margin-top:34px}@media(max-width:800px){.hero,.grid{grid-template-columns:1fr}.hero h1{font-size:36px}.wrap{padding:16px}.table{font-size:12px}}
.raffle-stage{min-height:100vh;background:radial-gradient(circle at 50% 25%,#087c83 0,#00485f 35%,#00283f 70%,#001a2c 100%);color:#fff;display:flex;align-items:center;justify-content:center;position:relative;overflow:hidden}.particles{position:absolute;inset:0;background-image:radial-gradient(circle,rgba(77,231,216,.34) 1px,transparent 1px);background-size:34px 34px;animation:particleMove 16s linear infinite}.raffle-inner{position:relative;z-index:2;text-align:center;width:min(1000px,92vw);padding:35px}.raffle-brand{font-size:26px;font-weight:900;margin-bottom:38px}.raffle-brand span,.raffle-label,.prize-caption{color:#4de7d8}.raffle-label{font-size:13px;letter-spacing:4px;font-weight:900}.raffle-inner h1{font-size:64px}.countdown{font-size:150px;font-weight:900;text-shadow:0 0 45px rgba(77,231,216,.65);margin:24px}.spinner-ring{width:190px;height:190px;border:3px solid rgba(255,255,255,.12);border-top-color:#4de7d8;border-radius:50%;position:absolute;left:50%;transform:translate(-50%,-185px);animation:spin 1.1s linear infinite}.raffle-msg{font-size:22px;font-weight:700}.fade-out{animation:fadeOut .65s both}.winner-area{display:none}.winner-area.show{display:block;animation:reveal .9s both}.reveal-card{background:#fff;color:#003b5c;border-radius:28px;padding:30px;margin:22px auto;max-width:720px;box-shadow:0 25px 80px rgba(0,0,0,.32)}.winner-name{font-size:52px;font-weight:900}.winner-company{font-size:23px}.raffle-back,.raffle-button{display:inline-block;background:#4de7d8;color:#003b5c;border:0;border-radius:12px;padding:15px 25px;font-weight:900;text-decoration:none;cursor:pointer;margin-top:22px}.register-stage{align-items:flex-start;padding:36px 0}.register-shell{position:relative;z-index:2;width:min(1120px,92vw)}.register-grid{display:grid;grid-template-columns:1.05fr .95fr;gap:30px}.prize-show,.register-card{border-radius:28px;padding:34px}.prize-show{background:rgba(0,37,57,.45);border:1px solid rgba(77,231,216,.25)}.prize-show h1{font-size:42px}.prize-show .prizeimg{height:330px;width:100%;object-fit:contain;background:#fff;border-radius:20px;margin:18px 0}.register-card{background:#fff;color:#244653;box-shadow:0 25px 80px rgba(0,0,0,.22)}.register-card h2{font-size:34px;color:#003b5c}.register-card .input{background:#f5f9fa}.register-card .raffle-button{width:100%}@keyframes spin{to{transform:translate(-50%,-185px) rotate(360deg)}}@keyframes particleMove{to{background-position:0 136px}}@keyframes fadeOut{to{opacity:0;transform:scale(.9)}}@keyframes reveal{from{opacity:0;transform:scale(.65)}to{opacity:1;transform:scale(1)}}@media(max-width:800px){.register-grid{grid-template-columns:1fr}.raffle-inner h1{font-size:42px}.countdown{font-size:110px}.winner-name{font-size:36px}.prize-show .prizeimg{height:240px}}
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
 c=db(); cs=c.execute('select * from campaigns where active=1 order by id desc').fetchall(); c.close()
 if not cs: return layout('Sorteio Zanthus | Neos','<div class="wrap"><div class="brand">Zanthus <b>| Neos</b></div><div class="card"><h1>Nenhuma campanha ativa no momento.</h1></div></div>')
 cards=''.join(f'''<div class="card"><h2>{x["title"]}</h2>{f'<img class="prizeimg" src="/uploads/{x["image"]}">' if x["image"] else ''}<p><b>Prêmio:</b> {x["prize"]}</p><a class="btn a" href="/cadastro/{x["id"]}">QUERO PARTICIPAR →</a></div>''' for x in cs)
 return layout('Sorteio Zanthus | Neos',f'''<div class="wrap"><div class="top"><div class="brand">Zanthus <b>| Neos</b></div><a href="/admin/login">Área administrativa</a></div><h1>Campanhas ativas</h1><div class="grid">{cards}</div></div>''')

@app.route('/cadastro')
def cadastro_padrao():
 x=camp(); return redirect(f'/cadastro/{x["id"]}') if x else redirect('/')

@app.route('/cadastro/<int:cid>',methods=['GET','POST'])
def cadastro(cid):
 x=camp(cid,True)
 if not x: return layout('Campanha indisponível','<div class="wrap"><div class="card"><h1>Campanha indisponível</h1></div></div>'),404
 if request.method=='POST':
  if not okcsrf(): flash('Sessão expirada.'); return redirect(f'/cadastro/{cid}')
  vals=[request.form.get(k,'').strip() for k in ('name','whatsapp','email','company')]
  if not all(vals) or not request.form.get('consent'): flash('Preencha todos os campos.'); return redirect(f'/cadastro/{cid}')
  c=db()
  try: c.execute('insert into participants(campaign_id,name,whatsapp,email,company,created_at) values(?,?,?,?,?,?)',(cid,vals[0],vals[1],vals[2].lower(),vals[3],now()));c.commit()
  except sqlite3.IntegrityError: c.close();flash('Este e-mail já está cadastrado nesta campanha.');return redirect(f'/cadastro/{cid}')
  c.close();return redirect(f'/sucesso/{cid}')
 img=f'<img class="prizeimg" src="/uploads/{x["image"]}">' if x['image'] else ''
 body=f'''<div class="raffle-stage register-stage"><div class="particles"></div><div class="register-shell"><div class="raffle-brand">ZANTHUS <span>| NEOS</span></div><div class="register-grid"><section class="prize-show"><div class="raffle-label">SORTEIO ESPECIAL</div><h1>{x["title"]}</h1>{img}<div class="prize-caption">VOCÊ PODE GANHAR</div><h2>{x["prize"]}</h2></section><section class="register-card"><div class="raffle-label">PARTICIPE AGORA</div><h2>Faça seu cadastro</h2><p>Preencha seus dados e boa sorte!</p><form method="post"><input type="hidden" name="csrf" value="{csrf()}"><label>Nome</label><input class="input" name="name" required><label>WhatsApp</label><input class="input" name="whatsapp" required><label>E-mail</label><input class="input" type="email" name="email" required><label>Empresa</label><input class="input" name="company" required><label class="terms"><input type="checkbox" name="consent" required> {x["terms"]}</label><button class="raffle-button">QUERO PARTICIPAR</button></form></section></div></div></div>'''
 return layout('Cadastro',body)

@app.route('/sucesso/<int:cid>')
def sucesso(cid): return layout('Sucesso',f'<div class="wrap"><div class="card" style="text-align:center"><h1>✅ Cadastro realizado!</h1><p>Você já está participando. Boa sorte!</p><a class="btn" href="/cadastro/{cid}">Voltar</a></div></div>')

@app.route('/admin/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  c=db(); u=c.execute('select * from users where username=? and active=1',(request.form.get('username',''),)).fetchone(); c.close()
  if u and check_password_hash(u['password'],request.form.get('password','')):
   session['uid']=u['id'];session['user']=u['username'];session['role']=u['role'] if 'role' in u.keys() else ('admin' if u['username']=='admin' else 'user');audit('LOGIN','Acesso ao painel administrativo')
   if ('force_password_change' in u.keys()) and u['force_password_change']: session['must_change_password']=1; return redirect('/admin/minha-senha')
   return redirect('/admin')
  flash('Usuário ou senha inválidos.')
 body='''<div class="login card"><div class="brand">Zanthus <b>| Neos</b></div><h1>Painel administrativo</h1><form method="post"><input class="input" name="username" placeholder="Usuário" required><input class="input" type="password" name="password" placeholder="Senha" required><button class="btn" style="width:100%">ENTRAR</button></form></div>'''; return layout('Login',body)
@app.route('/admin/minha-senha',methods=['GET','POST'])
@admin
def mypassword():
 if request.method=='POST':
  if not okcsrf(): flash('Sessão expirada.'); return redirect('/admin/minha-senha')
  p=request.form.get('password',''); p2=request.form.get('password2','')
  if len(p)<8: flash('A senha deve ter pelo menos 8 caracteres.'); return redirect('/admin/minha-senha')
  if p!=p2: flash('As senhas não conferem.'); return redirect('/admin/minha-senha')
  c=db();c.execute('update users set password=?,force_password_change=0 where id=?',(generate_password_hash(p),session['uid']));audit('SENHA_PROPRIA_DEFINIDA','Usuário definiu sua senha pessoal',c);c.commit();c.close();session.pop('must_change_password',None);flash('Senha definida com sucesso.');return redirect('/admin')
 body=f'''<div class="login card"><div class="brand">Zanthus <b>| Neos</b></div><h1>Defina sua senha</h1><form method="post"><input type="hidden" name="csrf" value="{csrf()}"><input class="input" type="password" name="password" placeholder="Nova senha" minlength="8" required><input class="input" type="password" name="password2" placeholder="Confirme a nova senha" minlength="8" required><button class="btn" style="width:100%">SALVAR MINHA SENHA</button></form></div>''';return layout('Definir senha',body)

@app.route('/admin/logout')
def logout(): session.clear(); return redirect('/')

@app.route('/admin')
@admin
def painel():
 cid=request.args.get('cid',type=int); x=camp(cid) or camp(); c=db(); cs=c.execute('select * from campaigns order by id desc').fetchall()
 if not x and cs: x=cs[0]
 ps=c.execute('select * from participants where campaign_id=? order by id desc',(x['id'],)).fetchall() if x else []
 ds=c.execute('select * from draws where campaign_id=? order by id desc limit 20',(x['id'],)).fetchall() if x else []
 us=c.execute('select id,username,name,active,force_password_change,role from users order by name,username').fetchall() if session.get('role')=='admin' else []; logs=c.execute('select * from audit_logs order by id desc limit 100').fetchall(); c.close()
 if not x:
  userrows=''.join(f'''<tr><td>{u["name"]}</td><td>{u["username"]}</td><td>{"Administrador" if u["role"]=="admin" else "Usuário"}</td><td>{("Troca de senha pendente" if u["force_password_change"] else "Ativo") if u["active"] else "Inativo"}</td><td>-</td></tr>''' for u in us)
  useradmin=(f'''<div class="card"><h2>Usuários do painel</h2><p class="muted">Crie uma campanha para liberar a operação do sorteio.</p><div style="overflow:auto"><table class="table"><tr><th>Nome</th><th>Usuário</th><th>Perfil</th><th>Status</th><th>Ações</th></tr>{userrows}</table></div></div>''' if session.get('role')=='admin' else '')
  create=f'''<div class="card"><h2>Nova campanha</h2><form method="post" enctype="multipart/form-data" action="/admin/campaign"><input type="hidden" name="csrf" value="{csrf()}"><input class="input" name="name" placeholder="Nome da campanha" required><input class="input" name="title" placeholder="Título da LP" required><input class="input" name="prize" placeholder="Prêmio" required><textarea name="terms" placeholder="Termos"></textarea><label>Imagem do prêmio</label><input class="input" type="file" name="image" accept="image/png,image/jpeg,image/webp,image/gif"><label><input type="checkbox" name="active" checked> Criar campanha ativa</label><br><br><button class="btn">Criar campanha</button></form></div>'''
  return layout('Admin',f'''<div class="wrap"><div class="top"><div class="brand">Zanthus <b>| Neos</b></div><div>Olá, {session.get("user")} · <a href="/admin/logout">Sair</a></div></div><h1>Painel do Sorteio</h1><div class="grid">{create}{useradmin}</div></div>''')
 rows=''.join(f'''<tr><td>{p['name']}</td><td>{p['company']}</td><td>{'🏆' if p['winner'] else '—'}</td><td>{'Bloqueado' if p['blocked'] else ('Elegível' if not p['winner'] else 'Sorteado')}</td><td class="actions"><form method="post" action="/admin/p/{p['id']}/block"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn gray">{'Desbloquear' if p['blocked'] else 'Bloquear'}</button></form><form method="post" action="/admin/p/{p['id']}/again"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn gray">{'Não repetir' if p['allow_again'] else 'Pode repetir'}</button></form><form method="post" action="/admin/p/{p['id']}/reenter"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn a">Recolocar</button></form></td></tr>''' for p in ps)
 camps=''.join(f'<option value="{z["id"]}" {"selected" if z["active"] else ""}>{z["name"]}</option>' for z in cs)
 hist=''.join(f'<li>{d["drawn_at"]} — operador {d["operator"]}</li>' for d in ds) or '<li>Sem sorteios ainda.</li>'
 userrows=''.join(f'''<tr><td>{u["name"]}</td><td>{u["username"]}</td><td>{"Administrador" if u["role"]=="admin" else "Usuário"}</td><td>{("Troca de senha pendente" if u["force_password_change"] else "Ativo") if u["active"] else "Inativo"}</td><td class="actions"><form method="post" action="/admin/user/{u['id']}/toggle"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn gray">{"Desativar" if u["active"] else "Ativar"}</button></form><form method="post" action="/admin/user/{u['id']}/password"><input type="hidden" name="csrf" value="{csrf()}"><input class="input" style="width:150px;display:inline" type="password" name="password" placeholder="Nova senha" minlength="8" required><button class="btn gray">Trocar senha</button></form></td></tr>''' for u in us)
 auditrows=''.join(f'<tr><td>{a["created_at"]}</td><td>{a["username"]}</td><td>{a["action"]}</td><td>{a["details"]}</td></tr>' for a in logs) or '<tr><td colspan="4">Sem alterações registradas.</td></tr>'
 useradmin=(f'''<div class="card"><h2>Usuários do painel</h2><form method="post" action="/admin/user"><input type="hidden" name="csrf" value="{csrf()}"><input class="input" name="name" placeholder="Nome" required><input class="input" name="username" placeholder="Usuário" required><select name="role" class="input" required><option value="user">Usuário</option><option value="admin">Administrador</option></select><input class="input" type="password" name="password" placeholder="Senha temporária (mínimo 8 caracteres)" minlength="8" required><label style="display:block;margin:5px 0 15px"><input type="checkbox" name="force_password_change" checked> Exigir troca de senha no primeiro acesso</label><button class="btn">Criar usuário</button></form><div style="overflow:auto"><table class="table"><tr><th>Nome</th><th>Usuário</th><th>Perfil</th><th>Status</th><th>Ações</th></tr>{userrows}</table></div></div>''' if session.get('role')=='admin' else '')
 camprows=''.join(f'''<tr><td>{z["name"]}</td><td>{"Ativa" if z["active"] else "Inativa"}</td><td>{z["created_at"]}</td><td class="actions"><a class="btn gray" href="/admin?cid={z["id"]}">Gerenciar</a> <a class="btn a" href="/qr/{z["id"]}.png" target="_blank">QR Code</a><form method="post" action="/admin/campaign/{z["id"]}/toggle"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn gray">{"Desativar" if z["active"] else "Ativar"}</button></form>{"" if z["active"] else f'<form method="post" action="/admin/campaign/{z["id"]}/delete" onsubmit="return confirm(\'Excluir esta campanha?\')"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn red">Excluir</button></form>'}</td></tr>''' for z in cs)
 body=f'''<div class="wrap"><div class="top"><div class="brand">Zanthus <b>| Neos</b></div><div><a href="/qr/{x['id']}.png">QR Code desta campanha</a> · <a href="/admin/export?cid={x['id']}">CSV</a> · <a href="/admin/logout">Sair</a></div></div><h1>Painel do Sorteio</h1><div class="grid"><div class="card"><b>Participantes</b><div style="font-size:38px">{len(ps)}</div></div><div class="card"><b>Campanha selecionada</b><div>{x['name']}</div></div><div class="card"><b>Prêmio</b><div>{x['prize']}</div></div></div><div class="card"><h2>Sorteio</h2><form method="post" action="/admin/draw"><input type="hidden" name="csrf" value="{csrf()}"><input type="hidden" name="cid" value="{x['id']}"><label>Quantidade de ganhadores</label><input class="input" type="number" min="1" max="20" value="1" name="count"><label>Segundos para revelar o resultado</label><input class="input" type="number" min="3" max="60" value="10" name="seconds"><button class="btn a">🎲 INICIAR SORTEIO</button></form><form method="post" action="/admin/reenter-all" style="margin-top:10px"><input type="hidden" name="csrf" value="{csrf()}"><input type="hidden" name="cid" value="{x['id']}"><button class="btn gray">↻ Recolocar ganhadores permitidos</button></form></div><div class="card"><h2>Participantes</h2><div style="overflow:auto"><table class="table"><tr><th>Nome</th><th>Empresa</th><th>Ganhou</th><th>Status</th><th>Ações</th></tr>{rows}</table></div></div><div class="card"><h2>Campanhas</h2><form method="post" enctype="multipart/form-data" action="/admin/campaign"><input type="hidden" name="csrf" value="{csrf()}"><input class="input" name="name" placeholder="Nome da campanha" required><input class="input" name="title" placeholder="Título da LP" required><input class="input" name="prize" placeholder="Prêmio" required><textarea name="terms" placeholder="Termos"></textarea><label>Imagem do prêmio</label><input class="input" type="file" name="image" accept="image/png,image/jpeg,image/webp,image/gif"><label><input type="checkbox" name="active" checked> Criar campanha ativa</label><br><br><button class="btn">Criar campanha</button></form><hr><form method="post" enctype="multipart/form-data" action="/admin/campaign/{x['id']}/image"><input type="hidden" name="csrf" value="{csrf()}"><label>Imagem do prêmio da campanha ativa</label><input class="input" type="file" name="image" accept="image/*" required><button class="btn">Enviar imagem</button></form></div><div class="card"><h2>Campanhas cadastradas</h2><div style="overflow:auto"><table class="table"><tr><th>Campanha</th><th>Status</th><th>Criada em</th><th>Ações</th></tr>{camprows}</table></div></div>{useradmin}<div class="card"><h2>Histórico de sorteios</h2><ul>{hist}</ul></div><details class="card"><summary style="cursor:pointer;font-size:20px;font-weight:700">Histórico de alterações</summary><p class="muted">Últimas 100 ações administrativas.</p><div style="overflow:auto"><table class="table"><tr><th>Data/hora</th><th>Usuário</th><th>Ação</th><th>Detalhes</th></tr>{auditrows}</table></div></details></div>'''; return layout('Painel',body)

@app.post('/admin/user')
@admin_only
def newuser():
 if not okcsrf(): return redirect('/admin')
 name=request.form.get('name','').strip(); username=request.form.get('username','').strip(); password=request.form.get('password',''); force=1 if request.form.get('force_password_change') else 0; role=request.form.get('role','user'); role=role if role in ('user','admin') else 'user'
 if not name or not username or len(password)<8: flash('Preencha nome, usuário e uma senha de pelo menos 8 caracteres.'); return redirect('/admin')
 c=db()
 try:
  c.execute('insert into users(username,password,name,active,force_password_change,role) values(?,?,?,?,?,?)',(username,generate_password_hash(password),name,1,force,role))
  audit('USUARIO_CRIADO',f'{name} ({username})',c); c.commit(); flash('Usuário criado com sucesso.')
 except sqlite3.IntegrityError:
  flash('Esse nome de usuário já existe.')
 finally: c.close()
 return redirect('/admin')

@app.post('/admin/user/<int:uid>/toggle')
@admin_only
def toggleuser(uid):
 if not okcsrf(): return redirect('/admin')
 if uid==session.get('uid'): flash('Você não pode desativar seu próprio usuário.'); return redirect('/admin')
 c=db();u=c.execute('select * from users where id=?',(uid,)).fetchone()
 if u:
  new=0 if u['active'] else 1;c.execute('update users set active=? where id=?',(new,uid));audit('USUARIO_STATUS_ALTERADO',f"{u['username']} -> {'ativo' if new else 'inativo'}",c);c.commit()
 c.close();return redirect('/admin')

@app.post('/admin/user/<int:uid>/password')
@admin_only
def resetuserpassword(uid):
 if not okcsrf(): return redirect('/admin')
 password=request.form.get('password','')
 if len(password)<8: flash('A senha deve ter pelo menos 8 caracteres.'); return redirect('/admin')
 c=db();u=c.execute('select * from users where id=?',(uid,)).fetchone()
 if u:
  c.execute('update users set password=?,force_password_change=1 where id=?',(generate_password_hash(password),uid));audit('SENHA_TEMPORARIA_REDEFINIDA',u['username'],c);c.commit();flash('Senha temporária definida. O usuário deverá trocá-la no próximo login.')
 c.close();return redirect('/admin')

@app.post('/admin/campaign')
@admin
def newcamp():
 if not okcsrf(): return redirect('/admin')
 n=saveimg(request.files.get('image')); active=1 if request.form.get('active') else 0; c=db(); c.execute('insert into campaigns(name,title,prize,terms,image,active,created_at) values(?,?,?,?,?,?,?)',(request.form['name'],request.form['title'],request.form['prize'],request.form.get('terms',''),n,active,now())); cid=c.execute('select last_insert_rowid()').fetchone()[0]; audit('CAMPANHA_CRIADA',request.form['name'],c);c.commit();c.close();flash('Campanha criada.');return redirect(f'/admin?cid={cid}')
@app.post('/admin/campaign/<int:i>/toggle')
@admin
def toggle_campaign(i):
 if not okcsrf(): return redirect('/admin')
 c=db(); z=c.execute('select * from campaigns where id=?',(i,)).fetchone()
 if z:
  new=0 if z['active'] else 1; c.execute('update campaigns set active=? where id=?',(new,i));audit('CAMPANHA_STATUS_ALTERADO',f"{z['name']} -> {'ativa' if new else 'inativa'}",c);c.commit()
 c.close();return redirect(f'/admin?cid={i}')
@app.post('/admin/campaign/<int:i>/image')
@admin
def image(i):
 if not okcsrf(): return redirect('/admin')
 n=saveimg(request.files.get('image')); c=db(); z=c.execute('select name from campaigns where id=?',(i,)).fetchone(); c.execute('update campaigns set image=? where id=?',(n,i));audit('IMAGEM_CAMPANHA_ATUALIZADA',z['name'] if z else str(i),c);c.commit();c.close();flash('Imagem atualizada.');return redirect(f'/admin?cid={i}')
@app.post('/admin/p/<int:i>/block')
@admin
def block(i):
 if not okcsrf(): return redirect('/admin')
 c=db();p=c.execute('select name from participants where id=?',(i,)).fetchone();c.execute('update participants set blocked=case blocked when 1 then 0 else 1 end where id=?',(i,));audit('PARTICIPANTE_BLOQUEIO_ALTERADO',p['name'] if p else str(i),c);c.commit();c.close();return redirect('/admin')
@app.post('/admin/p/<int:i>/again')
@admin
def again(i):
 if not okcsrf(): return redirect('/admin')
 c=db();p=c.execute('select name from participants where id=?',(i,)).fetchone();c.execute('update participants set allow_again=case allow_again when 1 then 0 else 1 end where id=?',(i,));audit('REENTRADA_ALTERADA',p['name'] if p else str(i),c);c.commit();c.close();return redirect('/admin')
@app.post('/admin/p/<int:i>/reenter')
@admin
def reenter(i):
 if not okcsrf(): return redirect('/admin')
 c=db();p=c.execute('select * from participants where id=?',(i,)).fetchone()
 if p and p['allow_again'] and not p['blocked']: c.execute('update participants set winner=0 where id=?',(i,));audit('PARTICIPANTE_RECOLOCADO',p['name'],c);c.commit();flash('Participante recolocado.')
 else: flash('Participante não pode voltar ao sorteio.')
 c.close();return redirect('/admin')
@app.post('/admin/reenter-all')
@admin
def reall():
 if not okcsrf(): return redirect('/admin')
 x=camp(request.form.get('cid'));c=db();c.execute('update participants set winner=0 where campaign_id=? and allow_again=1 and blocked=0',(x['id'],));audit('GANHADORES_RECOLOCADOS',x['name'],c);c.commit();c.close();flash('Ganhadores permitidos recolocados.');return redirect('/admin')

@app.post('/admin/draw')
@admin
def draw():
 if not okcsrf(): return redirect('/admin')
 x=camp(request.form.get('cid')); n=max(1,min(int(request.form.get('count','1')),20)); c=db(); pool=c.execute('select * from participants where campaign_id=? and winner=0 and blocked=0',(x['id'],)).fetchall()
 if len(pool)<n: c.close();flash('Participantes elegíveis insuficientes.');return redirect('/admin')
 ws=random.SystemRandom().sample(pool,n); ids=[w['id'] for w in ws]
 for i in ids:c.execute('update participants set winner=1 where id=?',(i,))
 c.execute('insert into draws(campaign_id,drawn_at,winner_ids,operator) values(?,?,?,?)',(x['id'],now(),json.dumps(ids),session['user']));audit('SORTEIO_REALIZADO',f'{x["name"]}: {len(ids)} ganhador(es)',c);c.commit();c.close(); seconds=max(3,min(int(request.form.get('seconds','10')),60)); return redirect('/admin/draw-screen?ids='+','.join(map(str,ids))+'&seconds='+str(seconds))
@app.route('/admin/draw-screen')
@admin
def screen():
 ids=[int(v) for v in request.args.get('ids','').split(',') if v.isdigit()]; seconds=max(3,min(request.args.get('seconds',10,type=int),60)); c=db(); q=','.join('?'*len(ids)); ws=c.execute(f'select * from participants where id in ({q})',ids).fetchall() if ids else []; c.close()
 cards=''.join(f'<div class="reveal-card"><div class="trophy">★</div><div class="winner-name">{w["name"]}</div><div class="winner-company">{w["company"]}</div></div>' for w in ws)
 body=f'''<div class="raffle-stage"><div class="particles"></div><div class="raffle-inner"><div class="raffle-brand">ZANTHUS <span>| NEOS</span></div><div id="countArea"><div class="raffle-label">SORTEIO AO VIVO</div><h1>Prepare-se!</h1><p>O resultado será revelado em</p><div id="countdown" class="countdown">{seconds}</div><div class="spinner-ring"></div><div id="raffleMsg" class="raffle-msg">Embaralhando participantes...</div></div><div id="winnerArea" class="winner-area"><div class="raffle-label">RESULTADO DO SORTEIO</div><h1 class="congrats">TEMOS GANHADOR!</h1>{cards}<a class="raffle-back" href="/admin">VOLTAR AO PAINEL</a></div></div></div><script>let n={seconds};const el=document.getElementById('countdown'),msg=document.getElementById('raffleMsg');const timer=setInterval(()=>{{n--;el.textContent=n;if(n<=Math.ceil({seconds}/2))msg.textContent='Quase lá...';if(n<=3)msg.textContent='Preparando o resultado...';if(n<=0){{clearInterval(timer);document.getElementById('countArea').classList.add('fade-out');setTimeout(()=>{{document.getElementById('countArea').style.display='none';document.getElementById('winnerArea').classList.add('show')}},650)}}}},1000);</script>'''
 return layout('Sorteio Zanthus | Neos',body)

@app.route('/admin/export')
@admin
def export():
 x=camp(request.args.get('cid'));c=db();rs=c.execute('select * from participants where campaign_id=? order by id',(x['id'],)).fetchall();c.close();o=io.StringIO();w=csv.writer(o);w.writerow(['Nome','WhatsApp','Email','Empresa','Ganhador','Pode repetir','Bloqueado']);[w.writerow([r['name'],r['whatsapp'],r['email'],r['company'],r['winner'],r['allow_again'],r['blocked']]) for r in rs];return Response('\ufeff'+o.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=participantes.csv'})
@app.route('/qr.png')
def qr_padrao():
 x=camp(); return redirect(f'/qr/{x["id"]}.png') if x else ('Sem campanha ativa',404)
@app.route('/qr/<int:cid>.png')
def qr(cid):
 x=camp(cid,True)
 if not x: return ('Campanha indisponível',404)
 img=qrcode.make(request.url_root.rstrip('/')+f'/cadastro/{cid}'); b=io.BytesIO();img.save(b,format='PNG');b.seek(0);return Response(b.getvalue(),mimetype='image/png')


init()
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT','5000')))