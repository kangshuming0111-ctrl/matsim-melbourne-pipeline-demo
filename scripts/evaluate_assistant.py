"""Evaluate a locked internal suite; preserve every answer, failure and timing.
Development tuning is separate from a one-time, code-frozen holdout evaluation.
"""
import argparse,hashlib,json,math,statistics,time
from datetime import datetime,timezone
from pathlib import Path
from wrapper.analytics import ROOT
from wrapper.assistant import ask,get_store
from wrapper.ai_provider import status

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def percentile(values,p):
 if not values:return None
 s=sorted(values);x=(len(s)-1)*p;i=int(x);return s[i]+(s[min(i+1,len(s)-1)]-s[i])*(x-i)
def score(case,response):
 expected=case['expected'];errors=[]
 if response['status']!=expected['status']:errors.append('status')
 if response['plan'].get('tool')!=expected['tool']:errors.append('tool')
 primary=[f for f in response.get('facts',[]) if f['role']=='primary']
 if expected['values'] is not None:
  if len(primary)!=len(expected['values']):errors.append('primary_fact_count')
  else:
   for actual,value in zip(primary,expected['values']):
    got=actual['value']
    if (value is None and got is not None) or (value is not None and (got is None or not math.isclose(got,value,rel_tol=1e-10,abs_tol=1e-8))):errors.append('numeric_value')
    if actual['unit']!=expected['unit']:errors.append('unit')
    if expected['metric'] and actual['metric']!=expected['metric']:errors.append('metric')
 sources={s['id']:s for s in response.get('sources',[])}
 for fact in response.get('facts',[]):
  if not fact.get('unit') or not fact.get('source_ids'):errors.append('missing_citation')
  for ref in fact.get('source_ids',[]):
   source=sources.get(ref)
   if not source:errors.append('unknown_citation');continue
   if source['source_kind']=='hypothetical_fixture':
    if source['run_ids']:errors.append('fixture_presented_as_run')
   elif not source.get('run_ids') or len(source.get('query_sha256',''))!=64 or not source.get('artifacts'):errors.append('incomplete_provenance')
 if expected['tool']=='explain_detour' and response['status']=='answered':
  ids={c['id'] for c in response['explanation']}
  if not {'outcome','uptake','route','hypothesis','scope'}<=ids:errors.append('explanation_coverage')
  gold={'time':.0977872947894222,'observed_detour_trips':6,'car_trips':934,'observed_detour_share':.6423982869379015,'existing_freeflow':20.880345959079616,'corridor_freeflow':42.73902140993215}
  for f in response['facts']:
   if f['metric'] not in gold or not math.isclose(f['value'],gold[f['metric']],rel_tol=1e-10,abs_tol=1e-8):errors.append('explanation_numeric_value')
 return {'passed':not errors,'errors':sorted(set(errors))}

