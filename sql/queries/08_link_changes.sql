-- Like-for-like link geometry only; changing users still limit causal interpretation.
WITH comparisons(label,before_key,after_key) AS (VALUES
 ('closure_vs_baseline','baseline','closure'),('alternative_vs_closure','closure','alternative')),
 matched AS (
 SELECT rb.case_id,rb.seed,c.label,b.link_id,b.from_node,b.to_node,b.length_m,
 b.complete_count before_traversals,a.complete_count after_traversals,
 b.mean_travel_time_s before_mean_s,a.mean_travel_time_s after_mean_s,
 a.mean_travel_time_s-b.mean_travel_time_s delta_mean_s,
 a.complete_count-b.complete_count delta_traversals
 FROM comparisons c JOIN runs rb ON rb.scenario_key=c.before_key
 JOIN runs ra ON ra.case_id=rb.case_id AND ra.seed=rb.seed AND ra.scenario_key=c.after_key
 JOIN link_metrics b ON b.run_id=rb.run_id
 JOIN link_metrics a ON a.run_id=ra.run_id AND a.link_id=b.link_id
 WHERE b.role='existing' AND a.role='existing' AND b.car_allowed AND a.car_allowed
 AND b.from_node=a.from_node AND b.to_node=a.to_node AND abs(b.length_m-a.length_m)<1e-6
 AND abs(b.freespeed_m_s-a.freespeed_m_s)<1e-9 AND a.complete_count>0 AND b.complete_count>0
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY case_id,seed,label ORDER BY abs(delta_mean_s) DESC,link_id) magnitude_rank
 FROM matched
)
SELECT * FROM ranked WHERE magnitude_rank<=5 ORDER BY case_id,label,seed,magnitude_rank;
