"""Alert generation for Sniper V2."""
import os
from pathlib import Path


def generate_alert_markdown(listings, kst_now_fn=None):
    """Return the alert file body for a list of classified listings."""
    if kst_now_fn is None:
        from datetime import datetime, timezone, timedelta
        KST = timezone(timedelta(hours=9))
        kst_now_fn = lambda: datetime.now(KST)

    lines = [
        "# 🎯 SNIPER ALERTS — LLM Hardware",
        "",
        f"> **Last scan:** {kst_now_fn().strftime('%Y-%m-%d %H:%M:%S KST')}",
        f"> **Markets:** Daangn (당근마켓) + Joonggonara (중고나라)",
        f"> **Total listings:** {len(listings)}",
        "",
    ]

    for tier in ("STEAL", "ALERT", "SUSPICIOUS", "NORMAL", "UNKNOWN"):
        tier_items = [r for r in listings if r.get("tier") == tier]
        if not tier_items:
            continue
        lines.append(f"## {tier} ({len(tier_items)})")
        lines.append("")
        for item in tier_items:
            price_str = format_price(item.get("price"))
            title = (item.get("title") or "").split("\n")[0][:60]
            lines.append(f"- {item.get('icon', '')} **{title}** — {price_str}")
            lines.append(f"  Market: {item.get('market', '')} | Query: {item.get('query', '')}")
            if item.get("stock_photo"):
                lines.append("  🚨 STOCK PHOTO DETECTED")
            lines.append(f"  {item.get('url', '')}")
            lines.append("")

    if not listings:
        lines.append("_No new listings match alert criteria._")

    return "\n".join(lines)


def format_price(price):
    if not price:
        return "가격 미표시"
    if price >= 10_000_000:
        return f"{price / 10_000_000:.1f}억"
    elif price >= 10_000:
        return f"{price // 10_000}만원"
    return f"{price:,}원"


def write_alerts(output_path, markdown_text):
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(markdown_text, encoding="utf-8")
    return p
