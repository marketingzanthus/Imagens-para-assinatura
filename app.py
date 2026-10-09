import os, io, csv, json, random, secrets, sqlite3
from database import connect, create_schema, insert_campaign, IntegrityError, DATABASE_URL
import media_storage
from markupsafe import escape
from openpyxl import Workbook
from openpyxl.styles import Font
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

@app.before_request
def require_durable_uploads():
 if os.getenv('RENDER')=='true' and not media_storage.BUCKET and request.method=='POST':
  file=request.files.get('image')
  if file and file.filename:
   flash('O armazenamento permanente de imagens ainda precisa ser configurado. Envie a campanha sem imagem por enquanto.')
   return redirect('/admin')

def db():
 return connect(DB)

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
 c=db(); create_schema(c)
 if not DATABASE_URL and not c.execute('select 1 from campaigns limit 1').fetchone():
  c.execute('insert into campaigns(name,title,prize,terms,active,created_at) values(?,?,?,?,1,?)',('Campanha principal','Participe do nosso sorteio','Kit Neos + Brindes','Ao participar, você concorda com as regras da ação.',now()))
 if not c.execute('select 1 from users limit 1').fetchone():
  user=os.getenv('ADMIN_USER','admin'); pwd=os.getenv('ADMIN_PASSWORD')
  if not pwd: c.close(); raise RuntimeError('ADMIN_PASSWORD obrigatória para inicializar administrador.')
  c.execute('insert into users(username,password,name,role) values(?,?,?,?)',(user,generate_password_hash(pwd),'Administrador','admin'))
  print(f'INITIAL_ADMIN_USER={user}',flush=True); print('INITIAL_ADMIN_PASSWORD_CONFIGURED=true',flush=True)
 # Capture available names for older draws without changing existing snapshots.
 for d in c.execute('select id,campaign_id,winner_ids from draws where winner_details is null').fetchall():
  details=[]
  for pid in json.loads(d['winner_ids'] or '[]'):
   winner=c.execute('select id,name,company from participants where id=? and campaign_id=?',(pid,d['campaign_id'])).fetchone()
   details.append(dict(winner) if winner else {'id':pid,'name':'Participante não disponível','company':''})
  c.execute('update draws set winner_details=? where id=?',(json.dumps(details,ensure_ascii=False),d['id']))
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
 n=f'{datetime.now().strftime("%Y%m%d%H%M%S")}_{secrets.token_hex(3)}.{ext}'; media_storage.save(f,n,UPLOAD); return n

CSS='''
:root{--p:#172554;--a:#14b8a6;--bg:#f6f8fb;--tx:#172033}*{box-sizing:border-box}body{margin:0;font-family:Inter,Arial,sans-serif;background:var(--bg);color:var(--tx)}a{text-decoration:none}.wrap{max-width:1180px;margin:auto;padding:28px}.brand{font-size:25px;font-weight:800;color:var(--p)}.brand b{color:var(--a)}.hero{background:linear-gradient(135deg,#0f1f4b,#18366f);color:#fff;border-radius:26px;padding:48px;display:grid;grid-template-columns:1.4fr 1fr;gap:28px;align-items:center}.hero h1{font-size:48px;margin:12px 0}.btn{display:inline-block;border:0;border-radius:12px;padding:13px 18px;font-weight:750;cursor:pointer;background:var(--p);color:white}.btn.a{background:var(--a);color:#042f2e}.btn.red{background:#b91c1c}.btn.gray{background:#e5e7eb;color:#111827}.card{background:white;border:1px solid #e5e7eb;border-radius:18px;padding:22px;margin:16px 0;box-shadow:0 7px 24px #0f172a0a}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.input,textarea,select{width:100%;padding:12px;border:1px solid #cbd5e1;border-radius:10px;margin:6px 0 13px;background:white}.prizeimg{max-width:100%;max-height:330px;border-radius:18px;object-fit:contain;background:white}.top{display:flex;justify-content:space-between;align-items:center;gap:15px}.muted{color:#64748b}.flash{padding:12px;background:#ecfeff;border:1px solid #99f6e4;border-radius:10px;margin:10px 0}.table{width:100%;border-collapse:collapse;font-size:14px}.table th,.table td{padding:10px;border-bottom:1px solid #e5e7eb;text-align:left}.pill{padding:4px 8px;border-radius:999px;background:#eef2ff}.actions form{display:inline-block;margin:2px}.winner{font-size:56px;font-weight:900;text-align:center;color:var(--p);padding:40px}.login{max-width:430px;margin:70px auto}.qr{max-width:220px}.sectiontitle{margin-top:34px}@media(max-width:800px){.hero,.grid{grid-template-columns:1fr}.hero h1{font-size:36px}.wrap{padding:16px}.table{font-size:12px}}
.raffle-stage{min-height:100vh;background:radial-gradient(circle at 50% 25%,#087c83 0,#00485f 35%,#00283f 70%,#001a2c 100%);color:#fff;display:flex;align-items:center;justify-content:center;position:relative;overflow:hidden}.particles{position:absolute;inset:0;background-image:radial-gradient(circle,rgba(77,231,216,.34) 1px,transparent 1px);background-size:34px 34px;animation:particleMove 16s linear infinite}.raffle-inner{position:relative;z-index:2;text-align:center;width:min(1000px,92vw);padding:35px}.raffle-inner #countArea{min-height:70vh;display:flex;flex-direction:column;align-items:center;justify-content:center}.countdown-wrap{position:relative;width:240px;height:240px;margin:24px auto;display:grid;place-items:center}.countdown-wrap .countdown{position:absolute;inset:0;width:100%;height:100%;margin:0;display:grid;place-items:center;line-height:1;z-index:2}.countdown-wrap .spinner-ring{position:absolute;inset:10px;width:auto;height:auto;margin:0;left:10px;top:10px;transform:none;z-index:1;pointer-events:none;box-sizing:border-box}.raffle-brand{font-size:26px;font-weight:900;margin-bottom:38px}.raffle-brand span,.raffle-label,.prize-caption{color:#4de7d8}.raffle-label{font-size:13px;letter-spacing:4px;font-weight:900}.raffle-inner h1{font-size:64px}.countdown{font-size:150px;font-weight:900;text-shadow:0 0 45px rgba(77,231,216,.65);margin:24px}.spinner-ring{width:190px;height:190px;border:3px solid rgba(255,255,255,.12);border-top-color:#4de7d8;border-radius:50%;position:absolute;left:50%;transform:translate(-50%,-185px);animation:spin 1.1s linear infinite}.raffle-msg{font-size:22px;font-weight:700}.fade-out{animation:fadeOut .65s both}.winner-area{display:none}.winner-area.show{display:block;animation:reveal .9s both}.reveal-card{background:#fff;color:#003b5c;border-radius:28px;padding:30px;margin:22px auto;max-width:720px;box-shadow:0 25px 80px rgba(0,0,0,.32)}.winner-name{font-size:52px;font-weight:900}.winner-company{font-size:23px}.raffle-back,.raffle-button{display:inline-block;background:#4de7d8;color:#003b5c;border:0;border-radius:12px;padding:15px 25px;font-weight:900;text-decoration:none;cursor:pointer;margin-top:22px}.register-stage{align-items:flex-start;padding:36px 0}.register-shell{position:relative;z-index:2;width:min(1120px,92vw)}.register-grid{display:grid;grid-template-columns:1.05fr .95fr;gap:30px}.prize-show,.register-card{border-radius:28px;padding:34px}.prize-show{background:rgba(0,37,57,.45);border:1px solid rgba(77,231,216,.25)}.prize-show h1{font-size:42px}.prize-show .prizeimg{height:330px;width:100%;object-fit:contain;background:#fff;border-radius:20px;margin:18px 0}.register-card{background:#fff;color:#244653;box-shadow:0 25px 80px rgba(0,0,0,.22)}.register-card h2{font-size:34px;color:#003b5c}.register-card .input{background:#f5f9fa}.register-card .raffle-button{width:100%}@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}@keyframes particleMove{to{background-position:0 136px}}@keyframes fadeOut{to{opacity:0;transform:scale(.9)}}@keyframes reveal{from{opacity:0;transform:scale(.65)}to{opacity:1;transform:scale(1)}}@media(max-width:800px){.register-grid{grid-template-columns:1fr}.raffle-inner h1{font-size:42px}.countdown{font-size:110px}.winner-name{font-size:36px}.prize-show .prizeimg{height:240px}}
'''

