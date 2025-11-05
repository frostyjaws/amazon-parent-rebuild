import os
import json
import re
import requests
import streamlit as st
from typing import List, Dict

# Local imports
from helpers.auth import get_amazon_access_token
from helpers.util import (
    build_child_sku,
    split_variation,
    extract_keywords_from_title,
    injected_bullets,
    injected_description,
    injected_generic_keywords,
    parse_swatches,
    compact_json,
)
from inventory_feed_submitter import submit_inventory_feed

# =========================
# 🔧 CONFIG / SECRETS
# =========================
LWA_CLIENT_ID = st.secrets["LWA_CLIENT_ID"]
LWA_CLIENT_SECRET = st.secrets["LWA_CLIENT_SECRET"]
REFRESH_TOKEN = st.secrets["REFRESH_TOKEN"]
MARKETPLACE_ID = st.secrets["MARKETPLACE_ID"]
SELLER_ID = st.secrets["SELLER_ID"]

# =========================
# 🎨 PAGE SETUP
# =========================
st.set_page_config(page_title="Amazon Parent/Child Rebuilder", layout="wide")
st.title("🧸 Amazon Parent / Replace Children (JSON_LISTINGS_FEED)")
st.caption("Deletes old children, creates new ones, and optionally updates parent attributes.")

# =========================
# ⚙️ BASE SETTINGS
# =========================
col1, col2, col3, col4 = st.columns(4)
brand_name = col1.text_input("brand_name", value="NOFO VIBES")
item_type_keyword = col2.text_input("item_type_keyword", value="infant-and-toddler-bodysuits")
default_price = float(col3.text_input("Default price (USD)", value="18.99"))
default_qty = int(col4.text_input("Default quantity", value="999"))

variation_theme = "SIZE/COLOR"
care_instructions = "Machine Wash"

include_parent_partial = st.checkbox("Include Parent Partial Update", value=True)
inject_from_title = st.checkbox("Inject pre-dash keywords into bullets/description", value=True)

st.markdown("### 🎨 Swatch Mapping (Color → URL, one per line: `White,https://...`)")
SWATCHES = parse_swatches(
    st.text_area(
        "Swatches",
        value="White,https://example.com/white.png\nNatural,https://example.com/natural.png\nPink,https://example.com/pink.png",
        height=100,
    )
)

# =========================
# 📄 TEXT BLOCKS
# =========================
DEFAULT_DESCRIPTION = """
Soft 100% cotton baby bodysuit with snap closure and comfy fit.
"""

DEFAULT_BULLETS = [
    "🎨 High-Quality Ink Printing: Vibrant, long-lasting colors thanks to DTG printing.",
    "🎖️ Veteran-Owned: Support small business while dressing your little one in style.",
    "👶 Comfort & Convenience: Soft cotton fabric and easy snap closures.",
    "🎁 Perfect Baby Shower Gift: Adorable and meaningful keepsake bodysuit.",
    "📏 Versatile Sizing: Available in multiple colors and sizes for every little one."
]

DESCRIPTION = st.text_area("Product Description", value=DEFAULT_DESCRIPTION, height=140)
BULLETS = st.text_area("Bullets", value="\n".join(DEFAULT_BULLETS), height=150).splitlines()

# =========================
# 🧱 INPUT SECTIONS
# =========================
st.markdown("### 🧩 Step 1: Parent SKUs")
PARENTS = [ln.strip() for ln in st.text_area("Parent SKUs", height=120).splitlines() if ln.strip()]

st.markdown("### 🧩 Step 2: New Variations (e.g. `0-3M Short White`)")
VARIATIONS = [ln.strip() for ln in st.text_area("New Variations", height=220).splitlines() if ln.strip()]

st.markdown("### 🧩 Step 3: Old Children (for deletion, optional)")
OLD_CHILDREN = [ln.strip() for ln in st.text_area("Old child SKUs", height=120).splitlines() if ln.strip()]

