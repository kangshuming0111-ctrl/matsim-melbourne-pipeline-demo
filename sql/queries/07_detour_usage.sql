-- Link traversals are NOT trip counts; split-existing links are excluded.
WITH road AS (
 SELECT run_id,count(*) added_links,count(*) FILTER(WHERE complete_count>0) used_added_links,
 sum(entered_count) entered_link_traversals,sum(complete_count) complete_link_traversals,
 sum(travel_time_sum_s)/nullif(sum(complete_count),0) weighted_link_travel_s,
 sum(delay_sum_s)/nullif(sum(complete_count),0) weighted_link_delay_s
 FROM link_metrics WHERE role='added_road' AND car_allowed GROUP BY run_id
), usage AS (
 SELECT run_id,count(*) FILTER(WHERE mode='car' AND key_valid AND NOT duplicate_key) car_trips,
 count(*) FILTER(WHERE observed_detour) observed_detour_trips
 FROM trips GROUP BY run_id
)
SELECT r.case_id,r.seed,r.scenario_key,u.car_trips,u.observed_detour_trips,
 100.*u.observed_detour_trips/nullif(u.car_trips,0) observed_detour_pct,
 d.* EXCLUDE(run_id)
FROM runs r JOIN usage u USING(run_id) JOIN road d USING(run_id)
ORDER BY r.case_id,r.seed;
