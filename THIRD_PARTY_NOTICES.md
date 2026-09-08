# Third-party notices

This repository is a clean integration snapshot. It does not preserve the
separate Git histories of the upstream projects. Upstream authorship must not
be attributed to the integration repository owner.

## MATSim Melbourne network

- Source: https://github.com/matsim-melbourne/network
- Included under: `vendor/network/`
- License: MIT; the upstream license is retained at
  `vendor/network/LICENSE`.

## MATSim Melbourne demand

- Source: https://github.com/matsim-melbourne/demand
- Included under: `vendor/demand/`
- License: MIT; the upstream license is retained at
  `vendor/demand/LICENSE`.

## MATSim Melbourne baseline

- Source: https://github.com/matsim-melbourne/baseline
- Included under: `vendor/baseline/`
- The included Maven project declares GNU Lesser General Public License 3.0 in
  `vendor/baseline/pom.xml`. The upstream GitHub repository does not currently
  expose a separate machine-detected license file, so review the upstream
  project and its declared license before redistribution.
- `RunPocScenario.java` is an integration-specific entry point added by this
  project and is identified as such in its source comment.

## Three.js

- Source: https://github.com/mrdoob/three.js
- Included browser files: `wrapper/static/vendor/three/`
- Version: r128, as identified by the bundled build header
- License: MIT; a copy is retained at
  `wrapper/static/vendor/three/LICENSE`.

MATSim and other Maven/R/Python dependencies are not copied into this Git
repository merely because they appear in lock files or build manifests. Their
own license terms apply when they are downloaded and used.
