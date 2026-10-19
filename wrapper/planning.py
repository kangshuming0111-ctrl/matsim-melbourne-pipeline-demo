"""Concept-road plans: validate, compile topology, audit footprint conflicts.

No simulator or rendering side effects in compile_plan. All operations compile
in memory and the caller publishes the network only after all checks succeed.
Road heights are offsets above terrain, NOT structural/clearance certification.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from xml.etree import ElementTree as ET

from shapely.geometry import LineString, Polygon

from wrapper.building_screen import load_corridor_buildings, road_corridors
from wrapper.ifline import validate_intervention, resolve_run_assets, _network_tree
from wrapper.runs import refreshed_landmark_scene, refreshed_building_scene

WARNINGS = [
    '交通概念方案：没有信号配时、施工、结构承重或规范合规验证。',
    '人口及活动位置固定；不预测诱发需求、房价、拆迁成本或长期城市发展。',
    '建筑冲突来自现有轮廓的平面占用检查；高度、净空和用地权属仍需专业核验。',
    '基线未提供完整桥梁层级；未标记高度的 link 按地面处理，新交叉口须人工核验。',
]


def validate_plan(raw):
    if not isinstance(raw, dict):
        raise ValueError('方案必须是对象')
    ops = raw.get('operations')
    if not isinstance(ops, list) or not 1 <= len(ops) <= 12:
        raise ValueError('一个方案需包含 1–12 项修改')
    out = []
    for op in ops:
        if not isinstance(op,dict) or op.get('type') not in ('new_road','speed_limit','capacity_scale','road_closure'):
            raise ValueError('方案只接受单项道路修改，不允许嵌套方案')
        spec = validate_intervention(op)
        if spec['type'] == 'new_road':
            if not spec['lanes'].is_integer():
                raise ValueError('每方向车道数必须是整数')
            heights = op.get('heights', [0]*len(spec['points']))
            if not isinstance(heights,list) or len(heights)!=len(spec['points']):
                raise ValueError('每个道路控制点必须有一个相对地面高度')
            try:
                heights = [float(h) for h in heights]
            except (TypeError,ValueError):
                raise ValueError('道路高度必须为数字')
            if any(not math.isfinite(h) or not 0 <= h <= 50 for h in heights):
                raise ValueError('演示道路高度需在 0–50 米之间；这不是工程规范阈值')
            if heights[0]!=0 or heights[-1]!=0:
                raise ValueError('路线两端必须以地面高度接入路网；中间控制点可形成高架与匝道')
            spec['heights'] = heights
            snap_points = op.get('snap_points', [True]*len(spec['points']))
            if (not isinstance(snap_points,list) or len(snap_points)!=len(spec['points'])
                    or any(not isinstance(value,bool) for value in snap_points)):
                raise ValueError('snap_points 必须是与道路控制点等长的布尔值列表')
            spec['snap_points'] = list(snap_points)
        out.append(spec)
    labels = raw.get('building_labels', {})
    if not isinstance(labels,dict) or len(labels)>5000:
        raise ValueError('建筑编号记录无效')
    if any(not isinstance(k,str) or not isinstance(v,int) or isinstance(v,bool) or not 1<=v<=10000
           for k,v in labels.items()) or len(set(labels.values()))!=len(labels):
        raise ValueError('建筑编号必须唯一且为正整数')
    return {'type':'plan','operations':out,'building_labels':dict(labels)}


def _attribute(link,name,default=0):
    elem=link.find(f"attributes/attribute[@name='{name}']")
    return float(elem.text) if elem is not None else default


def _set_attribute(link,name,value):
    attrs=link.find('attributes')
    if attrs is None: attrs=ET.SubElement(link,'attributes')
    elem=attrs.find(f"attribute[@name='{name}']")
    if elem is None: elem=ET.SubElement(attrs,'attribute',{'name':name,'class':'java.lang.Double'})
    elem.text=str(value)


def compile_plan(source_network, raw, scene=None):
    spec=validate_plan(raw)
    tree,links,nodes=_network_tree(source_network)
    node_root=tree.getroot().find('nodes')
    baseline={e.get('id'):copy.deepcopy(e) for e in links}
    elevated_nodes={e.get(end) for e in links for end,tag in
                    [('from','ifline:height_from'),('to','ifline:height_to')] if _attribute(e,tag)>0}
    changed=[]; roads=[]; aliases={k:[k] for k in baseline}; counter=0
    bounds=(min(x for x,y in nodes.values()),min(y for x,y in nodes.values()),
            max(x for x,y in nodes.values()),max(y for x,y in nodes.values()))
    def new_id(kind):
        nonlocal counter
        while True:
            counter+=1; value=f'ifplan_{kind}_{counter}'
            if value not in nodes and all(e.get('id')!=value for e in links): return value
    def node(x,y,reuse=True):
        if reuse:
            for key,xy in nodes.items():
                if key not in elevated_nodes and math.dist((x,y),xy)<1e-5: return key
        key=new_id('n');nodes[key]=(x,y)
        ET.SubElement(node_root,'node',{'id':key,'x':str(x),'y':str(y)})
        return key
    def car_nodes():
        ids={e.get(k) for e in links if 'car' in e.get('modes','').split(',')
             and _attribute(e,'ifline:height_from')==0 and _attribute(e,'ifline:height_to')==0
             for k in ('from','to')}
        return [(k,nodes[k]) for k in sorted(ids)]
    for index,op in enumerate(spec['operations']):
        if op['type']!='new_road':
            origin=baseline.get(op['link_id'])
            if origin is None or 'car' not in origin.get('modes','').split(','):
                raise ValueError('已有道路修改必须指定基线中的机动车 link')
            ids=[op['link_id']]
            if op['include_reverse']:
                ids += [k for k,e in baseline.items() if k!=op['link_id'] and
                        e.get('from')==origin.get('to') and e.get('to')==origin.get('from')
                        and 'car' in e.get('modes','').split(',')]
            for key in ids:
                for piece_id in aliases[key]:
                    link=next(e for e in links if e.get('id')==piece_id)
                    before=dict(link.attrib)
                    if op['type']=='speed_limit': link.set('freespeed',str(op['value']/3.6))
                    elif op['type']=='capacity_scale':
                        link.set('capacity',str(float(baseline[key].get('capacity'))*op['value']/100))
                    else: link.set('modes',','.join(m for m in link.get('modes','').split(',') if m!='car'))
                    changed.append({'action':'modified','operation':index+1,'link_id':piece_id,
                                    'before':before,'after':dict(link.attrib)})
            continue
        resolved=[]
        candidates=car_nodes()
        if not candidates: raise ValueError('方案中已没有可接入的地面机动车节点')
        for i,((x,y),h,snap) in enumerate(zip(op['points'],op['heights'],op['snap_points'])):
            if not bounds[0]<=x<=bounds[2] or not bounds[1]<=y<=bounds[3]:
                raise ValueError('控制点超出已准备的路网区域')
            nearest,xy=min(candidates,key=lambda pair:math.dist(pair[1],(x,y)))
            distance=math.dist(xy,(x,y)); endpoint=i in (0,len(op['points'])-1)
            if endpoint and snap and distance>op['snap_tolerance_m']:
                raise ValueError(f'道路端点离可接入节点 {distance:.1f} 米，请靠近路口')
            if endpoint and not snap:
                if distance>1e-5:
                    raise ValueError(f'道路端点 {i+1} 已关闭吸附，必须连接到地面机动车节点（误差不超过 1e-5 米）；'
                                     '请将端点移到可接入路口，或开启该点吸附（snap_points=true）')
                # Reuse the connection without changing the supplied coordinates.
                key=nearest
            elif snap and h==0 and distance<=op['snap_tolerance_m']:
                key=nearest;x,y=xy
            else:
                key=node(x,y,reuse=h==0)
                if h>0: elevated_nodes.add(key)
            if resolved and resolved[-1][:3]==[x,y,h]: continue
            resolved.append([x,y,h,key])
        if len(resolved)<2: raise ValueError('吸附后道路退化为一个节点')
        effective=[]
        for a,b in zip(resolved,resolved[1:]):
            horizontal=math.dist(a[:2],b[:2])
            if horizontal<2: raise ValueError('吸附后相邻控制点间距必须至少 2 米')
            if abs(b[2]-a[2])/horizontal>0.12:
                raise ValueError('匝道超过本演示的 12% 几何坡度上限，请延长匝道；该上限不是规范认证')
            line=LineString([a[:2],b[:2]]); cuts=[(0,a),(1,b)]
            if a[2]==b[2]==0:
                for old in list(links):
                    if 'car' not in old.get('modes','').split(','): continue
                    if _attribute(old,'ifline:height_from') or _attribute(old,'ifline:height_to'): continue
                    oldline=LineString([nodes[old.get('from')],nodes[old.get('to')]])
                    cross=line.intersection(oldline)
                    if cross.is_empty: continue
                    if cross.geom_type!='Point':
                        if cross.length>0.1: raise ValueError('新道路与已有道路重合，请修改走向或调整已有道路')
                        continue
                    x,y=cross.x,cross.y; key=node(x,y)
                    t=line.project(cross)/line.length; u=oldline.project(cross)/oldline.length
                    if 1e-7<t<1-1e-7: cuts.append((t,[x,y,0,key]))
                    if 1e-7<u<1-1e-7:
                        if min(u,1-u)*oldline.length<0.1:
                            raise ValueError('交叉点距现有节点过近，请吸附到该节点')
                        oldid=old.get('id');before=dict(old.attrib);oldto=old.get('to')
                        length=float(old.get('length')); copy_link=copy.deepcopy(old);splitid=new_id('split')
                        old.set('to',key);old.set('length',str(length*u))
                        copy_link.set('id',splitid);copy_link.set('from',key);copy_link.set('to',oldto)
                        copy_link.set('length',str(length*(1-u)));links.append(copy_link)
                        for original,pieces in aliases.items():
                            if oldid in pieces: pieces.append(splitid)
                        changed.extend([{'action':'split','operation':index+1,'link_id':oldid,'before':before,'after':dict(old.attrib)},
                                        {'action':'split','operation':index+1,'link_id':splitid,'before':None,'after':dict(copy_link.attrib)}])
            unique={round(t,10):(t,p) for t,p in cuts}
            pieces=sorted(unique.values(),key=lambda pair:pair[0])
            for (_,p),(_,q) in zip(pieces,pieces[1:]):
                if math.dist(p[:2],q[:2])<0.1: raise ValueError('新交叉口产生过短路段')
                effective.append([p[:3],q[:3]])
                for start,end in [(p,q)]+([(q,p)] if op['bidirectional'] else []):
                    key=new_id('road'); length=math.dist(start[:3],end[:3])
                    e=ET.SubElement(links,'link',{'id':key,'from':start[3],'to':end[3],
                        'length':str(length),'capacity':str(op['capacity_per_hour']),
                        'freespeed':str(op['speed_kph']/3.6),'permlanes':str(op['lanes']),
                        'oneway':'1','modes':','.join(op['modes'])})
                    for tag,value in [('ifline:height_from',start[2]),('ifline:height_to',end[2]),
                                      ('ifline:width_m',op['lanes']*3.5*(2 if op['bidirectional'] else 1)+2)]:
                        _set_attribute(e,tag,value)
                    changed.append({'action':'added','operation':index+1,'link_id':key,'before':None,
                                    'after':dict(e.attrib)})
        roads.append({'operation':index+1,'segments':effective,
                      'width_m':op['lanes']*3.5*(2 if op['bidirectional'] else 1)+2})
    # Every new node must participate in the final network. No side effects on
    # failure; stale/overridden operations stay visible in the ordered audit.
    conflicts,labels=building_conflicts(roads,scene,spec['building_labels'])
    spec['building_labels']=labels
    return tree,{'plan':spec,'changed_links':changed,'roads':roads,'conflicts':conflicts,
                 'warnings':list(WARNINGS),'building_data_available':scene is not None}


def building_conflicts(roads,scene,labels):
    labels=dict(labels);hits=[]
    if scene is None: return hits,labels
    tr=scene['coordinate_transform'];s=tr['scene_units_per_metre']
    def native(ring): return [(x/s+tr['center_x'],z/s+tr['center_y']) for x,z in ring]
    corridors=road_corridors(roads)
    grouped={}
    for b in scene.get('landmarks',{}).get('buildings',[]):
        p=Polygon(native(b['points']),[native(h) for h in b.get('holes',[])])
        if not p.is_valid or p.is_empty:
            raise ValueError('建筑轮廓无效，需修复场景数据后再检查，不能跳过后宣称无冲突')
        affected=[i for i,corridor in corridors if corridor.intersection(p).area>0.01]
        if not affected: continue
        key=str(b.get('osm_id') or hashlib.sha256(p.wkb).hexdigest()[:16])
        hit=grouped.setdefault(key,{'key':key,'name':b.get('name',''), 'operation_ids':[],
                                   'focus':{'x':p.centroid.x,'y':p.centroid.y},'points':b['points'],
                                   'holes':b.get('holes',[]),'height':b.get('height',3)})
        hit['operation_ids']=sorted(set(hit['operation_ids']+affected))
    for key,hit in sorted(grouped.items()):
        if key not in labels: labels[key]=max(labels.values(),default=0)+1
        hit['label']=f'建筑{labels[key]}';hits.append(hit)
    return sorted(hits,key=lambda hit:labels[hit['key']]),labels


def check_plan(baseline_run,raw):
    assets=resolve_run_assets(baseline_run)
    # Compile geometry without treating display-capped meshes as footprint input.
    # compile_plan remains pure and accepts explicit scene fixtures when desired.
    tree,report=compile_plan(assets['network_file'],raw)
    scene_path=assets['sim_dir']/'skyline_scene.json'
    scene_path=refreshed_landmark_scene(scene_path) or scene_path
    scene_path=refreshed_building_scene(scene_path) or scene_path
    scene_bytes=scene_path.read_bytes() if scene_path.is_file() else b''
    scene={}
    try:
        scene=json.loads(scene_bytes) if scene_bytes else {}
        if not isinstance(scene,dict): scene={}
    except (ValueError,UnicodeError):
        if report['roads']: raise ValueError('基线坐标场景无效，请先更新场景') from None
    source_digest=b''
    if report['roads']:
        if not isinstance(scene.get('coordinate_transform'),dict):
            raise ValueError('基线场景缺少坐标变换，请先更新场景')
        screening_scene,evidence=load_corridor_buildings(
            assets.get('region_key'),report['roads'],scene['coordinate_transform'])
        conflicts,labels=building_conflicts(report['roads'],screening_scene,report['plan']['building_labels'])
        report['conflicts']=conflicts;report['plan']['building_labels']=labels
        report['building_data_available']=True
        report['building_screen']=evidence
        source_digest=json.dumps(evidence,sort_keys=True).encode()
        report['warnings'].append('已用未受显示数量上限裁剪的已知建筑源检查新道路完整宽度；'
                                  '源数据仍可能漏楼，不代表净空、权属或工程批准。')
    else:
        # Keep the legacy availability field for consumers of valid old scenes;
        # building_screen is authoritative about whether a scan was performed.
        report['building_data_available']=isinstance(scene.get('landmarks'),dict) and 'buildings' in scene['landmarks']
        report['building_screen']={'schema_version':1,'status':'not_required',
            'scope':'no_new_road_footprint','basis':None,'operation_ids':[],
            'source':None,'source_bounds_wgs84':None,'corridors_within_source_extent':None,
            'counts':None,'known_source_only':True}
        report['warnings'].append('本方案没有新道路占地，未扫描建筑轮廓；0 冲突不代表完整建筑覆盖或用地批准。')
    digest=hashlib.sha256(assets['network_file'].read_bytes()+scene_bytes+
                          json.dumps(report['plan'],sort_keys=True).encode()+source_digest).hexdigest()
    report['token']=digest;report['baseline_run']=baseline_run
    report['source_scene']=scene_path.name if scene_bytes else None
    return tree,report
