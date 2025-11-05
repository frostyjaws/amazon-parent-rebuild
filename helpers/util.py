import json
import re

STOP_WORDS = {"NOFO", "VIBES", "BODYSUIT", "ONESIE"}

# -----------------------------
# Keyword extraction & injections
# -----------------------------
def extract_keywords_from_title(title: str):
    """
    Pull words before the first ' - ' to use as keywords.
    Dedupes, removes STOP_WORDS, preserves original casing/order.
    """
    if " - " in title:
        pre = title.split(" - ", 1)[0]
    else:
        pre = title
    words = [w for w in re.findall(r"[A-Za-z0-9']+", pre) if w]
    out, seen = [], set()
    for w in words:
        if w.upper() in STOP_WORDS:
            continue
        lw = w.lower()
        if lw not in seen:
            out.append(w)
            seen.add(lw)
    return out

def injected_bullets(keywords, base_bullets):
    """
    Fill bullet lines with light keyword echoes; fallback to provided base bullets.
    """
    templates = [
        "🎨 Premium DTG print featuring '{kw}'.",
        "🎖️ Veteran-Owned — support small while rocking '{kw}'.",
        "👶 Comfy 100% cotton — '{kw}' design they’ll love.",
        "🎁 Perfect gift — cute '{kw}' theme.",
        "📏 Sizes & colors available — see chart."
    ]
    bullets = []
    for i in range(5):
        if i < len(keywords):
            bullets.append(templates[i].format(kw=keywords[i]))
        elif i < len(base_bullets):
            bullets.append(base_bullets[i])
        else:
            bullets.append("")
    return bullets

def injected_description(base_description: str, keywords):
    """
    Append a short keyword echo to the description.
    """
    if not keywords:
        return base_description
    return base_description.strip() + " " + f"<p>Design theme: {', '.join(keywords[:3])}.</p>"

def injected_generic_keywords(keywords):
    """
    Comma-separated generic keywords string (cap at ~10).
    """
    return ", ".join(keywords[:10])

def compact_json(obj):
    return json.dumps(obj, indent=2)

# -----------------------------
# Variation parsing & SKU codes
# -----------------------------
def parse_variation(variation_str: str):
    """
    Converts '0-3M White Short Sleeve' -> ('0-3M', 'White', 'Short Sleeve').
    Accepts formats like:
      'Newborn White Short Sleeve'
      '6M Natural Short Sleeve'
      '0-3M Blue Long Sleeve'
    """
    parts = variation_str.strip().split()
    if len(parts) >= 4:
        size = parts[0]
        color = parts[1]
        sleeve = " ".join(parts[2:])  # "Short Sleeve" or "Long Sleeve"
    elif len(parts) == 3:
        size, color, sleeve = parts
        if "Short" in sleeve and "Sleeve" not in sleeve:
            sleeve = "Short Sleeve"
        if "Long" in sleeve and "Sleeve" not in sleeve:
            sleeve = "Long Sleeve"
    elif len(parts) == 2:
        size, color = parts
        sleeve = ""
    else:
        size = parts[0] if parts else ""
        color = parts[1] if len(parts) > 1 else ""
        sleeve = " ".join(parts[2:]) if len(parts) > 2 else ""
    # Normalize capitalization
    size = size.strip()
    color = color.capitalize().strip()
    sleeve = sleeve.title().strip()
    return size, color, sleeve

def _size_code(size: str) -> str:
    mapping = {
        "Newborn": "NB", "0-3M": "03M", "3-6M": "36M", "6-9M": "69M",
        "6M": "06M", "12M": "12M", "18M": "18M", "24M": "24M",
    }
    return mapping.get(size, re.sub(r"[^A-Za-z0-9]", "", size).upper()[:4])

def _color_code(color: str) -> str:
    mapping = {"White": "WH", "Natural": "NA", "Pink": "PK", "Blue": "BL"}
    key = color.capitalize()
    return mapping.get(key, re.sub(r"[^A-Za-z0-9]", "", key).upper()[:2] or "XX")

def _sleeve_code(sleeve: str) -> str:
    if "Long" in sleeve:
        return "LS"
    return "SS"  # default short

def sku_from_variation(base_name: str, size: str, color: str, sleeve: str) -> str:
    """
    Build a stable child SKU:
      base_name-<SIZECODE>-<COLORCODE>-<SLEEVE>
    Example:
      base=GYROBABY, 0-3M/White/Short Sleeve -> GYROBABY-03M-WH-SS
    """
    base = base_name.strip()
    sc = _size_code(size)
    cc = _color_code(color)
    sl = _sleeve_code(sleeve)
    return f"{base}-{sc}-{cc}-{sl}"

