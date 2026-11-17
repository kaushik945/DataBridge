"""Run inside the local backend container; writes evidence from actual embeddings."""
import argparse
import json
from pathlib import Path

from sqlalchemy import func, select

from app.config import settings
from app.local_provider import diagnostics
from app.models import Chunk, DB
from app.retrieval import collection, embed

if settings.ai_mode != 'local':
    raise SystemExit('Explicit local mode required')
parser = argparse.ArgumentParser()
parser.add_argument('--output', default='/tmp/local-rag-smoke.json')
args = parser.parse_args()
query = 'subscription plan starter professional business approved aliases'
vector = embed([query], 'RETRIEVAL_QUERY')[0]
coll = collection()
with DB() as db:
    count = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.collection == coll))
    hits = list(db.execute(select(Chunk, Chunk.embedding.cosine_distance(vector).label('distance'))
        .where(Chunk.collection == coll).order_by('distance').limit(4)))
    report = {'mode':'local', 'embedding_collection':coll, 'persisted_chunks':count,
              'query':query, 'query_dimensions':len(vector),
              'matches':[{'id':c.id,'title':c.title,'document':c.document,'text':c.text,
                  'content_hash':c.content_hash,'distance':float(distance),'stored_dimensions':len(c.embedding)} for c,distance in hits],
              'runtime':diagnostics()}
Path(args.output).write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ('matches','runtime')},indent=2))
print('Retrieved:', ', '.join(c.title for c,_ in hits))