GIRO_PUBLIC_CSS = '''
:root{--p:#3b45f2;--a:#2c2f62;--bg:#f5f5fa;--tx:#111119}
body,input,textarea,select,button{font-family:Figtree,Arial,sans-serif;font-size:16px}
.btn{background:#3b45f2;border-radius:8px;font-weight:500;min-height:44px}
.card{border-color:#cfd0da;border-radius:8px;box-shadow:none}
.raffle-stage{background:radial-gradient(circle at 50% 25%,#cadaff 0,#f5f5fa 65%);color:#2c2f62}
.particles{background-image:radial-gradient(circle,rgba(79,131,251,.15) 1px,transparent 1px)}
.raffle-brand,.raffle-label,.winner-name{font-weight:700}
.raffle-brand span,.raffle-label,.prize-caption{color:#2c2f62}
.raffle-label{font-size:14px;letter-spacing:2px}
.raffle-inner h1{font-weight:700}
.countdown{color:#3b45f2;font-weight:700;text-shadow:none}
.spinner-ring{border-color:#cadaff;border-top-color:#3b45f2}
.reveal-card{color:#2c2f62;border:1px solid #cfd0da;border-radius:8px;box-shadow:0 8px 24px #2c2f6210}
.raffle-back,.raffle-button{background:#3b45f2;color:#fff;border-radius:8px;font-size:16px;font-weight:500;min-height:44px;padding:12px 24px}
.raffle-back:hover,.raffle-button:hover,.btn:hover{filter:brightness(.95)}
.raffle-back:focus-visible,.raffle-button:focus-visible,.input:focus-visible{outline:3px solid #4f83fb;outline-offset:3px}
.register-stage{background:#f5f5fa}
.register-grid{gap:24px}
.prize-show,.register-card{background:#fff;color:#111119;border:1px solid #cfd0da;border-radius:8px;padding:28px;box-shadow:none}
.prize-show h1{font-size:40px;font-weight:700;color:#2c2f62;line-height:1.2}
.prize-show h2{font-size:24px;font-weight:700;line-height:1.3;color:#2c2f62}
.prize-show .prizeimg{border-radius:8px}
.register-card h2{font-size:32px;font-weight:700;color:#2c2f62}
.register-card .input{background:#fff;border-color:#cfd0da;border-radius:8px;min-height:44px}
.register-card .terms{line-height:1.5}
@media(max-width:800px){.register-stage{padding:24px 0}.prize-show,.register-card{padding:24px}.prize-show h1{font-size:32px}.register-card h2{font-size:28px}.raffle-inner{padding:24px 8px}.winner-name{overflow-wrap:anywhere}}
'''

GIRO_PUBLIC_CSS += '\n.public-logo{position:relative;overflow:hidden;width:220px;max-width:100%;aspect-ratio:583/72;margin-right:auto}\n.public-logo img{position:absolute;display:block;width:329.331%;max-width:none;height:auto;left:-54.2024%;top:-663.8889%}\n.raffle-inner .public-logo{width:280px;margin-left:auto;margin-right:auto}\n.raffle-stage,.register-stage{background-color:#f5f5fa;background-image:url("data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20width%3D%22240%22%20height%3D%22240%22%20viewBox%3D%220%200%20240%20240%22%3E%3Cg%20fill%3D%22none%22%20stroke%3D%22%234f83fb%22%20stroke-opacity%3D%22.18%22%20stroke-width%3D%221%22%3E%3Cpath%20d%3D%22M0%2040h60l30%2030h50v70l40%2040h60M0%20160h40l30-30V0M120%20240v-50l30-30h90M180%200v40l60%2060%22/%3E%3Ccircle%20cx%3D%2290%22%20cy%3D%2270%22%20r%3D%224%22/%3E%3Ccircle%20cx%3D%22140%22%20cy%3D%22140%22%20r%3D%224%22/%3E%3Ccircle%20cx%3D%2270%22%20cy%3D%22130%22%20r%3D%224%22/%3E%3Ccircle%20cx%3D%22180%22%20cy%3D%2240%22%20r%3D%224%22/%3E%3C/g%3E%3C/svg%3E"),radial-gradient(ellipse at top,#cadaff80,transparent 65%);background-size:240px 240px,100% 100%}\n.raffle-stage:not(.register-stage)::before{content:"";position:absolute;inset:0;background-image:url("data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20width%3D%22420%22%20height%3D%22380%22%20viewBox%3D%220%200%20420%20380%22%3E%3Cg%20fill%3D%22none%22%20stroke%3D%22%234f83fb%22%20stroke-opacity%3D%22.16%22%20stroke-width%3D%223%22%20stroke-linejoin%3D%22round%22%3E%3Cpath%20d%3D%22M35%2070h90v25H35zM44%2095h72v60H44zM80%2070v85M80%2070C40%2070%2044%2035%2062%2042q18%208%2018%2028c0-35%2035-39%2032-17-2%2016-20%2017-32%2017M280%20235h60v25q0%2040-30%2040t-30-40zM280%20240h-20v12q0%2028%2030%2028M340%20240h20v12q0%2028-30%2028M310%20300v25M290%20325h40%22/%3E%3Cpath%20d%3D%22m180%2040%205%2010%2011%202-8%208%202%2011-10-5-10%205%202-11-8-8%2011-2zM50%20270l8%2014M200%20210l12-8M365%2075l-8%2015%22/%3E%3C/g%3E%3C/svg%3E");background-size:420px 380px;pointer-events:none}\n.raffle-stage .particles{opacity:.35;pointer-events:none}\n@media(prefers-reduced-motion:reduce){.particles,.spinner-ring{animation:none}}\n'

GIRO_PUBLIC_CSS += '\n.trophy{display:flex;justify-content:center;margin-bottom:16px}\n.winner-area{position:relative}\n.winner-confetti{position:absolute;inset:-60px -30px 0;overflow:hidden;pointer-events:none}\n.winner-confetti i{position:absolute;left:var(--x);top:0;width:9px;height:16px;background:var(--color);opacity:0;transform:rotate(var(--r));border-radius:2px}\n.winner-area.show .winner-confetti i{animation:celebrate 2.8s ease-out var(--delay) both}\n@keyframes celebrate{0%{opacity:0;transform:translateY(100px) scale(.3) rotate(var(--r))}15%{opacity:1;transform:translateY(-20px) scale(1) rotate(var(--r))}85%{opacity:1}100%{opacity:0;transform:translateY(650px) rotate(calc(var(--r) + 360deg))}}\n@media(prefers-reduced-motion:reduce){.winner-area.show,.winner-area.show .winner-confetti i{animation:none}.winner-confetti{display:none}}\n'

def layout(title,body):
 msgs=''.join(f'<div class="flash">{m}</div>' for m in __import__('flask').get_flashed_messages())
 return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;700&amp;display=swap" rel="stylesheet"><style>{CSS}{GIRO_PUBLIC_CSS}</style></head><body>{msgs}{body}</body></html>'''

@app.route('/health')
def health():
 try:
  c=db()
  try: c.execute('select 1 from campaigns limit 1').fetchone()
  finally: c.close()
  return {'ok':True,'database':'postgresql' if DATABASE_URL else 'sqlite','images_durable':bool(media_storage.BUCKET)}
 except Exception:
  return {'ok':False},503
@app.route('/uploads/<path:n>')
def up(n): return media_storage.serve(n,UPLOAD)

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
  except IntegrityError: c.close();flash('Este e-mail já está cadastrado nesta campanha.');return redirect(f'/cadastro/{cid}')
  c.close();return redirect(f'/sucesso/{cid}')
 img=f'<img class="prizeimg" src="/uploads/{x["image"]}">' if x['image'] else ''
 body=f'''<div class="raffle-stage register-stage"><div class="particles"></div><div class="register-shell"><div class="raffle-brand"><div class="public-logo"><img src="/static/zanthus-neos-transparente.png" alt="Zanthus Tecnologia de Resultados | Neos" width="1920" height="1080"></div></div><div class="register-grid"><section class="prize-show"><div class="raffle-label">SORTEIO ESPECIAL</div><h1>{x["title"]}</h1>{img}<div class="prize-caption" style="text-align:center">VOCÊ PODE GANHAR</div><h2>{x["prize"]}</h2></section><section class="register-card"><div class="raffle-label">PARTICIPE AGORA</div><h2>Faça seu cadastro</h2><p>Preencha seus dados e boa sorte!</p><form method="post"><input type="hidden" name="csrf" value="{csrf()}"><label>Nome</label><input class="input" name="name" required><label>WhatsApp</label><input class="input" type="tel" name="whatsapp" id="whatsapp" inputmode="numeric" autocomplete="tel" maxlength="15" placeholder="(11) 99999-9999" required oninput="var v=this.value.replace(/[^0-9]/g,'').slice(0,11);if(v.length>7)this.value='('+v.slice(0,2)+') '+v.slice(2,7)+'-'+v.slice(7);else if(v.length>2)this.value='('+v.slice(0,2)+') '+v.slice(2);else if(v.length)this.value='('+v;else this.value='';" onblur="var v=this.value.replace(/[^0-9]/g,'');this.setCustomValidity(v.length===11?'':'Digite um celular com DDD e 11 números. Ex.: (11) 99999-9999');"><label>E-mail</label><input class="input" type="email" name="email" required><label>Empresa</label><input class="input" name="company" required><label class="terms"><input type="checkbox" name="consent" required> {x["terms"]}</label><button class="raffle-button">Quero participar</button></form></section></div></div></div>'''
 return layout('Cadastro',body)