# =========================
# 🧠 CORE BUILDERS
# =========================
def msg_parent_partial(parent_sku: str) -> Dict:
    base = re.sub(r"-Parent$", "", parent_sku.strip(), flags=re.IGNORECASE)
    title = f"{base.replace('-', ' ').strip()} - Baby Bodysuit"
    keywords = extract_keywords_from_title(title) if inject_from_title else []
    desc = injected_description(DESCRIPTION, keywords)
    bullets = injected_bullets(keywords, BULLETS)
    gen_kw = injected_generic_keywords(keywords)

    return {
        "messageId": 0,
        "sku": parent_sku,
        "operationType": "UPDATE",
        "productType": "LEOTARD",
        "requirements": "LISTING",
        "attributes": {
            "item_name": [{"value": title}],
            "brand": [{"value": brand_name}],
            "item_type_keyword": [{"value": item_type_keyword}],
            "product_description": [{"value": desc}],
            "bullet_point": [{"value": x} for x in bullets],
            "generic_keywords": [{"value": gen_kw}],
            "parentage_level": [{"value": "parent"}],
            "variation_theme": [{"name": variation_theme}],
            "fabric_type": [{"value": "100% cotton"}],
            "care_instructions": [{"value": care_instructions}],
            "supplier_declared_has_product_identifier_exemption": [{"value": True}],
        },
    }


def msg_child_delete(sku: str) -> Dict:
    return {
        "messageId": 0,
        "sku": sku,
        "operationType": "DELETE",
        "productType": "LEOTARD",
        "requirements": "LISTING",
        "attributes": {},
    }


def msg_child_update(parent_sku: str, variation_str: str) -> Dict:
    size, sleeve, color = split_variation(variation_str)
    child_sku = build_child_sku(parent_sku, variation_str)
    base = re.sub(r"-Parent$", "", parent_sku.strip(), flags=re.IGNORECASE)
    title = f"{base.replace('-', ' ').strip()} {variation_str} - Baby Bodysuit"
    keywords = extract_keywords_from_title(title) if inject_from_title else []
    desc = injected_description(DESCRIPTION, keywords)
    bullets = injected_bullets(keywords, BULLETS)
    gen_kw = injected_generic_keywords(keywords)
    swatch = SWATCHES.get(color, "")

    return {
        "messageId": 0,
        "sku": child_sku,
        "operationType": "UPDATE",
        "productType": "LEOTARD",
        "requirements": "LISTING",
        "attributes": {
            "item_name": [{"value": title}],
            "brand": [{"value": brand_name}],
            "item_type_keyword": [{"value": item_type_keyword}],
            "product_description": [{"value": desc}],
            "bullet_point": [{"value": x} for x in bullets],
            "generic_keywords": [{"value": gen_kw}],
            "parentage_level": [{"value": "child"}],
            "child_parent_sku_relationship": [
                {"child_relationship_type": "variation", "parent_sku": parent_sku}
            ],
            "variation_theme": [{"name": variation_theme}],
            "size": [{"value": size}],
            "style": [{"value": f"{sleeve} Sleeve"}] if sleeve else [],
            "color": [{"value": color}],
            "swatch_image_locator": [{"media_location": swatch, "marketplace_id": MARKETPLACE_ID}] if swatch else [],
            "list_price": [{"currency": "USD", "value": default_price}],
            "purchasable_offer": [
                {
                    "currency": "USD",
                    "our_price": [{"schedule": [{"value_with_tax": default_price}]}],
                    "marketplace_id": MARKETPLACE_ID,
                }
            ],
            "fulfillment_availability": [
                {
                    "quantity": default_qty,
                    "fulfillment_channel_code": "DEFAULT",
                    "marketplace_id": MARKETPLACE_ID,
                }
            ],
            "supplier_declared_has_product_identifier_exemption": [{"value": True}],
        },
    }

