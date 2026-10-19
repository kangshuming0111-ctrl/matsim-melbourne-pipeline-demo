-- Baseline-anchored car cohort; do not pool repeated seeds as independent people.
SELECT case_id,seed,label,count(*) eligible_keys,
 count(*) FILTER(WHERE pairing_status='unmatched') unmatched_keys,
 count(*) FILTER(WHERE pairing_status='invalid') invalid_pairs,
 count(*) FILTER(WHERE pairing_status='paired') paired_keys,
 count(*) FILTER(WHERE pairing_status='paired' AND before_mode<>after_mode) mode_switches,
 avg(delta_s) FILTER(WHERE pairing_status='paired') mean_delta_s,
 median(delta_s) FILTER(WHERE pairing_status='paired') median_delta_s,
 quantile_cont(delta_s,0.05) FILTER(WHERE pairing_status='paired') p05_delta_s,
 quantile_cont(delta_s,0.95) FILTER(WHERE pairing_status='paired') p95_delta_s,
 min(delta_s) FILTER(WHERE pairing_status='paired') min_delta_s,
 max(delta_s) FILTER(WHERE pairing_status='paired') max_delta_s
FROM paired_trips WHERE before_mode='car'
GROUP BY ALL ORDER BY case_id,label,seed;
