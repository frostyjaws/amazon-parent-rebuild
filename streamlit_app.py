# streamlit_app.py
import streamlit as st
import json
import time
import re
import pandas as pd
import requests

# Robust imports: try helpers.* first (your original layout), fall back to local files
try:
    from helpers.auth import get_amazon_access_token
    from helpers.util import (
        extract_keywords_from_title,
        injected_bullets,
        injected_description,
        parse_variation,
        sku_from_variation,
        compact_json,
        validate_messages_patch,
        build_patch_message,
        required_core_attrs_for_child,
        required_core_attrs_for_parent,
        PRICE_MAP,
    )
except ModuleNotFoundError:
    from auth import get_amazon_access_token
    from util import (
        extract_keywords_from_title,
        injected_bullets,
        injected_description,
        parse_variation,
        sku_from_variation,
        compact_json,
        validate_messages_patch,
        build_patch_message,
        required_core_attrs_for_child,
        required_core_attrs_for_parent,
        PRICE_MAP,
    )

st.set_page_config(page_title="Amazon Parent Rebuilder — PATCH", layout="wide")
st.title("🧩 Amazon Parent Rebuilder — Unified Bulk (PATCH)")

AMZ_ENDPOINT = "https://sellingpartnerapi-na.amazon.com"
CHECK_INTERVAL = 60
MAX_WAIT_MINUTES = 30

# ---------------- UI ----------------
st.markdown("Paste **Parent SKUs** (one per line):")
parents_text = st.text_area("Parent SKUs", height=200, placeholder="GYROBABY-PARENT\nDINOBABY-PARENT")

st.markdown("*(Optional)* Provide **old child SKUs** to delete; leave blank to delete the set we’re about to rebuild.")
old_children_text = st.text_area("Old child SKUs", height=140, placeholder="GYROBABY-03M-WH-SS\n...")

cols = st.columns(4)
with cols[0]:
    inject_from_title = st.checkbox("Inject keywords from title (for bullets/desc)", value=True)
with cols[1]:
    include_parent_update = st.checkbox("Include PARENT update", value=True)
with cols[2]:
    include_inventory_sync = st.checkbox("Sync inventory after listing", value=True)
with cols[3]:
    default_qty = st.number_input("Inventory quantity", value=999, min_value=0, step=1)

brand_name = st.text_input("Brand Name", "NOFO VIBES")
item_type_keyword = st.text_input("Item Type Keyword", "infant-and-toddler-bodysuits")
variation_theme_display = st.text_input("Variation Theme", "SIZE/COLOR")

DESCRIPTION = st.text_area(
    "Base Description (HTML OK)",
    "<p>Celebrate your little one with our adorable Custom Baby Onesie® — soft, beautiful, and full of NOFO vibes.</p>",
    height=140,
)

BULLETS = st.text_area(
    "Base Bullets (one per line)",
    "\n".join([
        "🎨 Premium DTG Printing — vibrant, lasting color.",
        "🎖️ Veteran-Owned Small Business.",
        "👶 Soft Cotton Comfort — gentle on baby skin.",
        "🎁 Perfect Baby Shower Gift.",
        "📏 Available in multiple sizes & colors."
    ]),
    height=150
).splitlines()

VARIATIONS = [
    "Newborn White Short Sleeve", "Newborn White Long Sleeve", "Newborn Natural Short Sleeve",
    "0-3M White Short Sleeve", "0-3M White Long Sleeve", "0-3M Pink Short Sleeve", "0-3M Blue Short Sleeve",
    "3-6M White Short Sleeve", "3-6M White Long Sleeve", "3-6M Blue Short Sleeve", "3-6M Pink Short Sleeve",
    "6M Natural Short Sleeve", "6-9M White Short Sleeve", "6-9M White Long Sleeve", "6-9M Pink Short Sleeve",
    "6-9M Blue Short Sleeve", "12M White Short Sleeve", "12M White Long Sleeve", "12M Natural Short Sleeve",
    "12M Pink Short Sleeve", "12M Blue Short Sleeve", "18M White Short Sleeve", "18M White Long Sleeve",
    "18M Natural Short Sleeve", "24M White Short Sleeve", "24M White Long Sleeve", "24M Natural Short Sleeve"
]

def submit_json_feed(messages, label, token):
    # Remap messageIds 1..N just before submit
    for i, m in enumerate(messages, 1):
        m["messageId"] = i

    payload = {
        "header": {
            "sellerId": st.secrets["SELLER_ID"],
            "version": "2.0",
            "issueLocale": "en_US"
        },
        "messages": messages,
    }

    doc = requests.post(
        f"{AMZ_ENDPOINT}/feeds/2021-06-30/documents",
        headers={"x-amz-access-token": token, "Content-Type": "application/json"},
        json={"contentType": "application/json"}
    ).json()

    requests.put(doc["url"], data=json.dumps(payload).encode("utf-8"),
                 headers={"Content-Type": "application/json"}).raise_for_status()

    res = requests.post(
        f"{AMZ_ENDPOINT}/feeds/2021-06-30/feeds",
        headers={"x-amz-access-token": token, "Content-Type": "application/json"},
        json={
            "feedType": "JSON_LISTINGS_FEED",
            "marketplaceIds": [st.secrets["MARKETPLACE_ID"]],
            "inputFeedDocumentId": doc["feedDocumentId"],
        }
    ).json()
    fid = res["feedId"]
    st.markdown(f"**📡 {label} Feed ID:** `{fid}`")
    return fid

def poll_feed_until_terminal(feed_id, label, token):
    start = time.time()
    while True:
        time.sleep(CHECK_INTERVAL)
        r = requests.get(f"{AMZ_ENDPOINT}/feeds/2021-06-30/feeds/{feed_id}",
                         headers={"x-amz-access-token": token})
        r.raise_for_status()
        data = r.json()
        status = data.get("processingStatus")
        if status in ("DONE", "FATAL", "CANCELLED"):
            st.markdown(f"✅ **{label} Feed {status}** in {(time.time()-start)/60:.1f} min")
            return status, data
        st.markdown(f"⏳ {label} Feed still {status}...")
        if time.time()-start > MAX_WAIT_MINUTES*60:
            st.error(f"⛔ Timeout waiting for {label} Feed")
            return "TIMEOUT", data

def download_processing_report_if_ready(feed_json, token):
    doc_id = feed_json.get("resultFeedDocumentId")
    if not doc_id: return None
    info = requests.get(f"{AMZ_ENDPOINT}/feeds/2021-06-30/documents/{doc_id}",
                        headers={"x-amz-access-token": token}).json()
    url = info.get("url")
    if not url: return None
    rep = requests.get(url); rep.raise_for_status()
    return rep.text

# ---------------- Action ----------------
if st.button("🚀 Run Full Rebuild (PATCH)"):
    parents = [p.strip() for p in parents_text.splitlines() if p.strip()]
    old_children = [c.strip() for c in old_children_text.splitlines() if c.strip()]
    if not parents:
        st.error("Enter at least one parent SKU."); st.stop()

    token = get_amazon_access_token()

    delete_msgs = []
    create_msgs = []
    parent_msgs = []
    inventory_rows = []

    for parent_sku in parents:
        base = re.sub(r"-PARENT$", "", parent_sku.strip(), flags=re.I)
        title_val = f"{base.replace('-', ' ').strip()} - Baby Bodysuit"

        kws = extract_keywords_from_title(title_val) if inject_from_title else []
        desc = injected_desc_