@app.route('/sucesso/<int:cid>')
def sucesso(cid): return layout('Sucesso',f'<div class="wrap"><div class="card" style="text-align:center"><h1 style="font-size:clamp(24px,5vw,28px);line-height:1.25">✅ Cadastro realizado!</h1><p>Você já esta participando do nosso Sorteio.<br><span style="display:block;margin-top:8px">Boa Sorte!</span></p><a class="btn" href="/cadastro/{cid}">Voltar</a><div style="max-width:435px;margin:24px auto 0"><h2 style="font-size:19px;font-weight:400;margin:0 0 8px">Patrocinadores</h2><div style="position:relative;overflow:hidden;aspect-ratio:1080/260"><img src="/static/patrocinadores-atualizados.png" alt="Laurenti, Elgin, Fiserv, Custom Brasil, Super Troco e Transire" width="1080" height="1440" style="display:block;width:100%;height:auto;position:absolute;top:0;transform:translateY(-42.0139%)"></div></div></div></div>')

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

def admin_navigation(body):
 items=[('INÍCIO','#inicio'),('SORTEIO','#sorteio'),('PARTICIPANTES','#participantes'),('NOVA CAMPANHA','/admin?nova=1#campanha'),('CAMPANHAS CADASTRADAS','#campanhas'),('USUÁRIOS DO PAINEL','#usuarios'),('HISTÓRICO DE SORTEIOS','#historico-sorteios'),('HISTÓRICO DE ALTERAÇÕES','#historico-alteracoes'),('EXCLUIR PARTICIPANTES','#excluir-participantes')]
 if session.get('role')!='admin': items=[item for item in items if item[1] not in ('#usuarios','#excluir-participantes')]
 icons={
 '#inicio':'<path d="m3 10 9-7 9 7v11h-6v-7H9v7H3z"/>',
 '#sorteio':'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1"/><circle cx="16" cy="8" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="8" cy="16" r="1"/><circle cx="16" cy="16" r="1"/>',
 '#participantes':'<circle cx="9" cy="7" r="3"/><path d="M3 21v-4a6 6 0 0 1 12 0v4M17 4a3 3 0 0 1 0 6M21 21v-4a6 6 0 0 0-4-5"/>',
 '#campanha':'<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M12 8v8M8 12h8"/>',
 '#campanhas':'<path d="M3 7h7l2 2h9v11H3zM3 7V4h8l2 3h8v2"/>',
 '#usuarios':'<circle cx="12" cy="7" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/>',
 '#historico-sorteios':'<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 3"/>',
 '#historico-alteracoes':'<path d="M8 4H4v18h16V4h-4M8 10h8M8 14h8M8 18h5"/><rect x="8" y="2" width="8" height="4" rx="1"/>',
 '#excluir-participantes':'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>'}
 def menu_link(label,href):
  icon=icons[href[href.index('#'):]]
  svg=f'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{icon}</svg>'
  return f'<a href="{href}" title="{label.capitalize()}" onclick="var t=document.getElementById(this.hash.slice(1));if(t&amp;&amp;t.tagName===\'DETAILS\')t.open=true;">{svg}<span>{label.capitalize()}</span></a>'
 links=''.join(menu_link(label,href) for label,href in items)
 style='''<style>body:has(.admin-layout){background:#fff;color:#25252b}.admin-layout{display:grid;grid-template-columns:240px minmax(0,1fr);min-height:100vh;margin:0}.admin-layout>.wrap{width:100%;min-width:0;max-width:none;padding:12px 24px}.admin-menu{align-self:start;position:sticky;top:0;min-height:100vh;background:#fff;color:#25252b;border-right:1px solid #e4e4e8}.admin-menu summary{padding:25px 20px;cursor:pointer;font-weight:700;font-size:16px;list-style:none}.admin-menu summary::-webkit-details-marker{display:none}.admin-menu nav{padding:8px 10px}.admin-menu a{display:block;color:#33333b;padding:13px 14px;font-size:12px;font-weight:500;border-radius:7px;line-height:1.4;margin:4px 0}.admin-menu a:hover,.admin-menu a:focus-visible{background:#f2f1f7;color:#443cf0}.admin-menu a[aria-current="page"]{background:#eae9ef!important;color:#25252b!important;font-weight:700}.admin-layout .top{padding:13px 16px;border:1px solid #dedee4;border-radius:7px;min-height:58px;background:white;box-shadow:0 1px 2px #00000008;margin-bottom:25px}.admin-layout .brand{font-size:18px}.admin-layout .top a{font-size:13px;color:#5148dd}.admin-layout .card{box-shadow:none;border:1px solid #e6e6eb;border-radius:8px;padding:20px;margin:18px 0}.admin-layout h2{font-size:20px;margin:0 0 20px}.admin-layout h3{font-size:16px}.admin-layout .btn{background:#443cf0;border-radius:6px;padding:11px 16px;font-size:13px;font-weight:600}.admin-layout .btn.a{background:#443cf0;color:white}.admin-layout .btn.gray{background:#fff;color:#5148dd;border:1px solid #dedee4}.admin-layout .btn.red{background:#b91c1c;color:white}.admin-layout .input,.admin-layout textarea,.admin-layout select{border-color:#dedee4;border-radius:6px}.admin-layout .input:focus,.admin-layout textarea:focus{outline:2px solid #d1d9ff;border-color:#8078f6}.admin-layout .table th{font-weight:500;color:#777780}.admin-layout .table td,.admin-layout .table th{padding:13px 10px;border-bottom:1px solid #ededf1}.admin-layout [id]{scroll-margin-top:20px}.admin-layout #inicio{min-height:65vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px;border:1px solid #e6e6eb;border-radius:8px;margin:18px 0;background:white}.admin-layout #inicio h1{font-size:32px;color:#25252b;margin:0;font-weight:700}.admin-layout #inicio img{width:440px;max-width:85%;height:auto}.admin-layout details.card>summary{font-size:18px!important}.admin-layout [hidden]{display:none!important}@media(max-width:900px){.admin-layout{display:block}.admin-menu{position:static;min-height:0;border-right:0;border-bottom:1px solid #e4e4e8}.admin-menu summary{padding:16px}.admin-menu nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.admin-layout>.wrap{padding:12px}.admin-layout .top{flex-wrap:wrap}.admin-layout #inicio{min-height:45vh}}@media(max-width:440px){.admin-menu nav{grid-template-columns:1fr}}</style>'''
 style+='''<style>body:has(.admin-layout){font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#202024}.admin-layout{grid-template-columns:266px minmax(0,1fr)}.admin-menu summary{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:18px 14px}.admin-nav-logo{width:210px;max-width:90%;height:auto}.admin-menu a{font-size:12px;min-height:38px;padding:10px 14px;font-weight:700}.admin-menu a[aria-current="page"]{font-weight:700}.admin-layout .top{min-height:58px;padding:10px 14px}.admin-header-logo{width:190px;max-width:100%;height:auto;display:block}.admin-layout .top a{font-size:12px}.admin-layout .btn{font-family:inherit;font-size:12px;line-height:16px;padding:8px 12px;border-radius:6px;font-weight:500;background:#443cf0}.admin-layout .btn.gray{color:#5148dd;background:white;border:1px solid #d8d8de}.admin-layout .input,.admin-layout textarea,.admin-layout select{font-family:inherit;font-size:13px;padding:10px 12px;border-color:#d8d8de}.admin-layout h2{font-size:20px;font-weight:700}.admin-layout .card{border-radius:7px}.admin-layout .table{font-size:12px}.admin-layout .table td,.admin-layout .table th{padding:12px 10px}.admin-layout details.card>summary{font-size:16px!important}.admin-layout label{font-size:13px}.admin-layout #inicio h1{font-size:30px}@media(max-width:900px){.admin-layout{display:block}.admin-nav-logo{width:190px}.admin-menu summary{padding:12px 14px}}</style>'''
 style+='''<style>.admin-menu{overflow:visible}.admin-side-brand{height:64px;display:flex;align-items:center;padding:12px 14px}.admin-nav-logo{width:205px;max-width:95%}.admin-menu nav{display:block;padding:0 14px 0 6px;margin-top:4px}.admin-menu a{display:flex;align-items:center;gap:10px;height:38px;min-height:38px;padding:10px 14px;margin:6px 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;font-weight:700;border-radius:6px;color:#22222a}.admin-menu a svg{flex:none}.admin-menu a[aria-current="page"]{font-weight:700}.admin-side-toggle{position:absolute;right:-10px;top:20px;width:21px;height:21px;border-radius:50%;border:0;background:#443cf0;color:white;display:flex;align-items:center;justify-content:center;cursor:pointer;padding:0;z-index:2}.admin-side-toggle svg{width:12px;height:12px}.admin-layout.menu-collapsed{grid-template-columns:64px minmax(0,1fr)}.menu-collapsed .admin-side-brand{overflow:hidden;padding:10px 6px}.menu-collapsed .admin-nav-logo{width:205px;max-width:none}.menu-collapsed .admin-menu a span{display:none}.menu-collapsed .admin-menu nav{padding:0 6px}.menu-collapsed .admin-menu a{justify-content:center;padding:10px}.menu-collapsed .admin-side-toggle svg{transform:rotate(180deg)}@media(max-width:900px){.admin-menu{min-height:0}.admin-menu nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));padding:0 10px 10px}.admin-side-toggle{right:14px}.admin-layout.menu-collapsed{display:block}.menu-collapsed .admin-menu nav{display:none}.menu-collapsed .admin-side-brand{padding:12px 14px}.menu-collapsed .admin-nav-logo{max-width:95%;width:205px}}@media(max-width:440px){.admin-menu nav{grid-template-columns:1fr}}</style>'''
 menu=f'<aside class="admin-menu"><div class="admin-side-brand"><img src="/static/zanthus-neos-logo.png" alt="Zanthus | Neos" class="admin-nav-logo"></div><button class="admin-side-toggle" aria-label="Recolher menu lateral" aria-expanded="true" onclick="var closed=document.querySelector(\'.admin-layout\').classList.toggle(\'menu-collapsed\');this.setAttribute(\'aria-expanded\',String(!closed));this.setAttribute(\'aria-label\',closed?\'Expandir menu lateral\':\'Recolher menu lateral\');"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m14 6-6 6 6 6"/></svg></button><nav aria-label="Funcionalidades do painel">{links}</nav></aside>'
 home='''<section id="inicio"><h1>Sorteador de brindes</h1></section>'''
 body=body.replace('<h1>Painel do Sorteio</h1>',home+'<h1>Painel do Sorteio</h1>')
 script='''<style>.admin-layout [hidden]{display:none!important}.admin-menu a[aria-current="page"]{background:#14b8a6;color:#042f2e}</style><script>(function(){function show(){var main=document.querySelector('.admin-layout>.wrap');var id=location.hash.slice(1)||'inicio';var selected=document.getElementById(id);if(!selected||!main.contains(selected)){id='inicio';selected=document.getElementById(id);}Array.from(main.children).forEach(function(el){var keep=el.classList.contains('top')||el===selected||(id==='sorteio'&&el.classList.contains('grid'));el.hidden=!keep;});main.querySelectorAll('details.card').forEach(function(el){el.open=el===selected;});document.querySelectorAll('.admin-menu a').forEach(function(a){var match=a.hash==='#'+id;if(match)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});window.scrollTo(0,0);requestAnimationFrame(function(){window.scrollTo(0,0);});}window.addEventListener('hashchange',show);window.addEventListener('load',show);show();})();</script>'''
 header_start=body.index('<div class="top">')
 header_end=body.index('</div></div>',header_start)+len('</div></div>')
 current_campaign=camp(request.args.get('cid',type=int)) or camp()
 qr_href=f"/qr/{current_campaign['id'] if current_campaign else 0}.png"
 export_href=qr_href.replace('/qr/','/admin/export?cid=').replace('.png','')
 def header_icon(paths):
  return f'<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths}</svg>'
 qr_icon=header_icon('<rect x="3" y="3" width="6" height="6"/><rect x="15" y="3" width="6" height="6"/><rect x="3" y="15" width="6" height="6"/><path d="M15 15h3v3h3v3h-6zM12 3v9H3M21 12h-6M12 15v6"/>')
 file_icon=header_icon('<path d="M5 2h9l5 5v15H5zM14 2v6h5M8 12h8M8 16h8M11 10v10"/>')
 user_icon=header_icon('<circle cx="12" cy="7" r="4"/><path d="M5 19a7 7 0 0 1 14 0v2H5z"/>')
 clock_icon=header_icon('<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>')
 arrow='<svg viewBox="0 0 12 12" width="10" height="10" fill="none" stroke="currentColor" aria-hidden="true"><path d="m3 4 3 3 3-3"/></svg>'
 c=db()
 try:
  active_campaigns=c.execute('select id,name from campaigns where active=1 order by name,id').fetchall()
 finally:
  c.close()
 qr_links=''.join(f'<a href="/qr/{z["id"]}.png" data-campaign="{escape(z["name"])}"><strong>{escape(z["name"])}</strong><span>QR Code · Campanha {z["id"]}</span></a>' for z in active_campaigns) or '<p>Nenhuma campanha ativa.</p>'
 header=f'<div class="top admin-toolbar"><img class="admin-header-logo" src="/static/zanthus-neos-logo.png" alt="Zanthus | Neos"><div class="admin-toolbar-actions"><span class="admin-clock">{clock_icon}<time id="admin-clock">--:--:--</time></span><details class="toolbar-user toolbar-qr"><summary class="toolbar-item"><span class="toolbar-circle">{qr_icon}</span><strong>QR Code</strong>{arrow}</summary><div class="toolbar-dropdown qr-campaigns">{qr_links}</div></details><a class="toolbar-item" href="{export_href}"><span class="toolbar-circle">{file_icon}</span><strong>XLSX</strong>{arrow}</a><details class="toolbar-user"><summary class="toolbar-item"><span class="toolbar-circle">{user_icon}</span><strong>{escape(session.get("user") or "Usuário")}</strong>{arrow}</summary><div class="toolbar-dropdown"><a href="/admin/logout">Sair</a></div></details></div></div>'
 body=body[:header_start]+header+body[header_end:]
 style+='''<style>.admin-layout .admin-toolbar{display:flex;justify-content:space-between;align-items:center;padding:9px 14px;min-height:58px;border-color:#dedee4;border-radius:6px;margin-top:0}.admin-toolbar-actions{display:flex;align-items:center;gap:24px}.admin-clock{display:flex;align-items:center;gap:8px;color:#929299;font-size:11px;white-space:nowrap;font-variant-numeric:tabular-nums;letter-spacing:.5px}.admin-clock svg{width:14px;height:14px}.admin-layout .toolbar-item{display:flex;align-items:center;gap:10px;color:#25252b;font-size:12px;white-space:nowrap;cursor:pointer;list-style:none}.toolbar-circle{display:flex;align-items:center;justify-content:center;width:37px;height:37px;border-radius:50%;background:#cedbff;color:#26364c;flex:none}.toolbar-item>svg{margin-left:2px;color:#a4a4aa}.toolbar-user{position:relative}.toolbar-user summary::-webkit-details-marker{display:none}.toolbar-dropdown{position:absolute;right:0;top:46px;min-width:140px;padding:6px;background:white;border:1px solid #dedee4;border-radius:6px;box-shadow:0 4px 16px #00000012;z-index:10}.admin-layout .toolbar-dropdown a{display:block;padding:10px;color:#25252b;font-size:12px}.toolbar-dropdown a:hover{background:#eeedf3;border-radius:4px}@media(max-width:900px){.admin-toolbar-actions{gap:14px;flex-wrap:wrap}.admin-layout .admin-toolbar{gap:12px}.toolbar-circle{width:32px;height:32px}}@media(max-width:440px){.admin-toolbar-actions{gap:10px;width:100%;justify-content:space-between}.admin-clock{display:none}.admin-layout .toolbar-item{gap:6px;font-size:11px}}</style><script>(function(){function updateClock(){var el=document.getElementById('admin-clock');if(el)el.textContent=new Date().toLocaleTimeString('pt-BR',{hour12:false});}window.addEventListener('DOMContentLoaded',updateClock);setInterval(updateClock,1000);})();</script>'''
 body=body.replace('<div class="brand">Zanthus <b>| Neos</b></div>','<div class="brand"><img class="admin-header-logo" src="/static/zanthus-neos-logo.png" alt="Zanthus | Neos"></div>')
 style+='''<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;700&amp;display=swap" rel="stylesheet"><style>body:has(.admin-layout){--giro-primary:#2c2f62;--giro-action:#3b45f2;--giro-primary-dark:#0d1874;--giro-primary-light:#cadaff;--giro-text:#111119;--giro-muted:#88898c;--giro-border:#cfd0da;--giro-selected:#e8e8ee;--giro-surface:#ffffff;--giro-subtle:#f5f5fa;font-family:'Figtree',sans-serif;font-size:14px;line-height:1.5;color:var(--giro-text);background:var(--giro-surface)}.admin-layout,.admin-layout button,.admin-layout input,.admin-layout textarea,.admin-layout select,.admin-menu a{font-family:'Figtree',sans-serif!important}.admin-menu{color:var(--giro-text);background:var(--giro-surface);border-color:var(--giro-border)}.admin-menu a{font-size:14px;font-weight:700;color:var(--giro-text);height:44px}.admin-menu a:hover,.admin-menu a:focus-visible{background:var(--giro-subtle);color:var(--giro-action)}.admin-menu a[aria-current="page"]{background:var(--giro-selected)!important;color:var(--giro-text)!important}.admin-side-toggle{background:var(--giro-action)}.admin-layout .card,.admin-layout .top,.admin-layout #inicio,.toolbar-dropdown{border-color:var(--giro-border);background:var(--giro-surface);border-radius:8px}.admin-layout .btn,.admin-layout .btn.a{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 24px;border-radius:8px;font-size:14px;font-weight:500;line-height:20px;background:var(--giro-action);color:#fff;border:1px solid transparent}.admin-layout .btn:hover,.admin-layout .btn.a:hover{background:var(--giro-primary-dark)}.admin-layout .btn.gray{background:#fff;color:var(--giro-action);border:1px solid var(--giro-border)}.admin-layout .btn.gray:hover{background:var(--giro-subtle)}.admin-layout .btn.red{background:#e81e42;color:#fff}.admin-layout .btn.red:hover{background:#b4052f}.admin-layout .btn:focus-visible,.admin-side-toggle:focus-visible{outline:3px solid var(--giro-primary-light);outline-offset:2px}.admin-layout .input,.admin-layout textarea,.admin-layout select{font-size:14px;line-height:20px;border-color:var(--giro-border);border-radius:8px;color:var(--giro-text)}.admin-layout .input:focus,.admin-layout textarea:focus,.admin-layout select:focus{outline:2px solid var(--giro-primary-light);border-color:var(--giro-action)}.admin-layout label,.admin-layout .table,.admin-layout .top a,.admin-layout .toolbar-item,.admin-layout .toolbar-dropdown a{font-size:14px}.admin-layout h2{font-size:20px;font-weight:700;color:var(--giro-text)}.admin-layout h3,.admin-layout details.card>summary{font-size:18px!important;font-weight:700}.admin-layout #inicio h1{font-size:32px;color:var(--giro-text)}.admin-layout .table th,.admin-layout .muted,.admin-clock{color:var(--giro-muted)}.admin-layout .table td,.admin-layout .table th{border-color:var(--giro-selected)}.admin-layout .top a{color:var(--giro-action)}.admin-layout .toolbar-item{color:var(--giro-text)}.toolbar-circle{background:var(--giro-primary-light);color:var(--giro-primary)}.toolbar-dropdown a:hover{background:var(--giro-subtle)}.admin-layout .actions{display:flex;flex-wrap:wrap;gap:16px}.admin-layout .actions form{margin:0}.admin-layout input[type=checkbox],.admin-layout input[type=radio]{accent-color:var(--giro-action)}@media(max-width:440px){.admin-layout .toolbar-item{font-size:12px}}</style>'''
 style+='''<style>.admin-layout>.wrap{margin:0;align-self:start}.admin-layout .admin-toolbar{position:sticky;top:12px;z-index:20;align-self:start}.toolbar-qr .qr-campaigns{min-width:260px;max-width:min(360px,85vw);max-height:60vh;overflow:auto}.admin-layout .qr-campaigns a{white-space:normal;display:flex;flex-direction:column;gap:2px}.qr-campaigns a span{font-size:12px;color:var(--giro-muted)}.qr-campaigns p{margin:8px;font-size:14px}@media(max-width:900px){.admin-layout .admin-toolbar{top:0}}</style>'''
 qr_popup='''<dialog id="qr-popup" aria-labelledby="qr-popup-title"><div class="qr-popup-heading"><h2 id="qr-popup-title">QR Code da campanha</h2><button type="button" class="qr-popup-close" aria-label="Fechar QR Code">×</button></div><p id="qr-popup-campaign"></p><img id="qr-popup-image" alt="QR Code da campanha" width="320" height="320"><p class="muted">Escaneie para abrir o cadastro desta campanha.</p><button type="button" class="btn gray qr-popup-close">Fechar</button></dialog>'''
 style+='''<style>#qr-popup{width:400px;max-width:calc(100vw - 32px);max-height:90vh;overflow:auto;border:1px solid #cfd0da;border-radius:8px;padding:24px;color:#111119;font-family:'Figtree',sans-serif}#qr-popup::backdrop{background:rgba(17,17,25,.5)}.qr-popup-heading{display:flex;align-items:center;justify-content:space-between;gap:16px}.qr-popup-heading h2{margin:0;font-size:20px}.qr-popup-heading button{border:0;background:transparent;font-size:28px;cursor:pointer;color:#505255;padding:0 4px}#qr-popup-campaign{font-weight:700;font-size:16px}#qr-popup-image{display:block;max-width:100%;height:auto;margin:16px auto}#qr-popup p.muted{font-size:14px}</style>'''
 script+=r'''<script>(function(){var popup=document.getElementById('qr-popup');document.querySelector('.admin-layout').addEventListener('click',function(e){var link=e.target.closest('a');if(!link||!/^\/qr\/\d+\.png$/.test(link.getAttribute('href')||''))return;e.preventDefault();var row=link.closest('tr');var name=link.dataset.campaign||(row?row.querySelector('td').textContent:'Campanha');document.getElementById('qr-popup-campaign').textContent=name;document.getElementById('qr-popup-image').src=link.getAttribute('href');var dropdown=link.closest('details');if(dropdown)dropdown.open=false;popup.showModal();});popup.querySelectorAll('.qr-popup-close').forEach(function(button){button.addEventListener('click',function(){popup.close();});});popup.addEventListener('click',function(e){if(e.target!==popup)return;var r=popup.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)popup.close();});})();</script>'''
 return style+'<div class="admin-layout">'+menu+body+qr_popup+'</div>'+script

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
  useradmin=(f'''<details class="card" id="usuarios"><summary style="cursor:pointer;font-size:20px;font-weight:700">Usuários do painel</summary><p class="muted">Crie uma campanha para liberar a operação do sorteio.</p><div style="overflow:auto"><table class="table"><tr><th>Nome</th><th>Usuário</th><th>Perfil</th><th>Status</th><th>Ações</th></tr>{userrows}</table></div></details>''' if session.get('role')=='admin' else '')
  create=f'''<div class="card" id="campanha"><h2>Nova campanha</h2><form method="post" enctype="multipart/form-data" action="/admin/campaign"><input type="hidden" name="csrf" value="{csrf()}"><input class="input" name="name" placeholder="Nome da campanha" required><input class="input" name="title" placeholder="Título da LP" required><input class="input" name="prize" placeholder="Prêmio" required><textarea name="terms" placeholder="Termos"></textarea><label>Imagem do prêmio</label><input class="input" type="file" name="image" accept="image/png,image/jpeg,image/webp,image/gif"><label><input type="checkbox" name="active" checked> Criar campanha ativa</label><br><br><button class="btn">Criar campanha</button></form></div>'''
  return layout('Admin',f'''<div class="wrap"><div class="top"><div class="brand">Zanthus <b>| Neos</b></div><div>Olá, {session.get("user")} · <a href="/admin/logout">Sair</a></div></div><h1>Painel do Sorteio</h1><div class="grid">{create}{useradmin}</div></div>''')
 def delete_participant_form(p):
  if session.get('role')!='admin': return ''
  return f'''<form method="post" action="/admin/p/{p['id']}/delete" onsubmit="return confirm('Excluir este participante? Esta ação não pode ser desfeita.');"><input type="hidden" name="csrf" value="{csrf()}"><input type="hidden" name="cid" value="{x['id']}"><button class="btn red">Excluir</button></form>'''
 rows=''.join(f'''<tr><td>{p['name']}</td><td>{p['company']}</td><td>{'🏆' if p['winner'] else '—'}</td><td>{'Bloqueado' if p['blocked'] else ('Elegível' if not p['winner'] else 'Sorteado')}</td><td class="actions"><form method="post" action="/admin/p/{p['id']}/block"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn gray">{'Desbloquear' if p['blocked'] else 'Bloquear'}</button></form><form method="post" action="/admin/p/{p['id']}/again"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn gray">{'Não repetir' if p['allow_again'] else 'Pode repetir'}</button></form><form method="post" action="/admin/p/{p['id']}/reenter"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn a">Recolocar</button></form>{delete_participant_form(p)}</td></tr>''' for p in ps)
 camps=''.join(f'<option value="{z["id"]}" {"selected" if z["active"] else ""}>{z["name"]}</option>' for z in cs)
 def draw_history(d):
  winners=json.loads(d['winner_details'] or '[]')
  rows=''.join(f'<li><strong>{escape(w["name"])}</strong> — {escape(w.get("company") or "Empresa não informada")}</li>' for w in winners)
  return f'<li style="margin-bottom:18px"><strong>{escape(d["drawn_at"] or "")}</strong><br>Usuário que realizou o sorteio: <strong>{escape(d["operator"] or "Não informado")}</strong><br>Ganhador(es):<ul>{rows or "<li>Dados dos ganhadores não disponíveis.</li>"}</ul></li>'
 hist=''.join(draw_history(d) for d in ds) or '<li>Sem sorteios ainda.</li>'
 userrows=''.join(f'''<tr><td>{u["name"]}</td><td>{u["username"]}</td><td>{"Administrador" if u["role"]=="admin" else "Usuário"}</td><td>{("Troca de senha pendente" if u["force_password_change"] else "Ativo") if u["active"] else "Inativo"}</td><td class="actions"><form method="post" action="/admin/user/{u['id']}/toggle"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn gray">{"Desativar" if u["active"] else "Ativar"}</button></form><form method="post" action="/admin/user/{u['id']}/password"><input type="hidden" name="csrf" value="{csrf()}"><input class="input" style="width:150px;display:inline" type="password" name="password" placeholder="Nova senha" minlength="8" required><button class="btn gray">Trocar senha</button></form></td></tr>''' for u in us)
 auditrows=''.join(f'<tr><td>{a["created_at"]}</td><td>{a["username"]}</td><td>{a["action"]}</td><td>{a["details"]}</td></tr>' for a in logs) or '<tr><td colspan="4">Sem alterações registradas.</td></tr>'
 useradmin=(f'''<details class="card" id="usuarios"><summary style="cursor:pointer;font-size:20px;font-weight:700">Usuários do painel</summary><form method="post" action="/admin/user"><input type="hidden" name="csrf" value="{csrf()}"><input class="input" name="name" placeholder="Nome" required><input class="input" name="username" placeholder="Usuário" required><select name="role" class="input" required><option value="user">Usuário</option><option value="admin">Administrador</option></select><input class="input" type="password" name="password" placeholder="Senha temporária (mínimo 8 caracteres)" minlength="8" required><label style="display:block;margin:5px 0 15px"><input type="checkbox" name="force_password_change" checked> Exigir troca de senha no primeiro acesso</label><button class="btn">Criar usuário</button></form><div style="overflow:auto"><table class="table"><tr><th>Nome</th><th>Usuário</th><th>Perfil</th><th>Status</th><th>Ações</th></tr>{userrows}</table></div></details>''' if session.get('role')=='admin' else '')
 camprows=''.join(f'''<tr><td>{z["name"]}</td><td>{"Ativa" if z["active"] else "Inativa"}</td><td>{z["created_at"]}</td><td class="actions"><a class="btn gray" href="/admin?cid={z["id"]}#campanha">Gerenciar</a> <a class="btn a" href="/qr/{z["id"]}.png" target="_blank">QR Code</a><form method="post" action="/admin/campaign/{z["id"]}/toggle"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn gray">{"Desativar" if z["active"] else "Ativar"}</button></form>{"" if z["active"] else f'<form method="post" action="/admin/campaign/{z["id"]}/delete" onsubmit="return confirm(\'Excluir esta campanha e todos os participantes e sorteios dela? Esta ação não pode ser desfeita.\')"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn red">Excluir</button></form>'}</td></tr>''' for z in cs)
 selected_image=(f'''<h3>Imagem do prêmio da campanha selecionada</h3><img src="/uploads/{escape(x['image'])}" alt="Imagem do prêmio da campanha selecionada" style="display:block;max-width:100%;width:420px;max-height:340px;object-fit:contain;border-radius:16px">''' if x['image'] else f'''<form method="post" enctype="multipart/form-data" action="/admin/campaign/{x['id']}/image"><input type="hidden" name="csrf" value="{csrf()}"><label>Imagem do prêmio da campanha selecionada</label><input class="input" type="file" name="image" accept="image/*" required><button class="btn">Enviar imagem</button></form>''')
 edit=f'''<div class="card" id="campanha"><h2>Gerenciar campanha</h2><p class="muted">Atualize as informações e salve nesta mesma campanha.</p><form method="post" enctype="multipart/form-data" action="/admin/campaign/{x['id']}/update"><input type="hidden" name="csrf" value="{csrf()}"><label for="edit-name">Nome da campanha</label><input id="edit-name" class="input" name="name" value="{escape(x['name'])}" required><label for="edit-title">Título da página de cadastro</label><input id="edit-title" class="input" name="title" value="{escape(x['title'])}" required><label for="edit-prize">Prêmio</label><input id="edit-prize" class="input" name="prize" value="{escape(x['prize'])}" required><label for="edit-terms">Regras e termos</label><textarea id="edit-terms" name="terms">{escape(x['terms'] or '')}</textarea><label for="edit-image">Alterar imagem do prêmio (opcional)</label><input id="edit-image" class="input" type="file" name="image" accept="image/png,image/jpeg,image/webp,image/gif"><p class="muted">Escolha uma nova imagem para substituir a atual. Sem novo arquivo, a imagem será mantida.</p><button class="btn">Salvar alterações</button></form><hr>{selected_image}</div>'''
 create=f'''<div class="card" id="campanha"><h2>Nova campanha</h2><form method="post" enctype="multipart/form-data" action="/admin/campaign"><input type="hidden" name="csrf" value="{csrf()}"><input class="input" name="name" placeholder="Nome da campanha" required><input class="input" name="title" placeholder="Título da LP" required><input class="input" name="prize" placeholder="Prêmio" required><textarea name="terms" placeholder="Termos"></textarea><label>Imagem do prêmio</label><input class="input" type="file" name="image" accept="image/png,image/jpeg,image/webp,image/gif"><label><input type="checkbox" name="active" checked> Criar campanha ativa</label><br><br><button class="btn">Criar campanha</button></form></div>'''
 campaign_form=create if request.args.get('nova')=='1' else edit
 clear_form=(f'''<div class="card" id="excluir-participantes"><h2>Limpar participantes desta campanha</h2><p>Exclui permanentemente os cadastros. O histórico de sorteios será mantido.</p><form method="post" action="/admin/campaign/{x['id']}/clear-participants" onsubmit="return confirm('Excluir permanentemente todos os participantes desta campanha? O histórico será mantido.');"><input type="hidden" name="csrf" value="{csrf()}"><label>Digite o nome da campanha para confirmar</label><input class="input" name="confirm_name" required placeholder="{escape(x['name'])}"><button class="btn red">Limpar participantes</button></form></div>''' if session.get('role')=='admin' else '')
 body=f'''<div class="wrap"><div class="top"><div class="brand">Zanthus <b>| Neos</b></div><div><a href="/qr/{x['id']}.png">QR Code desta campanha</a> · <a href="/admin/export?cid={x['id']}">XLSX</a> · <a href="/admin/logout">Sair</a></div></div><h1>Painel do Sorteio</h1><div class="grid"><div class="card"><b>Participantes</b><div style="font-size:38px">{len(ps)}</div></div><div class="card"><b>Campanha selecionada</b><div>{x['name']}</div></div><div class="card"><b>Prêmio</b><div>{x['prize']}</div></div></div><div class="card" id="sorteio"><h2>Sorteio</h2><form method="post" action="/admin/draw"><input type="hidden" name="csrf" value="{csrf()}"><input type="hidden" name="cid" value="{x['id']}"><label>Quantidade de ganhadores</label><input class="input" type="number" min="1" max="20" value="1" name="count"><label>Segundos para revelar o resultado</label><input class="input" type="number" min="3" max="60" value="10" name="seconds"><button class="btn a">🎲 Iniciar sorteio</button></form><form method="post" action="/admin/reenter-all" style="margin-top:10px"><input type="hidden" name="csrf" value="{csrf()}"><input type="hidden" name="cid" value="{x['id']}"><button class="btn gray">↻ Recolocar ganhadores permitidos</button></form></div><div class="card" id="participantes"><h2>Participantes</h2><div style="overflow:auto"><table class="table"><tr><th>Nome</th><th>Empresa</th><th>Ganhou</th><th>Status</th><th>Ações</th></tr>{rows}</table></div></div>{campaign_form}<div class="card" id="campanhas"><h2>Campanhas cadastradas</h2><a class="btn" href="/admin?nova=1#campanha">Nova campanha</a><div style="overflow:auto"><table class="table"><tr><th>Campanha</th><th>Status</th><th>Criada em</th><th>Ações</th></tr>{camprows}</table></div></div>{useradmin}<details class="card" id="historico-sorteios"><summary style="cursor:pointer;font-size:20px;font-weight:700">Histórico de sorteios</summary><ul>{hist}</ul></details><details class="card" id="historico-alteracoes"><summary style="cursor:pointer;font-size:20px;font-weight:700">Histórico de alterações</summary><p class="muted">Últimas 100 ações administrativas.</p><div style="overflow:auto"><table class="table"><tr><th>Data/hora</th><th>Usuário</th><th>Ação</th><th>Detalhes</th></tr>{auditrows}</table></div></details>{clear_form}</div>'''; return layout('Painel',admin_navigation(body))

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
 except IntegrityError:
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
 n=saveimg(request.files.get('image')); active=1 if request.form.get('active') else 0; c=db(); cid=insert_campaign(c,(request.form['name'],request.form['title'],request.form['prize'],request.form.get('terms',''),n,active,now())); audit('CAMPANHA_CRIADA',request.form['name'],c);c.commit();c.close();flash('Campanha criada.');return redirect(f'/admin?cid={cid}')
