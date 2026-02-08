#!/usr/bin/env python3
"""
🎤 N'oubliez pas les Paroles — Serveur Cloud
=============================================
Serveur qui lit les chansons depuis Cloudflare R2 et sert le frontend.

Peut fonctionner en deux modes :
  - LOCAL  : lit depuis un dossier local (./videos/)
  - CLOUD  : lit depuis un bucket Cloudflare R2

Le mode est déterminé automatiquement :
  - Si la variable R2_BUCKET_NAME est définie → mode cloud
  - Sinon → mode local

Variables d'environnement (mode cloud) :
  R2_BUCKET_NAME       - Nom du bucket R2
  R2_ACCOUNT_ID        - Account ID Cloudflare
  R2_ACCESS_KEY_ID     - Clé d'accès R2
  R2_SECRET_ACCESS_KEY - Clé secrète R2
  R2_PUBLIC_URL        - URL publique du bucket (ex: https://pub-xxx.r2.dev)

Variables optionnelles :
  PORT                 - Port du serveur (défaut: 8742)
  VIDEOS_DIR           - Dossier local des vidéos (défaut: ./videos)
"""

import http.server
import json
import os
import re
import sys
import random
import mimetypes
import urllib.parse
import threading
import time
from pathlib import Path
from io import BytesIO

# ============================================================
# CONFIG
# ============================================================
PORT = int(os.environ.get("PORT", 8742))
VIDEOS_DIR = os.environ.get("VIDEOS_DIR", "./videos")

# R2 Config
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "")
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "")  # URL publique pour les vidéos

IS_CLOUD = bool(R2_BUCKET_NAME)

# ============================================================
# SRT PARSER
# ============================================================
def parse_srt(content):
    """Parse du contenu SRT (string) et retourne une liste de cues."""
    cues = []
    blocks = re.split(r"\n\s*\n", content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        timestamp_line = None
        text_lines = []
        for i, line in enumerate(lines):
            if "-->" in line:
                timestamp_line = line
                text_lines = lines[i + 1:]
                break

        if not timestamp_line:
            continue

        match = re.match(
            r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})",
            timestamp_line.strip(),
        )
        if not match:
            continue

        g = match.groups()
        start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000
        end = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000

        text = " ".join(text_lines)
        text = re.sub(r"<[^>]+>", "", text).strip()

        if text:
            cues.append({"start": round(start, 3), "end": round(end, 3), "text": text})

    return cues


def parse_srt_file(filepath):
    """Parse un fichier SRT depuis le disque."""
    try:
        with open(filepath, "r", encoding="utf-8-sig") as f:
            return parse_srt(f.read())
    except UnicodeDecodeError:
        with open(filepath, "r", encoding="latin-1") as f:
            return parse_srt(f.read())


# ============================================================
# R2 STORAGE BACKEND
# ============================================================
s3_client = None

def init_r2():
    """Initialise la connexion R2 via boto3."""
    global s3_client
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        print("❌ boto3 requis pour le mode cloud : pip install boto3")
        sys.exit(1)

    endpoint = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

    s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )
    print(f"  ☁️  Connecté à R2 : {R2_BUCKET_NAME}")


def r2_list_folders():
    """Liste les 'dossiers' (préfixes) dans le bucket R2."""
    folders = set()
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=R2_BUCKET_NAME, Delimiter="/"):
        for prefix in page.get("CommonPrefixes", []):
            folder = prefix["Prefix"].rstrip("/")
            if not folder.startswith("_"):
                folders.add(folder)
    return sorted(folders)


def r2_get_text(key):
    """Récupère un fichier texte depuis R2."""
    try:
        response = s3_client.get_object(Bucket=R2_BUCKET_NAME, Key=key)
        return response["Body"].read().decode("utf-8")
    except Exception:
        return None


def r2_file_exists(key):
    """Vérifie si un fichier existe dans R2."""
    try:
        s3_client.head_object(Bucket=R2_BUCKET_NAME, Key=key)
        return True
    except Exception:
        return False


