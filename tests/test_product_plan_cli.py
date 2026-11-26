"""Exercise the CLI plan route through a synthetic subprocess transport."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


CLI = Path(__file__).resolve().parents[1] / 'scripts' / 'zhiying.py'
FIXTURE = '''
import json,sys
from pathlib import Path
state=Path(sys.argv[1]); log=Path(sys.argv[2])
payload=json.load(sys.stdin)
with log.open('a',encoding='utf-8') as f:f.write(payload['command']+'\\n')
record=json.loads(state.read_text(encoding='utf-8'))
if payload['command'].endswith('.detail'):
    print(json.dumps({'ok':True,'record':record}))
elif payload['command']=='sale.update':
    if any(record.get(k)!=v for k,v in payload['expected'].items()):
        print(json.dumps({'ok':False,'error':'conflict'}))
    else:
        record.update(payload['fields']); record['sale_log']='Updated'
        state.write_text(json.dumps(record),encoding='utf-8')
        print(json.dumps({'ok':True}))
else:raise SystemExit(1)
'''


class ProductPlanCliTests(unittest.TestCase):
    def test_batch_plan_show_apply_restore_uses_existing_transport(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            script=root/'transport.py';script.write_text(FIXTURE,encoding='utf-8')
            state=root/'state.json';log=root/'calls.txt';plan=root/'plan.local.json'
            original={'sale_id':1001,'sale_stock':'[{"key":"A","money":1.44},{"key":"B"}]',
                      'sale_intro':'{"en":"Text","zh":"Keep"}','sale_log':'Old'}
            state.write_text(json.dumps(original),encoding='utf-8')
            env=dict(os.environ,LOCALAPPDATA=str(root/'local'))
            env.pop('ZHIYING_COLLECTED_TRANSPORT',None);env.pop('ZHIYING_SESSION_FILE',None)
            transport=['--transport',sys.executable,'--transport-arg',str(script),
                       '--transport-arg',str(state),'--transport-arg',str(log)]
            def run(*args):
                result=subprocess.run([sys.executable,str(CLI),*args],capture_output=True,encoding='utf-8',env=env)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                return json.loads(result.stdout)
            prepared=run('product-plan','--namespace','sale','--product-id','1001',
                         '--adjust-surcharge','A','0.01','--adjust-surcharge','B','0.01',
                         '--append-intro','*','--output',str(plan),*transport)
            self.assertFalse(prepared['update_sent'])
            self.assertEqual(run('product-plan-show','--plan',str(plan))['state'],'prepared')
            self.assertTrue(run('product-apply','--plan',str(plan),*transport)['remote_read_back_verified'])
            self.assertTrue(run('product-restore','--plan',str(plan),*transport)['remote_read_back_verified'])
            restored=json.loads(state.read_text(encoding='utf-8'))
            self.assertEqual(json.loads(restored['sale_stock']),json.loads(original['sale_stock']))
            self.assertEqual(json.loads(restored['sale_intro']),json.loads(original['sale_intro']))
            self.assertEqual(log.read_text(encoding='utf-8').splitlines(),
                             ['sale.detail','sale.detail','sale.update','sale.detail','sale.detail','sale.update','sale.detail'])


if __name__=='__main__':unittest.main()
