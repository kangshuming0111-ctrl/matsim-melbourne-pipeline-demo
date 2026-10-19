"""Build the two-page English review from the checked-in aggregate SQL evidence.
Optional authoring dependency: reportlab. No simulator or raw trip table needed.
"""
from pathlib import Path
import json,statistics
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor,white
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph,Table,TableStyle
from reportlab.lib.pagesizes import A4
ROOT=Path(__file__).resolve().parents[1]
D=json.loads((ROOT/'portfolio/evidence/sql/sql-evidence.json').read_text())['results']
def rows(n):return next(v['rows'] for k,v in D.items() if k.startswith(n+'_'))
def find(n,**kw):return next(r for r in rows(n) if all(r[k]==v for k,v in kw.items()))
mean=statistics.fmean
alt=[r for r in rows('03') if r['label']=='alternative_vs_closure']
closure=[r for r in rows('03') if r['label']=='closure_vs_baseline']
base=[r for r in rows('03') if r['label']=='alternative_vs_baseline']
assert all(r['paired_keys']==934 and r['unmatched_keys']==r['invalid_pairs']==r['mode_switches']==0 for r in rows('03'))
path=ROOT/'portfolio/reports/MATSim-detour-analysis.pdf';path.parent.mkdir(exist_ok=True)
c=canvas.Canvas(str(path),pagesize=A4);c.setTitle('Why the added road did not improve travel time | MATSim case review');c.setAuthor('IF Line / MATSim personal integration project')
W,H=A4;M=42;CW=W-2*M
ink=HexColor('#192e33');muted=HexColor('#53676b');teal=HexColor('#145e53');rust=HexColor('#9b452c');line=HexColor('#d5ddd5');paper=HexColor('#f5f4ed')
style=ParagraphStyle('body',fontName='Helvetica',fontSize=9.6,leading=13.5,textColor=ink,spaceAfter=0)
def p(text,y,x=M,width=CW,size=9.6,color=ink):
 st=ParagraphStyle('p',parent=style,fontSize=size,leading=size*1.4,textColor=color)
 obj=Paragraph(text,st);_,height=obj.wrap(width,H)
 assert y-height>40,(text,y,height)
 obj.drawOn(c,x,y-height);return y-height

def heading(text,y):return p(text,y,size=12.3,color=teal)-8

def table(data,y,widths=None):
 cells=[[Paragraph(str(v),ParagraphStyle('cell',parent=style,fontSize=8.5,leading=11.7,textColor=white if i==0 else ink)) for v in row] for i,row in enumerate(data)]
 t=Table(cells,colWidths=widths or [CW/len(data[0])]*len(data[0]))
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),ink),('BACKGROUND',(0,1),(-1,-1),white),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),('LINEBELOW',(0,1),(-1,-1),.4,line)]))
 _,height=t.wrap(CW,H);assert y-height>40;t.drawOn(c,M,y-height);return y-height

def frame(page):
 c.setFillColor(paper);c.rect(0,0,W,H,fill=1,stroke=0)
 c.setFillColor(teal);c.setFont('Helvetica-Bold',9);c.drawString(M,H-31,'IF LINE / MATSim MELBOURNE')
 c.setFillColor(muted);c.setFont('Helvetica',8);c.drawRightString(W-M,H-31,'CASE REVIEW  /  2026.10-P1')
 c.setStrokeColor(line);c.line(M,35,W-M,35);c.setFont('Helvetica',7.4);c.drawString(M,23,'Synthetic simulation evidence | SQL queries 01-10 | No real-traffic calibration');c.drawRightString(W-M,23,f'{page} / 2')

frame(1);y=H-58
y=p('Why the added road did not<br/>improve travel time',y,size=25)-12
y=p('Decision: do not present this design as a travel-time improvement. In three matched-seed comparisons, the alternative was effectively unchanged relative to closure and did not recover the closure loss.',y,size=10.6)-17
# KPI cards: equal seed weights, never pseudo-replicated people.
metrics=[(f'+{mean(r["mean_delta_s"] for r in closure):.3f} s','Closure minus baseline'),(f'+{mean(r["mean_delta_s"] for r in alt):.3f} s','Alternative minus closure'),('6 / 934','Observed new-road trips / run')]
for i,(value,label) in enumerate(metrics):
 x=M+i*(CW/3);c.setFillColor(white);c.roundRect(x,y-67,CW/3-8,67,5,fill=1,stroke=0)
 p(value,y-10,x+12,CW/3-30,20,rust if i<2 else teal);p(label,y-42,x+12,CW/3-26,8,muted)
y-=84
y=heading('01  A controlled comparison, with explicit denominators',y)
y=p('One fixed synthetic population of 1,037 people; three scenarios per seed (4711, 4712, 4713); iterations 0-9. Each run has 3,623 trips, including 934 car trips. Pairing uses person + trip number, anchored to the before-scenario departure in [0, 30 h). All 934 car keys pair; no mode switches in these comparisons. [Q01-Q03]',y)-11
data=[['Seed','Baseline mean (s)','Closure mean (s)','Alternative mean (s)','Alt. - closure (s)']]
for seed in [4711,4712,4713]:
 data.append([seed]+[f'{find("02",seed=seed,scenario_key=s,mode="car")["mean_time_s"]:.3f}' for s in ['baseline','closure','alternative']]+[f'+{find("03",seed=seed,label="alternative_vs_closure")["mean_delta_s"]:.3f}'])
