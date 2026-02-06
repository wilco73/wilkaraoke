#!/usr/bin/env python3
"""
🎤 N'oubliez pas les Paroles — Outil d'upload R2
=================================================
Upload, liste et gère tes chansons sur Cloudflare R2.

Configuration (variables d'environnement ou fichier .env) :
  R2_BUCKET_NAME       - Nom du bucket
  R2_ACCOUNT_ID        - Account ID Cloudflare
  R2_ACCESS_KEY_ID     - Clé d'accès
  R2_SECRET_ACCESS_KEY - Clé secrète
  R2_PUBLIC_URL        - URL publique (optionnel)

Usage :
  python upload.py add videos/ma-chanson/        Upload un dossier chanson
  python upload.py add videos/ma-chanson/ --id mon-titre   Upload avec ID custom
  python upload.py list                          Liste les chansons sur R2
  python upload.py delete ma-chanson             Supprime une chanson
  python upload.py sync videos/                  Upload toutes les chansons d'un dossier
"""

import argparse
import json
import mimetypes
import os
import sys
from pathlib import Path

# ============================================================
# CONFIG — charge depuis .env si présent
# ============================================================
def load_env():
    """Charge les variables depuis .env si le fichier existe."""
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    value = value.strip().strip("'\"")
                    os.environ.setdefault(key.strip(), value)

load_env()

R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "")
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "")

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".avi", ".mov", ".m4v", ".ogg"}
UPLOAD_EXTENSIONS = VIDEO_EXTENSIONS | {".srt", ".json", ".txt", ".vtt"}


def check_config():
    missing = []
    if not R2_BUCKET_NAME: missing.append("R2_BUCKET_NAME")
    if not R2_ACCOUNT_ID: missing.append("R2_ACCOUNT_ID")
    if not R2_ACCESS_KEY_ID: missing.append("R2_ACCESS_KEY_ID")
    if not R2_SECRET_ACCESS_KEY: missing.append("R2_SECRET_ACCESS_KEY")

    if missing:
        print("❌ Variables d'environnement manquantes :")
        for m in missing:
            print(f"   - {m}")
        print()
        print("Créez un fichier .env à côté de ce script :")
        print('   R2_BUCKET_NAME="mon-bucket"')
        print('   R2_ACCOUNT_ID="abc123"')
        print('   R2_ACCESS_KEY_ID="..."')
        print('   R2_SECRET_ACCESS_KEY="..."')
        print('   R2_PUBLIC_URL="https://pub-xxx.r2.dev"')
        sys.exit(1)


def get_s3_client():
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        print("❌ boto3 requis : pip install boto3")
        sys.exit(1)

    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


# ============================================================
# COMMANDS
# ============================================================
def cmd_add(args):
    """Upload un dossier chanson vers R2."""
    folder = Path(args.path)

    if not folder.is_dir():
        print(f"❌ '{folder}' n'est pas un dossier")
        sys.exit(1)

    # Vérifier qu'il y a au moins un SRT
    srt_files = [f for f in folder.iterdir() if f.suffix.lower() == ".srt"]
    if not srt_files:
        print(f"❌ Aucun fichier .srt trouvé dans '{folder}'")
        print("   Générez-en un avec : python generate_subtitles.py " + str(folder))
        sys.exit(1)

    # ID du dossier sur R2
    song_id = args.id if args.id else folder.name
    song_id = song_id.lower().replace(" ", "-")

    s3 = get_s3_client()

    # Lister les fichiers à uploader
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in UPLOAD_EXTENSIONS]

    if not files:
        print(f"❌ Aucun fichier uploadable trouvé dans '{folder}'")
        sys.exit(1)

    print(f"📤 Upload de '{song_id}' vers R2...")
    print()

    for filepath in files:
        key = f"{song_id}/{filepath.name}"
        content_type = mimetypes.guess_type(str(filepath))[0] or "application/octet-stream"
        file_size = filepath.stat().st_size
        size_str = format_size(file_size)

        print(f"  ⬆️  {filepath.name} ({size_str})...", end=" ", flush=True)

        with open(filepath, "rb") as f:
            s3.upload_fileobj(
                f,
                R2_BUCKET_NAME,
                key,
                ExtraArgs={"ContentType": content_type},
            )

        print("✅")

    print()
    print(f"✨ '{song_id}' uploadé avec succès !")

    if R2_PUBLIC_URL:
        video_files = [f for f in files if f.suffix.lower() in VIDEO_EXTENSIONS]
        if video_files:
            url = f"{R2_PUBLIC_URL.rstrip('/')}/{song_id}/{video_files[0].name}"
            print(f"🔗 URL vidéo : {url}")

    print("   Rafraîchissez l'app pour voir la chanson.")


