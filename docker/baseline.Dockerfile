FROM maven:3.9-eclipse-temurin-11

WORKDIR /app

COPY vendor/baseline/pom.xml pom.xml
RUN mvn -B dependency:go-offline || true

COPY vendor/baseline/ .

RUN mvn -B -DskipTests package

ENTRYPOINT ["java", "-cp", "baseline-project-1.0-SNAPSHOT.jar", "io.github.matsimmelbourne.baseline.run.RunPocScenario"]
