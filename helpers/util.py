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
        # append a tiny keyword sentence
        return desc_html.rstrip() + f' <p>Keywords: {" · ".join(keywords[:8])}</p>'
    except Exception:
        return desc_html

def parse_variation(v: str) -> Tuple[str, str, str]:
    """
    Accepts lines like '0-3M White Short Sleeve' or '12M Natural Short Sleeve'
    Returns (size, color, sleeve)
    """
    tokens = v.split()
    # Try to detect sleeve (Long/Short)
    sleeve = "Long Sleeve" if "Long" in v else "Short Sleeve"
    # color assumed to be last token before sleeve's first word
    sleeve_first = "Long" if "Long" in v else "Short"
    try:
        idx = tokens.index(sleeve_first)
    except ValueError:
        idx = len(tokens) - 2  # safe-ish fallback
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
        "Pink": "PK",
        "Blue": "BL",
    }.get(c.capitalize(), re.sub(r"[^A-Za-z0-9]", "", c).upper()[:2] or "XX")

def _sleeve_code(s):
    return "LS" if "Long" in s else "SS"

def sku_from_variation(base, size, color, sleeve):
    return f"{base}-{_size_code(size)}-{_color_code(color)}-{_sleeve_code(sleeve)}"

# -----------------------------
# Price map (edit as needed)
# -----------------------------
PRICE_MAP = {
    "Newborn White Short Sleeve": 29.99,
    "Newborn White Long Sleeve": 30.99,
    "Newborn Natural Short Sleeve": 33.99,
    "0-3M White Short Sleeve": 29.99,
    "0-3M White Long Sleeve": 30.99,
    "0-3M Pink Short Sleeve": 33.99,
    "0-3M Blue Short Sleeve": 33.99,
    "3-6M White Short Sleeve": 29.99,
    "3-6M White Long Sleeve": 30.99,
    "3-6M Blue Short Sleeve": 33.99,
    "3-6M Pink Short Sleeve": 33.99,
    "6M Natural Short Sleeve": 33.99,
    "6-9M White Short Sleeve": 29.99,
    "6-9M White Long Sleeve": 30.99,
    "6-9M Pink Short Sleeve": 33.99,
    "6-9M Blue Short Sleeve": 33.99,
    "12M White Short Sleeve": 29.99,
    "12M White Long Sleeve": 30.99,
    "12M Natural Short Sleeve": 33.99,
    "12M Pink Short Sleeve": 33.99,
    "12M Blue Short Sleeve": 33.99,
    "18M White Short Sleeve": 29.99,
    "18M White Long Sleeve": 30.99,
    "18M Natural Short Sleeve": 33.99,
    "24M White Short Sleeve": 29.99,
    "24M White Long Sleeve": 30.99,
    "24M Natural Short Sleeve": 33.99,
}

# -----------------------------
# PATCH message helpers (2025 schema)
# -----------------------------
def build_patch_message(*, message_id: int, sku: str, product_type: str, attributes: dict):
    """
    Build a JSON_LISTINGS_FEED 'PATCH' message with attributes nested under
    patches[].value[0].attributes  (Amazon requires value to be an ARRAY).
    """
    return {
        "messageId": message_id,
        "sku": sku,
        "operationType": "PATCH",
        "productType": product_type,
        "patches": [{
            "op": "replace",
            "path": "/",
            "value": [{
                "attributes": attributes
            }]
        }]
    }

