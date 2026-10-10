import unittest
from test_campaign_edit import module

class CampaignDelete(unittest.TestCase):
 def test_delete_and_guards(self):
  client=module.app.test_client()
  c=module.db()
  c.execute("insert into campaigns(id,name,title,prize,active) values(90,'Excluir','Teste','Kit',0)")
  c.execute("insert into participants(campaign_id,name,email) values(90,'Teste','delete@example.invalid')")
  c.execute("insert into draws(campaign_id,winner_ids) values(90,'[]')")
  c.commit()
  with client.session_transaction() as session: session.update(uid=1,user='admin',role='user',csrf='token')
  client.post('/admin/campaign/90/delete',data={'csrf':'token'})
  self.assertIsNotNone(c.execute('select * from campaigns where id=90').fetchone())
  with client.session_transaction() as session: session['role']='admin'
  client.post('/admin/campaign/90/delete',data={'csrf':'bad'})
  self.assertIsNotNone(c.execute('select * from campaigns where id=90').fetchone())
  client.post('/admin/campaign/1/delete',data={'csrf':'token'})
  self.assertIsNotNone(c.execute('select * from campaigns where id=1').fetchone())
  self.assertEqual(client.post('/admin/campaign/90/delete',data={'csrf':'token'}).location,'/admin#campanhas')
  for table in ('participants','draws'):
   self.assertEqual(c.execute(f'select count(*) from {table} where campaign_id=90').fetchone()[0],0)
  self.assertIsNone(c.execute('select * from campaigns where id=90').fetchone())
  self.assertEqual(c.execute("select count(*) from audit_logs where action='CAMPANHA_EXCLUIDA'").fetchone()[0],1)
  client.post('/admin/campaign/90/delete',data={'csrf':'token'})
  c.close()

if __name__=='__main__': unittest.main()

