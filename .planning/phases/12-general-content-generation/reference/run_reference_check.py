from medical_safety_reference import *
from safety_cases import *
def rep(name, items, fn, expect):
    bad=[(s,fn(s)) for s in items if bool(fn(s))!=expect]
    print(f"{name}: {len(items)-len(bad)}/{len(items)} OK; wrong={bad}")
rep("DOSAGE_POS(應攔)",DOSAGE_POS,check_dosage_prescription,True)
rep("DOSAGE_NEG(應放)",DOSAGE_NEG,check_dosage_prescription,False)
rep("WARN_POS",WARN_POS,has_doctor_warning,True)
rep("WARN_NEG",WARN_NEG,has_doctor_warning,False)
print("integration",[(s,check_dosage_prescription(s),has_doctor_warning(s)) for s in INTEGRATION if check_dosage_prescription(s) or not has_doctor_warning(s)])
print("conservative",[(s,check_dosage_prescription(s)) for s in DOSAGE_KNOWN_CONSERVATIVE])
print(len(DOSAGE_POS),len(DOSAGE_NEG),len(WARN_POS),len(WARN_NEG))
import sqlite3
c=sqlite3.connect("file:/home/hsu/Desktop/clinicbrain/clinic.db?mode=ro",uri=True)
rej=[]
for i,q,a in c.execute("select id,question,answer from faq_cache where source_type='clinic_upload'"):
    r=check_dosage_prescription(a)
    if r: rej.append((i,r))
print("clinic backscan rejects:",rej, "of", c.execute("select count(*) from faq_cache").fetchone())
