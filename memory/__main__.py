"""Maintenance: python -m memory status|backfill|index [--batches N]."""

import argparse
import json

from sqlalchemy.orm import Session

from db.migrate import migrate
from db.repository import engine, init_db
from memory.indexer import backfill_batch, index_lexical_batch, index_vector_batch, initialize
from memory.retrieval import status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "backfill", "index"])
    parser.add_argument("--batches", type=int, default=1, help="Bounded batches; repeat to resume")
    args = parser.parse_args()
    init_db()
    migrate(engine)
    initialize(engine)
    if args.command != "status":
        for _ in range(max(1, args.batches)):
            backfill_batch(engine)
            index_lexical_batch(engine)
            if args.command == "index":
                index_vector_batch(engine)
    with Session(engine) as db:
        print(json.dumps(status(db), indent=2))


if __name__ == "__main__":
    main()
