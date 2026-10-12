"""データベースと保存ファイルのバックアップ。

    uv run manage.py backup                # backups/ に作成し、30世代を保持
    uv run manage.py backup --dir /mnt/nas/kustomfinance --keep 90

復元:
    pg_restore --clean --if-exists -d kustomfinance backups/db_YYYYmmdd_HHMMSS.dump
    tar -xzf backups/media_YYYYmmdd_HHMMSS.tar.gz -C <MEDIA_ROOT の親ディレクトリ>
"""

import os
import shutil
import subprocess
import tarfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "PostgreSQL のダンプと保存ファイル（media）をバックアップします"

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=str(settings.BASE_DIR / "backups"), help="保存先ディレクトリ")
        parser.add_argument("--keep", type=int, default=30, help="保持する世代数")

    def handle(self, *args, **options):
        if not shutil.which("pg_dump"):
            raise CommandError(
                "pg_dump が見つかりません。PostgreSQL クライアントをインストールしてください。"
            )
        out = Path(options["dir"])
        out.mkdir(parents=True, exist_ok=True)
        stamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        db = settings.DATABASES["default"]
        env = {**os.environ, "PGPASSWORD": str(db.get("PASSWORD") or "")}
        cmd = ["pg_dump", "-Fc", "-f", str(out / f"db_{stamp}.dump"), "-d", db["NAME"]]
        for flag, key in (("-h", "HOST"), ("-p", "PORT"), ("-U", "USER")):
            if db.get(key):
                cmd += [flag, str(db[key])]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise CommandError(f"pg_dump に失敗しました: {result.stderr.strip()}")
        media = Path(settings.MEDIA_ROOT)
        if media.exists():
            with tarfile.open(out / f"media_{stamp}.tar.gz", "w:gz") as tar:
                tar.add(media, arcname=media.name)
        for pattern in ("db_*.dump", "media_*.tar.gz"):
            for old in sorted(out.glob(pattern))[: -options["keep"]]:
                old.unlink()
        self.stdout.write(self.style.SUCCESS(f"バックアップを作成しました: {out}/db_{stamp}.dump"))
