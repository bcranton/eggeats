# Northernlion Travel Guide

An interactive map at [eggeats.com](https://eggeats.com) that displays local businesses, restaurants, and attractions mentioned by Northernlion (YouTuber/streamer) across his videos. Business mentions are extracted from YouTube transcripts using the Claude AI API.

## Features

- **Interactive Google Maps** with sentiment-coloured pins (green=positive, red=negative)
- **Filter** by city, category, and NL's vibe
- **Business detail panel** with direct quotes and YouTube timestamp links
- **LLM pipeline** that extracts mentions from video transcripts, handles typos, geocodes businesses
- **Admin panel** with Google OAuth (restricted to allowlisted emails) for reviewing flagged businesses
- **Automatic detection** of new playlist videos via scheduled pipeline runs

## Stack

| Component | Technology |
|---|---|
| Backend | Python 3.12 + FastAPI |
| Database | PostgreSQL + SQLAlchemy + Alembic |
| LLM | Claude API (claude-sonnet-4-6) |
| Map | Google Maps JavaScript API |
| Geocoding | Google Places API |
| YouTube | YouTube Data API v3 + youtube-transcript-api |
| Admin Auth | Google OAuth 2.0 |
| Deploy | Docker + Railway |

## Quick Start (Local)

### Prerequisites

- Docker + Docker Compose
- Google Cloud project with these APIs enabled:
  - YouTube Data API v3
  - Places API
  - Maps JavaScript API
  - OAuth 2.0 (Web Client)
- Anthropic API key

### Setup

```bash
cp .env.example .env
# Fill in all API keys in .env
docker compose up --build
```

App will be available at http://localhost:8000

### Run the pipeline

After starting the app, open the admin panel at http://localhost:8000/admin.html, sign in with Google, and click **Run Pipeline**. This will:
1. Fetch all videos from the playlist
2. Download transcripts
3. Extract business mentions with Claude
4. Geocode businesses with Google Places
5. Flag uncertain matches for admin review

## Deployment (Railway)

1. Push this repo to GitHub
2. Create a new Railway project, connect the repo
3. Add a **PostgreSQL** plugin to the project
4. Set all environment variables from `.env.example` in Railway's settings
5. Set `GOOGLE_REDIRECT_URI=https://eggeats.com/auth/callback`
6. Deploy — `alembic upgrade head` runs automatically on startup
7. Set up a Railway **Cron Job** to call `POST /api/admin/pipeline/run` (e.g. every 6 hours) to pick up new playlist videos automatically

## Adding New Cities

1. Insert a row into the `cities` table:
   ```sql
   INSERT INTO cities (name, country, search_keywords, center_lat, center_lng)
   VALUES ('Kingston', 'CA', 'Kingston,Kingston Ontario', 44.2312, -76.4860);
   ```
2. Insert a playlist linked to that city:
   ```sql
   INSERT INTO playlists (youtube_playlist_id, city_id, name)
   VALUES ('YOUR_PLAYLIST_ID', <city_id>, 'NL Kingston Videos');
   ```
3. Run the pipeline — it will search for city keywords in transcripts automatically.

## Project Structure

```
eggeats/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   ├── config.py            # Settings (env vars)
│   │   ├── database.py          # SQLAlchemy engine
│   │   ├── models.py            # ORM models
│   │   ├── api/
│   │   │   ├── map.py           # Public map endpoints
│   │   │   ├── auth.py          # Google OAuth
│   │   │   └── admin.py         # Admin endpoints
│   │   └── pipeline/
│   │       ├── processor.py     # Pipeline orchestrator
│   │       ├── playlist_fetcher.py
│   │       ├── transcript_fetcher.py
│   │       ├── llm_extractor.py # Claude extraction
│   │       └── geocoder.py      # Google Places
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
