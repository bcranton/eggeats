# Roadmap & Future Improvements

This document tracks planned features and improvements for the Northernlion Travel Guide.

---

## Backlog

### API-Key Pipeline Trigger
Add a simple `X-Pipeline-Key` header authentication so Railway's cron job (or any external
scheduler) can `POST /api/admin/pipeline/run` without needing a browser OAuth session cookie.
Currently the pipeline must be triggered manually from the admin UI.

**Why:** Enables fully automated video processing — any new video added to the playlist gets
processed within hours without any manual action.

---

### Frontend Polish
- Better mobile layout (collapsible sidebar, bottom sheet for business detail)
- Skeleton loading animation while map data fetches
- Search/autocomplete bar to find a specific business by name
- "Jump to city" button that re-centers and rezooms the map

---

### Email / Discord Notifications
Alert the admin when new businesses are flagged for review, so the review queue doesn't go
unnoticed. Options:
- **Email** via SendGrid or SMTP (simple, no extra accounts needed)
- **Discord webhook** (paste a webhook URL into env vars, get a message in a channel)

---

### Multi-City UI
When more cities are added (Kingston, Seattle, Los Angeles, Orlando, etc.), the frontend needs:
- A city dropdown in the header that re-centers the map and filters pins
- Separate map bounds per city so the view fits the active city
- "All cities" mode that shows a zoomed-out world/North America view

The backend already supports multiple cities via the `cities` table — this is purely frontend work.

---

### Testing
- Unit tests for the pipeline modules (`llm_extractor`, `geocoder`, `transcript_fetcher`)
- Integration tests for the public API endpoints (`/api/map-data`, `/api/businesses/{id}`)
- A mock/fixture system so tests don't require live API keys (mock Claude + Google Places)
- CI via GitHub Actions: run tests on every push to `main`

---

### Rate Limit Protection
The public API endpoints (`/api/map-data`, `/api/businesses`) are unauthenticated and could be
scraped or hammered.
- Add `slowapi` rate limiting (e.g. 60 requests/minute per IP)
- Add ETag support so unchanged responses return `304 Not Modified` instead of full payloads
- Consider a CDN layer (Cloudflare free tier) in front of Railway for automatic DDoS protection

---

### SEO / Meta Tags
- OpenGraph tags on `index.html` so link previews look good when shared (title, description,
  preview image of the map)
- A canonical `<title>` and `<meta description>` per business detail (would require server-side
  rendering or a dedicated `/place/{id}` route that returns HTML with injected meta)
- Sitemap generation for search engine indexing
