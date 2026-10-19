-- Every issue_count must be zero for the accepted export.
WITH duplicate_groups AS (
 SELECT run_id,person_key,trip_number,count(*) n,bool_and(duplicate_key) all_flagged
 FROM trips WHERE key_valid GROUP BY ALL
), row_counts AS (SELECT run_id,count(*) n FROM trips GROUP BY run_id)
SELECT 'trip_row_count_mismatch' check_name,count(*) issue_count FROM runs r LEFT JOIN row_counts c USING(run_id) WHERE r.trip_rows<>coalesce(c.n,0)
UNION ALL SELECT 'unflagged_duplicate_keys',count(*) FROM duplicate_groups WHERE n>1 AND NOT all_flagged
UNION ALL SELECT 'orphan_trips',count(*) FROM trips t LEFT JOIN runs r USING(run_id) WHERE r.run_id IS NULL
UNION ALL SELECT 'invalid_time_semantics',count(*) FROM trips WHERE (time_status='valid')<>(travel_time_s IS NOT NULL) OR travel_time_s<0 OR NOT isfinite(travel_time_s)
UNION ALL SELECT 'invalid_distance_semantics',count(*) FROM trips WHERE (distance_status='valid')<>(distance_m IS NOT NULL) OR distance_m<0 OR NOT isfinite(distance_m)
UNION ALL SELECT 'case_plans_mismatch',count(*) FROM runs r JOIN cases c USING(case_id) WHERE r.plans_sha256<>c.plans_sha256
UNION ALL SELECT 'incomplete_seed_triplet',count(*) FROM (SELECT case_id,seed FROM runs GROUP BY ALL HAVING count(*)<>3 OR count(DISTINCT normalized_config_sha256)<>1)
UNION ALL SELECT 'missing_core_source_hash',count(*) FROM runs r CROSS JOIN (VALUES ('trips'),('events'),('network'),('config'),('plans')) k(artifact)
 LEFT JOIN source_artifacts s ON s.run_id=r.run_id AND s.artifact=k.artifact WHERE s.sha256 IS NULL OR length(s.sha256)<>64
ORDER BY check_name;