@app.post('/admin/campaign/<int:i>/update')
@admin
def update_campaign(i):
 if not session.get('csrf') or not okcsrf():
  flash('Sessão expirada. Atualize a página e tente novamente.'); return redirect(f'/admin?cid={i}')
 values=tuple(request.form.get(key,'').strip() for key in ('name','title','prize','terms'))
 if not all(values[:3]):
  flash('Preencha nome, título e prêmio.'); return redirect(f'/admin?cid={i}')
 c=db()
 try:
  z=c.execute('select * from campaigns where id=?',(i,)).fetchone()
  if not z:
   flash('Campanha não encontrada.'); return redirect('/admin')
  changed=[label for key,label,value in zip(('name','title','prize','terms'),('nome','título','prêmio','termos'),values) if (z[key] or '')!=value]
  image=z['image']
  file=request.files.get('image')
  if file and file.filename:
   filename=secure_filename(file.filename)
   if '.' not in filename or filename.rsplit('.',1)[-1].lower() not in ALLOWED:
    flash('Escolha uma imagem PNG, JPG, WEBP ou GIF.'); return redirect(f'/admin?cid={i}')
   try:
    image=saveimg(file)
   except Exception:
    flash('Não foi possível salvar a nova imagem. Nenhuma alteração foi aplicada. Tente novamente.'); return redirect(f'/admin?cid={i}')
   changed.append('imagem')
  if changed:
   c.execute('update campaigns set name=?,title=?,prize=?,terms=?,image=? where id=?',(*values,image,i))
   audit('CAMPANHA_ATUALIZADA',f"Campanha {i}: {', '.join(changed)}",c); c.commit()
  flash('Campanha atualizada.' if changed else 'Nenhuma alteração para salvar.')
 finally:
  c.close()
 return redirect(f'/admin?cid={i}')