def required_core_attrs_for_child(*, title_val: str, size: str, color: str, sleeve: str,
                                  brand: str, item_type_keyword: str, desc_html: str, bullets: list,
                                  country_of_origin: str = "US", import_designation: str = "Made in USA",
                                  department: str = "Baby Girls", target_gender: str = "female",
                                  age_range: str = "Infant", fabric_type: str = "100% cotton",
                                  care_instructions: str = "Machine Wash",
                                  batteries_required: bool = False,
                                  dg_regulation: str = "not_applicable",
                                  pkg_len: float = 3, pkg_wid: float = 3, pkg_hgt: float = 1, pkg_unit: str = "inches",
                                  pkg_weight: float = 0.19, pkg_weight_unit: str = "kilograms",
                                  model_name: str = "Crew Neck Bodysuit",
                                  list_price: float = 29.99) -> Dict:
    """
    Returns a dict of all attributes the processing report said were required.
    (We intentionally omit generic_keywords because Amazon drops it for this PT.)
    """
    return {
        "item_name": [{"value": title_val}],
        "brand": [{"value": brand}],
        "item_type_keyword": [{"value": item_type_keyword}],
        "product_description": [{"value": desc_html}],
        "bullet_point": [{"value": b} for b in bullets if b],
        "parentage_level": [{"value": "child"}],
        "country_of_origin": [{"value": country_of_origin}],
        "import_designation": [{"value": import_designation}],
        "department": [{"value": department}],
        "target_gender": [{"value": target_gender}],
        "age_range_description": [{"value": age_range}],
        "fabric_type": [{"value": fabric_type}],
        "care_instructions": [{"value": care_instructions}],
        "batteries_required": [{"value": batteries_required}],
        "supplier_declared_dg_hz_regulation": [{"value": dg_regulation}],
        "item_package_dimensions": [{
            "length": {"value": pkg_len, "unit": pkg_unit},
            "width": {"value": pkg_wid, "unit": pkg_unit},
            "height": {"value": pkg_hgt, "unit": pkg_unit},
        }],
        "item_package_weight": [{"value": pkg_weight, "unit": pkg_weight_unit}],
        "model_name": [{"value": model_name}],
        "list_price": [{"currency": "USD", "value": list_price}],
        # Variation specifics
        "variation_theme": [{"name": "SIZE/COLOR"}],
        "size": [{"value": size}],
        "color": [{"value": color}],
        "style": [{"value": sleeve}] if sleeve else [],
    }

def required_core_attrs_for_parent(*, title_val: str, brand: str, item_type_keyword: str,
                                   desc_html: str, bullets: list,
                                   variation_theme_display: str = "SIZE/COLOR") -> Dict:
    """
    Minimal but complete parent-level attributes (no price for parent).
    """
    return {
        "item_name": [{"value": title_val}],
        "brand": [{"value": brand}],
        "item_type_keyword": [{"value": item_type_keyword}],
        "product_description": [{"value": desc_html}],
        "bullet_point": [{"value": b} for b in bullets if b],
        "parentage_level": [{"value": "parent"}],
        "variation_theme": [{"name": variation_theme_display}],
        # include the same meta fields expected on children to avoid parent-only failures:
        "country_of_origin": [{"value": "US"}],
        "import_designation": [{"value": "Made in USA"}],
        "department": [{"value": "Baby Girls"}],
        "target_gender": [{"value": "female"}],
        "age_range_description": [{"value": "Infant"}],
        "fabric_type": [{"value": "100% cotton"}],
        "care_instructions": [{"value": "Machine Wash"}],
        "batteries_required": [{"value": False}],
        "supplier_declared_dg_hz_regulation": [{"value": "not_applicable"}],
        "model_name": [{"value": "Crew Neck Bodysuit"}],
    }

# -----------------------------
# Validator for PATCH messages
# -----------------------------
def validate_messages_patch(messages: List[Dict], label: str) -> List[str]:
    problems = []
    for i, m in enumerate(messages, 1):
        pre = f"[{label} #{i}]"
        for k in ("messageId", "sku", "operationType", "productType", "patches"):
            if k not in m:
                problems.append(f"{pre} missing key '{k}'")
        if m.get("operationType") != "PATCH":
            problems.append(f"{pre} operationType must be 'PATCH'")
        patches = m.get("patches")
        if not isinstance(patches, list) or not patches:
            problems.append(f"{pre} patches must be a non-empty list")
            continue
        p0 = patches[0]
        if p0.get("op") != "replace" or p0.get("path") != "/":
            problems.append(f"{pre} patch must have op='replace' and path='/'")

        # NEW: value must be a non-empty ARRAY; first element must contain attributes dict
        val = p0.get("value")
        if not isinstance(val, list) or not val:
            problems.append(f"{pre} value must be a non-empty list (Amazon 2025 schema)")
            continue
        first = val[0] if isinstance(val[0], dict) else {}
        attrs = first.get("attributes")
        if not isinstance(attrs, dict) or not attrs:
            problems.append(f"{pre} value[0].attributes must be a non-empty object")

        # quick sanity: some required attrs
        if isinstance(attrs, dict):
            for field in ("item_name", "brand", "item_type_keyword", "product_description"):
                if field not in attrs:
                    problems.append(f"{pre} missing attributes.{field}")
    return problems
