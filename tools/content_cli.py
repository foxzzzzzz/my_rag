"""Explicitly backfill or reconcile durable knowledge files."""
import argparse, json
from personalkb.workflow import load_config, make_store

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command', choices=['reconcile','verify'])
    parser.add_argument('--config')
    parser.add_argument('--source-id')
    args=parser.parse_args()
    store=make_store(load_config(args.config))
    if args.command=='reconcile': result=store.reconcile(args.source_id)
    else:
        ids=[args.source_id] if args.source_id else [s['id'] for s in store.list_sources()]
        result={sid:store.content_status(sid) for sid in ids}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if all(x=='synced' for x in result.values()) else 1
if __name__=='__main__': raise SystemExit(main())
