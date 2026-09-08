# Added by the Python wrapper (not part of upstream matsim-melbourne/demand).
# Takes a region polygon (same one `network` uses) and finds which SA1 census
# regions it overlaps, so `demand` can be scoped to match `network`'s coverage
# instead of defaulting to all of Melbourne.
library(sf)

regionFile <- Sys.getenv("SCENARIO_REGION_FILE", "")
if (regionFile == "") stop("SCENARIO_REGION_FILE env var not set; unable to proceed")

bufferDist <- as.numeric(Sys.getenv("SCENARIO_REGION_BUFFER_DIST", "500"))
outputFile <- Sys.getenv("SA1_SUBSET_OUTPUT", "")
if (outputFile == "") stop("SA1_SUBSET_OUTPUT env var not set; unable to proceed")

sa1 <- st_read("../data/absRegionsReprojected.sqlite", layer = "sa1_2016_aust", quiet = TRUE)

region <- st_read(regionFile, quiet = TRUE)
region <- st_transform(region, st_crs(sa1))
regionBuffered <- st_buffer(region, bufferDist)

matches <- sa1[st_intersects(sa1, regionBuffered, sparse = FALSE)[, 1], ]

if (nrow(matches) == 0) {
  stop(paste0(
    "No SA1 regions intersect ", regionFile, " (buffered by ", bufferDist, "m). ",
    "Region may be outside Melbourne, or too small/offset. Unable to proceed."
  ))
}

out <- data.frame(
  SA1_MAINCODE_2016 = matches$sa1_maincode_2016,
  SA1_7DIGCODE = matches$sa1_7digitcode_2016
)
write.csv(out, outputFile, row.names = FALSE)

cat(paste0("Wrote ", nrow(out), " matching SA1 regions to ", outputFile, "\n"))
