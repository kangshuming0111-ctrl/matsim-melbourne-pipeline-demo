-- Preserve invalid/missing rows; zero is a real observation.
SELECT r.case_id,r.seed,r.scenario_key,coalesce(t.mode,'[missing]') AS mode,
 count(*) AS row_count,count(t.travel_time_s) valid_time_rows,
 count(*) FILTER(WHERE time_status='missing') missing_time_rows,
 count(*) FILTER(WHERE time_status='invalid') invalid_time_rows,
 count(*) FILTER(WHERE travel_time_s=0) zero_time_rows,
 count(t.distance_m) valid_distance_rows,
 count(*) FILTER(WHERE distance_status='missing') missing_distance_rows,
 count(*) FILTER(WHERE distance_status='invalid') invalid_distance_rows,
 count(*) FILTER(WHERE NOT key_valid) invalid_key_rows,
 count(*) FILTER(WHERE duplicate_key) duplicate_key_rows,
 count(*) FILTER(WHERE departure_status<>'valid') bad_departure_rows
FROM runs r JOIN trips t USING(run_id)
GROUP BY ALL ORDER BY r.case_id,r.seed,r.scenario_key,mode;