# =========================
# 🧱 FEED SUBMISSION
# =========================
def submit_json_feed(messages: List[Dict]) -> str:
    """Upload feed and return Feed ID"""
    token = get_amazon_access_token(LWA_CLIENT_ID, LWA_CLIENT_SECRET, REFRESH_TOKEN)

    # Remap message IDs
    for i, m in enumerate(messages, start=1):
        m["messageId"] = i

    body = {
        "header": {
            "sellerId": SELLER_ID,
            "version": "2.0",
            "issueLocale": "en_US",
        },
        "messages": messages,
    }

    # 1. Create document
    doc_res = requests.post(
        "https://sellingpartnerapi-na.amazon.com/feeds/2021-06-30/documents",
        headers={"x-amz-access-token": token, "Content-Type": "application/json"},
        json={"contentType": "application/json"},
    )
    doc_res.raise_for_status()
    doc = doc_res.json()

    # 2. Upload JSON
    upload = requests.put(
        doc["url"],
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    upload.raise_for_status()

    # 3. Submit feed
    feed_res = requests.post(
        "https://sellingpartnerapi-na.amazon.com/feeds/2021-06-30/feeds",
        headers={"x-amz-access-token": token, "Content-Type": "application/json"},
        json={
            "feedType": "JSON_LISTINGS_FEED",
            "marketplaceIds": [MARKETPLACE_ID],
            "inputFeedDocumentId": doc["feedDocumentId"],
        },
    )
    feed_res.raise_for_status()
    return feed_res.json()["feedId"]

# =========================
# 🧩 BUILD & PREVIEW
# =========================
DELETE_MSGS, CREATE_MSGS, PARENT_MSGS = [], [], []

c1, c2, c3 = st.columns(3)
if c1.button("🗑️ Build DELETE messages"):
    targets = OLD_CHILDREN or [build_child_sku(p, v) for p in PARENTS for v in VARIATIONS]
    DELETE_MSGS = [msg_child_delete(sku) for sku in targets]
    st.warning(f"DELETE messages built: {len(DELETE_MSGS)}")
    st.code(compact_json(DELETE_MSGS, 3), language="json")

if c2.button("🧩 Build CREATE messages"):
    CREATE_MSGS = [msg_child_update(p, v) for p in PARENTS for v in VARIATIONS]
    st.success(f"CREATE messages built: {len(CREATE_MSGS)}")
    st.code(compact_json(CREATE_MSGS, 3), language="json")

if c3.button("🏷️ Build PARENT PartialUpdate messages") and include_parent_partial:
    PARENT_MSGS = [msg_parent_partial(p) for p in PARENTS]
    st.info(f"PARENT messages built: {len(PARENT_MSGS)}")
    st.code(compact_json(PARENT_MSGS, 1), language="json")

# =========================
# 🚀 SUBMIT
# =========================
st.markdown("## 🚀 Submit Feeds to Amazon")
b1, b2, b3 = st.columns(3)

if b1.button("Submit DELETE Feed") and DELETE_MSGS:
    try:
        fid = submit_json_feed(DELETE_MSGS)
        st.success(f"DELETE Feed Submitted ✅ — Feed ID: {fid}")
    except Exception as e:
        st.exception(e)

if b2.button("Submit CREATE Feed") and CREATE_MSGS:
    try:
        fid = submit_json_feed(CREATE_MSGS)
        st.success(f"CREATE Feed Submitted ✅ — Feed ID: {fid}")
    except Exception as e:
        st.exception(e)

if b3.button("Submit PARENT PartialUpdate Feed") and include_parent_partial and PARENT_MSGS:
    try:
        fid = submit_json_feed(PARENT_MSGS)
        st.success(f"PARENT Feed Submitted ✅ — Feed ID: {fid}")
    except Exception as e:
        st.exception(e)

# =========================
# 🧾 INVENTORY SYNC (Optional)
# =========================
st.markdown("### 🧾 Update Inventory Quantities (Optional)")
if st.button("Submit Inventory Feed for New Children"):
    try:
        token = get_amazon_access_token(LWA_CLIENT_ID, LWA_CLIENT_SECRET, REFRESH_TOKEN)
        skus = [msg["sku"] for msg in CREATE_MSGS]
        fid = submit_inventory_feed(skus, token, MARKETPLACE_ID, SELLER_ID)
        st.success(f"Inventory Feed Submitted — Feed ID: {fid}")
    except Exception as e:
        st.exception(e)

st.caption("Workflow: Submit DELETE → wait → CREATE → (optional PARENT partial update) → (optional INVENTORY update).")
