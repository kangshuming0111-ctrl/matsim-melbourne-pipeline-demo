-- Same endpoints in every scenario. Static free-flow costs, not observed whole trips.
SELECT r.case_id,r.seed,d.direction,d.start_node,d.end_node,
 max(d.freeflow_s) FILTER(WHERE r.scenario_key='baseline' AND d.route_kind='shortest_network') baseline_shortest_s,
 max(d.freeflow_s) FILTER(WHERE r.scenario_key='closure' AND d.route_kind='shortest_network') closure_shortest_s,
 max(d.freeflow_s) FILTER(WHERE r.scenario_key='alternative' AND d.route_kind='shortest_network') alternative_shortest_s,
 max(d.freeflow_s) FILTER(WHERE r.scenario_key='alternative' AND d.route_kind='added_road_only') added_corridor_s,
 max(d.distance_m) FILTER(WHERE r.scenario_key='alternative' AND d.route_kind='added_road_only') added_corridor_m
FROM route_diagnostics d JOIN runs r USING(run_id)
GROUP BY r.case_id,r.seed,d.direction,d.start_node,d.end_node ORDER BY ALL;
