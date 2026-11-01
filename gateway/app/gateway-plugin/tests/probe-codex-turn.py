"""No providers/storage/startup: exercise the actual functions using AST and fakes."""
import ast
import json
from pathlib import Path
from typing import Any
root = Path(__file__).resolve().parents[2]
ns = {'Any': Any, 'json': json}
def load(file, names):
    tree = ast.parse((root/file).read_text())
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[]), file, 'exec'), ns)
load('oauth.py', {'_codex_prompt'})
prompt = ns['_codex_prompt']([{'role':'system','content':'current tools'}, {'role':'assistant','content':'old tools'}, {'role':'user','content':'read'}])
assert '<turn role="USER">\nread\n</turn>' in prompt
assert 'historial es contexto, no un catálogo' in prompt
assert 'devuelve kind=tool_call ahora' in prompt
load('server.py', {'run_openai_until_result','source_cards_from_messages','source_cards_from_tool_result','merge_source_cards'})
old = {'title':'Old','url':'https://example.org/old'}
messages = [{'role':'assistant','content':'old', 'sources':[old]}, {'role':'user','content':'read'}]
script = iter([{'kind':'tool_call','tool_name':'read_project_file','arguments':'{}'}, {'kind':'answer','content':'read done'}])
executed=[]; saved=[]; requests=[]
def model(ms,*args):
    requests.append(list(ms)); return next(script)
ns.update(MAX_TOOL_ROUNDS=4, OPENAI_RESPONSE_SCHEMA={}, TOOL_SCHEMAS=[{'function':{'name':'read_project_file'}}], SENSITIVE_TOOL_NAMES=set(), update_activity=lambda *a,**k:None, utc_now=lambda:'now', run_openai_codex=model, controller_execute_tool=lambda name,args:executed.append(name) or {'ok':True,'action':name,'content':'file'}, tool_message_for_result=lambda r,v:{'role':'tool','content':json.dumps(r)}, save_assistant_message=lambda cid,m:saved.append(m))
r=ns['run_openai_until_result']('openai-codex-oauth/gpt-6-sol',messages,'isolated')
assert executed == ['read_project_file']
assert requests[1][-1]['role']=='tool'
assert r['tools_used']==['read_project_file'] and r['sources']==[]
assert 'sources' not in saved[0]
print('7/7 Codex prompt and execution assertions passed')
