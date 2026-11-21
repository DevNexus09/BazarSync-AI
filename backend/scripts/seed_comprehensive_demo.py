"""Seed or validate the interconnected local BazarSync demo account."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from app.db.session import SessionLocal
from app.services.comprehensive_demo_seed_service import ComprehensiveDemoSeedService
from app.services.demo_seed_service import DemoSeedError


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--email", default="demo1@gmail.com")
    cli.add_argument("--as-of", type=date.fromisoformat)
    cli.add_argument("--apply", action="store_true", help="Write seller-scoped demo data.")
    cli.add_argument("--dry-run", action="store_true", help="Inspect scope without writes (default).")
    cli.add_argument("--validate-only", action="store_true")
    cli.add_argument("--skip-external-services", action="store_true")
    cli.add_argument("--report", type=Path, default=Path("artifacts/comprehensive-demo-seed-report.json"))
    cli.add_argument("--markdown-report", type=Path, default=Path("artifacts/comprehensive-demo-seed-report.md"))
    return cli


def main() -> int:
    args = parser().parse_args()
    if args.email.casefold() != "demo1@gmail.com":
        print("demo_seed_failed reason=only demo1@gmail.com is allowed", file=sys.stderr)
        return 2
    as_of = args.as_of or datetime.now(ZoneInfo("Asia/Dhaka")).date()
    apply = bool(args.apply and not args.validate_only)
    try:
        with SessionLocal() as session:
            service = ComprehensiveDemoSeedService(session, as_of_date=as_of)
            result = service.run(
                apply=apply,
                validate_only=args.validate_only,
                skip_external_services=args.skip_external_services,
            )
            payload = result.to_dict()
            rendered = json.dumps(payload, indent=2, default=str)
            print(rendered)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered + "\n", encoding="utf-8")
            service.write_markdown_report(result, args.markdown_report)
    except DemoSeedError as exc:
        print(f"demo_seed_failed reason={exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"demo_seed_failed error_type={type(exc).__name__} reason={exc}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

