"""Build standalone Nginx/Docker static error pages with the current Makken theme."""
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string

from core.error_content import CATALOG, page_context


class Command(BaseCommand):
    help = "Generate static HTML error pages and ocean-blue theme assets inside the repo/Docker output directory."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=str(Path(settings.BASE_DIR) / "makken_errors"),
            help="Target directory for generated error HTML files and assets/",
        )
        parser.add_argument(
            "--asset-base",
            default=getattr(settings, "MAKKEN_ERROR_ASSET_BASE", "/__makken_errors/assets/"),
            help="Public URL prefix for error page assets",
        )

    def handle(self, *args, **options):
        out_dir = Path(options["output"])
        assets_dir = out_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        src_assets = Path(settings.BASE_DIR) / "core" / "static" / "core" / "errors"
        for filename in ("error.css", "error.js", "header-logo.svg"):
            shutil.copy2(src_assets / filename, assets_dir / filename)

        asset_base = options["asset_base"]
        for code in sorted(CATALOG):
            context = page_context(code, asset_base=asset_base, method="GET", seconds=20)
            html = render_to_string("core/errors/error.html", context)
            (out_dir / f"{code}.html").write_text(html, encoding="utf-8")

        self.stdout.write(
            self.style.SUCCESS(f"Built {len(CATALOG)} error pages and assets in {out_dir}")
        )
