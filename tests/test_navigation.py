import os,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
tmp=tempfile.TemporaryDirectory()
os.environ.update(DB_NAME=tmp.name+'/test.db',UPLOAD_DIR=tmp.name+'/uploads',ADMIN_PASSWORD='local-test-only')
os.environ.pop('DATABASE_URL',None)
import app
client=app.app.test_client()
with client.session_transaction() as s: s.update(uid=1,user='admin',role='admin',csrf='token')
c=app.db()
c.execute("insert into campaigns(name,title,prize,active) values('Second','Second','Prize',1)")
c.execute("insert into participants(campaign_id,name,email) values(2,'Test','test@example.invalid')")
c.commit();c.close()
for path,section,data in [('/admin/p/1/block','participantes',{}),('/admin/p/1/again','participantes',{}),('/admin/p/1/reenter','participantes',{}),('/admin/campaign/2/toggle','campanhas',{}),('/admin/campaign/2/update','campanha',dict(name='Second',title='Title',prize='Prize')),('/admin/user','usuarios',{}),('/admin/campaign/2/clear-participants','excluir-participantes',{}),('/admin/reenter-all','sorteio',{'cid':2})]:
 r=client.post(path,data=dict(csrf='token',_return_cid=2,**data))
 assert r.location==f'/admin?cid=2#{section}',(path,r.status_code,r.location)
 assert client.get(r.location).status_code==200
# Invalid CSRF retains origin; external locations cannot be supplied.
r=client.post('/admin/p/1/block',data={'csrf':'bad','_return_cid':2,'_return_section':'https://evil.invalid'})
assert r.location=='/admin?cid=2#participantes'
assert '/admin/login' in app.app.test_client().post('/admin/p/1/block').location
html=client.get('/admin?cid=2').text
assert 'name="_return_cid" value="2"' in html
assert "document.addEventListener('submit'" in html
# Delete selected campaign and then last campaign, retaining list view.
for cid in (2,1):
 c=app.db();c.execute('update campaigns set active=0 where id=?',(cid,));c.commit();c.close()
 r=client.post(f'/admin/campaign/{cid}/delete',data={'csrf':'token','_return_cid':cid})
 assert r.location=='/admin#campanhas',r.location
 html=client.get(r.location).text
 assert 'id="campanhas"' in html
print('Navigation checks passed: actions, validation errors, selected campaign, authentication, and last campaign deletion.')
