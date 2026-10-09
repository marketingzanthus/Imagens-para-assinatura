import json
import unittest
from test_campaign_edit import module

class DrawHistory(unittest.TestCase):
 def test_old_and_new_winner_snapshots(self):
  c=module.db()
  c.execute("insert into participants(id,campaign_id,name,email,company) values(70,1,'Ana','ana@example.invalid','Empresa A')")
  c.execute("insert into draws(campaign_id,drawn_at,winner_ids,operator) values(1,'2026-10-08 10:00:00','[70]','operador-antigo')")
  c.commit(); module.init()
  old=c.execute('select * from draws order by id limit 1').fetchone()
  self.assertEqual(json.loads(old['winner_details'])[0]['company'],'Empresa A')
  client=module.app.test_client()
  with client.session_transaction() as session: session.update(uid=1,user='admin',role='admin',csrf='token')
  self.assertEqual(client.post('/admin/draw',data=dict(csrf='token',cid='1',count='1',seconds='3')).status_code,302)
  drawn=c.execute('select * from draws order by id desc limit 1').fetchone()
  self.assertEqual(drawn['operator'],'admin')
  self.assertEqual(json.loads(drawn['winner_details'])[0]['name'],'Ana')
  c.execute("update participants set name='Alterado',company='Outra empresa' where id=70")
  c.commit(); module.init()
  html=client.get('/admin?cid=1').get_data(as_text=True)
  self.assertIn('Usuário que realizou o sorteio:',html)
  self.assertIn('operador-antigo',html)
  self.assertIn('<strong>Ana</strong> — Empresa A',html)
  self.assertEqual(c.execute('select winner_details from draws order by id desc limit 1').fetchone()[0],drawn['winner_details'])
  c.close()

if __name__=='__main__': unittest.main()
