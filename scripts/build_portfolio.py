"""Build the offline page from its reviewed aggregate evidence, without network access."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
directory=ROOT/"portfolio"
data=json.loads((directory/"evidence/case.json").read_text(encoding="utf-8"))
sql=json.loads((directory/'evidence/sql/sql-evidence.json').read_text(encoding='utf-8'))['results']
sql_embedded=json.dumps({k:v for k,v in sql.items() if k[:2] in ('03','04','07','09')},allow_nan=False).replace('<','\\u003c')
ai=json.loads((directory/'evidence/ai/evaluation.json').read_text(encoding='utf-8'))
ai_embedded=json.dumps(ai,ensure_ascii=False,allow_nan=False).replace('<','\\u003c')
template=(directory/"template.html").read_text(encoding="utf-8")
embedded=json.dumps(data,ensure_ascii=False,allow_nan=False).replace("<", "\\u003c")
(directory/"index.html").write_text(template.replace("__CASE_JSON__",embedded).replace("__SQL_JSON__",sql_embedded).replace("__AI_JSON__",ai_embedded),encoding="utf-8")
print("Built portfolio/index.html from portfolio/evidence/case.json")
