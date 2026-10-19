-- Raw scenario means have separate valid denominators, not paired cohorts.
WITH means AS (
 SELECT r.case_id,r.seed,r.scenario_key,t.mode,count(*) trips,
 count(t.travel_time_s) valid_time_rows,avg(t.travel_time_s) mean_time_s,
 count(t.distance_m) valid_distance_rows,avg(t.distance_m) mean_distance_m
 FROM runs r JOIN trips t USING(run_id) GROUP BY ALL
 UNION ALL
 SELECT r.case_id,r.seed,r.scenario_key,'ALL',count(*),count(t.travel_time_s),
 avg(t.travel_time_s),count(t.distance_m),avg(t.distance_m)
 FROM runs r JOIN trips t USING(run_id) GROUP BY r.case_id,r.seed,r.scenario_key
)
SELECT a.*,a.mean_time_s-b.mean_time_s change_from_baseline_s,
 100*(a.mean_time_s-b.mean_time_s)/nullif(b.mean_time_s,0) change_from_baseline_pct
FROM means a JOIN means b ON a.case_id=b.case_id AND a.seed=b.seed AND a.mode=b.mode AND b.scenario_key='baseline'
ORDER BY a.case_id,a.seed,a.mode,a.scenario_key;