def code_hashes():
 paths=['wrapper/assistant.py','wrapper/ai_provider.py','wrapper/measurements.py','scripts/evaluate_assistant.py','sql/schema.sql','portfolio/evidence/sql/sql-evidence.json']
 paths += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'sql/queries').glob('*.sql'))]
 return {p:digest(ROOT/p) for p in paths}
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--split',choices=['development','holdout'],required=True);parser.add_argument('--engine',choices=['ai','deterministic'],required=True);parser.add_argument('--output',type=Path,required=True)
 args=parser.parse_args();suite=ROOT/'evals/assistant';locked=json.loads((suite/'suite-lock.json').read_text());questions=suite/(args.split+'.jsonl')
 assert digest(questions)==locked['files'][questions.name],'Evaluation questions changed'
 if args.output.exists():raise FileExistsError('Preserve previous evaluation; select a new output directory')
 model=status()
 freeze=suite/'holdout-freeze.json'
 if args.split=='holdout':
  if not freeze.exists():raise ValueError('Freeze code/model before first holdout use with scripts.freeze_assistant')
  data=json.loads(freeze.read_text());assert data['code_sha256']==code_hashes(),'Frozen implementation differs'
  if args.engine=='ai':
   assert model.get('available') and model.get('model_digest')==data['model'].get('model_digest'),'Frozen local model is unavailable or changed'
   marker=suite/'holdout-ai-opened.json'
   if marker.exists():raise ValueError('Holdout already used: do not represent a repeat as unseen')
   marker.write_text(json.dumps({'opened_at_utc':datetime.now(timezone.utc).isoformat(),'output':str(args.output)}))
 cases=[json.loads(line) for line in questions.read_text().splitlines()];args.output.mkdir(parents=True)
 start=time.perf_counter();outcomes=[]
 for case in cases:
  response=ask(case['question'],args.engine);assessment=score(case,response);record={'case':case,'response':response,'assessment':assessment};outcomes.append(record)
  with (args.output/'answers.jsonl').open('a') as f:f.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n')
  print(json.dumps({'id':case['id'],'passed':assessment['passed'],'errors':assessment['errors'],'ai_used':response.get('ai_used'),'latency_ms':response['latency_ms']},ensure_ascii=False),flush=True)
 numeric=[r for r in outcomes if r['case']['expected']['values'] is not None];answerable=[r for r in outcomes if r['case']['expected']['status']=='answered'];unavailable=[r for r in outcomes if r['case']['expected']['status']=='insufficient_evidence']
 successful=sum(r['assessment']['passed'] for r in outcomes);numeric_good=sum(r['assessment']['passed'] for r in numeric)
 model_numeric_good=sum(r['assessment']['passed'] and r['response'].get('ai_used') and not r['response'].get('notes') for r in numeric)
 lat=[r['response']['latency_ms'] for r in outcomes];model_lat=[r['response']['latency_ms'] for r in outcomes if r['response'].get('ai_used')]
 summary={'suite':locked['suite'],'split':args.split,'engine':args.engine,'count':len(outcomes),'passed':successful,'all_case_accuracy':successful/len(outcomes),'numeric_answerable_count':len(numeric),'numeric_answerable_correct':numeric_good,'numeric_answerable_accuracy':numeric_good/len(numeric) if numeric else None,'ai_numeric_without_fallback_correct':model_numeric_good if args.engine=='ai' else None,'ai_numeric_without_fallback_accuracy':model_numeric_good/len(numeric) if numeric and args.engine=='ai' else None,'insufficient_evidence_cases':len(unavailable),'correct_refusals':sum(r['assessment']['passed'] for r in unavailable),'citation_failures':sum(any('citation' in e or 'provenance' in e for e in r['assessment']['errors']) for r in outcomes),'ai_used_cases':len(model_lat),'fallback_cases':sum(bool(r['response'].get('notes')) for r in outcomes),'explicit_parameter_corrected_cases':sum(bool(r['response'].get('explicit_parameter_constraints')) for r in outcomes),'latency_ms':{'all_p50':percentile(lat,.5),'all_p95':percentile(lat,.95),'model_invoked_p50':percentile(model_lat,.5),'model_invoked_p95':percentile(model_lat,.95)},'api_cost_usd_total':0,'api_cost_usd_per_question':0,'cost_scope':'Local inference API fee only; electricity/hardware unmeasured. Download/storage/setup costs excluded.','model':model,'wall_time_seconds':time.perf_counter()-start,'code_sha256':code_hashes(),'suite_sha256':digest(questions),'created_at_utc':datetime.now(timezone.utc).isoformat(),'failed_ids':[r['case']['id'] for r in outcomes if not r['assessment']['passed']],'limitations':['Small same-author internal suite; not an external benchmark or production reliability guarantee.','Policy refusals can occur before the model; guarded refusals are not claims about unguarded model safety.','Evidence-bound explanations use reviewed claim blocks; the model routes and organizes, not unrestricted causal writing.','Reported accuracy is the guarded system, including deterministic literal-parameter constraints; not raw model accuracy.']}
 (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
