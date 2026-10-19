import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shapely.affinity import rotate
from shapely.geometry import Polygon, box

from wrapper.building_geometry import prepare_buildings
from wrapper import runs
from scripts.refresh_scene_buildings import refresh_buildings


def building(poly, **extra):
    return {'points':list(poly.exterior.coords),
            'holes':[list(r.coords) for r in poly.interiors],
            'height':30, 'height_m':150, 'roof':'flat', 'osm_id':'way/1',
            'name':'', **extra}


class BuildingModelTests(unittest.TestCase):
    def model(self, poly, **extra):
        return prepare_buildings([building(poly,**extra)])[0][0]

    def test_rotated_roof_stays_inside_real_footprint(self):
        p=rotate(box(0,0,15,5),37)
        profile=self.model(p)['architecture']
        self.assertEqual(profile['kind'],'setback')
        roof=Polygon(profile['inset']['points'],profile['inset']['holes'])
        self.assertTrue(p.buffer(1e-6).covers(roof))
        self.assertAlmostEqual(profile['body_top']+profile['depth'],30)

    def test_courtyard_remains_open_in_setback(self):
        p=Polygon(box(0,0,15,15).exterior.coords,[box(5,5,10,10).exterior.coords])
        roof=self.model(p)['architecture']['inset']
        q=Polygon(roof['points'],roof['holes'])
        self.assertEqual(len(q.interiors),1)
        self.assertTrue(p.covers(q))

    def test_concave_roof_never_bridges_missing_corner(self):
        p=Polygon([(0,0),(15,0),(15,5),(5,5),(5,15),(0,15)])
        profile=self.model(p)['architecture']
        self.assertEqual(profile['kind'],'setback')
        self.assertTrue(p.covers(Polygon(profile['inset']['points'],profile['inset']['holes'])))

    def test_split_inset_does_not_make_roof_islands(self):
        p=box(0,0,5,5).union(box(9,0,14,5)).union(box(5,2.45,9,2.55))
        self.assertEqual(self.model(p)['architecture']['kind'],'flat')

    def test_clipped_edge_does_not_get_fake_crown(self):
        self.assertEqual(self.model(box(0,0,12,8),clipped=True)['architecture']['kind'],'flat')

    def test_exact_duplicate_preserves_taller_envelope_and_source_ids(self):
        p=box(0,0,8,8)
        low=building(p,height=9,osm_id='way/low',name='Named building')
        high=building(p,height=18,osm_id='relation/high')
        high['points'].reverse()
        models,stats=prepare_buildings([low,high])
        self.assertEqual(len(models),1)
        self.assertEqual(models[0]['height'],18)
        self.assertEqual(models[0]['name'],'Named building')
        self.assertEqual(models[0]['source_ids'],['relation/high','way/low'])
        self.assertEqual(stats['duplicate_height_conflicts'],1)

    def test_neighbours_and_real_overlaps_are_not_merged(self):
        entries=[building(box(0,0,10,10)),building(box(10,0,20,10)),building(box(2,2,8,8),height=40)]
        models,stats=prepare_buildings(entries)
        self.assertEqual(len(models),3)
        self.assertEqual(stats['duplicate_footprints'],0)

    def test_thin_building_is_preserved_without_oversized_roof(self):
        models,_=prepare_buildings([building(box(0,0,0.1,10))])
        self.assertEqual(len(models),1)
        self.assertEqual(models[0]['architecture']['kind'],'flat')

    def test_rotated_gable_has_exact_footprint_and_bounded_height(self):
        p=rotate(box(0,0,12,5),29)
        roof=self.model(p,height=3,height_m=16,roof='gabled')['architecture']
        self.assertEqual(roof['kind'],'pitched')
        area=0
        for i in range(0,len(roof['faces']),3):
            a,b,c=roof['faces'][i:i+3]
            tri=Polygon([(v[0],v[2]) for v in (a,b,c)])
            self.assertTrue(p.buffer(1e-6).covers(tri))
            area+=tri.area
            self.assertGreater((b[2]-a[2])*(c[0]-a[0])-(b[0]-a[0])*(c[2]-a[2]),0)
        self.assertAlmostEqual(area,p.area)
        self.assertTrue(all(0<=v[1]<=roof['depth'] for v in roof['faces']+roof['skirts']))
        self.assertAlmostEqual(roof['body_top']+roof['depth'],3)

    def test_hipped_roof_is_footprint_based_not_axis_aligned_box(self):
        p=rotate(box(0,0,8,5),41)
        roof=self.model(p,height=3,height_m=16,roof='hipped')['architecture']
        self.assertEqual(roof['kind'],'pitched')
        self.assertEqual(len(roof['faces']),12)
        self.assertTrue(all(p.buffer(1e-6).covers(Polygon([(v[0],v[2]) for v in roof['faces'][i:i+3]]))
                            for i in range(0,len(roof['faces']),3)))

    def test_no_pyramid_over_a_holed_lowrise(self):
        p=Polygon(box(0,0,12,12).exterior.coords,[box(3,3,9,9).exterior.coords])
        self.assertEqual(self.model(p,height=3,height_m=16,roof='hipped')['architecture']['kind'],'flat')

    def test_unknown_roof_and_civic_name_do_not_invent_domes(self):
        b=self.model(box(0,0,8,5),height=3,height_m=16,roof='many',name='Library',heritage=True,kind='civic')
        self.assertEqual(b['architecture']['kind'],'flat')

    def test_input_is_not_mutated_and_output_is_deterministic(self):
        entries=[building(box(0,0,12,8))]
        before=copy.deepcopy(entries)
        self.assertEqual(prepare_buildings(entries),prepare_buildings(entries))
        self.assertEqual(entries,before)

    def test_nonfinite_height_is_rejected_with_diagnostic(self):
        models,stats=prepare_buildings([building(box(0,0,8,8),height=math.nan)])
        self.assertEqual(models,[])
        self.assertEqual(stats['invalid'],1)


