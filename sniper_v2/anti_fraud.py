"""Anti-fraud checks for Sniper V2."""
import re


def is_stock_photo_url(url, stock_photo_domains=None, known_stock_photo_patterns=None):
    """Check if an image URL looks like a stock/manufacturer photo."""
    if not url:
        return False
    url_lower = url.lower()

    if stock_photo_domains:
        for domain in stock_photo_domains:
            if domain.lower() in url_lower:
                return True

    if known_stock_photo_patterns:
        for pattern in known_stock_photo_patterns:
            if re.search(pattern, url_lower):
                return True

    return False


def is_registration_page(url):
    """Reject listing URLs that point to registration pages."""
    if not url:
        return False
    lower = url.lower()
    return "form?type=regist" in lower or "/regist" in lower


def price_anomaly(listing_price, category_max, suspicious_min, ratio=0.4):
    """Return True if price is suspiciously low compared to category max."""
    if not listing_price or not category_max:
        return False
    if listing_price <= suspicious_min:
        return True
    if listing_price < category_max * ratio:
        return True
    return False
