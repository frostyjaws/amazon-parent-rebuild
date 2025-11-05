# util.py
import re, json
from typing import List, Dict, Tuple

# -----------------------------
# Tiny helpers you use elsewhere
# -----------------------------
def compact_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

def extract_keywords_from_title(title: str) -> List[str]:
    """
    From your rules: take words before the first ' - ' dash, strip punctuation,
    drop NOFO/VIBES/BODYSUIT, de-dupe preserving order.
    """
    parts = title.split(" - ", 1)
    head = parts[0] if parts else title
    words = re.split(r"\s+", re.sub(r"[^\w\s]", " ", head))
    cleaned = []
    seen = set()
    for w in words:
        if not w:
            continue
        up = w.upper()
        if up in {"NOFO", "VIBES", "BODYSUIT"}:
            continue
        if up not in seen:
            cleaned.append(w)
            seen.add(up)
    return cleaned

def injected_bullets(keywords: List[str], base_bullets: List[str]) -> List[str]:
    """
    One-time use rule: first 4-5 keywords replace first N bullets; if fewer,
    keep remaining base bullets.
    """
    bullets = base_bullets[:] if base_bullets else []
    if not bullets:
        return [*keywords[:5]]
    out = []
    kw_i = 0
    for i, b in enumerate(bullets):
        if kw_i < len(keywords) and i < 5:
            out.append(f"{b} ({keywords[kw_i]})")
            kw_i += 1
        else:
            out.append(b)
    return out

def injected_description(desc_html: str, keywords: List[str]) -> str:
    if not keywords:
        return desc_html
    try:
        return desc_html.rstrip() + f' <p>Keywords: {" · ".join(keywords[:8])}</p>'
    except Exception:
        return desc_html

def parse_variation(v: str) -> Tuple[str, str, str]:
    """
    Accepts lines like '0-3M White Short Sleeve' or '12M Natural Short Sleeve'
    Returns (size, color, sleeve)
    """
    tokens = v.split()
    sleeve = "Long Sleeve" if "Long" in v else "Short Sleeve"
    sleeve_first = "Long" if "Long" in v else "Short"
    try:
        idx = tokens.index(sleeve_first)
    except ValueError:
        idx = len(tokens) - 2
    color = tokens[idx - 1] if idx - 1 >= 0 else "White"
    size = " ".join(tokens[: idx - 1]) if idx - 1 > 0 else tokens[0]
    return size.strip(), color.strip(), sleeve

def _size_code(s):
    return {
        "Newborn": "NB",
        "0-3M": "03M",
        "3-6M": "36M",
        "6-9M": "69M",
        "6M": "06M",
        "12M": "12M",
        "18M": "18M",
        "24M": "24M",
    }.get(s, re.sub(r"[^A-Za-z0-9]", "", s).upper()[:4] or "SZ")

def _color_code(c):
    return {
        "White": "WH",
        "Natural": "NA",
