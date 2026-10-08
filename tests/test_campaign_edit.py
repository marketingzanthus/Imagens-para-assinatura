import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
temporary=tempfile.TemporaryDirectory()
os.environ.pop('DATABASE_URL',None)
os.environ.pop('RENDER',None)
os.environ['DB_NAME']=str(Path(temporary.name)/'test.db')
os.environ['UPLOAD_DIR']=str(Path(temporary.name)/'uploads')
os.environ['ADMIN_PASSWORD']='local-test-only-password'
import app as module

class CampaignEdit(unittest.TestCase):
 def test_edit_preserves_campaign_and_related_records(self):
  client=module.app.test_client()
  with client.session_transaction() as session:
   session.update(uid=1,user='admin',role='admin',csrf='token')
  c=module.db()
  c.execute("update campaigns set image='existing.png' where id=1")
  c.execute("insert into participants(campaign_id,name,email) values(1,'Pessoa','test@example.invalid')")
  c.execute("insert into draws(campaign_id,winner_ids) values(1,'[1]')")
  c.commit()
  before=dict(c.execute('select * from campaigns where id=1').fetchone())
  values=dict(csrf='token',name='Novo "nome"',title='Novo título',prize='Novo prêmio',terms='</textarea><script>alert(1)</script>')
  unauthenticated=module.app.test_client()
  self.assertIn('/admin/login',unauthenticated.post('/admin/campaign/1/update',data=values).location)
  self.assertEqual(client.post('/admin/campaign/1/update',data={**values,'csrf':'wrong'}).status_code,302)
  self.assertEqual(dict(c.execute('select * from campaigns where id=1').fetchone()),before)
  client.post('/admin/campaign/1/update',data={**values,'name':' '})
  self.assertEqual(dict(c.execute('select * from campaigns where id=1').fetchone()),before)
  response=client.post('/admin/campaign/1/update',data=values)
  self.assertEqual(response.location,'/admin?cid=1')
  after=dict(c.execute('select * from campaigns where id=1').fetchone())
  for key in ('id','active','image','created_at'): self.assertEqual(after[key],before[key])
  for key in ('name','title','prize','terms'): self.assertEqual(after[key],values[key])
  self.assertEqual(c.execute('select count(*) from campaigns').fetchone()[0],1)
  self.assertEqual(c.execute('select count(*) from participants where campaign_id=1').fetchone()[0],1)
  self.assertEqual(c.execute('select count(*) from draws where campaign_id=1').fetchone()[0],1)
  self.assertEqual(c.execute("select count(*) from audit_logs where action='CAMPANHA_ATUALIZADA'").fetchone()[0],1)
  html=client.get('/admin?cid=1').get_data(as_text=True)
  self.assertIn('Salvar alterações',html)
  self.assertIn('&lt;/textarea&gt;&lt;script&gt;',html)
  self.assertIn('Novo &#34;nome&#34;',html)
  client.post('/admin/campaign/999/update',data=values)
  self.assertEqual(c.execute('select count(*) from campaigns').fetchone()[0],1)
  c.close()

if __name__=='__main__':
 unittest.main()

