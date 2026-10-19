# SQL review entry point

Start with [the schema](schema.sql), then [the paired distribution](queries/03_paired_distribution.sql), [detour usage](queries/07_detour_usage.sql) and [ranked link changes](queries/08_link_changes.sql).

The full run commands, grain/keys, metric definitions, query guide, provenance and limitations are in [docs/ANALYTICS.md](../docs/ANALYTICS.md). There are ten checked-in analytical queries. Aggregate outputs are in `portfolio/evidence/sql/`; the person-level DuckDB stays in local `output/analytics/` and is not included in the shareable release.