def cmd_list(args):
    """Liste les chansons sur R2."""
    s3 = get_s3_client()

    print("📚 Chansons sur R2 :\n")

    folders = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=R2_BUCKET_NAME):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            parts = key.split("/", 1)
            if len(parts) == 2:
                folder = parts[0]
                filename = parts[1]
                if folder not in folders:
                    folders[folder] = {"files": [], "total_size": 0}
                folders[folder]["files"].append(filename)
                folders[folder]["total_size"] += obj["Size"]

    if not folders:
        print("  (vide)")
        return

    for folder in sorted(folders):
        info = folders[folder]
        files = info["files"]
        size = format_size(info["total_size"])
        has_video = any(os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS for f in files)
        has_srt = any(f.endswith(".srt") for f in files)
        has_config = any(f == "config.json" for f in files)

        status = "🎬" if has_video else "🎵"
        srt_status = "✅" if has_srt else "❌"
        config_status = "✅" if has_config else "➖"

        print(f"  {status} {folder}/")
        print(f"     Fichiers: {', '.join(files)}")
        print(f"     Taille: {size} | SRT: {srt_status} | Config: {config_status}")
        print()

    print(f"  Total : {len(folders)} chanson(s)")


def cmd_delete(args):
    """Supprime une chanson de R2."""
    song_id = args.song_id
    s3 = get_s3_client()

    # Lister les fichiers du dossier
    objects = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=R2_BUCKET_NAME, Prefix=f"{song_id}/"):
        for obj in page.get("Contents", []):
            objects.append({"Key": obj["Key"]})

    if not objects:
        print(f"❌ Chanson '{song_id}' non trouvée sur R2")
        sys.exit(1)

    print(f"🗑  Suppression de '{song_id}' ({len(objects)} fichiers)...")

    # Confirmation
    confirm = input("   Confirmer ? (oui/non) : ").strip().lower()
    if confirm not in ("oui", "o", "yes", "y"):
        print("   Annulé.")
        return

    s3.delete_objects(Bucket=R2_BUCKET_NAME, Delete={"Objects": objects})
    print(f"✅ '{song_id}' supprimé.")


def cmd_sync(args):
    """Upload toutes les chansons d'un dossier local."""
    base_dir = Path(args.path)
    if not base_dir.is_dir():
        print(f"❌ '{base_dir}' n'est pas un dossier")
        sys.exit(1)

    folders = [f for f in sorted(base_dir.iterdir())
               if f.is_dir() and not f.name.startswith("_")]

    if not folders:
        print(f"❌ Aucun sous-dossier trouvé dans '{base_dir}'")
        sys.exit(1)

    print(f"📤 Sync de {len(folders)} dossier(s)...\n")

    s3 = get_s3_client()

    for folder in folders:
        srt_files = [f for f in folder.iterdir() if f.suffix.lower() == ".srt"]
        if not srt_files:
            print(f"  ⏭  {folder.name}/ — pas de .srt, ignoré")
            continue

        song_id = folder.name.lower().replace(" ", "-")
        files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in UPLOAD_EXTENSIONS]

        print(f"  📤 {song_id}/ ({len(files)} fichiers)...", end=" ", flush=True)

        for filepath in files:
            key = f"{song_id}/{filepath.name}"
            content_type = mimetypes.guess_type(str(filepath))[0] or "application/octet-stream"

            with open(filepath, "rb") as f:
                s3.upload_fileobj(f, R2_BUCKET_NAME, key, ExtraArgs={"ContentType": content_type})

        print("✅")

    print(f"\n✨ Sync terminé !")


# ============================================================
# HELPERS
# ============================================================
def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / 1024**2:.1f} MB"
    else:
        return f"{size_bytes / 1024**3:.1f} GB"


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="🎤 Gestion des chansons sur Cloudflare R2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="Commande")

    # add
    p_add = sub.add_parser("add", help="Upload un dossier chanson")
    p_add.add_argument("path", help="Chemin du dossier chanson")
    p_add.add_argument("--id", help="ID custom (défaut: nom du dossier)")

    # list
    sub.add_parser("list", help="Liste les chansons sur R2")

    # delete
    p_del = sub.add_parser("delete", help="Supprime une chanson")
    p_del.add_argument("song_id", help="ID de la chanson à supprimer")

    # sync
    p_sync = sub.add_parser("sync", help="Upload toutes les chansons d'un dossier")
    p_sync.add_argument("path", help="Dossier contenant les sous-dossiers chansons")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    check_config()

    if args.command == "add":
        cmd_add(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "delete":
        cmd_delete(args)
    elif args.command == "sync":
        cmd_sync(args)


if __name__ == "__main__":
    main()