@app.post('/admin/campaign/<int:i>/toggle')
@admin
def toggle_campaign(i):
 if not okcsrf(): return redirect('/admin')
 c=db(); z=c.execute('select * from campaigns where id=?',(i,)).fetchone()
 if z:
  new=0 if z['active'] else 1; c.execute('update campaigns set active=? where id=?',(new,i));audit('CAMPANHA_STATUS_ALTERADO',f"{z['name']} -> {'ativa' if new else 'inativa'}",c);c.commit()
 c.close();return redirect(f'/admin?cid={i}')
@app.post('/admin/campaign/<int:i>/delete')
@admin_only
def delete_campaign(i):
 if not session.get('csrf') or not okcsrf():
  flash('Sessão expirada. Atualize a página e tente novamente.'); return redirect('/admin')
 c=db()
 try:
  # Lock status while checking/deleting so an activation cannot race deletion.
  z=c.execute('select * from campaigns where id=?'+(' for update' if DATABASE_URL else ''),(i,)).fetchone()
  if not z:
   flash('Campanha não encontrada.'); return redirect('/admin')
  if z['active']:
   flash('Desative a campanha antes de excluir.'); return redirect(f'/admin?cid={i}')
  c.execute('delete from participants where campaign_id=?',(i,))
  c.execute('delete from draws where campaign_id=?',(i,))
  c.execute('delete from campaigns where id=?',(i,))
  audit('CAMPANHA_EXCLUIDA',f"Campanha {i}: {z['name']} (incluindo participantes e sorteios)",c)
  c.commit(); flash('Campanha excluída.')
 finally:
  c.close()
 return redirect('/admin')
