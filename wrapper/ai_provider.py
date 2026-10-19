"""Local-only Ollama transport; no shell execution or query-supplied destinations."""
from __future__ import annotations
import json,os,subprocess,threading,time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request,ProxyHandler,build_opener

DEFAULT_MODEL='qwen3:4b-instruct-2507-q4_K_M'
RUNTIME=Path.home()/'.local/share/matsim-ai'
_START_LOCK=threading.Lock()
class ModelUnavailable(RuntimeError):pass

def configuration():
 base=os.environ.get('MATSIM_AI_URL','http://127.0.0.1:11434').rstrip('/')
 u=urlparse(base)
 if u.scheme!='http' or u.hostname not in {'127.0.0.1','localhost','::1'} or u.path or u.query or u.fragment or u.username:
  raise ModelUnavailable('Only a local loopback Ollama endpoint is supported')
 return base,os.environ.get('MATSIM_AI_MODEL',DEFAULT_MODEL)

def request(path,payload=None,timeout=3):
 base,_=configuration();body=json.dumps(payload,allow_nan=False).encode() if payload is not None else None
 req=Request(base+path,data=body,headers={'Content-Type':'application/json'})
 with build_opener(ProxyHandler({})).open(req,timeout=timeout) as response:
  raw=response.read(1024*1024+1)
  if len(raw)>1024*1024:raise ModelUnavailable('Model response too large')
  return json.loads(raw)

def status():
 _,model=configuration()
 try:
  version=request('/api/version')['version'];models=request('/api/tags').get('models',[])
  found=next((r for r in models if r['name']==model),None)
  return {'available':found is not None,'provider':'ollama-local','model':model,'version':version,'model_digest':found.get('digest') if found else None,'api_cost_usd':0,'cost_note':'Local inference: no API fee; electricity and hardware are not priced.'}
 except (OSError,ValueError,KeyError,ModelUnavailable):return {'available':False,'provider':'ollama-local','model':model,'reason':'Local model service unavailable or model not installed'}

def ensure_service():
 if status()['available']:return
 with _START_LOCK:
  if status()['available']:return
  base,_=configuration();binary=RUNTIME/'bin/ollama'
  if base!='http://127.0.0.1:11434' or not binary.is_file():raise ModelUnavailable('Start/install the configured local model; deterministic mode remains available')
  # Reuse a running service even when the requested model is absent.
  try:request('/api/version');raise ModelUnavailable('Configured model is not installed')
  except ModelUnavailable:raise
  except (OSError,ValueError):pass
  log=RUNTIME/'server.log';env=dict(os.environ,OLLAMA_HOST='127.0.0.1:11434',OLLAMA_MODELS=str(RUNTIME/'models'),OLLAMA_NO_CLOUD='1',OLLAMA_NUM_PARALLEL='1')
  with log.open('ab',buffering=0) as stream:
   child=subprocess.Popen([str(binary),'serve'],stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,env=env,start_new_session=True,close_fds=True)
  for _ in range(40):
   if status()['available']:return
   if child.poll() is not None:break
   time.sleep(.1)
  raise ModelUnavailable('Local model did not become ready; see local runtime log')

class OllamaProvider:
 def __init__(self):self.calls=[]
 def generate(self,system,user,schema,stage):
  ensure_service();_,model=configuration();start=time.perf_counter()
  payload={'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':user}],
   'format':schema,'stream':False,'keep_alive':'20m','options':{'temperature':0,'seed':42,'num_ctx':4096,'num_predict':300,'num_thread':8}}
  try:
   result=request('/api/chat',payload,timeout=120)
   if not result.get('done') or result.get('done_reason')=='length':raise ModelUnavailable('Incomplete model response')
   parsed=json.loads(result['message']['content'])
  except (OSError,ValueError,KeyError) as exc:raise ModelUnavailable('Model transport or structured response failed') from exc
  self.calls.append({'stage':stage,'model':model,'latency_ms':round((time.perf_counter()-start)*1000,3),
   'prompt_tokens':result.get('prompt_eval_count'),'output_tokens':result.get('eval_count'),'api_cost_usd':0})
  return parsed
