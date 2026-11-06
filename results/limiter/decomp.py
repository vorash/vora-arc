import json,sys,statistics as st,collections
rows=[json.loads(l) for l in open(sys.argv[1])]
H={r['session']:r for r in rows if r['type']=='header'}; F={r['session']:r for r in rows if r['type']=='footer'}
R=[r for r in rows if r['type']=='run' and r['phase']!='warmup']
print('phases',collections.Counter(r['phase'] for r in rows if r['type']=='run'))
arms=collections.defaultdict(list)
for r in R: arms[r['arm']].append(r)
def m(x): return round(st.mean(x),2) if x else None
def med(x): return round(st.median(x),2) if x else None
for a,rs in arms.items():
    sess=[s for s,h in H.items() if h.get('arm')==a or any(True for r in rs[:1] if r['session']==s)]
    ss=sorted({r['session'] for r in rs})
    meas=sum(F[s]['measured_seconds'] for s in ss); cpu=sum(F[s]['client_cpu_seconds'] for s in ss)
    conc=8
    ceiling=conc*1000/st.mean(r['cycle_ms'] for r in rs)
    print(f"\n{a}: n={len(rs)} measured_s={meas:.1f} prog/s={len(rs)/meas:.1f} ceiling(8*1000/mean cycle)={ceiling:.1f} client_cpu%window={100*cpu/meas:.0f}")
    print(' mean wall',m([r['wall_ms'] for r in rs]),'cycle',m([r['cycle_ms'] for r in rs]),'client_startup',m([r['client_startup_ms'] for r in rs]),'exec',m([r['exec_ms'] for r in rs]),'median exec',med([r['exec_ms'] for r in rs]))
    print(' cycle-wall mean',m([r['cycle_ms']-r['wall_ms'] for r in rs]),'median',med([r['cycle_ms']-r['wall_ms'] for r in rs]))
    su=[r['startup_ms'] for r in rs if r['startup_ms'] is not None]; print(' startup_ms mean',m(su),'median',med(su),'n',len(su))
    rz=[r['reset_ms'] for r in rs if r['reset_ms'] is not None]; print(' reset_ms mean',m(rz),'n',len(rz))
    print(' outcomes',dict(collections.Counter(r['reset_outcome'] for r in rs)),'retire',dict(collections.Counter(r['retire_cause'] for r in rs)))
    cls=collections.defaultdict(list)
    for r in rs: cls[r['candidate_class']].append(r['wall_ms'])
    tot=sum(sum(v) for v in cls.values())
    print(' class: median wall, share of slot time');
    for c,v in sorted(cls.items(),key=lambda kv:-sum(kv[1])): print(f"   {c:18} n={len(v):5} med={st.median(v):8.1f} share={100*sum(v)/tot:5.1f}%")
    print(' per session prog/s',[round(sum(1 for r in rs if r['session']==s)/F[s]['measured_seconds'],1) for s in ss])
    print(' load at start',[round(H[s]['load_start'][0],1) if 'load_start' in H[s] else None for s in ss])
