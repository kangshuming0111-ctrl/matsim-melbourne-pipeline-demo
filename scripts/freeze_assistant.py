"""Lock code/prompt/model before the first holdout evaluation."""
import json
from datetime import datetime,timezone
from wrapper.analytics import ROOT
from wrapper.ai_provider import status
from scripts.evaluate_assistant import code_hashes
path=ROOT/'evals/assistant/holdout-freeze.json'
if path.exists():raise FileExistsError('Freeze already exists; do not overwrite held-out protocol')
path.write_text(json.dumps({'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'code_sha256':code_hashes(),'model':status()},indent=2)+'\n')
print('Holdout implementation frozen')
