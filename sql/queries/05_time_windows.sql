-- Fixed descriptive windows, using before-scenario departure time.
WITH windows AS (
 SELECT *,CASE WHEN departure_s>=25200 AND departure_s<32400 THEN 'AM 07-09'
 WHEN departure_s>=57600 AND departure_s<64800 THEN 'PM 16-18' ELSE 'Other 00-30' END departure_window
 FROM paired_trips WHERE before_mode='car' AND pairing_status='paired'
)
SELECT case_id,seed,label,departure_window,count(*) trips,avg(delta_s) mean_delta_s,
 median(delta_s) median_delta_s,quantile_cont(delta_s,.95) p95_delta_s
FROM windows GROUP BY ALL ORDER BY case_id,label,seed,departure_window;
