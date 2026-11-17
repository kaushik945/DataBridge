import argparse
import getpass
import os
from pathlib import Path

from argon2 import PasswordHasher
from sqlalchemy import select

from .models import DB, Operator
from .retrieval import ingest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["setup-operator", "ingest", "reindex", "local-diagnostics"]
    )
    parser.add_argument("--username", default="operator")
    parser.add_argument("--path", default="knowledge")
    args = parser.parse_args()
    with DB() as db:
        if args.command == "local-diagnostics":
            import json
            from .local_provider import diagnostics

            print(json.dumps(diagnostics(), indent=2))
        elif args.command in ("ingest", "reindex"):
            if args.command == "reindex":
                from sqlalchemy import delete
                from .models import Chunk
                from .retrieval import collection

                db.execute(delete(Chunk).where(Chunk.collection == collection()))
            print(f"Reindexed {ingest(db, Path(args.path))} documents")
        else:
            if db.scalar(select(Operator)):
                raise SystemExit("An operator already exists; v1 permits one account")
            password = os.environ.get("SETUP_PASSWORD") or getpass.getpass(
                "Operator password (12+ characters): "
            )
            if len(password) < 12:
                raise SystemExit("Use at least 12 characters")
            db.add(
                Operator(
                    username=args.username,
                    password_hash=PasswordHasher().hash(password),
                )
            )
            db.commit()
            print("Operator created")


if __name__ == "__main__":
    main()
