# EggEats — Northernlion Travel Guide

An interactive map at [eggeats.com](https://eggeats.com) that tracks every restaurant, café, and bar Northernlion has visited across his food vlogs. A background pipeline fetches new videos hourly, transcribes them, and uses Claude AI to extract food mentions — complete with his exact quotes and sentiment. All submissions are manually reviewed for accuracy before being published.

## Features

- **Interactive map** (OpenFreeMap, dark theme) with sentiment-coloured pins (green=positive, red=negative)
- **Filter** by city, category, date range, and NL's vibe
- **List view** with full business details, quotes, and YouTube timestamp links
- **Business detail panel** with address, street view, direct quotes, and links back to the exact video moment
- **LLM pipeline** that extracts mentions from transcripts, handles typos, and geocodes businesses via Google Places
- **Hourly pipeline** that automatically picks up new playlist videos
- **Admin panel** with Google OAuth (restricted to allowlisted emails) for reviewing, editing, and managing all data
- **Discord notifications** when new videos are processed
- **Manual review** of all AI-extracted data before publishing

## Stack

| Component | Technology |
|---|---|
| Backend | Python 3.13 + FastAPI |
| Database | PostgreSQL + SQLAlchemy + Alembic |
| LLM | Claude API (claude-sonnet-4-6) |
| Map | MapLibre GL JS + OpenFreeMap |
| Geocoding | Google Places API |
| Transcripts | Supadata + youtube-transcript-api |
| YouTube | YouTube Data API v3 |
| Admin Auth | Google OAuth 2.0 |
| Deploy | Docker + Railway |

## Quick Start (Local)

### Prerequisites

- Docker + Docker Compose
- Google Cloud project with these APIs enabled:
  - YouTube Data API v3
  - Places API
  - OAuth 2.0 (Web Client)
- Anthropic API key
- Supadata API key (optional — falls back to youtube-transcript-api on local IPs)

### Setup

```bash
cp .env.example .env
# Fill in all API keys in .env
docker compose up --build
```

App will be available at http://localhost:8000

### Run the pipeline

After starting the app, open the admin panel at http://localhost:8000/admin.html, sign in with Google, and click **Run Pipeline**. This will:

1. Fetch all videos from the configured playlist
2. Download transcripts via Supadata or youtube-transcript-api
3. Extract business mentions with Claude
4. Geocode businesses with Google Places
5. Flag uncertain matches for admin review

## Deployment (Railway)

1. Push this repo to GitHub
2. Create a new Railway project and connect the repo
3. Add a **PostgreSQL** plugin to the project
4. Set all environment variables from `.env.example` in Railway's settings
5. Set `GOOGLE_REDIRECT_URI=https://yourdomain.com/auth/callback`
6. Deploy — `alembic upgrade head` runs automatically on startup

The pipeline runs automatically every hour via an asyncio background task. No separate cron service needed.

## Adding New Cities

Use the admin panel's **Setup** tab to seed a new city and playlist, or insert directly:

```sql
INSERT INTO cities (name, country, search_keywords, center_lat, center_lng)
VALUES ('Kingston', 'CA', 'Kingston,Kingston Ontario', 44.2312, -76.4860);

INSERT INTO playlists (youtube_playlist_id, city_id, name)
VALUES ('YOUR_PLAYLIST_ID', <city_id>, 'NL Kingston Videos');
```

Then run the pipeline — it will search for city keywords in transcripts automatically.

## Project Structure

```
eggeats/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point + hourly scheduler
│   │   ├── config.py            # Settings (env vars)
│   │   ├── database.py          # SQLAlchemy engine
│   │   ├── models.py            # ORM models
│   │   ├── cache.py             # In-memory TTL cache
│   │   ├── api/
│   │   │   ├── map.py           # Public map endpoints
│   │   │   ├── auth.py          # Google OAuth
│   │   │   └── admin.py         # Admin endpoints
│   │   └── pipeline/
│   │       ├── processor.py     # Pipeline orchestrator
│   │       ├── playlist_fetcher.py
│   │       ├── transcript_fetcher.py
│   │       ├── llm_extractor.py # Claude extraction
│   │       ├── geocoder.py      # Google Places
│   │       └── discord.py       # Discord notifications
│   ├── alembic/                 # DB migrations
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── index.html               # Main map page
│   ├── admin.html               # Admin panel
│   ├── js/
│   │   ├── map.js
│   │   └── admin.js
│   └── css/
│       ├── styles.css
│       └── admin.css
├── docker-compose.yml
├── railway.toml
└── .env.example
```