@app.post('/admin/campaign/<int:i>/image')
@admin
def image(i):
 if not okcsrf(): return redirect('/admin')
 n=saveimg(request.files.get('image')); c=db(); z=c.execute('select name from campaigns where id=?',(i,)).fetchone(); c.execute('update campaigns set image=? where id=?',(n,i));audit('IMAGEM_CAMPANHA_ATUALIZADA',z['name'] if z else str(i),c);c.commit();c.close();flash('Imagem atualizada.');return redirect(f'/admin?cid={i}')
@app.post('/admin/campaign/<int:i>/clear-participants')
@admin_only
def clear_participants(i):
 target=f'/admin?cid={i}'
 if not session.get('csrf') or not okcsrf():
  flash('Sessão expirada.'); return redirect(target)
 c=db()
 try:
  campaign=c.execute('select * from campaigns where id=?'+(' for update' if DATABASE_URL else ''),(i,)).fetchone()
  if not campaign or request.form.get('confirm_name')!=campaign['name']:
   flash('Confirme o nome da campanha para limpar os participantes.'); return redirect(target)
  for d in c.execute('select id,winner_ids,winner_details from draws where campaign_id=?',(i,)).fetchall():
   if d['winner_details'] is not None: continue
   details=[]
   for pid in json.loads(d['winner_ids'] or '[]'):
    p=c.execute('select id,name,company from participants where id=? and campaign_id=?',(pid,i)).fetchone()
    details.append(dict(p) if p else {'id':pid,'name':'Participante não disponível','company':''})
   c.execute('update draws set winner_details=? where id=?',(json.dumps(details,ensure_ascii=False),d['id']))
  count=c.execute('select count(*) from participants where campaign_id=?',(i,)).fetchone()[0]
  c.execute('delete from participants where campaign_id=?',(i,))
  audit('PARTICIPANTES_LIMPOS',f"Campanha {i} ({campaign['name']}): {count} participantes excluídos; histórico mantido",c)
  c.commit(); flash(f'{count} participantes excluídos. Histórico de sorteios mantido.')
 finally:
  c.close()
 return redirect(target)

