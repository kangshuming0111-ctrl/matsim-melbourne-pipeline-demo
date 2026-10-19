-- Mutually exclusive: faster <= -1 s; unchanged (-1,+1); slower >= +1 s.
WITH classified AS (
 SELECT *,CASE WHEN delta_s<=-1 THEN 'faster' WHEN delta_s>=1 THEN 'slower' ELSE 'unchanged' END change_bin
 FROM paired_trips WHERE before_mode='car' AND pairing_status='paired'
)
SELECT case_id,seed,label,change_bin,count(*) trips,sum(delta_s) total_delta_s,
 avg(delta_s) mean_delta_s,min(delta_s) min_delta_s,max(delta_s) max_delta_s
FROM classified GROUP BY ALL ORDER BY case_id,label,seed,change_bin;
