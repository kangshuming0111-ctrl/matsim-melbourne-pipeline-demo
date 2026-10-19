import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from fastapi import HTTPException
from wrapper.planning import compile_plan, validate_plan, building_conflicts, check_plan, _attribute
from wrapper.api import PlanRequest, run_city_plan
from wrapper.skyline import _network_data
from wrapper.ifline import render_difference_scene

# A square with a north-south road crossing a proposed west-east chord.
NETWORK='''<network><nodes>
<node id="w" x="0" y="100"/><node id="e" x="400" y="100"/>
<node id="n" x="200" y="200"/><node id="s" x="200" y="0"/>
</nodes><links>
<link id="wn" from="w" to="n" length="224" freespeed="10" capacity="900" permlanes="1" modes="car,bike"/>
<link id="ne" from="n" to="e" length="224" freespeed="10" capacity="900" permlanes="1" modes="car,bike"/>
<link id="cross" from="n" to="s" length="200" freespeed="10" capacity="900" permlanes="1" modes="car,bike"/>
<link id="reverse" from="s" to="n" length="200" freespeed="10" capacity="900" permlanes="1" modes="car,bike"/>
</links></network>'''
ROAD={'type':'new_road','points':[[0,100],[400,100]],'heights':[0,0],
      'speed_kph':40,'lanes':1,'capacity_per_hour':900,'snap_tolerance_m':5,'modes':['car'],'bidirectional':True}


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.source=Path(self.tmp.name)/'network.xml';self.source.write_text(NETWORK)

    def compile(self,*ops):return compile_plan(self.source,{'operations':list(ops)})

    def checked_assets(self):
        cache=Path(self.tmp.name)/'buildings.json'
        cache.write_text(json.dumps({'metadata':{'bounds':[-.01,.01,-.01,.01]},'buildings':[
            {'osm_id':'outside-corridor','coords':[[.008,.008],[.009,.008],[.009,.009],[.008,.009]]}]}))
        patcher=patch('wrapper.building_screen.landmark_cache_path',return_value=cache)
        patcher.start();self.addCleanup(patcher.stop)
        return {'sim_dir':Path(self.tmp.name),'network_file':self.source,'region_key':'fixture'}

    def test_disabled_intermediate_snap_preserves_geometry_and_canonical_report(self):
        road={**ROAD,'points':[[0,100],[198,2],[400,100]],'heights':[0,0,0],
              'snap_points':[True,False,True]}
        tree,report=self.compile(road)
        nodes={e.get('id'):(float(e.get('x')),float(e.get('y'))) for e in tree.getroot().find('nodes')}
        self.assertIn((198,2),nodes.values())
        points=[p for segment in report['roads'][0]['segments'] for p in segment]
        self.assertIn([198,2,0],points)
        self.assertNotIn([200,0,0],points)
        self.assertEqual(report['plan']['operations'][0]['snap_points'],[True,False,True])
        self.assertEqual(report['plan']['operations'][0]['points'],road['points'])
        _,rechecked=compile_plan(self.source,report['plan'])
        self.assertEqual(rechecked,report)

    def test_disabled_endpoints_require_exact_network_connection(self):
        for endpoint in (0,1):
            for distance in (2e-5,1,10):
                road=copy.deepcopy(ROAD);road['snap_points']=[True,True]
                road['snap_points'][endpoint]=False
                road['points'][endpoint][0]+=distance if endpoint==0 else -distance
                with self.subTest(endpoint=endpoint,distance=distance):
                    with self.assertRaisesRegex(ValueError,'关闭吸附.*地面机动车节点.*开启该点吸附'):
                        self.compile(road)

    def test_exact_disabled_endpoints_reuse_ground_car_nodes(self):
        for distance in (0,5e-6,1e-5):
            road={**ROAD,'points':[[distance,100],[400-distance,100]],'snap_points':[False,False]}
            with self.subTest(distance=distance):
                tree,report=self.compile(road)
                segments=report['roads'][0]['segments']
                self.assertEqual(segments[0][0],road['points'][0]+[0])
                self.assertEqual(segments[-1][1],road['points'][-1]+[0])
                added=[r['after'] for r in report['changed_links'] if r['action']=='added']
                self.assertTrue(any(link['from']=='w' for link in added))
                self.assertTrue(any(link['to']=='e' for link in added))
                self.assertEqual(len(tree.getroot().find('nodes')),5)
                self.assertEqual(report['plan']['operations'][0]['snap_points'],[False,False])

    def test_disabled_endpoint_rejects_noncar_and_elevated_nodes(self):
        for kind in ('noncar','elevated'):
            root=ET.fromstring(NETWORK)
            link=root.find("links/link[@id='wn']")
            if kind=='noncar':
                link.set('modes','bike')
            else:
                attributes=ET.SubElement(link,'attributes')
                ET.SubElement(attributes,'attribute',{'name':'ifline:height_from'}).text='8'
                ET.SubElement(attributes,'attribute',{'name':'ifline:height_to'}).text='8'
            self.source.write_text(ET.tostring(root,encoding='unicode'))
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError,'关闭吸附.*地面机动车节点'):
                    self.compile({**ROAD,'snap_points':[False,True]})

    def test_legacy_snap_defaults_match_explicit_true(self):
        road={**ROAD,'points':[[1,100],[198,2],[399,100]],'heights':[0,0,0]}
        tree,legacy=self.compile(road)
        explicit_tree,explicit=self.compile({**road,'snap_points':[True,True,True]})
        self.assertEqual(legacy,explicit)
        self.assertEqual(ET.tostring(tree.getroot()),ET.tostring(explicit_tree.getroot()))
        self.assertEqual(legacy['plan']['operations'][0]['snap_points'],[True,True,True])
        self.assertEqual(legacy['roads'][0]['segments'],[
            [[0,100,0],[200,0,0]],[[200,0,0],[400,100,0]]])

    def test_snap_points_validation_rejects_wrong_lengths_and_nonbooleans(self):
        invalid=[None,True,0,'false',{},(True,True),[],[True],[True,True,False],
                 [True,0],[1,False],[True,1.0],[False,None],['false',True],[[True],False]]
        for snap_points in invalid:
            with self.subTest(snap_points=snap_points):
                with self.assertRaisesRegex(ValueError,'snap_points.*布尔值列表'):
                    validate_plan({'operations':[{**ROAD,'snap_points':snap_points}]})

    def test_elevated_points_remain_unsnapped_for_either_flag(self):
        for point in ([198,2],[200,0]):
            for snap in (True,False):
                road={**ROAD,'points':[[0,100],point,[400,100]],'heights':[0,8,0],
                      'snap_points':[True,snap,True]}
                with self.subTest(point=point,snap=snap):
                    tree,report=self.compile(road)
                    self.assertEqual(report['roads'][0]['segments'],[
                        [[0,100,0],point+[8]],[point+[8],[400,100,0]]])
                    added=[link for link in tree.getroot().find('links')
                           if _attribute(link,'ifline:height_to')==8]
                    self.assertEqual(len(added),2)
                    self.assertTrue(all(link.get('to')!='s' for link in added))
                    self.assertFalse(any(r['action']=='split' for r in report['changed_links']))

    def test_snap_points_survive_check_and_affect_token(self):
        root=Path(self.tmp.name)
        (root/'skyline_scene.json').write_text(json.dumps({'coordinate_transform':{
            'network_crs':'EPSG:3857','scene_units_per_metre':1,'center_x':0,'center_y':0},'landmarks':{'buildings':[]}}))
        with patch('wrapper.planning.resolve_run_assets',return_value=self.checked_assets()):
            _,legacy=check_plan('base',{'operations':[ROAD]})
            _,disabled=check_plan('base',{'operations':[{**ROAD,'snap_points':[False,False]}]})
            _,rechecked=check_plan('base',disabled['plan'])
        self.assertEqual(disabled['plan']['operations'][0]['snap_points'],[False,False])
        self.assertEqual(disabled['roads'],legacy['roads'])
        self.assertNotEqual(disabled['token'],legacy['token'])
        self.assertEqual(rechecked['token'],disabled['token'])

    def test_ground_cross_splits_both_directions_into_one_shared_junction(self):
        tree,report=self.compile(ROAD)
        nodes={e.get('id'):(float(e.get('x')),float(e.get('y'))) for e in tree.getroot().find('nodes')}
        junction=[k for k,xy in nodes.items() if xy==(200,100)]
        self.assertEqual(len(junction),1)
        links=list(tree.getroot().find('links'))
        self.assertEqual(sum(junction[0] in [e.get('from'),e.get('to')] for e in links),8)
        self.assertEqual(len([r for r in report['changed_links'] if r['action']=='split']),4)
        self.assertEqual(self.source.read_text(),NETWORK)

    def test_elevated_middle_never_connects_to_ground_crossing(self):
        bridge={**ROAD,'points':[[0,100],[100,100],[300,100],[400,100]],'heights':[0,8,8,0]}
        tree,report=self.compile(bridge)
        self.assertFalse(any(r['action']=='split' for r in report['changed_links']))
        links=list(tree.getroot().find('links'))
        deck=[e for e in links if _attribute(e,'ifline:height_from')==8 and _attribute(e,'ifline:height_to')==8]
        self.assertEqual(len(deck),2)
        # Metadata survives a MATSim-style XML export/parser round trip.
        with gzip.open(Path(self.tmp.name)/'output_network.xml.gz','wb') as f:tree.write(f)
        _,parsed=_network_data(Path(self.tmp.name))
        self.assertEqual(parsed[deck[0].get('id')]['height_from_m'],8)
        self.assertEqual(parsed[deck[0].get('id')]['physical_width_m'],9)

    def test_modify_split_descendants_preserves_capacity_and_bike_mode(self):
        tree,_=self.compile(ROAD,{'type':'capacity_scale','link_id':'cross','value':150,'include_reverse':True},
                           {'type':'road_closure','link_id':'cross','include_reverse':True})
        pieces=[e for e in tree.getroot().find('links') if e.get('id') in ('cross','reverse') or 'split' in e.get('id')]
        self.assertEqual(len(pieces),4)
        self.assertTrue(all(float(e.get('capacity'))==1350 and e.get('modes')=='bike' for e in pieces))

    def test_invalid_last_operation_is_atomic(self):
        with self.assertRaises(ValueError):self.compile(ROAD,{'type':'speed_limit','link_id':'missing','value':30})
        self.assertEqual(self.source.read_text(),NETWORK)
        self.assertEqual(len(list(Path(self.tmp.name).iterdir())),1)

    def test_validation_rejects_nested_nan_fractional_lanes_and_elevated_endpoints(self):
        for op in [None,{'type':'plan','operations':[ROAD]}, {**ROAD,'heights':[0,float('nan')]},
                   {**ROAD,'lanes':1.5},{**ROAD,'heights':[1,0]}]:
            with self.subTest(op=op),self.assertRaises(ValueError):validate_plan({'operations':[op]})

    def test_steep_ramp_offmap_and_overlap_are_blocked(self):
        cases=[{**ROAD,'points':[[0,100],[10,100],[400,100]],'heights':[0,8,0]},
               {**ROAD,'points':[[0,100],[410,100]]},
               {**ROAD,'points':[[0,100],[200,200]]}]
        for road in cases:
            with self.subTest(road=road),self.assertRaises(ValueError):self.compile(road)

    def test_conflicts_use_width_holes_and_stable_names_without_mutating_buildings(self):
        scene={'coordinate_transform':{'scene_units_per_metre':1,'center_x':0,'center_y':0},'landmarks':{'buildings':[
            {'osm_id':'real-b','points':[[10,102],[20,102],[20,104],[10,104]],'height':8},
            {'osm_id':'courtyard','points':[[40,80],[80,80],[80,120],[40,120]],
             'holes':[[[42,82],[78,82],[78,118],[42,118]]],'height':5}]}}
        original=copy.deepcopy(scene)
        roads=[{'operation':1,'width_m':9,'segments':[[[0,100,0],[30,100,0]]]},
               {'operation':2,'width_m':4,'segments':[[[50,100,0],[70,100,0]]]}]
        hits,labels=building_conflicts(roads,scene,{'real-b':3})
        self.assertEqual([h['label'] for h in hits],['建筑3']);self.assertEqual(scene,original)
        self.assertEqual(labels,{'real-b':3})

    def test_check_token_changes_with_input_but_reuses_canonical_labels(self):
        root=Path(self.tmp.name)
        (root/'skyline_scene.json').write_text(json.dumps({'coordinate_transform':{'network_crs':'EPSG:3857','scene_units_per_metre':1,'center_x':0,'center_y':0},'landmarks':{'buildings':[]}}))
        with patch('wrapper.planning.resolve_run_assets',return_value=self.checked_assets()):
            _,a=check_plan('base',{'operations':[ROAD]});_,b=check_plan('base',a['plan'])
            self.assertEqual(a['token'],b['token'])
            _,c=check_plan('base',{'operations':[{**ROAD,'speed_kph':45}]})
            self.assertNotEqual(a['token'],c['token'])

    def test_invalid_building_geometry_cannot_silently_pass(self):
        scene={'coordinate_transform':{'scene_units_per_metre':1,'center_x':0,'center_y':0},
               'landmarks':{'buildings':[{'points':[[0,0],[2,2],[0,2],[2,0]]}]}}
        with self.assertRaises(ValueError):building_conflicts([],scene,{})

    def test_stale_or_unacknowledged_plan_never_queues(self):
        report={'token':'current','conflicts':[{'label':'建筑1'}],'plan':{'operations':[ROAD]}}
        with patch('wrapper.api.check_city_plan',return_value=report),patch('wrapper.api.submit_with_id') as submit:
            for token,ack,status in [('old',True,409),('current',False,400)]:
                with self.assertRaises(HTTPException) as error:
                    run_city_plan(PlanRequest(baseline_run='base',plan=report['plan'],check_token=token,acknowledge_conflicts=ack))
                self.assertEqual(error.exception.status_code,status)
            submit.assert_not_called()

    def test_submission_binds_exact_job_and_run_identity(self):
        report={'token':'current','conflicts':[],'plan':{'operations':[ROAD]}}
        with patch('wrapper.api.check_city_plan',return_value=report),patch('wrapper.api.submit_with_id') as submit:
            result=run_city_plan(PlanRequest(baseline_run='base',plan=report['plan'],check_token='current'))
            self.assertEqual(submit.call_args.args[0],result['job_id'])
            self.assertEqual(submit.call_args.kwargs['run_id'],result['run_id'])

    def test_split_and_missing_observations_are_not_reported_as_delay_improvements(self):
        root=Path(self.tmp.name)
        (root/'skyline_scene.json').write_text(json.dumps({'roads':[
            {'link_id':k} for k in ['same','split','new','unobserved']]}))
        with patch('wrapper.ifline._delay_by_link',side_effect=[
            ({'same':10,'split':50,'unobserved':99},{}),({'same':8,'split':2,'new':7},{})]):
            path,summary=render_difference_scene(root,root,{'new','split'},{'split'})
        roads={r['link_id']:r for r in json.loads(path.read_text())['roads']}
        self.assertEqual(summary['links_with_less_delay'],1)
        self.assertEqual(summary['links_with_more_delay'],0)
        self.assertEqual(roads['same']['delay_delta_seconds'],-2)
        for key in ['split','new','unobserved']:
            self.assertIsNone(roads[key]['delay_delta_seconds'])
            self.assertFalse(roads[key]['delay_comparable'])
