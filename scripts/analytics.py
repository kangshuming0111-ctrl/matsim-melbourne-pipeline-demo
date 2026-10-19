"""Local analytical database and aggregate SQL exports; no simulation is started."""
import argparse,csv,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from wrapper.analytics import ROOT,DEFAULT_CASE,import_case

def query_rows(connection,query):
    cursor=connection.execute(query)
    fields=[col[0] for col in cursor.description]
    return fields,[dict(zip(fields,row)) for row in cursor.fetchall()]

def export(database,destination):
    import duckdb
    if destination.exists():raise FileExistsError('Choose a new export directory')
    results={};hashes={}
    with duckdb.connect(str(database),read_only=True) as connection:
        for path in sorted((ROOT/'sql/queries').glob('*.sql')):
            fields,rows=query_rows(connection,path.read_text())
            results[path.stem]={'columns':fields,'rows':rows}
            hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        if not results:raise ValueError('No checked-in SQL queries found')
        _,provenance=query_rows(connection,"SELECT r.run_id,r.case_id,r.seed,r.scenario_key,r.fingerprint,r.normalized_config_sha256,r.plans_sha256,s.artifact,s.relative_path,s.sha256,s.bytes FROM runs r JOIN source_artifacts s USING(run_id) ORDER BY r.run_id,s.artifact")
        _,event_quality=query_rows(connection,"SELECT run_id,event_quality_json,completion_json FROM runs ORDER BY run_id")
        counts={name:connection.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in ('runs','trips','link_metrics','source_artifacts')}
    destination.mkdir(parents=True)
    for name,result in results.items():
        with (destination/(name+'.csv')).open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=result['columns']);writer.writeheader();writer.writerows(result['rows'])
    evidence={'release':'2026.10-p1','created_at_utc':datetime.now(timezone.utc).isoformat(),
        'scope':'Aggregate-only SQL export of saved simulations; no new simulation, no individual rows',
        'duckdb_version':duckdb.__version__,'table_counts':counts,'query_sha256':hashes,'source_provenance':provenance,'event_diagnostics':event_quality,'results':results}
    (destination/'sql-evidence.json').write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n')
    return counts

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['import','export','query'])
    parser.add_argument('--database',type=Path,default=ROOT/'output/analytics/matsim.duckdb')
    parser.add_argument('--case',default=DEFAULT_CASE)
    parser.add_argument('--destination',type=Path)
    parser.add_argument('--name',help='A checked-in SQL query stem, e.g. 03_paired_distribution')
    args=parser.parse_args()
    if args.command=='import':result=import_case(args.database,args.case)
    elif args.command=='export':
        if args.destination is None:parser.error('--destination required')
        result=export(args.database,args.destination)
    else:
        import duckdb
        allowed={p.stem:p for p in (ROOT/'sql/queries').glob('*.sql')}
        if args.name not in allowed:parser.error('--name must be a checked-in query stem')
        with duckdb.connect(str(args.database),read_only=True) as connection:
            _,result=query_rows(connection,allowed[args.name].read_text())
    print(json.dumps(result,indent=2,default=str))

if __name__=='__main__':main()
