import json, re

STOP_WORDS = {"NOFO", "VIBES", "BODYSUIT", "ONESIE"}

# -----------------------------
# Keyword extraction & injections
# -----------------------------
def extract_keywords_from_title(title: str):
    pre = title.split(" - ", 1)[0] if " - " in title else title
    words = [w for w in re.findall(r"[A-Za-z0-9']+", pre) if w]
    seen, out = set(), []
    for w in words:
        if w.upper() in STOP_WORDS: 
            continue
        lw = w.lower()
        if lw not in seen:
            seen.add(lw); out.append(w)
    return out

def injected_bullets(kws, base_bullets):
    tpls = [
        "🎨 Premium DTG print: '{kw}'",
        "🎖️ Veteran-Owned small biz — '{kw}'",
        "👶 100% cotton comfort — '{kw}'",
        "🎁 Great baby shower gift: '{kw}'",
        "📏 Many sizes & colors available."
    ]
    out = []
    for i in range(5):
        if i < len(kws):
            out.append(tpls[i].format(kw=kws[i]))
        elif i < len(base_bullets):
            out.append(base_bullets[i])
        else:
            out.append("")
    return out

def injected_description(base_html, kws):
    if not kws:
        return base_html
    return base_html.rstrip() + " " + f"<p>Design theme: {', '.join(kws[:3])}.</p>"

def compact_json(obj):
    return json.dumps(obj, indent=2)

# -----------------------------
# Variation parsing & SKU codes
# -----------------------------
def parse_variation(variation_str: str):
    parts = variation_str.strip().split()
    if len(parts) >= 3:
        size, color, sleeve = parts[0], parts[1], " ".join(parts[2:])
    elif len(parts) == 2:
        size, color, sleeve = parts[0], parts[1], ""
    else:
        size, color, sleeve = parts[0] if parts else "", "", ""
    return size, color.capitalize(), sleeve.title()

def _size_code(s):
    return {"Newborn":"NB","0-3M":"03M","3-6M":"36M","6-9M":"69M","6M":"06M","12M":"12M","18M":"18M","24M":"24M"}.get(s, re.sub(r"[^A-Za-z0-9]","",s).upper()[:4] or "SZ")

def _color_code(c):
    return {"White":"WH","Natural":"NA","Pink":"PK","Blue":"BL"}.get(c.capitalize(), re.sub(r"[^A-Za-z0-9]","",c).upper()[:2] or "XX")

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
    "24M Natural Short Sleeve": 33.99
}

# -----------------------------
# PATCH message helpers (2025 schema)
# -----------------------------
def build_patch_message(*, message_id:int, sku:str, product_type:str, attributes:dict):
    """
    Build a JSON_LISTINGS_FEED 'PATCH' message with attributes nested under patches[].value.attributes
    """
    return {
        "messageId": message_id,
        "sku": sku,
        "operationType": "PATCH",
        "productType": product_type,
        "patches": [{
            "op": "replace",
            "path": "/",
            "value": {
                "attributes": attributes
            }
        }]
    }

def required_core_attrs_for_child(*, title_val:str, size:str, color:str, sleeve:str,
                                  brand:str, item_type_keyword:str, desc_html:str, bullets:list,
                                  country_of_origin:str="US", import_designation:str="Made in USA",
                                  department:str="Baby Girls", target_gender:str="female",
                                  age_range:str="Infant", fabric_type:str="100% cotton",
                                  care_instructions:str="Machine Wash",
                                  batteries_required:bool=False,
                                  dg_regulation:str="not_applicable",
                                  pkg_len:float=3, pkg_wid:float=3, pkg_hgt:float=1, pkg_unit:str="inches",
                                  pkg_weight:float=0.19, pkg_weight_unit:str="kilograms",
                                  model_name:str="Crew Neck Bodysuit",
                                  list_price:float=29.99):
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
            "width":  {"value": pkg_wid, "unit": pkg_unit},
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

def required_core_attrs_for_parent(*, title_val:str, brand:str, item_type_keyword:str,
                                   desc_html:str, bullets:list,
                                   variation_theme_display:str="SIZE/COLOR"):
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
def validate_messages_patch(messages, label):
    problems=[]
    for i, m in enumerate(messages, 1):
        pre=f"[{label} #{i}]"
        for k in ("messageId","sku","operationType","productType","patches"):
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
        val = p0.get("value", {})
        attrs = val.get("attributes")
        if not isinstance(attrs, dict) or not attrs:
            problems.append(f"{pre} value.attributes must be a non-empty object")
        # quick sanity: some required attrs
        for field in ("item_name","brand","item_type_keyword","product_description"):
            if field not in attrs:
                problems.append(f"{pre} missing attributes.{field}")
    return problems
