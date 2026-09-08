FROM --platform=linux/amd64 rocker/geospatial:4.2.1

WORKDIR /app

COPY vendor/network/renv.lock renv.lock

RUN R --slave -e "install.packages('renv'); renv::restore(confirm=FALSE)"

# Copy renv cache to system library so all R processes can find packages
RUN cp -r /usr/local/lib/R/site-library/.renv/* /usr/local/lib/R/site-library/ 2>/dev/null || true

# Verify key packages are available
RUN R --slave -e "for (pkg in c('sf','data.table','osmextract','igraph','terra','lwgeom')) { stopifnot(require(pkg,character.only=TRUE,quietly=TRUE)) }; cat('All packages verified\n')"

COPY vendor/network/ .

ENTRYPOINT ["Rscript", "-e", "source('NetworkGenerator.R'); makeNetwork(Sys.getenv('NETWORK_CITY', 'city'), Sys.getenv('NETWORK_OUTPUT_SUBDIR', 'generated_network'))"]