@app.post('/admin/p/<int:i>/delete')
@admin_only
def delete_participant(i):
 cid=request.form.get('cid',type=int)
 target=f'/admin?cid={cid}' if cid else '/admin'
 if not session.get('csrf') or not okcsrf():
  flash('Sessão expirada. Atualize a página e tente novamente.'); return redirect(target)
 c=db()
 try:
  p=c.execute('select * from participants where id=? and campaign_id=?',(i,cid)).fetchone()
  if not p:
   flash('Participante não encontrado nesta campanha.'); return redirect(target)
  draws=c.execute('select winner_ids from draws where campaign_id=?',(cid,)).fetchall()
  if p['winner'] or any(i in json.loads(d['winner_ids'] or '[]') for d in draws):
   flash('Este participante consta no histórico de ganhadores. Use Bloquear para impedir novos sorteios sem perder o histórico.'); return redirect(target)
  c.execute('delete from participants where id=? and campaign_id=?',(i,cid))
  audit('PARTICIPANTE_EXCLUIDO',f"Campanha {cid}: participante {i} ({p['name']})",c)
  c.commit(); flash('Participante excluído.')
 finally:
  c.close()
 return redirect(target)

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
 details=json.dumps([{'id':w['id'],'name':w['name'],'company':w['company']} for w in ws],ensure_ascii=False)
 c.execute('insert into draws(campaign_id,drawn_at,winner_ids,operator,winner_details) values(?,?,?,?,?)',(x['id'],now(),json.dumps(ids),session['user'],details));audit('SORTEIO_REALIZADO',f'{x["name"]}: {len(ids)} ganhador(es)',c);c.commit();c.close(); seconds=max(3,min(int(request.form.get('seconds','10')),60)); return redirect('/admin/draw-screen?ids='+','.join(map(str,ids))+'&seconds='+str(seconds))