def r2_find_video(folder):
    """Trouve un fichier vidéo dans un dossier R2."""
    video_exts = {".mp4", ".webm", ".mkv", ".avi", ".mov", ".m4v", ".ogg"}
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=R2_BUCKET_NAME, Prefix=f"{folder}/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            ext = os.path.splitext(key)[1].lower()
            if ext in video_exts:
                return key
    return None


# ============================================================
# LIBRARY SCANNER
# ============================================================
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".avi", ".mov", ".m4v", ".ogg"}


def scan_library_local(videos_dir):
    """Scanne un dossier local."""
    songs = []
    videos_path = Path(videos_dir)

    if not videos_path.exists():
        videos_path.mkdir(parents=True, exist_ok=True)
        return songs

    for folder in sorted(videos_path.iterdir()):
        if not folder.is_dir() or folder.name.startswith("_"):
            continue

        # Chercher vidéo
        video_file = None
        for f in folder.iterdir():
            if f.suffix.lower() in VIDEO_EXTENSIONS:
                video_file = f
                break

        # Chercher SRT
        srt_file = None
        for f in folder.iterdir():
            if f.suffix.lower() == ".srt":
                srt_file = f
                break

        if not srt_file:
            continue

        # Config
        config = {}
        config_file = folder / "config.json"
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                pass

        lyrics = parse_srt_file(srt_file)
        if not lyrics:
            continue

        duration = max(c["end"] for c in lyrics)
        default_title = folder.name.replace("-", " ").replace("_", " ").title()

        # Support cutoff_windows (nouveau) ou cutoff_time (ancien format)
        cutoff_windows = config.get("cutoff_windows", None)
        if not cutoff_windows:
            # Rétro-compatibilité: convertir cutoff_time en une fenêtre
            ct = config.get("cutoff_time", round(duration * 0.5, 1))
            cutoff_windows = [[ct, duration]]

        song = {
            "id": folder.name,
            "title": config.get("title", default_title),
            "artist": config.get("artist", "Artiste inconnu"),
            "difficulty": config.get("difficulty", "medium"),
            "cutoff_windows": cutoff_windows,
            "subtitle_offset": config.get("subtitle_offset", 0),
            "duration": duration,
            "has_video": video_file is not None,
            "video_url": f"/videos/{folder.name}/{video_file.name}" if video_file else None,
            "lyrics": lyrics,
            "folder": folder.name,
        }
        songs.append(song)
        windows_str = ", ".join(f"{float(w[0]):.0f}s→{float(w[1]):.0f}s" for w in cutoff_windows)
        print(f"  🎬 {song['title']} — {song['artist']} ({len(lyrics)} cues, coupures: {windows_str})")

    return songs


def scan_library_r2():
    """Scanne le bucket R2."""
    songs = []
    folders = r2_list_folders()

    for folder in folders:
        # Chercher SRT
        srt_content = r2_get_text(f"{folder}/subtitles.srt")
        if not srt_content:
            print(f"  ⏭  {folder}/ → pas de subtitles.srt")
            continue

        lyrics = parse_srt(srt_content)
        if not lyrics:
            continue

        # Config
        config = {}
        config_text = r2_get_text(f"{folder}/config.json")
        if config_text:
            try:
                config = json.loads(config_text)
            except Exception:
                pass

        # Chercher vidéo
        video_key = r2_find_video(folder)
        has_video = video_key is not None
        video_url = None
        if has_video and R2_PUBLIC_URL:
            video_url = f"{R2_PUBLIC_URL.rstrip('/')}/{video_key}"

        duration = max(c["end"] for c in lyrics)
        default_title = folder.replace("-", " ").replace("_", " ").title()

        # Support cutoff_windows (nouveau) ou cutoff_time (ancien format)
        cutoff_windows = config.get("cutoff_windows", None)
        if not cutoff_windows:
            ct = config.get("cutoff_time", round(duration * 0.5, 1))
            cutoff_windows = [[ct, duration]]

        song = {
            "id": folder,
            "title": config.get("title", default_title),
            "artist": config.get("artist", "Artiste inconnu"),
            "difficulty": config.get("difficulty", "medium"),
            "cutoff_windows": cutoff_windows,
            "subtitle_offset": config.get("subtitle_offset", 0),
            "duration": duration,
            "has_video": has_video,
            "video_url": video_url,
            "lyrics": lyrics,
            "folder": folder,
        }
        songs.append(song)
        windows_str = ", ".join(f"{float(w[0]):.0f}s→{float(w[1]):.0f}s" for w in cutoff_windows)
        status = "🎬" if has_video else "🎵"
        print(f"  {status} {song['title']} — {song['artist']} ({len(lyrics)} cues, coupures: {windows_str})")

    return songs


