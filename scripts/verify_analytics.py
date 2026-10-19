from pathlib import Path
import json,math,shutil,duckdb
from wrapper.analyze import compute_summary_data
from wrapper.impact import analyze_impact
from wrapper.analytics import ROOT,import_case
root=ROOT
evidence=json.loads((root/'portfolio/evidence/sql/sql-evidence.json').read_text());results=evidence['results']
old=json.loads((root/'portfolio/evidence/case.json').read_text())
con=duckdb.connect(str(root/'output/analytics/matsim.duckdb'),read_only=True)
checks=[];errors=[]
from scripts.analytics import query_rows
import hashlib
for path in sorted((root/'sql/queries').glob('*.sql')):
 assert hashlib.sha256(path.read_bytes()).hexdigest()==evidence['query_sha256'][path.name]
 fields,current=query_rows(con,path.read_text())
 assert current==results[path.stem]['rows'],path.name
 assert fields==results[path.stem]['columns'],path.name
def close(a,b):
 if a is None or b is None:assert a is b,(a,b)
 else:assert math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-9),(a,b)
for run in old['runs']:
 actual=compute_summary_data(run['run'])
 for mode in actual['mode_rows']:
  sql=next(r for r in results['02_scenario_means']['rows'] if r['seed']==run['seed'] and r['scenario_key']==run['scenario'] and r['mode']==mode['mode'])
  close(sql['mean_time_s'],mode['avg_time_seconds']);close(sql['mean_distance_m'],mode['avg_distance_m'])
  checks.append({'run':run['run'],'mode':mode['mode'],'summary_match':True})
 for name,sha in run['artifact_sha256'].items():
  got=con.execute('SELECT sha256 FROM source_artifacts WHERE run_id=? AND relative_path LIKE ?',[run['run'],'%/'+name]).fetchone()
  assert got and got[0]==sha,(name,run['run'])
for row in results['03_paired_distribution']['rows']:
 before,after={'closure_vs_baseline':('baseline','closure'),'alternative_vs_baseline':('baseline','alternative'),'alternative_vs_closure':('closure','alternative')}[row['label']]
 ids={r['scenario']:r['run'] for r in old['runs'] if r['seed']==row['seed']}
 impact=analyze_impact(ids[before],ids[after])['trips']
 for field,other in [('mean_delta_s','mean'),('median_delta_s','median'),('p95_delta_s','p95')]:close(row[field],impact['delta_s'][other])
 assert row['paired_keys']==impact['paired_count']==934
 for b in results['04_change_bins']['rows']:
  if b['seed']==row['seed'] and b['label']==row['label']:
   assert b['trips']==impact[{'faster':'faster_count','slower':'slower_count','unchanged':'within_1s_count'}[b['change_bin']]]
 checks.append({'seed':row['seed'],'comparison':row['label'],'paired_impact_match':True})
assert all(r['issue_count']==0 for r in results['10_integrity']['rows'])
counts=evidence['table_counts'];con.close()
repeat=import_case(root/'output/analytics/matsim.duckdb');assert repeat==dict(imported_runs=0,skipped_runs=9)
with duckdb.connect(str(root/'output/analytics/matsim.duckdb'),read_only=True) as db:
 assert counts=={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in counts}
record={'release':'2026.10-p1','result':'passed','summary_comparisons':36,'paired_comparisons':9,'numeric_tolerance':{'relative':1e-12,'absolute':1e-9},'prior_p0_source_hashes_matched':27,'integrity_checks':results['10_integrity']['rows'],'idempotence':repeat,'table_counts_unchanged':counts,'checks':checks,'limitations':['Native parsers and event pairing are shared with the existing impact layer; this cross-check independently validates SQL aggregation, joins and percentiles, not an independent event parser.','No new simulation or external reviewer session was performed.']}
(root/'validation/2026-10-18-p1-sql.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({k:v for k,v in record.items() if k!='checks'},indent=2))