class BuildingReplayTests(unittest.TestCase):
    def test_sidecar_changes_only_building_display_and_detects_stale_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'ifline_scene.landuse-v2.json'
            original={'roads':[{'link_id':'1','delta':2}], 'terrain':{'x':3},'vehicles':[{'trips':[]}],
                      'ifline':{'baseline':'test'},'landmarks':{'parks':[{'points':[]}],
                      'buildings':[building(box(0,0,10,8))],'labels':[{'name':'test'}]}}
            source.write_text(json.dumps(original))
            before=source.read_bytes()
            dest,_=refresh_buildings(source)
            after=json.loads(dest.read_text())
            self.assertEqual(source.read_bytes(),before)
            for key in original.keys()-{'landmarks'}: self.assertEqual(original[key],after[key])
            self.assertEqual(after['landmarks']['parks'],original['landmarks']['parks'])
            self.assertEqual(after['landmarks']['labels'],original['landmarks']['labels'])
            self.assertEqual(runs.refreshed_building_scene(source),dest)
            source.write_text(json.dumps({**original,'roads':[]}))
            self.assertIsNone(runs.refreshed_building_scene(source))

    def test_ifline_selects_its_own_building_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);sim=root/'demo_sim';sim.mkdir()
            for name in runs.REQUIRED_RESULT_FILES: (sim/name).write_text('fixture')
            for name in ('skyline_scene.json','ifline_scene.json'):
                source=sim/name
                source.write_text(json.dumps({'roads':[],'terrain':{},'landmarks':{'buildings':[]}}))
                refresh_buildings(source)
            with patch.object(runs,'OUTPUT_DIR',root),patch.object(runs,'compute_summary_data',return_value={}), \
                 patch.object(runs,'_ifline_record',return_value={'comparison':{'example':1}}):
                data=runs.result_payload('demo_sim')
            self.assertEqual(data['skyline_scene_url'],'/results/demo_sim/ifline_scene.buildings-v1.json')
            self.assertEqual(data['recorded_ifline_comparison'],{'example':1})
            self.assertNotIn('ifline_comparison', data)
            self.assertIn('comparison_unavailable_reason', data)


if __name__=='__main__': unittest.main()