def scan_library():
    """Scanne selon le mode (local ou cloud)."""
    if IS_CLOUD:
        return scan_library_r2()
    else:
        return scan_library_local(VIDEOS_DIR)


# ============================================================
# HTTP SERVER
# ============================================================
# ============================================================
# GAME STATE — room-based (shared between regie and overlay)
# ============================================================
game_rooms = {}   # { room_id: { state: {...}, last_activity: timestamp } }
rooms_lock = threading.Lock()

ROOM_EXPIRY_SECONDS = 2 * 3600  # 2 hours


def get_room_state(room_id):
    """Get state for a room, or empty state if not found."""
    with rooms_lock:
        room = game_rooms.get(room_id)
        if room:
            return dict(room["state"])
        return {"song_id": None, "room_id": room_id}


def update_room_state(room_id, data):
    """Update state for a room."""
    with rooms_lock:
        if room_id not in game_rooms:
            game_rooms[room_id] = {"state": {}, "last_activity": time.time()}
        game_rooms[room_id]["state"].update(data)
        game_rooms[room_id]["state"]["room_id"] = room_id
        game_rooms[room_id]["state"]["timestamp"] = time.time()
        game_rooms[room_id]["last_activity"] = time.time()


def check_room_exists(room_id):
    """Check if a room exists and is active."""
    with rooms_lock:
        return room_id in game_rooms


def cleanup_expired_rooms():
    """Remove expired rooms."""
    now = time.time()
    with rooms_lock:
        expired = [rid for rid, room in game_rooms.items()
                   if now - room["last_activity"] > ROOM_EXPIRY_SECONDS]
        for rid in expired:
            del game_rooms[rid]
            print(f"  🧹 Room expirée : {rid}")


def list_active_rooms():
    """List active rooms."""
    with rooms_lock:
        return [
            {
                "room_id": rid,
                "song": room["state"].get("song_title", ""),
                "artist": room["state"].get("song_artist", ""),
                "active": time.time() - room["last_activity"] < 30,
            }
            for rid, room in game_rooms.items()
        ]


songs_cache = []
songs_lock = threading.Lock()


class GameHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        msg = format % args
        if "/api/" in msg or "GET / " in msg:
            print(f"  📡 {msg}")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # --- API ---
        if path == "/api/songs":
            with songs_lock:
                data = [strip_lyrics(s) for s in songs_cache]
            self.send_json({"songs": data})
            return

        if path.startswith("/api/songs/"):
            song_id = urllib.parse.unquote(path.split("/api/songs/", 1)[1])
            with songs_lock:
                song = next((s for s in songs_cache if s["id"] == song_id), None)
            if song:
                self.send_json(song)
            else:
                self.send_json({"error": "Not found"}, 404)
            return

        if path == "/api/random":
            with songs_lock:
                if songs_cache:
                    self.send_json(random.choice(songs_cache))
                else:
                    self.send_json({"error": "No songs"}, 404)
            return

        if path == "/api/refresh":
            refresh_songs()
            with songs_lock:
                data = [strip_lyrics(s) for s in songs_cache]
            self.send_json({"songs": data, "message": "OK"})
            return

        # --- Game state (overlay reads this) ---
        if path == "/api/state":
            params = urllib.parse.parse_qs(parsed.query)
            room_id = params.get("room", [""])[0].strip()
            if not room_id:
                self.send_json({"error": "Missing room parameter"}, 400)
            else:
                self.send_json(get_room_state(room_id))
            return

        # --- List active rooms ---
        if path == "/api/rooms":
            cleanup_expired_rooms()
            self.send_json({"rooms": list_active_rooms()})
            return

        # --- Check room availability ---
        if path == "/api/room/check":
            params = urllib.parse.parse_qs(parsed.query)
            room_id = params.get("room", [""])[0].strip().lower()
            if not room_id:
                self.send_json({"error": "Missing room parameter"}, 400)
            else:
                exists = check_room_exists(room_id)
                self.send_json({"room_id": room_id, "exists": exists})
            return

        # --- Serve local videos (local mode only) ---
        if not IS_CLOUD and path.startswith("/videos/"):
            self.serve_local_file(path)
            return

        # --- Frontend ---
        if path == "/" or path == "/index.html":
            self.serve_frontend("index.html")
            return

        # --- Overlay ---
        if path == "/overlay" or path == "/overlay.html":
            self.serve_frontend("overlay.html")
            return

        self.send_error(404)

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # --- Game state update (regie pushes this) ---
        if path == "/api/state":
            try:
                params = urllib.parse.parse_qs(parsed.query)
                room_id = params.get("room", [""])[0].strip()
                if not room_id:
                    self.send_json({"error": "Missing room parameter"}, 400)
                    return

                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body.decode("utf-8"))

                update_room_state(room_id, data)
                self.send_json({"ok": True})
            except Exception as e:
                self.send_json({"error": str(e)}, 400)
            return

        self.send_error(404)

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def serve_local_file(self, path):
        """Sert un fichier local avec support Range."""
        clean = os.path.normpath(path.lstrip("/"))
        if clean.startswith(".."):
            self.send_error(403)
            return

        relative = clean[len("videos/"):]
        filepath = os.path.join(VIDEOS_DIR, relative)

        if not os.path.isfile(filepath):
            self.send_error(404)
            return

        file_size = os.path.getsize(filepath)
        mime_type = mimetypes.guess_type(filepath)[0] or "application/octet-stream"

        # Range request support
        range_header = self.headers.get("Range")
        if range_header:
            match = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if match:
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else file_size - 1
                end = min(end, file_size - 1)
                length = end - start + 1

                self.send_response(206)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", length)
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()

                with open(filepath, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                return

        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", file_size)
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def serve_frontend(self, filename="index.html"):
        frontend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        if not os.path.isfile(frontend_path):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(f"{filename} not found".encode())
            return

        with open(frontend_path, "r", encoding="utf-8") as f:
            body = f.read().encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


def strip_lyrics(song):
    return {k: v for k, v in song.items() if k != "lyrics"}


def refresh_songs():
    global songs_cache
    print("📚 Scan de la bibliothèque...")
    new_songs = scan_library()
    with songs_lock:
        songs_cache = new_songs
    print(f"  ✅ {len(new_songs)} chanson(s)")


# ============================================================
# MAIN
# ============================================================
def main():
    print()
    print("=" * 55)
    print("  🎤 N'oubliez pas les Paroles — Serveur")
    print("=" * 55)

    if IS_CLOUD:
        print(f"  ☁️  Mode    : CLOUD (Cloudflare R2)")
        print(f"  📦 Bucket  : {R2_BUCKET_NAME}")
        print(f"  🔗 URL pub : {R2_PUBLIC_URL or '(non configurée)'}")
        init_r2()
    else:
        print(f"  💻 Mode    : LOCAL")
        print(f"  📁 Dossier : {os.path.abspath(VIDEOS_DIR)}")

    print(f"  🌐 Port    : {PORT}")
    print("=" * 55)
    print()

    refresh_songs()

    if not songs_cache:
        print()
        if IS_CLOUD:
            print("  💡 Uploadez des chansons avec : python upload.py videos/ma-chanson/")
        else:
            print(f"  💡 Ajoutez des sous-dossiers dans {VIDEOS_DIR}/")
        print()

    server = http.server.HTTPServer(("0.0.0.0", PORT), GameHandler)
    print(f"  🚀 Serveur lancé sur http://localhost:{PORT}")
    print("  🛑 Ctrl+C pour arrêter")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  👋 Arrêté.")
        server.server_close()


if __name__ == "__main__":
    main()
