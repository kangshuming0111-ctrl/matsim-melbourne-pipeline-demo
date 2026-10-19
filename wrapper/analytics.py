"""Transactional DuckDB ingestion of immutable completed MATSim case evidence.

Only the optional analytics command imports DuckDB. The local simulator/API
continues to work without it. Source trip/event files are never changed.
"""
from __future__ import annotations
import csv
import gzip
import hashlib
import heapq
import json
import math
import tempfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

from wrapper.measurements import parse_time, nonnegative_number, trip_mode
from wrapper.ifline import resolve_run_assets
from wrapper.provenance import sha256_file
# Internal, already-tested evidence readers; no new event-pairing implementation.
from wrapper.impact import _artifacts, _config, _verify_input_path, _network, _trips, _events

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_CASE='cbd_expanded1037_detour_10it_review_r02'
IMPORTER_VERSION='1.0'
STAGES=('baseline','closure','alternative')

def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def measurement(value,parser):
    if value is None or not str(value).strip():return None,'missing'
    parsed=parser(value)
    return (parsed,'valid') if parsed is not None else (None,'invalid')

def trip_rows(path:Path,run_id:str):
    with gzip.open(path,'rt',encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream,delimiter=';')
        fields=reader.fieldnames or []
        required={'person','trip_number','dep_time','trav_time','traveled_distance'}
        if len(fields)!=len(set(fields)) or not required<=set(fields) or not {'main_mode','modes'}&set(fields):
            raise ValueError('Trip headers missing or duplicated')
        rows=[]
        for line,row in enumerate(reader,start=2):
            person=row.get('person')
            person=person if person and person.strip() else None
            try:
                number=int(row.get('trip_number') or '')
                if number<1:raise ValueError
            except (ValueError,TypeError):number=None
            mode,fallback=trip_mode(row)
            departure,departure_status=measurement(row.get('dep_time'),parse_time)
            duration,time_status=measurement(row.get('trav_time'),parse_time)
            distance,distance_status=measurement(row.get('traveled_distance'),nonnegative_number)
            if None in row:
                duration,distance=None,None
                time_status=distance_status='invalid'
            rows.append({'run_id':run_id,'source_row':line,'person_key':person,
                'trip_number':number,'key_valid':person is not None and number is not None,
                'duplicate_key':False,'mode':mode,'mode_fallback':fallback,
                'departure_s':departure,'departure_status':departure_status,
                'travel_time_s':duration,'time_status':time_status,
                'distance_m':distance,'distance_status':distance_status,
                'observed_detour':False,'observed_closed_link':False})
    keys=Counter((r['person_key'],r['trip_number']) for r in rows if r['key_valid'])
    for row in rows:row['duplicate_key']=row['key_valid'] and keys[row['person_key'],row['trip_number']]>1
    return rows

def shortest_path(links,origin,destination,*,only_added=False):
    adjacency={}
    for link in links:
        if not link['car_allowed'] or (only_added and link['role']!='added_road'):continue
        adjacency.setdefault(link['from_node'],[]).append(link)
    queue=[(0.,0.,0,origin)];best={origin:0.}
    while queue:
        cost,distance,count,node=heapq.heappop(queue)
        if cost!=best[node]:continue
        if node==destination:return cost,distance,count
        for link in adjacency.get(node,[]):
            candidate=cost+link['freeflow_s'];target=link['to_node']
            if candidate<best.get(target,math.inf):
                best[target]=candidate
                heapq.heappush(queue,(candidate,distance+link['length_m'],count+1,target))
    return None,None,None

