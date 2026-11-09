"""
Run recategorization inside the backend container.

    python -m app.recategorize --dry-run --limit 20
    python -m app.recategorize --apply --batch-id <id> --accepted 101,102
    python -m app.recategorize --rollback --batch-id <id>
    python -m app.recategorize --status --batch-id <id>

``--dry-run`` is the default. It uses the server's Chatwoot token and the
local vLLM client. It does not commit customer changes or call Chatwoot
with POST, PUT, PATCH, or DELETE. ``--rate`` defaults to 1 and cannot exceed 1.
"""

import argparse
import json
import sys

from app.services.recategorize_service import (
    SqlJobStore,
    build_chatwoot_fetchers,
    execute_apply,
    execute_dry_run,
    execute_rollback,
    load_customers_for_apply,
    load_customers_read_only,
    production_label_io,
    production_reset_session,
    save_customer_metadata,
)


def _print(payload) -> None:
    print(json.dumps(payload, default=str, indent=2))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="On-server customer recategorization.")
    parser.add_argument("--dry-run", action="store_true", help="Default mode. CSV and xlsx only.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--batch-id", default="")
    parser.add_argument("--accepted", default="", help="Comma-separated conversation ids from the dry-run CSV.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--conversation-id", default=None)
    parser.add_argument("--rate", type=float, default=1.0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    modes = sum(1 for flag in (args.apply, args.rollback, args.status) if flag)
    if modes > 1:
        sys.stderr.write("Choose only one of --apply, --rollback, or --status.\n")
        return 2
    if args.rate <= 0 or args.rate > 1:
        sys.stderr.write("refused: --rate must be greater than 0 and at most 1 request per second.\n")
        return 2

    store = SqlJobStore()
    if args.status:
        if not args.batch_id:
            sys.stderr.write("--batch-id is required.\n")
            return 2
        job = store.get_job(args.batch_id)
        if not job:
            sys.stderr.write("batch not found\n")
            return 1
        _print(job)
        return 0

    if args.rollback:
        if not args.batch_id:
            sys.stderr.write("--batch-id is required.\n")
            return 2
        store.update_job(args.batch_id, mode="rollback", status="running")
        _read, write_labels = production_label_io()
        outcome = execute_rollback(
            store=store,
            batch_id=args.batch_id,
            customers=load_customers_for_apply(),
            write_labels=write_labels,
            save_customer=save_customer_metadata,
            reset_session=production_reset_session,
        )
        _print(outcome)
        return 0

    if args.apply:
        if not args.batch_id or not args.accepted.strip():
            sys.stderr.write("--apply requires --batch-id and --accepted.\n")
            return 2
        accepted = [item.strip() for item in args.accepted.split(",") if item.strip()]
        store.update_job(args.batch_id, mode="apply", status="running", accepted_ids=accepted)
        read_labels, write_labels = production_label_io()
        outcome = execute_apply(
            store=store,
            batch_id=args.batch_id,
            accepted_conversation_ids=accepted,
            customers=load_customers_for_apply(),
            read_labels=read_labels,
            write_labels=write_labels,
            save_customer=save_customer_metadata,
            reset_session=production_reset_session,
        )
        _print(outcome)
        return 0

    job = store.create_job(
        batch_id=args.batch_id or None,
        mode="dry_run",
        rate=args.rate,
        conversation_limit=args.limit,
        conversation_id=args.conversation_id,
    )
    if args.resume and args.batch_id:
        existing = store.get_job(args.batch_id)
        if existing:
            job = existing
    fetch_page, fetch_details = build_chatwoot_fetchers(args.rate)
    outcome = execute_dry_run(
        customers=load_customers_read_only(),
        fetch_page=fetch_page,
        fetch_details=fetch_details,
        store=store,
        batch_id=job["batch_id"],
        limit=args.limit,
        conversation_id=args.conversation_id,
        resume=args.resume,
    )
    summary = outcome["summary"]
    print(f"dry-run csv: {outcome['output_csv']}")
    print(f"dry-run xlsx: {outcome['output_xlsx']}")
    print("proposed_category temperature count")
    for key, count in sorted(summary.items()):
        category, temperature = key.split("|", 1)
        print(f"{category} {temperature} {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
