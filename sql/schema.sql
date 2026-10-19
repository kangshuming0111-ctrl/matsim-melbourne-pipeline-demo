-- Local analytical store. Units: seconds, metres, and counts unless named otherwise.
CREATE TABLE IF NOT EXISTS analytics_meta(version INTEGER PRIMARY KEY);
INSERT INTO analytics_meta SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM analytics_meta);
CREATE TABLE IF NOT EXISTS cases (
 case_id VARCHAR PRIMARY KEY, spec_sha256 VARCHAR NOT NULL, plans_sha256 VARCHAR NOT NULL,
 description VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS scenarios (
 case_id VARCHAR REFERENCES cases(case_id), scenario_key VARCHAR, ordinal INTEGER NOT NULL,
 description VARCHAR NOT NULL, PRIMARY KEY(case_id, scenario_key)
);
CREATE TABLE IF NOT EXISTS runs (
 run_id VARCHAR PRIMARY KEY, case_id VARCHAR NOT NULL, scenario_key VARCHAR NOT NULL,
 seed INTEGER NOT NULL, fingerprint VARCHAR NOT NULL, importer_version VARCHAR NOT NULL,
 persons INTEGER NOT NULL, iterations INTEGER NOT NULL, trip_rows INTEGER NOT NULL,
 normalized_config_sha256 VARCHAR NOT NULL, plans_sha256 VARCHAR NOT NULL,
 event_quality_json VARCHAR NOT NULL, completion_json VARCHAR NOT NULL,
 imported_at TIMESTAMP DEFAULT current_timestamp,
 UNIQUE(case_id,seed,scenario_key),
 FOREIGN KEY(case_id,scenario_key) REFERENCES scenarios(case_id,scenario_key)
);
CREATE TABLE IF NOT EXISTS source_artifacts (
 run_id VARCHAR REFERENCES runs(run_id), artifact VARCHAR, relative_path VARCHAR NOT NULL,
 sha256 VARCHAR NOT NULL, bytes BIGINT NOT NULL, PRIMARY KEY(run_id,artifact)
);
CREATE TABLE IF NOT EXISTS trips (
 run_id VARCHAR REFERENCES runs(run_id), source_row INTEGER, person_key VARCHAR,
 trip_number INTEGER, key_valid BOOLEAN NOT NULL, duplicate_key BOOLEAN NOT NULL,
 mode VARCHAR, mode_fallback BOOLEAN NOT NULL,
 departure_s DOUBLE, departure_status VARCHAR NOT NULL,
 travel_time_s DOUBLE, time_status VARCHAR NOT NULL,
 distance_m DOUBLE, distance_status VARCHAR NOT NULL,
 observed_detour BOOLEAN NOT NULL, observed_closed_link BOOLEAN NOT NULL,
 PRIMARY KEY(run_id,source_row),
 CHECK (time_status IN ('valid','missing','invalid')),
 CHECK (distance_status IN ('valid','missing','invalid')),
 CHECK ((time_status='valid')=(travel_time_s IS NOT NULL)),
 CHECK ((distance_status='valid')=(distance_m IS NOT NULL)),
 CHECK (travel_time_s IS NULL OR (isfinite(travel_time_s) AND travel_time_s>=0)),
 CHECK (distance_m IS NULL OR (isfinite(distance_m) AND distance_m>=0))
);
CREATE TABLE IF NOT EXISTS link_metrics (
 run_id VARCHAR REFERENCES runs(run_id), link_id VARCHAR, from_node VARCHAR, to_node VARCHAR,
 length_m DOUBLE, freespeed_m_s DOUBLE, freeflow_s DOUBLE,
 car_allowed BOOLEAN, role VARCHAR, entered_count BIGINT, complete_count BIGINT,
 travel_time_sum_s DOUBLE, delay_sum_s DOUBLE,
 mean_travel_time_s DOUBLE, mean_delay_s DOUBLE,
 PRIMARY KEY(run_id,link_id),
 CHECK (role IN ('existing','added_road','split_existing')),
 CHECK (complete_count>=0 AND entered_count>=complete_count),
 CHECK ((complete_count=0)=(mean_travel_time_s IS NULL))
);
CREATE TABLE IF NOT EXISTS route_diagnostics (
 run_id VARCHAR REFERENCES runs(run_id), direction VARCHAR,
 start_node VARCHAR, end_node VARCHAR, route_kind VARCHAR,
 freeflow_s DOUBLE, distance_m DOUBLE, links INTEGER,
 PRIMARY KEY(run_id,direction,route_kind)
);

-- Keep malformed/duplicate keys in the raw analytical table for quality audits,
-- but exclude all occurrences of a duplicate key from pairing.
CREATE OR REPLACE VIEW usable_trip_keys AS
 SELECT * FROM trips WHERE key_valid AND NOT duplicate_key;

-- Baseline-anchored matching; travel mode changes are retained and counted.
-- The 0..30 h departure window matches the recorded strict impact review.
CREATE OR REPLACE VIEW paired_trips AS
 WITH comparisons(label,before_key,after_key) AS (VALUES
  ('closure_vs_baseline','baseline','closure'),
  ('alternative_vs_baseline','baseline','alternative'),
  ('alternative_vs_closure','closure','alternative'))
 SELECT rb.case_id,rb.seed,c.label,rb.run_id before_run,ra.run_id after_run,
  b.person_key,b.trip_number,b.mode before_mode,a.mode after_mode,
  b.departure_s,b.travel_time_s before_s,a.travel_time_s after_s,
  a.travel_time_s-b.travel_time_s delta_s,
  b.distance_m before_distance_m,a.distance_m after_distance_m,
  a.distance_m-b.distance_m distance_delta_m,
  a.observed_detour,
  CASE WHEN a.source_row IS NULL THEN 'unmatched'
       WHEN b.travel_time_s IS NULL OR a.travel_time_s IS NULL
        OR a.departure_s IS NULL OR a.mode IS NULL THEN 'invalid'
       ELSE 'paired' END pairing_status
 FROM comparisons c
 JOIN runs rb ON rb.scenario_key=c.before_key
 JOIN runs ra ON ra.case_id=rb.case_id AND ra.seed=rb.seed AND ra.scenario_key=c.after_key
 JOIN usable_trip_keys b ON b.run_id=rb.run_id
 LEFT JOIN usable_trip_keys a ON a.run_id=ra.run_id AND a.person_key=b.person_key AND a.trip_number=b.trip_number
 WHERE b.departure_s>=0 AND b.departure_s<108000 AND b.mode IS NOT NULL;