def prepare_case(case_id=DEFAULT_CASE):
    if Path(case_id).name!=case_id or '..' in case_id:raise ValueError('Invalid case id')
    directory=ROOT/'output/planning_cases'/case_id
    spec_path=directory/'case_spec.json';manifest_path=directory/'case_manifest.json'
    spec=json.loads(spec_path.read_text());manifest=json.loads(manifest_path.read_text())
    if manifest['status']!='completed':raise ValueError('Case must be completed')
    case={'case_id':case_id,'spec_sha256':sha256_file(spec_path),
          'plans_sha256':spec['inputs']['plans_file']['sha256'],
          'description':'Fixed synthetic population: baseline / closure / closure plus geometric detour'}
    prepared=[]
    for group in manifest['rows']:
        seed=group['seed'];configs=[]
        for stage in STAGES:
            completed=[a for a in group['stages'][stage]['attempts'] if a['status']=='completed']
            if len(completed)!=1:raise ValueError('Require exactly one completed attempt per stage')
            attempt=completed[0];result_ref=attempt['result'];result_path=ROOT/result_ref['path']
            if sha256_file(result_path)!=result_ref['sha256']:raise ValueError('Case result fingerprint changed')
            run_id=attempt['run_id']+'_sim'
            assets=resolve_run_assets(run_id)
            files=_artifacts(assets)
            files.update(persons=Path(assets['sim_dir'])/'output_persons.csv.gz',
                         scorestats=Path(assets['sim_dir'])/'scorestats.txt',case_spec=spec_path,case_result=result_path)
            normalized,params=_config(files['config']);configs.append(normalized)
            for key,artifact in [('inputPlansFile','plans'),('inputNetworkFile','input_network')]:
                module='plans' if artifact=='plans' else 'network'
                _verify_input_path(params[module,key],files[artifact],Path(assets['sim_dir']))
            if int(params['global','randomSeed'])!=seed:raise ValueError('Seed mismatch')
            sources=[{'run_id':run_id,'artifact':kind,'relative_path':path.relative_to(ROOT).as_posix(),
                      'sha256':sha256_file(path),'bytes':path.stat().st_size} for kind,path in files.items()]
            if next(x['sha256'] for x in sources if x['artifact']=='plans')!=case['plans_sha256']:
                raise ValueError('Input plans differ from the case')
            stamp={k:(p.stat().st_size,p.stat().st_mtime_ns) for k,p in files.items()}
            compiler_hashes={name:sha256_file(ROOT/name) for name in ('wrapper/analytics.py','wrapper/measurements.py','wrapper/impact.py','sql/schema.sql')}
            fingerprint=canonical_hash({'sources':sources,'importer':compiler_hashes,'case':case,'seed':seed,'stage':stage})
            prepared.append({'case':case,'run_id':run_id,'stage':stage,'seed':seed,'files':files,'sources':sources,
                'fingerprint':fingerprint,'stamps':stamp,'normalized_sha':canonical_hash(normalized),'spec':spec})
        if not all(c==configs[0] for c in configs):raise ValueError('Within-seed configuration mismatch')
    if {p['seed'] for p in prepared}!=set(spec['seeds']):raise ValueError('Seed set mismatch')
    return case,prepared

def extract_run(prepared):
    p=prepared;files=p['files'];run_id=p['run_id']
    network=_network(files['network']);strict_trips=_trips(files['trips'])
    with gzip.open(files['network'],'rb') if files['network'].suffix=='.gz' else files['network'].open('rb') as stream:
        xml=ET.parse(stream).getroot()
    mode_map={link.get('id'):link.get('modes','').split(',') for link in xml.findall('./links/link')}
    added={key for key in network if key.startswith('ifplan_road_')}
    if p['stage']=='alternative' and not added:raise ValueError('Alternative has no recorded added-road links')
    closed={item['id'] for item in p['spec']['geometry']['closure_links']}&network.keys()
    stats,hits,completion,quality=_events(files['events'],network,strict_trips,added,{'car'},0,108000)
    _,closed_hits,_,_=_events(files['events'],network,strict_trips,closed,{'car'},0,108000)
    trips=trip_rows(files['trips'],run_id)
    for trip in trips:
        key=trip['person_key'],trip['trip_number']
        # Membership means an observed complete traversal; absence is not proof of no route use.
        usable=trip['key_valid'] and not trip['duplicate_key'] and trip['mode']=='car'
        trip['observed_detour']=usable and key in hits
        trip['observed_closed_link']=usable and key in closed_hits
    links=[]
    for key,link in network.items():
        observed=stats.get(key)
        complete=observed.complete if observed else 0
        links.append({'run_id':run_id,'link_id':key,'from_node':link['from'],'to_node':link['to'],
            'length_m':link['length_m'],'freespeed_m_s':link['freespeed_m_s'],'freeflow_s':link['freeflow_s'],
            'car_allowed':'car' in mode_map[key],
            'role':'added_road' if key in added else 'split_existing' if key.startswith('ifplan_split_') else 'existing',
            'entered_count':observed.entered if observed else 0,'complete_count':complete,
            'travel_time_sum_s':observed.travel if complete else None,'delay_sum_s':observed.delay if complete else None,
            'mean_travel_time_s':observed.travel/complete if complete else None,
            'mean_delay_s':observed.delay/complete if complete else None})
    endpoints=p['spec']['geometry']['alternative_endpoint_nodes'];routes=[]
    for direction,(origin,destination) in [('forward',endpoints),('reverse',endpoints[::-1])]:
        for kind,restricted in [('shortest_network',False),('added_road_only',True)]:
            cost,distance,count=shortest_path(links,origin,destination,only_added=restricted)
            routes.append({'run_id':run_id,'direction':direction,'start_node':origin,'end_node':destination,
                'route_kind':kind,'freeflow_s':cost,'distance_m':distance,'links':count})
    with gzip.open(files['persons'],'rt') as stream:persons=sum(1 for _ in csv.DictReader(stream,delimiter=';'))
    with files['scorestats'].open() as stream:iterations=sum(1 for _ in csv.DictReader(stream,delimiter='\t'))
    for kind,path in files.items():
        if (path.stat().st_size,path.stat().st_mtime_ns)!=p['stamps'][kind]:raise ValueError('Source changed during ingestion')
    run={'run_id':run_id,'case_id':p['case']['case_id'],'scenario_key':p['stage'],'seed':p['seed'],
        'fingerprint':p['fingerprint'],'importer_version':IMPORTER_VERSION,'persons':persons,'iterations':iterations,
        'trip_rows':len(trips),'normalized_config_sha256':p['normalized_sha'],'plans_sha256':p['case']['plans_sha256'],
        'event_quality_json':json.dumps(quality),'completion_json':json.dumps(completion)}
    return {'run':run,'trips':trips,'link_metrics':links,'route_diagnostics':routes,'source_artifacts':p['sources']}

