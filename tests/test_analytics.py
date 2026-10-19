import copy,csv,gzip,json,tempfile,unittest
from pathlib import Path
from wrapper import analytics as a
from scripts.analytics import export
try: import duckdb
except ImportError: duckdb=None

class TripImportTests(unittest.TestCase):
 def parse(self,body):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'trips.csv.gz'
   with gzip.open(path,'wt') as f:f.write('person;trip_number;dep_time;trav_time;traveled_distance;main_mode\n'+body)
   return a.trip_rows(path,'r')
 def test_null_zero_invalid_and_extended_time(self):
  rows=self.parse('a;1;25:00:00;0;0;car\nb;1;1;;;car\nc;1;1;NaN;-1;car\n')
  self.assertEqual([r['time_status'] for r in rows],['valid','missing','invalid'])
  self.assertEqual([r['distance_status'] for r in rows],['valid','missing','invalid'])
  self.assertEqual(rows[0]['departure_s'],90000)
  self.assertEqual(rows[0]['travel_time_s'],0)
 def test_all_duplicate_occurrences_excluded_but_retained(self):
  rows=self.parse('a;1;0;10;100;car\na;1;0;20;200;car\na;2;0;10;100;car\n;1;0;10;100;car\n')
  self.assertEqual([r['duplicate_key'] for r in rows],[True,True,False,False])
  self.assertFalse(rows[-1]['key_valid'])
 def test_bad_headers_fail_closed(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'bad.gz'
   with gzip.open(path,'wt') as f:f.write('person;trav_time\na;10\n')
   with self.assertRaises(ValueError):a.trip_rows(path,'r')
 def test_extra_column_is_invalid(self):
  self.assertEqual(self.parse('a;1;0;10;100;car;unexpected\n')[0]['time_status'],'invalid')
 def test_shortest_path_car_and_added_road_restriction(self):
  def edge(x,y,c,role='existing',car=True):return dict(from_node=x,to_node=y,freeflow_s=c,length_m=c*10,role=role,car_allowed=car)
  links=[edge('a','b',2),edge('b','c',3),edge('a','c',9,'added_road'),edge('a','c',1,car=False)]
  self.assertEqual(a.shortest_path(links,'a','c'),(5,50,2))
  self.assertEqual(a.shortest_path(links,'a','c',only_added=True),(9,90,1))
  self.assertEqual(a.shortest_path(links,'c','a'),(None,None,None))

@unittest.skipUnless(duckdb,'optional analytics dependencies not installed')
class AnalyticsDatabaseTests(unittest.TestCase):
 def setUp(self):
  self.db=duckdb.connect(':memory:');self.addCleanup(self.db.close)
  self.case=dict(case_id='fixture',spec_sha256='s'*64,plans_sha256='p'*64,description='fixture')
  self.prepared=[dict(run_id=s,stage=s,seed=1,fingerprint=s) for s in a.STAGES]
 def extractor(self,p):
  run=dict(run_id=p['run_id'],case_id='fixture',scenario_key=p['stage'],seed=1,fingerprint=p['fingerprint'],importer_version='fixture',persons=3,iterations=10,trip_rows=0,normalized_config_sha256='n'*64,plans_sha256='p'*64,event_quality_json='{}',completion_json='{}')
  return dict(run=run,trips=[],link_metrics=[],route_diagnostics=[],source_artifacts=[])
 def row(self,run,key,time,number=1,duplicate=False,mode='car',distance=100):
  return dict(run_id=run,source_row=number,person_key=key,trip_number=1,key_valid=True,duplicate_key=duplicate,mode=mode,mode_fallback=False,departure_s=3600,departure_status='valid',travel_time_s=time,time_status='valid' if time is not None else 'missing',distance_m=distance,distance_status='valid' if distance is not None else 'missing',observed_detour=False,observed_closed_link=False)
 def load(self):return a.import_prepared(self.db,self.case,self.prepared,self.extractor)
 def test_idempotent_import_does_not_extract_again(self):
  self.assertEqual(self.load(),dict(imported_runs=3,skipped_runs=0))
  def fail(p):raise AssertionError('should skip')
  self.assertEqual(a.import_prepared(self.db,self.case,self.prepared,fail),dict(imported_runs=0,skipped_runs=3))
  self.assertEqual(self.db.execute('select count(*) from runs').fetchone()[0],3)
 def test_changed_fingerprint_refused(self):
  self.load();changed=copy.deepcopy(self.prepared);changed[1]['fingerprint']='changed'
  with self.assertRaisesRegex(ValueError,'changed'):a.import_prepared(self.db,self.case,changed,self.extractor)
  self.assertEqual(self.db.execute('select count(*) from runs').fetchone()[0],3)
 def test_changed_case_refused(self):
  self.load()
  with self.assertRaisesRegex(ValueError,'Case sources'):a.import_prepared(self.db,dict(self.case,spec_sha256='changed'),self.prepared,self.extractor)
 def test_batch_rolls_back_after_midway_failure(self):
  def fail(p):
   if p['stage']=='closure':raise ValueError('simulated extraction failure')
   return self.extractor(p)
  with self.assertRaises(ValueError):a.import_prepared(self.db,self.case,self.prepared,fail)
  self.assertEqual(self.db.execute('select count(*) from runs').fetchone()[0],0)
  self.assertEqual(self.db.execute('select count(*) from cases').fetchone()[0],0)
 def test_count_mismatch_rolls_back(self):
  def wrong(p):
   result=self.extractor(p);result['run']['trip_rows']=2;return result
  with self.assertRaisesRegex(ValueError,'Trip count'):a.import_prepared(self.db,self.case,self.prepared,wrong)
  self.assertEqual(self.db.execute('select count(*) from runs').fetchone()[0],0)
 def test_pairing_handles_missing_proposal_duplicate_and_mode_switch(self):
  self.load()
  a.bulk_insert(self.db,'trips',[self.row('baseline','a',10),self.row('baseline','b',20,2),self.row('baseline','c',30,3),self.row('baseline','d',0,4),self.row('closure','a',15,mode='walk'),self.row('closure','b',None,2),self.row('closure','c',50,3,True),self.row('closure','c',60,4,True),self.row('closure','d',0,5)])
  got=self.db.execute("select person_key,pairing_status,delta_s,after_mode from paired_trips where label='closure_vs_baseline' order by person_key").fetchall()
  self.assertEqual(got,[('a','paired',5,'walk'),('b','invalid',None,'car'),('c','unmatched',None,None),('d','paired',0,'car')])
  rows=self.db.execute((a.ROOT/'sql/queries/03_paired_distribution.sql').read_text()).fetchall()
  columns=[c[0] for c in self.db.description];record=next(dict(zip(columns,r)) for r in rows if r[2]=='closure_vs_baseline')
  self.assertEqual((record['paired_keys'],record['unmatched_keys'],record['mode_switches'],record['mean_delta_s'],record['p95_delta_s']),(2,1,1,2.5,4.75))
 def test_sql_means_keep_nulls_and_real_zero(self):
  self.load();a.bulk_insert(self.db,'trips',[self.row('baseline','a',90,distance=None),self.row('baseline','b',None,2,distance=1000),self.row('baseline','c',0,3,distance=0)])
  row=self.db.execute("select avg(travel_time_s),count(travel_time_s),avg(distance_m),count(distance_m) from trips").fetchone()
  self.assertEqual(row,(45,2,500,2))
 def test_constraints_reject_orphan_and_bad_measurements(self):
  self.load()
  with self.assertRaises(duckdb.ConstraintException):a.bulk_insert(self.db,'trips',[self.row('unknown','a',10)])
  with self.assertRaises(duckdb.ConstraintException):a.bulk_insert(self.db,'trips',[self.row('baseline','a',-1)])
 def test_every_review_query_executes_and_keeps_individual_keys_private(self):
  self.load()
  paths=list((a.ROOT/'sql/queries').glob('*.sql'));self.assertEqual(len(paths),10)
  for path in paths:
   self.db.execute(path.read_text()).fetchall()
   self.assertNotIn('person_key',[c[0] for c in self.db.description])
 def test_integrity_query_detects_row_count_mismatch(self):
  self.load();a.bulk_insert(self.db,'trips',[self.row('baseline','a',10)])
  checks=dict(self.db.execute((a.ROOT/'sql/queries/10_integrity.sql').read_text()).fetchall())
  self.assertEqual(checks['trip_row_count_mismatch'],1)
 def test_usage_aggregates_do_not_multiply_trips_by_links(self):
  self.load();one=self.row('alternative','a',10);one['observed_detour']=True
  a.bulk_insert(self.db,'trips',[one,self.row('alternative','b',20,2)])
  def link(key,n,role):return dict(run_id='alternative',link_id=key,from_node='x',to_node='y',length_m=10,freespeed_m_s=1,freeflow_s=10,car_allowed=True,role=role,entered_count=n,complete_count=n,travel_time_sum_s=n*12,delay_sum_s=n*2,mean_travel_time_s=12,mean_delay_s=2)
  a.bulk_insert(self.db,'link_metrics',[link('new1',2,'added_road'),link('new2',3,'added_road'),link('split',100,'split_existing')])
  cursor=self.db.execute((a.ROOT/'sql/queries/07_detour_usage.sql').read_text());record=dict(zip([r[0] for r in cursor.description],cursor.fetchone()))
  self.assertEqual((record['car_trips'],record['observed_detour_trips'],record['complete_link_traversals'],record['weighted_link_travel_s']),(2,1,5,12))
 def test_cohort_window_is_before_anchored_and_half_open(self):
  self.load();rows=[]
  for i,time in enumerate([0,107999,108000],1):
   before=self.row('baseline',str(i),10,i);before['departure_s']=time
   after=self.row('closure',str(i),20,i);after['departure_s']=120000
   rows.extend([before,after])
  a.bulk_insert(self.db,'trips',rows)
  self.assertEqual(self.db.execute("select count(*) from paired_trips where label='closure_vs_baseline' and pairing_status='paired'").fetchone()[0],2)
 def test_export_refuses_overwrite(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(FileExistsError):export(Path(d)/'unused.duckdb',Path(d))

if __name__=='__main__':unittest.main()
