"""Honest out-of-sample check: derive the weights from a random half of the
$4k+ buyers, then measure the resulting score on the half it never saw."""
import pickle, random, math, collections, statistics
people=pickle.load(open("people.pkl","rb")); F=pickle.load(open("feats.pkl","rb"))
random.seed(7)
buyers=[k for k in F if people[k]["maxval"]>=4000]
random.shuffle(buyers)
train=set(buyers[:len(buyers)//2]); test=set(buyers[len(buyers)//2:])
ctrl=[k for k in F if not people[k]["bought_soft"] and (F[k]["booked"] or F[k]["showed"] or F[k]["dq_stage"])]
random.shuffle(ctrl)
ctrl_tr=ctrl[:len(ctrl)//2]; ctrl_te=set(ctrl[len(ctrl)//2:])

FEATS=[("newsletter",lambda f:f["newsletter"]),
       ("live_webinar",lambda f:f["live_webinar_attended"]>=1),
       ("live_webinar_2plus",lambda f:f["live_webinar_attended"]>=2),
       ("cap_15k",lambda f:f["cap_band"]=="15k+"),("cap_10k",lambda f:f["cap_band"]=="10k+"),
       ("cap_5_9k",lambda f:f["cap_band"]=="5-9k"),("cap_1_4k",lambda f:f["cap_band"]=="1-4k"),
       ("cap_unsure",lambda f:f["cap_band"]=="unsure"),("bootcamp",lambda f:f["bootcamp"]),
       ("exp_mod",lambda f:f["exp_band"]=="moderate+"),("exp_none",lambda f:f["exp_band"]=="none"),
       ("paid_only",lambda f:f["paid_social"] and not f["live_webinar_attended"] and not f["newsletter"]),
       ("tier5",lambda f:f["tier5"]),("tier12",lambda f:f["tier12"]),
       ("dq",lambda f:f["dq_tag"] or f["dq_stage"]),
       ("ac_AB",lambda f:f["ac_tier"] in ("A","B")),("ac_D",lambda f:f["ac_tier"]=="D")]

W={}
print(f"{'feature':20} {'buy%':>7} {'ctl%':>7} {'lift':>7} {'weight':>7}   (fit on train half)")
for name,fn in FEATS:
    pb=sum(1 for k in train if fn(F[k]))/len(train)
    pc=sum(1 for k in ctrl_tr if fn(F[k]))/len(ctrl_tr)
    pb=max(pb,0.5/len(train)); pc=max(pc,0.5/len(ctrl_tr))
    w=max(-30,min(30,round(10*math.log2(pb/pc))))
    W[name]=w
    print(f"{name:20} {100*pb:6.1f}% {100*pc:6.1f}% {pb/pc:7.2f} {w:7}")

def sc(k):
    f=F[k]; return sum(W[n] for n,fn in FEATS if fn(f))
print("\n=== out-of-sample: score band vs ACTUAL $4k+ rate on the held-out half ===")
pool=list(test)+list(ctrl_te)+[k for k in F if k not in train and not people[k]["bought_soft"] and k not in ctrl_te]
pool=list(dict.fromkeys(pool))
bins=[(70,10**9),(50,70),(35,50),(20,35),(8,20),(-5,8),(-10**9,-5)]
for lo,hi in bins:
    g=[k for k in pool if lo<=sc(k)<hi]
    if not g: continue
    nb=sum(1 for k in g if k in test)
    lab=f"{lo}+" if hi>10**8 else f"{lo} to {hi}"
    print(f"  score {lab:12} n={len(g):6}  held-out buyers {nb:4} = {100*nb/len(g):6.2f}%")
base=len(test)/len(pool)
print(f"  base rate in this pool: {100*base:.2f}%  (lift at top band = {(100*sum(1 for k in pool if sc(k)>=70 and k in test)/max(1,len([k for k in pool if sc(k)>=70])))/(100*base):.0f}x)")
