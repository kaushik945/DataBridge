"""Fresh-process diagnostic on the existing development reproduction."""

import asyncio
import cProfile
import io
import json
import pstats
from pathlib import Path

from app.agents import suggest_mapping
from app.cases import cases
from app.domain import parse_csv
from app.models import DB

case = next(case for case in cases() if case.name == "country_optionality_review_regression")
headers, rows = parse_csv(case.csv)
profiler = cProfile.Profile()
with DB() as db:
    profiler.enable()
    _, run = asyncio.run(suggest_mapping(db, headers, rows, reviewer=True))
    profiler.disable()
profiler.dump_stats("/tmp/local-initialization.pstats")
stream = io.StringIO()
stats = pstats.Stats(profiler, stream=stream).sort_stats("cumulative")
stats.print_stats(45)
Path("/tmp/local-initialization.txt").write_text(stream.getvalue())
Path("/tmp/local-initialization.json").write_text(json.dumps({
    "note": "One fresh Python process, existing development input, cProfile overhead included. Excluded from latency comparisons and prospective evaluation.",
    "run": run,
}, indent=2))
print(stream.getvalue())
