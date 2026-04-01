"""
Sends Discord notifications for pipeline events via webhook.
Only fires if DISCORD_WEBHOOK_URL is configured.
"""
import logging

import httpx

logger = logging.getLogger(__name__)


def _send(webhook_url: str, payload: dict) -> None:
    try:
        r = httpx.post(webhook_url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        logger.warning(f"Discord notification failed: {e}")


def notify_pipeline_complete(
    webhook_url: str,
    processed: list[dict],  # [{title, youtube_video_id, mention_count, is_new}]
    failed: int,
) -> None:
    """Sends a summary embed after a pipeline run that did something notable."""
    if not webhook_url:
        return
    if not processed and not failed:
        return

    lines = []
    new_count = sum(1 for v in processed if v["is_new"])
    for v in processed:
        yt_url = f"https://youtube.com/watch?v={v['youtube_video_id']}"
        label = "🆕" if v["is_new"] else "🔄"
        mentions = v["mention_count"]
        mention_str = f"{mentions} mention{'s' if mentions != 1 else ''}" if mentions else "no mentions"
        lines.append(f"{label} [{v['title']}]({yt_url}) — {mention_str}")

    if failed:
        lines.append(f"❌ {failed} video{'s' if failed != 1 else ''} failed")

    description = "\n".join(lines) if lines else "Nothing to report."

    title = "Pipeline complete"
    if new_count:
        title += f" — {new_count} new video{'s' if new_count != 1 else ''} picked up"

    payload = {
        "embeds": [{
            "title": title,
            "description": description,
            "color": 0xe8a838 if not failed else 0xe05252,
        }]
    }
    _send(webhook_url, payload)
