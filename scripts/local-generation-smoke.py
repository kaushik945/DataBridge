"""One real synthetic Investigator call. Records failure honestly; no import."""
import asyncio
import argparse
import json
import time
from pathlib import Path

from app.agents import suggest_mapping
from app.cases import cases
from app.config import settings
from app.domain import parse_csv
from app.local_provider import diagnostics
from app.models import DB

parser = argparse.ArgumentParser()
parser.add_argument('--output', default='/tmp/local-generation-smoke.json')
args = parser.parse_args()
if settings.ai_mode != 'local':
    raise SystemExit('Explicit local mode required')
case = next(c for c in cases() if c.name == 'renamed')
headers, rows = parse_csv(case.csv)
started = time.monotonic()
result = {'mode':'local','case':case.name,'reviewer':False,'model':settings.local_model}
try:
    with DB() as db:
        mapping, run = asyncio.run(suggest_mapping(db, headers, rows, reviewer=False))
    result.update(success=True, mapping=mapping.model_dump(), run=run)
except Exception as exc:
    result.update(success=False, error_type=type(exc).__name__, error=str(exc)[:500])
result['wall_seconds'] = round(time.monotonic()-started,3)
result['runtime'] = diagnostics()
Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ('runtime','run','mapping')},indent=2))
