package io.github.matsimmelbourne.baseline.run;

import org.matsim.api.core.v01.Scenario;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.OutputDirectoryHierarchy;
import org.matsim.core.scenario.ScenarioUtils;

/**
 * Added by the Python wrapper. Deliberately does not reuse RunBaselineScenario,
 * whose run() unconditionally adds SBBTransitModule/SwissRailRaptorModule -
 * this scenario has no transit schedule, so it just does the standard
 * load-config -> load-scenario -> run pattern with no transit modules.
 */
public class RunPocScenario {
    public static void main(String[] args) {
        String configFile = args[0];
        Config config = ConfigUtils.loadConfig(configFile);
        config.controler().setOverwriteFileSetting(OutputDirectoryHierarchy.OverwriteFileSetting.deleteDirectoryIfExists);
        Scenario scenario = ScenarioUtils.loadScenario(config);
        Controler controler = new Controler(scenario);
        controler.run();
    }
}