def initialize(connection):
    connection.execute((ROOT/'sql/schema.sql').read_text())
    if connection.execute('SELECT version FROM analytics_meta').fetchall()!=[(1,)]:raise ValueError('Unsupported analytics schema version')

def bulk_insert(connection,table,rows):
    if table not in {'trips','link_metrics','route_diagnostics','source_artifacts'}:raise ValueError('Invalid table')
    if not rows:return
    columns=list(rows[0]);types={r[1]:r[2] for r in connection.execute(f"PRAGMA table_info('{table}')").fetchall()}
    if set(columns)!=set(types):raise ValueError('Column mismatch')
    with tempfile.TemporaryDirectory(prefix='matsim-sql-stage-') as temporary:
        path=Path(temporary)/'rows.csv'
        with path.open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader();writer.writerows(rows)
        quoted=','.join('"'+key+'"' for key in columns)
        type_sql='{'+','.join("'"+key+"':'"+types[key]+"'" for key in columns)+'}'
        connection.execute(f'INSERT INTO {table} ({quoted}) SELECT {quoted} FROM read_csv(?, header=true, nullstr=\'\', columns={type_sql})',[str(path)])

def import_prepared(connection,case,prepared,extractor=extract_run):
    """One case batch is atomic. Same fingerprint skips; changed sources are refused."""
    initialize(connection)
    connection.execute('BEGIN TRANSACTION')
    imported=skipped=0
    try:
        existing=connection.execute('SELECT spec_sha256,plans_sha256 FROM cases WHERE case_id=?',[case['case_id']]).fetchone()
        if existing and existing!=(case['spec_sha256'],case['plans_sha256']):raise ValueError('Case sources changed; use a new database or case revision')
        if not existing:
            connection.execute('INSERT INTO cases VALUES (?,?,?,?)',list(case.values()))
            for ordinal,stage in enumerate(STAGES):
                connection.execute('INSERT INTO scenarios VALUES (?,?,?,?)',[case['case_id'],stage,ordinal,stage.replace('_',' ')])
        for p in prepared:
            old=connection.execute('SELECT fingerprint FROM runs WHERE run_id=?',[p['run_id']]).fetchone()
            if old:
                if old[0]!=p['fingerprint']:raise ValueError('Run sources or importer changed; create a new database revision')
                skipped+=1;continue
            snapshot=extractor(p);run=snapshot['run']
            columns=','.join(run);markers=','.join('?' for _ in run)
            connection.execute(f'INSERT INTO runs ({columns}) VALUES ({markers})',list(run.values()))
            for table in ('trips','link_metrics','route_diagnostics','source_artifacts'):bulk_insert(connection,table,snapshot[table])
            actual=connection.execute('SELECT count(*) FROM trips WHERE run_id=?',[p['run_id']]).fetchone()[0]
            if actual!=run['trip_rows']:raise ValueError('Trip count mismatch')
            imported+=1
        connection.execute('COMMIT')
    except BaseException:
        connection.execute('ROLLBACK');raise
    return {'imported_runs':imported,'skipped_runs':skipped}

def import_case(database:Path,case_id=DEFAULT_CASE):
    import duckdb
    database.parent.mkdir(parents=True,exist_ok=True)
    case,prepared=prepare_case(case_id)
    with duckdb.connect(str(database)) as connection:return import_prepared(connection,case,prepared)
