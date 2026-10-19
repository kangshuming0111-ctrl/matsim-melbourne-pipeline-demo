-- Detour usage is selected AFTER treatment: association, not a causal subgroup effect.
WITH cohorts AS (
 SELECT p.*,'Observed added-road use in alternative' cohort_type,
 CASE WHEN p.observed_detour THEN 'observed' ELSE 'not observed' END cohort
 FROM paired_trips p WHERE p.label='alternative_vs_closure'
 UNION ALL
 SELECT p.*,'Observed closed-link use in baseline',
 CASE WHEN t.observed_closed_link THEN 'observed' ELSE 'not observed' END
 FROM paired_trips p JOIN runs r ON r.case_id=p.case_id AND r.seed=p.seed AND r.scenario_key='baseline'
 JOIN usable_trip_keys t ON t.run_id=r.run_id AND t.person_key=p.person_key AND t.trip_number=p.trip_number
)
SELECT case_id,seed,label,cohort_type,cohort,count(*) trips,avg(delta_s) mean_delta_s,
 sum(delta_s) total_delta_s,
 count(*) FILTER(WHERE delta_s<=-1) faster,count(*) FILTER(WHERE delta_s>=1) slower,
 count(*) FILTER(WHERE abs(delta_s)<1) unchanged,
 avg(distance_delta_m) mean_distance_delta_m
FROM cohorts WHERE before_mode='car' AND pairing_status='paired'
GROUP BY ALL ORDER BY case_id,label,cohort_type,seed,cohort;
