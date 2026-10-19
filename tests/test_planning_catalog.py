import copy
import hashlib
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from wrapper import planning_catalog as catalog
from wrapper.api import list_planning_cases


class PlanningCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'output'
        self.case = self.output / 'planning_cases' / 'case_one'
        self.case.mkdir(parents=True)
        self.patch = patch.object(catalog, 'OUTPUT', self.output)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.manifest = {'case_id': 'case_one', 'status': 'prepared', 'rows': [
            {'seed': 4711, 'stages': {s: {'attempts': []} for s in ('baseline', 'closure', 'alternative')}}]}
        self.spec = {'case_id': 'case_one', 'population_count': 10, 'total_iterations': 10,
                     'last_iteration': 9, 'seeds': [4711], 'limitations': 'Not calibrated',
                     'conflict_count': {'closure': 0, 'alternative': 0}}
        self.plans = self.output / 'case_inputs_demand' / '8.xml' / 'plan.xml'
        self.network = self.output / 'case_inputs_network' / 'network.xml'
        for path in (self.plans, self.network):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('<fixture/>')
        self.spec['inputs'] = {'plans_file': self.file_evidence(self.plans),
                               'network_file': self.file_evidence(self.network)}
        self.assets = {}
        self.results = {}
        self.resolver = patch.object(catalog, 'resolve_run_assets', side_effect=lambda run: self.assets[run])
        self.resolve = self.resolver.start()
        self.addCleanup(self.resolver.stop)
        self.write()

    def write(self):
        spec_bytes = json.dumps(self.spec).encode()
        (self.case / 'case_spec.json').write_bytes(spec_bytes)
        self.manifest['spec_sha256'] = hashlib.sha256(spec_bytes).hexdigest()
        (self.case / 'case_manifest.json').write_text(json.dumps(self.manifest))

    def evidence(self, path, value):
        payload = json.dumps(value).encode()
        path.write_bytes(payload)
        return {'path': str(path.relative_to(self.output.parent)), 'sha256': hashlib.sha256(payload).hexdigest()}

    def file_evidence(self, path):
        return {'path': str(path.relative_to(self.output.parent)),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def completed_stage(self, name):
        run_id = f'case_one_4711_{name}'
        sim = self.output / f'{run_id}_sim'
        sim.mkdir(exist_ok=True)
        (sim / 'output_config.xml').write_text('<config><fixture seed="4711" last="9"/></config>')
        record_path = self.output / 'run_records' / run_id / 'run_manifest.json'
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record = {'run_id': run_id, 'status': 'completed', 'random_seeds': {'matsim': 4711},
                  'configuration': {'matsim_first_iteration': 0, 'matsim_last_iteration': 9},
                  'outputs': {'network': str(self.network.parent.relative_to(self.output.parent)),
                              'demand': str(self.plans.parent.parent.relative_to(self.output.parent))}}
        self.evidence(record_path, record)
        self.assets[f'{run_id}_sim'] = {'run_name': f'{run_id}_sim', 'run_id': run_id,
            'record': record, 'matsim_seed': 4711, 'last_iteration': 9, 'plans_file': self.plans,
            'network_file': self.network, 'record_path': record_path, 'sim_dir': sim}
        self.results[name] = {'run_id': run_id, 'seed': 4711, 'stage': name, 'last_iteration': 9,
            'files': {key: self.file_evidence(path) for key, path in {
                'plans': self.plans, 'network': self.network, 'run_record': record_path,
                'output_config.xml': sim / 'output_config.xml'}.items()}}
        self.manifest['rows'][0]['stages'][name]['attempts'] = [{'status': 'completed', 'run_id': run_id}]
        self.publish_result(name)
        return self.assets[f'{run_id}_sim']

    def publish_result(self, name):
        latest = self.manifest['rows'][0]['stages'][name]['attempts'][-1]
        latest['result'] = self.evidence(self.case / f'{name}.json', self.results[name])
        self.write()

    def completed_case(self):
        for name in ('baseline', 'closure', 'alternative'):
            self.completed_stage(name)
        self.manifest['status'] = 'completed'
        self.write()

    def aggregate(self, completed=None):
        completed = [4711] if completed is None else completed
        measurement = {'n': len(completed), 'missing': 0, 'mean': 5, 'median': 5, 'min': 5, 'max': 5}
        value = {'expected_seeds': [4711], 'completed_seeds': completed,
            'incomplete_seeds': [] if completed else [4711],
            'paired_results': [{'seed': seed, 'comparisons': {}} for seed in completed],
            'descriptive_ranges': {name: {'car_mean_travel_time_s': copy.deepcopy(measurement)}
                for name in ('closure_vs_baseline', 'alternative_vs_baseline', 'alternative_vs_closure')} if completed else {}}
        self.publish_aggregate(value)
        return value

    def publish_aggregate(self, value):
        self.manifest['aggregate'] = self.evidence(self.case / 'aggregate.json', value)
        self.write()

    def one_case(self):
        return catalog.planning_cases()['cases'][0]

    def test_prepared_case_has_no_completed_links_and_does_not_resolve_or_run(self):
        with patch.object(catalog, 'resolve_run_assets') as resolve:
            row = catalog.planning_cases()['cases'][0]
        resolve.assert_not_called()
        self.assertEqual(row['status'], 'prepared')
        self.assertTrue(all(s['run'] is None for s in row['rows'][0]['stages'].values()))

    def test_partial_failure_preserves_only_verified_completed_stage(self):
        self.completed_stage('baseline')
        self.manifest['status'] = 'failed'
        self.manifest['rows'][0]['stages']['closure']['attempts'] = [{'status': 'failed', 'run_id': 'c'}]
        self.write()
        row = self.one_case()
        self.resolve.assert_called_once_with('case_one_4711_baseline_sim')
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['rows'][0]['stages']['baseline']['run'], 'case_one_4711_baseline_sim')
        self.assertTrue(row['rows'][0]['stages']['baseline']['controls_verified'])
        self.assertFalse(row['controls_verified'])
        self.assertEqual(row['controls_verification']['verified_stage_count'], 1)
        self.assertIsNone(row['rows'][0]['stages']['closure']['run'])

    def test_changed_aggregate_and_outside_evidence_fail_closed(self):
        self.completed_case()
        ev = self.evidence(self.case / 'aggregate.json', {})
        self.manifest['aggregate'] = ev
        self.write()
        (self.case / 'aggregate.json').write_text('{"tampered": true}')
        row = self.one_case()
        self.assertEqual(row['status'], 'completed')
        self.assertIsNone(row['aggregate'])
        self.assertIn('checksum mismatch', row['aggregate_error'])
        self.assertTrue(all(stage['run'] for stage in row['rows'][0]['stages'].values()))
        outside = self.output / 'elsewhere.json'
        self.manifest['aggregate'] = self.evidence(outside, {})
        self.write()
        row = self.one_case()
        self.assertEqual(row['status'], 'completed')
        self.assertIsNone(row['aggregate'])
        self.assertIn('outside', row['aggregate_error'])
        self.assertTrue(all(stage['run'] for stage in row['rows'][0]['stages'].values()))

    def test_malformed_or_mismatched_identity_is_not_silently_omitted(self):
        self.spec['case_id'] = 'other'
        self.write()
        rows = catalog.planning_cases()['cases']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'unavailable')

    def test_api_rejects_limit_without_scheduling_work(self):
        with patch('wrapper.api.submit_with_id') as submit:
            with self.assertRaises(HTTPException) as caught:
                list_planning_cases(0)
        self.assertEqual(caught.exception.status_code, 400)
        submit.assert_not_called()

    def test_empty_catalog_is_empty_not_fake_success(self):
        with patch.object(catalog, 'OUTPUT', self.output / 'missing'):
            self.assertEqual(catalog.planning_cases(), {'cases': []})

    def test_completed_label_cannot_hide_missing_stages(self):
        self.manifest['status'] = 'completed'
        self.write()
        self.assertEqual(catalog.planning_cases()['cases'][0]['status'], 'unavailable')

    def test_seed_rows_must_match_spec_and_not_duplicate(self):
        self.spec['seeds'] = [4711, 4712]
        self.write()
        self.assertEqual(catalog.planning_cases()['cases'][0]['status'], 'unavailable')
        self.spec['seeds'] = [4711, 4711]
        self.manifest['rows'].append(self.manifest['rows'][0])
        self.write()
        self.assertEqual(catalog.planning_cases()['cases'][0]['status'], 'unavailable')

    def test_modified_spec_does_not_relabel_experiment(self):
        self.spec['population_count'] = 999999
        (self.case / 'case_spec.json').write_text(json.dumps(self.spec))
        self.assertEqual(catalog.planning_cases()['cases'][0]['status'], 'unavailable')

    def test_valid_completed_case_declares_limited_controls_scope(self):
        self.completed_case()
        expected = self.aggregate()
        row = self.one_case()
        self.assertEqual(row['status'], 'completed')
        self.assertEqual(row['aggregate'], expected)
        self.assertIsNone(row['aggregate_error'])
        self.assertIs(row['controls_verified'], True)
        self.assertEqual(row['controls_verification']['scope'], 'completed_stage_metadata_and_control_source_hashes')
        self.assertEqual(row['controls_verification']['verified_stage_count'], 3)
        self.assertEqual(row['controls_verification']['expected_stage_count'], 3)
        self.assertIn('normalized_config_comparability', row['controls_verification']['not_checked'])
        self.assertIn('trip_event_data_quality', row['controls_verification']['not_checked'])

    def test_running_snapshot_resolves_only_completed_attempts(self):
        self.completed_stage('baseline')
        self.manifest['status'] = 'running'
        self.manifest['rows'][0]['stages']['closure']['attempts'] = [{'status': 'running', 'run_id': 'active'}]
        self.write()
        self.aggregate([])
        row = self.one_case()
        self.assertEqual(row['status'], 'running')
        self.assertFalse(row['controls_verified'])
        self.assertIsNone(row['aggregate_error'])
        self.assertEqual(row['aggregate']['completed_seeds'], [])
        self.assertEqual(row['aggregate']['incomplete_seeds'], [4711])
        self.assertIsNone(row['rows'][0]['stages']['closure']['run'])
        self.resolve.assert_called_once_with('case_one_4711_baseline_sim')

    def test_stale_aggregate_cannot_claim_unfinished_seed_is_complete(self):
        self.completed_stage('baseline')
        self.manifest['status'] = 'failed'
        self.manifest['rows'][0]['stages']['closure']['attempts'] = [{'status': 'failed', 'run_id': 'failed'}]
        self.aggregate([4711])
        row = self.one_case()
        self.assertEqual(row['status'], 'failed')
        self.assertIsNone(row['aggregate'])
        self.assertIn('completed_seeds', row['aggregate_error'])
        self.assertIsNotNone(row['rows'][0]['stages']['baseline']['run'])

    def test_aggregate_seed_partitions_and_paired_rows_must_match(self):
        self.completed_case()
        valid = self.aggregate()
        for field, value in [('expected_seeds', [999]), ('completed_seeds', [4711, 4711]),
                             ('incomplete_seeds', [4711]), ('paired_results', [])]:
            with self.subTest(field=field):
                invalid = copy.deepcopy(valid)
                invalid[field] = value
                self.publish_aggregate(invalid)
                row = self.one_case()
                self.assertEqual(row['status'], 'completed')
                self.assertIsNone(row['aggregate'])
                self.assertTrue(row['aggregate_error'])
                self.assertTrue(row['controls_verified'])
                self.assertTrue(all(stage['run'] for stage in row['rows'][0]['stages'].values()))

    def test_missing_malformed_aggregate_does_not_revoke_verified_links(self):
        self.completed_case()
        row = self.one_case()
        self.assertIsNone(row['aggregate'])
        self.assertIn('not been published', row['aggregate_error'])
        for value in ([], None, {}, {'completed_seeds': [4711]}):
            with self.subTest(value=value):
                self.publish_aggregate(value)
                row = self.one_case()
                self.assertEqual(row['status'], 'completed')
                self.assertIsNone(row['aggregate'])
                self.assertTrue(row['aggregate_error'])
                self.assertTrue(all(stage['run'] for stage in row['rows'][0]['stages'].values()))
        (self.case / 'aggregate.json').unlink()
        self.assertEqual(self.one_case()['status'], 'completed')
        self.assertIsNone(self.one_case()['aggregate'])

    def test_aggregate_measurements_distinguish_missing_from_observed_zero(self):
        self.completed_case()
        aggregate = self.aggregate()
        group = aggregate['descriptive_ranges']['closure_vs_baseline']
        group['car_mean_travel_time_s'] = {'n': 0, 'missing': 1, 'mean': None, 'median': None, 'min': None, 'max': None}
        self.publish_aggregate(aggregate)
        self.assertIsNone(self.one_case()['aggregate_error'])
        for changes in ({'mean': 0}, {'n': 1}, {'missing': -1}, {'n': True}):
            with self.subTest(changes=changes):
                invalid = copy.deepcopy(aggregate)
                invalid['descriptive_ranges']['closure_vs_baseline']['car_mean_travel_time_s'].update(changes)
                self.publish_aggregate(invalid)
                self.assertIsNone(self.one_case()['aggregate'])
        group['car_mean_travel_time_s'] = {'n': 1, 'missing': 0, 'mean': 0, 'median': 0, 'min': 0, 'max': 0}
        self.publish_aggregate(aggregate)
        self.assertEqual(self.one_case()['aggregate']['descriptive_ranges']['closure_vs_baseline']['car_mean_travel_time_s']['mean'], 0)
        group['car_mean_travel_time_s']['mean'] = float('nan')
        self.publish_aggregate(aggregate)
        self.assertIn('Non-finite', self.one_case()['aggregate_error'])

    def test_resolver_identity_seed_and_iteration_mismatches_fail_closed(self):
        assets = self.completed_stage('baseline')
        original = copy.deepcopy(assets)
        mutations = [('run_name', 'other_sim'), ('run_id', 'other'), ('matsim_seed', 999),
                     ('matsim_seed', True), ('last_iteration', 99), ('last_iteration', '9')]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                assets.clear()
                assets.update(copy.deepcopy(original))
                assets[key] = value
                row = self.one_case()
                self.assertEqual(row['status'], 'unavailable')
                self.assertFalse(row['controls_verified'])
                self.assertEqual(row['rows'], [])

    def test_record_completion_identity_and_controls_are_not_resolver_defaults(self):
        assets = self.completed_stage('baseline')
        original = copy.deepcopy(assets['record'])
        for section, key, value in [(None, 'run_id', 'wrong'), (None, 'status', 'running'),
                ('random_seeds', 'matsim', 999), ('configuration', 'matsim_first_iteration', 1),
                ('configuration', 'matsim_last_iteration', 99)]:
            with self.subTest(section=section, key=key):
                assets['record'] = copy.deepcopy(original)
                (assets['record'] if section is None else assets['record'][section])[key] = value
                row = self.one_case()
                self.assertEqual(row['status'], 'unavailable')
                self.assertFalse(row['controls_verified'])

    def test_actual_control_source_mutations_are_detected(self):
        assets = self.completed_stage('baseline')
        for path in (self.plans, self.network, assets['record_path'], assets['sim_dir'] / 'output_config.xml'):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b'changed')
                row = self.one_case()
                self.assertEqual(row['status'], 'unavailable')
                self.assertIn('checksum mismatch', row['error'])
                path.write_bytes(original)

    def test_control_evidence_must_name_the_resolved_file(self):
        self.completed_stage('baseline')
        copied = self.output / 'lookalike_plans.xml'
        copied.write_bytes(self.plans.read_bytes())
        self.results['baseline']['files']['plans'] = self.file_evidence(copied)
        self.publish_result('baseline')
        self.assertIn('path does not match', self.one_case()['error'])

    def test_source_evidence_cannot_escape_output_through_symlink(self):
        self.completed_stage('baseline')
        outside = Path(self.temp.name) / 'outside.xml'
        outside.write_bytes(self.plans.read_bytes())
        link = self.output / 'outside_link.xml'
        link.symlink_to(outside)
        self.results['baseline']['files']['plans'] = self.file_evidence(link)
        self.publish_result('baseline')
        self.assertIn('outside', self.one_case()['error'])

    def test_rehashed_result_cannot_hide_a_different_population(self):
        self.completed_stage('baseline')
        self.plans.write_text('<different_population/>')
        self.results['baseline']['files']['plans'] = self.file_evidence(self.plans)
        self.publish_result('baseline')
        self.assertEqual(self.one_case()['status'], 'unavailable')

    def test_missing_control_evidence_is_not_marked_verified(self):
        self.completed_stage('baseline')
        del self.results['baseline']['files']['output_config.xml']
        self.publish_result('baseline')
        self.assertFalse(self.one_case()['controls_verified'])
        self.assertEqual(self.one_case()['status'], 'unavailable')

    def test_top_level_json_shapes_are_isolated_as_unavailable(self):
        for value in (None, [], 'string', 42):
            with self.subTest(value=value):
                (self.case / 'case_manifest.json').write_text(json.dumps(value))
                row = self.one_case()
                self.assertEqual(row['status'], 'unavailable')
                self.assertIn('must be an object', row['error'])

    def test_bad_record_does_not_hide_other_cases_through_api(self):
        broken = self.output / 'planning_cases' / 'broken' / 'case_manifest.json'
        broken.parent.mkdir()
        broken.write_text('null')
        with patch('wrapper.api.submit_with_id', side_effect=AssertionError('No jobs')) as submit:
            rows = {row['id']: row for row in list_planning_cases(20)['cases']}
        self.assertEqual(rows['case_one']['status'], 'prepared')
        self.assertEqual(rows['broken']['status'], 'unavailable')
        submit.assert_not_called()

    def test_correctly_hashed_non_object_spec_is_unavailable(self):
        for value in (None, [], 'text'):
            with self.subTest(value=value):
                data = json.dumps(value).encode()
                (self.case / 'case_spec.json').write_bytes(data)
                self.manifest['spec_sha256'] = hashlib.sha256(data).hexdigest()
                (self.case / 'case_manifest.json').write_text(json.dumps(self.manifest))
                row = self.one_case()
                self.assertEqual(row['status'], 'unavailable')
                self.assertIn('specification must be an object', row['error'])

    def test_changed_result_identity_or_iteration_cannot_publish_a_link(self):
        self.completed_stage('baseline')
        original = copy.deepcopy(self.results['baseline'])
        for key, value in [('run_id', 'different'), ('seed', 999), ('stage', 'closure'), ('last_iteration', 10)]:
            with self.subTest(key=key):
                self.results['baseline'] = copy.deepcopy(original)
                self.results['baseline'][key] = value
                self.publish_result('baseline')
                self.assertEqual(self.one_case()['status'], 'unavailable')

    def test_latest_unfinished_attempt_cannot_reuse_older_completed_link(self):
        self.completed_stage('baseline')
        self.manifest['status'] = 'running'
        self.manifest['rows'][0]['stages']['baseline']['attempts'].append({'status': 'running', 'run_id': 'retry'})
        self.write()
        row = self.one_case()
        self.assertEqual(row['status'], 'running')
        self.assertIsNone(row['rows'][0]['stages']['baseline']['run'])
        self.assertFalse(row['rows'][0]['stages']['baseline']['controls_verified'])
        self.resolve.assert_not_called()

    def test_file_changing_during_hashing_is_rejected(self):
        self.completed_stage('baseline')
        original_stamp = catalog._file_stamp
        calls = 0
        def changing_stamp(path):
            nonlocal calls
            stamp = original_stamp(path)
            if path == self.plans.resolve():
                calls += 1
                if calls == 2:
                    return (*stamp[:-1], stamp[-1] + 1)
            return stamp
        with patch.object(catalog, '_file_stamp', side_effect=changing_stamp):
            row = self.one_case()
        self.assertEqual(row['status'], 'unavailable')
        self.assertIn('changed while being verified', row['error'])

    def test_nested_shapes_and_boolean_seeds_fail_closed(self):
        original = copy.deepcopy(self.manifest)
        for value in (None, {}, [{'seed': True, 'stages': {}}], [{'seed': 4711, 'stages': []}],
                      [{'seed': 4711, 'stages': {'baseline': {'attempts': {}}}}]):
            with self.subTest(value=value):
                self.manifest = copy.deepcopy(original)
                self.manifest['rows'] = value
                self.write()
                self.assertEqual(self.one_case()['status'], 'unavailable')

    def test_stat_failure_does_not_hide_healthy_case(self):
        broken = self.output / 'planning_cases' / 'broken' / 'case_manifest.json'
        broken.parent.mkdir()
        broken.write_text('{}')
        real_stat = Path.stat
        for error in (FileNotFoundError('disappeared'), PermissionError('not readable')):
            def stat(path, *args, **kwargs):
                if path == broken:
                    raise error
                return real_stat(path, *args, **kwargs)
            # Freeze discovery, then fail the sorting stat (not pathlib.glob's
            # own exists probe, which may legitimately omit disappearing files).
            with self.subTest(error=type(error).__name__), patch.object(Path, 'glob', return_value=[
                    self.case / 'case_manifest.json', broken]), patch.object(Path, 'stat', stat):
                rows = {row['id']: row for row in catalog.planning_cases()['cases']}
                self.assertEqual(rows['case_one']['status'], 'prepared')
                self.assertEqual(rows['broken']['status'], 'unavailable')
                self.assertIn('Cannot stat', rows['broken']['error'])

    def test_shared_control_files_are_hashed_once_per_read_not_cached_forever(self):
        self.completed_case()
        real_open = Path.open
        reads = []
        def counted_open(path, *args, **kwargs):
            if path.resolve() == self.plans.resolve():
                reads.append(path)
            self.assertNotIn(path.name, ('output_events.xml.gz', 'output_trips.csv.gz', 'output_persons.csv.gz'))
            return real_open(path, *args, **kwargs)
        with patch.object(Path, 'open', counted_open):
            self.assertTrue(self.one_case()['controls_verified'])
            self.assertEqual(len(reads), 1)
            self.assertTrue(self.one_case()['controls_verified'])
            self.assertEqual(len(reads), 2)

    def test_real_resolver_contract_and_read_only_execution(self):
        from wrapper import ifline
        self.completed_case()
        self.aggregate()
        before = {path: path.read_bytes() for path in self.output.rglob('*') if path.is_file()}
        with ExitStack() as stack:
            stack.enter_context(patch.object(ifline, 'OUTPUT_DIR', self.output))
            stack.enter_context(patch.object(ifline, 'PROJECT_ROOT', self.output.parent))
            stack.enter_context(patch.object(catalog, 'resolve_run_assets', ifline.resolve_run_assets))
            guards = [stack.enter_context(patch(target, side_effect=AssertionError('Read-only catalogue must not invoke ' + target)))
                      for target in ('wrapper.api.submit_with_id', 'wrapper.ifline.run_simulation',
                                     'wrapper.impact.analyze_impact', 'subprocess.Popen')]
            row = self.one_case()
        self.assertTrue(row['controls_verified'], row.get('error'))
        self.assertEqual(row['status'], 'completed')
        self.assertIsNone(row['aggregate_error'])
        self.assertTrue(all(guard.call_count == 0 for guard in guards))
        after = {path: path.read_bytes() for path in self.output.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
