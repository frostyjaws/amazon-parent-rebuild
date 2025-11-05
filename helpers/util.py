"""
helpers/util.py
----------------
Reusable utility functions for Amazon listing feed generation.
Handles:
- SKU formatting
- Variation parsing
- Keyword injection
- Safe text cleaning
"""

import re
from typing import List, Tuple, Dict

# Words we ignore when extracting pre-dash keywords
STOP_WORDS = {"NOFO", "VIBES", "BODYSUIT", "ONESIE"}

# -----------------------------
# 🔹 Basic text cleaning
# -----------------------------
def clean_text(text: str) -> str:
    """Remove excessive spaces, quotes, and weird characters."""
    return re.sub(r"\s+", " ", text.strip().replace('"', '').replace("'", ""))

def safe_slug(text: str) -> str:
    """Create a URL-safe or SKU-safe slug."""
    return re.sub(r"[^A-Za-z0-9-]", "-", text.strip()).upper()

# -----------------------------
# 🔹 Variation parsing helpers
# -----------------------------
def split_variation(variation_str: str) -> Tuple[str, str, str]:
    """
    Splits a variation like '0-3M Short White' into (size, sleeve, color).
    Handles flexible token counts gracefully.
    """
    parts = variation_str.strip().split()
    if len(parts) >= 3:
        return parts[0], parts[-2], parts[-1]
    elif len(parts) == 2:
        return parts[0], "", parts[1]
    elif len(parts) == 1:
        return parts[0], "", ""
    return "", "", ""

def build_child_sku(parent_sku: str, variation_str: str) -> str:
    """Build a child SKU using parent base and variation info."""
    base = re.sub(r"-PARENT$", "", parent_sku.strip(), flags=re.IGNORECASE)
    safe_var = re.sub(r"\s+", "-", variation_str.strip())
    return f"{base}-{safe_var}"

# -----------------------------
# 🔹 Keyword extraction
# -----------------------------
def extract_keywords_from_title(title: str) -> List[str]:
    """
    Extract words before the first dash from a title string, ignoring STOP_WORDS.
    Example:
        'Gyro Baby - Funny Bodysuit' → ['Gyro', 'Baby']
    """
    if " - " not in title:
        return []
    pre_dash = title.split(" - ", 1)[0]
    words = re.findall(r"[A-Za-z0-9']+", pre_dash)
    seen, keywords = set(), []
    for w in words:
        if w.upper() in STOP_WORDS:
            continue
        lw = w.lower()
        if lw not in seen:
            seen.add(lw)
            keywords.append(w)
    return keywords

# -----------------------------
# 🔹 Injected copy helpers
# -----------------------------
def injected_bullets(keywords: List[str], base_bullets: List[str]) -> List[str]:
    """
    Fill in bullets with extracted keywords where available, fallback to defaults.
    """
    base_templates = [
        "🎨 Premium DTG print featuring '{kw}'.",
        "🎖️ Veteran-Owned — support small while rocking '{kw}'.",
        "👶 Comfy 100% cotton — '{kw}' design they’ll love.",
        "🎁 Perfect gift — cute '{kw}' theme.",
        "📏 Sizes & colors available — see chart."
    ]

    bullets = []
    for i in range(5):
        if i < len(keywords):
            bullets.append(base_templates[i].format(kw=keywords[i]))
        elif i < len(base_bullets):
            bullets.append(base_bullets[i])
        else:
            bullets.append("")
    return bullets

def injected_description(base_description: str, keywords: List[str]) -> str:
    """
    Add a keyword echo to the product description.
    """
    if not keywords:
        return base_description
    tail = f" Design theme: {', '.join(keywords[:3])}."
    return clean_text(base_description + " " + tail)

def injected_generic_keywords(keywords: List[str]) -> str:
    """
    Return a comma-separated generic_keywords string.
    """
    return ", ".join(keywords[:6])

# -----------------------------
# 🔹 Misc helpers
# -----------------------------
def parse_swatches(txt: str) -> Dict[str, str]:
    """
    Parse color → URL lines from textarea input.
    Example:
        'White,https://example.com/white.png'
    """
    m = {}
    for line in txt.splitlines():
        if "," in line:
            k, v = line.split(",", 1)
            m[k.strip()] = v.strip()
    return m

def compact_json(messages: List[Dict], limit: int = 3) -> str:
    """
    Returns a compact JSON preview for Streamlit output.
    """
    import json
    return json.dumps({"messages": messages[:limit]}, indent=2) + ("\n...\n" if len(messages) > limit else "")
