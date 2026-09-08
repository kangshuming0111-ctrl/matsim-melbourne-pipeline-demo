# Data preparation

The public repository does not include complete source datasets or generated
simulation outputs. This keeps the repository small and avoids redistributing
data whose terms and provenance must be checked separately.

## Required for the fixed CBD demo

Place the following under the project-level `data/` directory.

### Road network

- `geofabrik_victoria-latest.osm.pbf`

Obtain the Victoria OpenStreetMap extract from Geofabrik and retain its source
attribution and applicable OpenStreetMap/ODbL notices. The fixed demo requires
this exact local filename so it cannot silently fall back to a whole-Australia
download.

### Demand-generation inputs

The upstream demand project documents its ABS 2016 and VISTA 2012–18 derived
data package in `vendor/demand/data/README.md`. The current preflight expects:

```text
VISTA_12_18_CSV.zip.dir/T_VISTA1218_V1.csv
absRegionsReprojected.sqlite
distanceMatrix.rds
distanceMatrixIndex.csv
SA1attributed.csv.gz
SA1centroids.csv.gz
addresses.csv.gz
vistaCohorts.csv.gz
expectedDistances.rds
vistaSummaries/destinationProbabilitiesSA3.rds
vistaSummaries/distanceDistributionsSA3.rds
vistaSummaries/distanceHistograms.rds
vistaSummaries/modeChoiceProbabilitiesSA3.rds
```

These inputs are aggregate or derived source data. The pipeline generates
synthetic agents and activity plans; it does not replay identified people's
observed trajectories.

### Optional 3D enrichment

- `dem/fabdem_melbourne.tif`
- `landmarks/<region_key>.json`

The landmark JSON can be regenerated from the local Victoria PBF with:

```bash
python3 -m pip install -r requirements-data.txt
python3 scripts/extract_landmarks.py --all
```

The 3D enrichment is optional for the transport run. If it is missing, preflight
reports a warning and the visualization contains less detail.

## Check before a long run

```bash
python3 -m wrapper.cli doctor
```

This checks file presence, runtime dependencies, Docker resources, region
boundaries and disk space. It does not download data or run a simulation.

Always review the current terms, attribution requirements and sharing permissions
of each source before redistributing any derived dataset.
