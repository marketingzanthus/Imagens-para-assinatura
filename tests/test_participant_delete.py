import unittest
from test_campaign_edit import module

class ParticipantDelete(unittest.TestCase):
 def test_deletion_requires_admin_and_preserves_winners(self):
  client=module.app.test_client()
  c=module.db()
  c.execute("insert into participants(id,campaign_id,name,email) values(50,1,'Excluir','delete@example.invalid')")
  c.execute("insert into participants(id,campaign_id,name,email) values(51,1,'Ganhador','winner@example.invalid')")
  c.execute("insert into draws(campaign_id,winner_ids) values(1,'[51]')")
  c.commit()
  data=dict(csrf='token',cid='1')
  with client.session_transaction() as session: session.update(uid=1,user='admin',role='user',csrf='token')
  client.post('/admin/p/50/delete',data=data)
  self.assertIsNotNone(c.execute('select * from participants where id=50').fetchone())
  with client.session_transaction() as session: session['role']='admin'
  self.assertIn('/admin/p/50/delete',client.get('/admin?cid=1').get_data(as_text=True))
  client.post('/admin/p/50/delete',data={**data,'csrf':'bad'})
  client.post('/admin/p/50/delete',data={**data,'cid':'999'})
  self.assertIsNotNone(c.execute('select * from participants where id=50').fetchone())
  result=client.post('/admin/p/50/delete',data=data)
  self.assertEqual(result.location,'/admin?cid=1#participantes')
  self.assertIsNone(c.execute('select * from participants where id=50').fetchone())
  self.assertEqual(c.execute("select count(*) from audit_logs where action='PARTICIPANTE_EXCLUIDO'").fetchone()[0],1)
  client.post('/admin/p/51/delete',data=data)
  self.assertIsNotNone(c.execute('select * from participants where id=51').fetchone())
  self.assertEqual(c.execute('select winner_ids from draws').fetchone()[0],'[51]')
  c.close()

if __name__=='__main__': unittest.main()