y=table(data,y,[43,115,115,125,CW-398])-10
y=p('The three-seed average is descriptive. The same population is reused; 2,802 paired records are not 2,802 independent travellers. A +0.098 s difference is not evidence of meaningful deterioration or statistical significance.',y,size=8.6,color=muted)-15
y=heading('02  Small gains are offset by losses',y)
y=p('Alternative versus closure: median change is 0 s and p95 is +1 s for every seed. Positive means slower. Bins use faster <= -1 s, unchanged |delta| < 1 s, slower >= +1 s. [Q03-Q04]',y)-9
for seed in [4711,4712,4713]:
 rr={r['change_bin']:r for r in rows('04') if r['seed']==seed and r['label']=='alternative_vs_closure'}
 p(str(seed),y,M,40,8.6);x=M+48;barw=300
 for key,color in [('faster',teal),('unchanged',HexColor('#c8d3ca')),('slower',rust)]:
  width=barw*rr[key]['trips']/934;c.setFillColor(color);c.rect(x,y-12,width,11,fill=1,stroke=0);x+=width
 p(f"{rr['faster']['trips']} / {rr['unchanged']['trips']} / {rr['slower']['trips']}",y,M+365,CW-365,8.6);y-=24
y=p('Bars: faster / unchanged / slower. Seed 4711 saves 205 trip-seconds but adds 314, leaving +109 / 934 = +0.117 s. Seeds 4712 and 4713 leave +91 and +74 trip-seconds. One trip is +109 s in each seed; its route-level cause is not established here.',y,size=9)-12
y=p('Compared with the original baseline, the alternative remains +7.628 s slower on average across seeds. Low median change therefore does not mean the closure impact was resolved. [Q03-Q04]',y,size=9)
c.showPage()

frame(2);y=H-58
y=p('The explanation, and its limits',y,size=24)-18
y=heading('03  Evidence supporting low route attractiveness and limited reach',y)
route=find('09',seed=4711,direction='forward');usage=find('07',seed=4711)
y=table([['Evidence','Interpretation'],
 [f"Same-endpoint free-flow costs [Q09]<br/>Existing shortest: {route['closure_shortest_s']:.2f} s<br/>Full new corridor: {route['added_corridor_s']:.2f} s / {route['added_corridor_m']:.2f} m",'The new corridor is about 2.05 times the existing minimum. The network minimum is unchanged in both directions after adding it. This supports a lack of endpoint-to-endpoint time advantage; it is not an observed trip-time prediction.'],
 [f"Observed usage [Q07]<br/>{usage['observed_detour_trips']} / 934 car trips ({usage['observed_detour_pct']:.2f}%)<br/>13 of 32 new directed links used",'The new road reaches few recorded trips. Each seed has 17 complete new-link traversals across six trips, not 17 users. Partial entry/exit links are excluded; absence of a complete traversal is not proof of no use.'],
 ['The affected baseline cohort [Q06]<br/>223-226 trips used the closed links','Their mean alternative-minus-baseline change remains +30.37 to +30.89 s. Adding the road changes this cohort by only +0.15 to +0.23 s versus closure; it does not restore the original connection.']],y,[190,CW-190])-13
y=p('Design context: the 356 m corridor was chosen for geometric feasibility before traffic outcomes, with 30 km/h, one lane per direction and capacity 900 vehicles/hour. A footprint-feasible path is not a travel-time-optimised path. Closed links and the new corridor have different endpoints; the direct cost test above deliberately uses the same endpoints. [case_spec.json, Q09]',y,size=9)-15
y=heading('04  What the remaining diagnostics can and cannot tell us',y)
y=p('<b>Observed:</b> the six new-road users are +5.50 to +5.67 s slower on average versus closure. This is a subgroup selected after the intervention, so it is not a causal estimate of the road\'s effect on users. Other trips also change. [Q06]',y,size=9.2)-8
y=p('<b>No broad delay relief is visible on comparable links:</b> the largest absolute mean-time change between alternative and closure is about 0.014 s (links 1871 and 9344). At seed 4711 both move from 72 to 73 complete traversals and from 10.000 to 10.014 s / 7.000 to 7.014 s. Changed geometry and unobserved links are excluded; changing traffic composition still matters. [Q08]',y,size=9.2)-8
y=p('<b>Time windows:</b> alternative minus closure is +0.068 s in 07-09, -0.022 s in 16-18, and +0.107 to +0.166 s otherwise. These descriptive windows do not demonstrate peak congestion relief. [Q05]',y,size=9.2)-15
y=heading('05  Next experiments, in order',y)
y=p('<b>1. Isolate topology from the road itself.</b> Run closure + identical link splits with the new corridor disabled; compare it with the full alternative using matched seeds. This separates junction/splitting effects from added connectivity.<br/><b>2. Test route attractiveness.</b> Inspect actual paths of the six users and the +109 s trip; then test a predeclared speed/capacity grid and demand-linked endpoint choices. Keep plans and seeds fixed.<br/><b>3. Test stability and realism.</b> Increase iterations and check score/route stability, expand seeds, then calibrate against observed demand/counts before making real-world claims. No convergence or policy-benefit claim is made now.',y,size=9.1)-13
y=p('<b>Audit trail.</b> Q01-Q10 map to sql/queries/01_...sql through 10_...sql; aggregate CSVs and source SHA-256 values are in portfolio/evidence/sql/. SQL retains missing/invalid values as NULL and real zero as zero. Nine-run metrics and pair distributions match the existing Python analysis; event parsing is shared, not independently reimplemented. See docs/ANALYTICS.md for definitions and docs/CONTRIBUTIONS.md for upstream and AI-assisted boundaries.',y,size=7.9,color=muted)
c.save();print(path)
