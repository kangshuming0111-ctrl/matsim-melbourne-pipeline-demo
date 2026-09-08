# Thin entrypoint added by the Python wrapper. Deliberately does NOT touch
# makeExamplePopulation.R (its args are already a clean public interface) and
# deliberately does NOT source makeExamplePopulationSmall.R, which defines a
# same-named makeExamplePopulation() with a different signature and would
# silently shadow this one if sourced.
source("makeExamplePopulation.R")

samplePercent <- as.numeric(Sys.getenv("DEMAND_SAMPLE_PERCENT", "0.1"))

numPlansEnv <- Sys.getenv("DEMAND_NUM_PLANS", "")
if (numPlansEnv == "") stop("DEMAND_NUM_PLANS env var not set; unable to proceed")
numPlans <- as.integer(numPlansEnv)

outputDir <- Sys.getenv("DEMAND_OUTPUT_DIR", "output/run1")

sa1SubsetEnv <- Sys.getenv("DEMAND_SA1_SUBSET", "")
sa1Subset <- if (sa1SubsetEnv == "") NA else sa1SubsetEnv

allDestinations <- as.logical(Sys.getenv("DEMAND_ALL_DESTINATIONS", "FALSE"))
output_crs <- as.integer(Sys.getenv("DEMAND_OUTPUT_CRS", "7899"))

randomSeedEnv <- Sys.getenv("DEMAND_RANDOM_SEED", "")
randomSeed <- if (randomSeedEnv == "") NULL else as.integer(randomSeedEnv)

makeExamplePopulation(
  samplePercent = samplePercent,
  numPlans = numPlans,
  outputDir = outputDir,
  sa1Subset = sa1Subset,
  allDestinations = allDestinations,
  output_crs = output_crs,
  rseed = randomSeed
)

finalOutput <- paste0('../', outputDir, '/8.xml/plan.xml')
if (!file.exists(finalOutput)) {
  stop(paste0(
    "Population generation did not produce ", finalOutput, " - check the log above. ",
    "This usually means checksum() rejected the input data files in data/ and all ",
    "steps were silently skipped rather than erroring loudly."
  ))
}
cat(paste0("SUCCESS: wrote ", finalOutput, "\n"))
