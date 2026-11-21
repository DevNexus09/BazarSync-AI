"""Validate or explicitly seed the local demo footwear seller."""

from __future__ import annotations

import argparse
from getpass import getpass
import json
import os
from pathlib import Path
import sys

from pydantic import ValidationError

from app.db.session import SessionLocal
from app.services.demo_seed_service import (
    DEFAULT_MANIFEST,
    DemoFootwearSeedService,
    DemoSeedError,
    load_demo_manifest,
)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    mode = cli.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Write seed-managed records.")
    mode.add_argument("--dry-run", action="store_true", help="Inspect without writing (default).")
    cli.add_argument("--validate", action="store_true", help="Validate the manifest and exit.")
    cli.add_argument("--report", type=Path, help="Write the JSON result to this path.")
    cli.add_argument("--with-synthetic-sales", action="store_true")
    cli.add_argument("--update-managed-records", action="store_true")
    return cli


def main() -> int:
    args = parser().parse_args()
    try:
        manifest = load_demo_manifest(args.manifest)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"manifest_validation_failed error_type={type(exc).__name__}", file=sys.stderr)
        return 2
    if args.validate:
        payload = {
            "manifest_valid": True,
            "verified_products": len(manifest.products),
            "target_products": 15,
            "listing_ids": [item.listing_id for item in manifest.products],
        }
        print(json.dumps(payload, indent=2))
        return 0

    password = None
    if args.apply:
        password = os.getenv("DEMO_SELLER_PASSWORD")
        if not password:
            password = getpass("Demo seller password: ")
    try:
        with SessionLocal() as session:
            result = DemoFootwearSeedService(session).run(
                manifest=manifest,
                manifest_path=args.manifest,
                apply=args.apply,
                password=password,
                with_synthetic_sales=args.with_synthetic_sales,
                update_managed_records=args.update_managed_records,
            )
    except DemoSeedError as exc:
        print(f"demo_seed_failed reason={exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"demo_seed_failed error_type={type(exc).__name__}", file=sys.stderr)
        return 4

    payload = result.to_dict()
    rendered = json.dumps(payload, indent=2, default=str)
    print(rendered)
    if args.report:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
