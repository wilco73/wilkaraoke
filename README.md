# 🎤 N'oubliez pas les Paroles — Version Cloud

Application de karaoké interactive déployable en ligne avec Render + Cloudflare R2.

---

## 🏗 Architecture

```
┌──────────────┐         ┌─────────────────┐
│   Navigateur │ ◄─────► │  Serveur Render  │
│   (joueur)   │  API    │  (server.py)     │
└──────┬───────┘         └────────┬─────────┘
       │                          │
       │  vidéos                  │ SRT + config
       ▼                          ▼
┌──────────────────────────────────┐
│        Cloudflare R2             │
│   (stockage vidéos + sous-titres)│
└──────────────────────────────────┘
```

- **Render** héberge le serveur Python (gratuit)
- **Cloudflare R2** stocke les vidéos et sous-titres (gratuit jusqu'à 10 Go)
- Les vidéos sont servies directement par R2 → rapide, pas de charge sur le serveur

---

## 🚀 Déploiement pas à pas

### Étape 1 : Créer le bucket Cloudflare R2

1. Va sur [dash.cloudflare.com](https://dash.cloudflare.com)
2. Menu latéral → **R2 Object Storage**
3. **Créer un bucket** (ex: `karaoke-videos`)
4. Dans les paramètres du bucket → **Settings** → **Public access**
5. Active l'accès public → note l'URL publique (ex: `https://pub-abc123.r2.dev`)

### Étape 2 : Créer les clés API R2

1. Cloudflare dashboard → **R2** → **Manage R2 API Tokens**
2. **Create API Token**
3. Permissions : **Object Read & Write**
4. Note les identifiants :
   - **Access Key ID**
   - **Secret Access Key**
   - **Account ID** (visible dans l'URL du dashboard)

### Étape 3 : Configurer en local

```bash
# Cloner / copier le projet
cd noubliez-pas-cloud

# Installer boto3
pip install boto3

# Créer le fichier .env
cp .env.example .env
# → Éditez .env avec vos clés R2
```

### Étape 4 : Ajouter des chansons

```bash
# Structure de chaque chanson :
#   videos/
#     ma-chanson/
#       video.mp4
#       subtitles.srt
#       config.json

# Générer les sous-titres automatiquement
pip install openai-whisper
python generate_subtitles.py videos/ma-chanson/video.mp4

# Éditer le config.json (titre, artiste, point de coupure)

# Uploader une chanson
python upload.py add videos/ma-chanson/

# Ou uploader tout d'un coup
python upload.py sync videos/

# Vérifier ce qui est sur R2
python upload.py list
```

### Étape 5 : Déployer sur Render

1. Push le code sur **GitHub** (sans le dossier `videos/` ni `.env`)
2. Va sur [render.com](https://render.com) → **New** → **Web Service**
3. Connecte ton repo GitHub
4. Render détecte `render.yaml` automatiquement
5. Dans **Environment** → ajoute les variables :
   - `R2_BUCKET_NAME` → nom de ton bucket
   - `R2_ACCOUNT_ID` → ton account ID
   - `R2_ACCESS_KEY_ID` → ta clé d'accès
   - `R2_SECRET_ACCESS_KEY` → ta clé secrète
   - `R2_PUBLIC_URL` → l'URL publique du bucket
6. **Deploy** → ton app est en ligne ! 🎉

---

## 💻 Utilisation en local

L'app fonctionne aussi en mode local sans R2 :

```bash
# Mode local (sans variables R2)
python server.py

# Ou en spécifiant un dossier
python server.py /chemin/vers/videos
```

Si les variables R2 ne sont pas définies, le serveur utilise le dossier `./videos/` local.

---

## 🛠 Commandes upload.py

| Commande | Description |
|----------|-------------|
| `python upload.py add videos/ma-chanson/` | Upload une chanson |
| `python upload.py add videos/ma-chanson/ --id titre-custom` | Upload avec un ID personnalisé |
| `python upload.py list` | Liste les chansons sur R2 |
| `python upload.py delete ma-chanson` | Supprime une chanson |
| `python upload.py sync videos/` | Upload tout un dossier de chansons |

---

## 📡 Intégration OBS (pour le stream)

1. Ouvre ton app déployée dans le navigateur (l'URL Render)
2. OBS → **Sources** → **+** → **Navigateur (Browser)**
3. URL : ton URL Render (ex: `https://noubliez-pas.onrender.com`)
4. Largeur: 1280, Hauteur: 900
5. Contrôle l'app depuis un autre onglet ou l'interface OBS

---

## 📁 Fichiers du projet

```
noubliez-pas-cloud/
  server.py                 ← Serveur (local + cloud)
  index.html                ← Frontend
  upload.py                 ← Outil d'upload R2
  generate_subtitles.py     ← Générateur SRT (Whisper)
  requirements.txt          ← Dépendances Python
  render.yaml               ← Config Render (déploiement auto)
  .env.example              ← Template de configuration
  .gitignore
```

---

## ❓ FAQ

**Les vidéos sont trop lourdes pour R2 ?**
→ Compressez avec ffmpeg : `ffmpeg -i input.mp4 -crf 28 -preset fast output.mp4`

**Le son est désynchronisé avec les sous-titres ?**
→ Utilisez un modèle Whisper plus précis : `--model medium` ou `--model large`

**Je veux changer le point de coupure ?**
→ Éditez le `config.json` local puis re-uploadez : `python upload.py add videos/ma-chanson/`

**Render met l'app en veille (plan gratuit) ?**
→ C'est normal, la première requête prend ~30s pour redémarrer. Pour éviter ça, passez au plan payant (~7$/mois) ou utilisez un service de ping comme UptimeRobot.
