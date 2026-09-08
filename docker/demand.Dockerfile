FROM --platform=linux/amd64 rocker/geospatial:4.2.1

WORKDIR /app

COPY vendor/demand/renv.lock renv.lock

RUN R --slave -e "install.packages('renv'); renv::restore(confirm=FALSE)"

# Copy renv cache to system library so all R processes can find packages
RUN cp -r /usr/local/lib/R/site-library/.renv/* /usr/local/lib/R/site-library/ 2>/dev/null || true

# Verify key packages are available
RUN R --slave -e "for (pkg in c('sf','data.table','XML','doParallel','haven','dplyr')) { stopifnot(require(pkg,character.only=TRUE,quietly=TRUE)) }; cat('All packages verified\n')"

COPY vendor/demand/ .

WORKDIR /app/R

ENTRYPOINT ["Rscript", "run_from_env.R"]
