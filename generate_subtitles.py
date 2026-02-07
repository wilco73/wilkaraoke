#!/usr/bin/env python3
"""
🎤 Générateur automatique de sous-titres avec Whisper
=====================================================
Ce script prend une vidéo en entrée et génère automatiquement :
  - Le fichier subtitles.srt
  - Un config.json pré-rempli

Prérequis :
  pip install openai-whisper

Usage :
  python generate_subtitles.py videos/ma-chanson/video.mp4
  python generate_subtitles.py videos/ma-chanson/video.mp4 --language fr --model medium
  python generate_subtitles.py videos/ma-chanson/  # détecte auto la vidéo
"""

import argparse
import json
import os
import sys
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".avi", ".mov", ".m4v", ".ogg", ".wav", ".mp3", ".flac"}


def find_video(path):
    """Trouve le fichier vidéo dans un dossier ou retourne le chemin si c'est un fichier."""
    p = Path(path)
    if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
        return p
    if p.is_dir():
        for f in p.iterdir():
            if f.suffix.lower() in VIDEO_EXTENSIONS:
                return f
    return None


def generate_subtitles(video_path, language="fr", model_name="base"):
    """Génère les sous-titres avec Whisper."""
    try:
        import whisper
    except ImportError:
        print("❌ Whisper n'est pas installé.")
        print("   Installez-le avec : pip install openai-whisper")
        sys.exit(1)

    video_path = Path(video_path)
    output_dir = video_path.parent

    print(f"🎤 Chargement du modèle Whisper ({model_name})...")
    model = whisper.load_model(model_name)

    print(f"🎵 Transcription de : {video_path.name}")
    print(f"   Langue : {language}")
    result = model.transcribe(str(video_path), language=language)

    # Générer le SRT
    srt_path = output_dir / "subtitles.srt"
    segments = result.get("segments", [])

    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = format_srt_time(seg["start"])
            end = format_srt_time(seg["end"])
            text = seg["text"].strip()
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")

    print(f"✅ Sous-titres générés : {srt_path}")
    print(f"   {len(segments)} segments trouvés")

    # Calculer la durée totale
    duration = segments[-1]["end"] if segments else 0

    # Générer config.json s'il n'existe pas
    config_path = output_dir / "config.json"
    if not config_path.exists():
        # Deviner le titre depuis le nom du dossier
        folder_name = output_dir.name
        title = folder_name.replace("-", " ").replace("_", " ").title()

        config = {
            "title": title,
            "artist": "Artiste à renseigner",
            "difficulty": "medium",
            "cutoff_windows": [
                [round(duration * 0.4, 1), round(duration * 0.6, 1)]
            ],
        }

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        print(f"📝 Config créée : {config_path}")
        print(f"   ⚠️  Pensez à éditer le titre, l'artiste et les fenêtres de coupure !")
        print(f"   💡 Format cutoff_windows : [[début1, fin1], [début2, fin2], ...]")
    else:
        print(f"ℹ️  config.json existe déjà, non modifié.")

    print()
    print(f"📊 Durée totale : {format_readable_time(duration)}")
    print(f"   Point de coupure suggéré : {format_readable_time(duration * 0.5)}")
    print()
    print("✨ Terminé ! Relancez le serveur ou cliquez Rafraîchir dans l'app.")


def format_srt_time(seconds):
    """Convertit des secondes en format SRT (HH:MM:SS,mmm)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_readable_time(seconds):
    """Format lisible."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def main():
    parser = argparse.ArgumentParser(description="Générer des sous-titres avec Whisper")
    parser.add_argument("path", help="Chemin vers la vidéo ou son dossier")
    parser.add_argument("--language", "-l", default="fr", help="Langue (défaut: fr)")
    parser.add_argument(
        "--model", "-m", default="base",
        help="Modèle Whisper: tiny, base, small, medium, large (défaut: base)"
    )
    parser.add_argument("--word_timestamps", "-w", default="False", help="Sous-titres mot par mot: True (default=False)")
    args = parser.parse_args()

    video = find_video(args.path)
    if not video:
        print(f"❌ Aucune vidéo trouvée dans : {args.path}")
        print(f"   Extensions supportées : {', '.join(sorted(VIDEO_EXTENSIONS))}")
        sys.exit(1)

    generate_subtitles(video, language=args.language, model_name=args.model)


if __name__ == "__main__":
    main()