@app.route('/admin/draw-screen')
@admin
def screen():
 ids=[int(v) for v in request.args.get('ids','').split(',') if v.isdigit()]; seconds=max(3,min(request.args.get('seconds',10,type=int),60)); c=db(); q=','.join('?'*len(ids)); ws=c.execute(f'select * from participants where id in ({q})',ids).fetchall() if ids else []; c.close()
 cards=''.join(f'<div class="reveal-card"><div class="trophy" aria-label="Troféu"><svg viewBox="0 0 64 64" width="64" height="64" fill="none" aria-hidden="true"><path d="M20 10h24v16c0 12-6 18-12 18s-12-6-12-18V10Z" fill="#cadaff" stroke="#2c2f62" stroke-width="3"/><path d="M20 15H10v9c0 9 5 14 13 14M44 15h10v9c0 9-5 14-13 14M32 44v10M23 56h18" stroke="#2c2f62" stroke-width="3" stroke-linecap="round"/><path d="m32 18 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1 3-6Z" fill="#3b45f2"/></svg></div><div class="winner-name">{w["name"]}</div><div class="winner-company">{w["company"]}</div></div>' for w in ws)
 body=f'''<div class="raffle-stage"><div class="particles"></div><div class="raffle-inner"><div class="raffle-brand"><div class="public-logo"><img src="/static/zanthus-neos-transparente.png" alt="Zanthus Tecnologia de Resultados | Neos" width="1920" height="1080"></div></div><div id="countArea"><div class="raffle-label">SORTEIO AO VIVO</div><h1>Prepare-se!</h1><p>O resultado será revelado em</p><div class="countdown-wrap"><div id="countdown" class="countdown">{seconds}</div><div class="spinner-ring"></div></div><div id="raffleMsg" class="raffle-msg">Embaralhando participantes...</div></div><div id="winnerArea" class="winner-area"><div class="raffle-label">RESULTADO DO SORTEIO</div><div class="winner-confetti" aria-hidden="true"><i style="--x:0%;--r:0deg;--delay:0.0s;--color:#3b45f2"></i><i style="--x:37%;--r:29deg;--delay:0.07s;--color:#4f83fb"></i><i style="--x:74%;--r:58deg;--delay:0.14s;--color:#8cd92a"></i><i style="--x:10%;--r:87deg;--delay:0.21000000000000002s;--color:#cadaff"></i><i style="--x:47%;--r:116deg;--delay:0.28s;--color:#3b45f2"></i><i style="--x:84%;--r:145deg;--delay:0.35000000000000003s;--color:#4f83fb"></i><i style="--x:20%;--r:174deg;--delay:0.0s;--color:#8cd92a"></i><i style="--x:57%;--r:203deg;--delay:0.07s;--color:#cadaff"></i><i style="--x:94%;--r:232deg;--delay:0.14s;--color:#3b45f2"></i><i style="--x:30%;--r:261deg;--delay:0.21000000000000002s;--color:#4f83fb"></i><i style="--x:67%;--r:290deg;--delay:0.28s;--color:#8cd92a"></i><i style="--x:3%;--r:319deg;--delay:0.35000000000000003s;--color:#cadaff"></i><i style="--x:40%;--r:348deg;--delay:0.0s;--color:#3b45f2"></i><i style="--x:77%;--r:377deg;--delay:0.07s;--color:#4f83fb"></i><i style="--x:13%;--r:406deg;--delay:0.14s;--color:#8cd92a"></i><i style="--x:50%;--r:435deg;--delay:0.21000000000000002s;--color:#cadaff"></i><i style="--x:87%;--r:464deg;--delay:0.28s;--color:#3b45f2"></i><i style="--x:23%;--r:493deg;--delay:0.35000000000000003s;--color:#4f83fb"></i><i style="--x:60%;--r:522deg;--delay:0.0s;--color:#8cd92a"></i><i style="--x:97%;--r:551deg;--delay:0.07s;--color:#cadaff"></i><i style="--x:33%;--r:580deg;--delay:0.14s;--color:#3b45f2"></i><i style="--x:70%;--r:609deg;--delay:0.21000000000000002s;--color:#4f83fb"></i><i style="--x:6%;--r:638deg;--delay:0.28s;--color:#8cd92a"></i><i style="--x:43%;--r:667deg;--delay:0.35000000000000003s;--color:#cadaff"></i><i style="--x:80%;--r:696deg;--delay:0.0s;--color:#3b45f2"></i><i style="--x:16%;--r:725deg;--delay:0.07s;--color:#4f83fb"></i><i style="--x:53%;--r:754deg;--delay:0.14s;--color:#8cd92a"></i><i style="--x:90%;--r:783deg;--delay:0.21000000000000002s;--color:#cadaff"></i><i style="--x:26%;--r:812deg;--delay:0.28s;--color:#3b45f2"></i><i style="--x:63%;--r:841deg;--delay:0.35000000000000003s;--color:#4f83fb"></i><i style="--x:100%;--r:870deg;--delay:0.0s;--color:#8cd92a"></i><i style="--x:36%;--r:899deg;--delay:0.07s;--color:#cadaff"></i><i style="--x:73%;--r:928deg;--delay:0.14s;--color:#3b45f2"></i><i style="--x:9%;--r:957deg;--delay:0.21000000000000002s;--color:#4f83fb"></i><i style="--x:46%;--r:986deg;--delay:0.28s;--color:#8cd92a"></i><i style="--x:83%;--r:1015deg;--delay:0.35000000000000003s;--color:#cadaff"></i></div><h1 class="congrats">O GANHADOR FOI!</h1>{cards}<a class="raffle-back" href="/admin">Voltar ao painel</a></div></div></div><script>let n={seconds};const el=document.getElementById('countdown'),msg=document.getElementById('raffleMsg');const timer=setInterval(()=>{{n--;el.textContent=n;if(n<=Math.ceil({seconds}/2))msg.textContent='Quase lá...';if(n<=3)msg.textContent='Preparando o resultado...';if(n<=0){{clearInterval(timer);document.getElementById('countArea').classList.add('fade-out');setTimeout(()=>{{document.getElementById('countArea').style.display='none';document.getElementById('winnerArea').classList.add('show')}},650)}}}},1000);</script>'''
 return layout('Sorteio Zanthus | Neos',body)

@app.route('/admin/export')
@admin
def export():
 x=camp(request.args.get('cid'))
 if not x: return ('Campanha não encontrada',404)
 c=db();rs=c.execute('select * from participants where campaign_id=? order by id',(x['id'],)).fetchall();c.close()
 wb=Workbook();ws=wb.active;ws.title='Participantes'
 headers=['Nome','WhatsApp','E-mail','Empresa','Ganhador','Pode repetir','Bloqueado']
 ws.append(headers)
 for cell in ws[1]: cell.font=Font(bold=True)
 for r in rs: ws.append([r['name'],r['whatsapp'],r['email'],r['company'],'Sim' if r['winner'] else 'Não','Sim' if r['allow_again'] else 'Não','Sim' if r['blocked'] else 'Não'])
 widths=[32,20,38,32,14,16,14]
 for i,w in enumerate(widths,1): ws.column_dimensions[chr(64+i)].width=w
 ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
 out=io.BytesIO();wb.save(out);out.seek(0)
 return Response(out.getvalue(),mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename=participantes.xlsx'})
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

