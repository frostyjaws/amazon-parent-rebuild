import streamlit as st
import json
import time
import re
from helpers.auth import get_amazon_access_token
from helpers.util import (
    extract_keywords_from_title,
    injected_bullets,
    injected_description,
    injected_generic_keywords,
    compact_json,
)
from inventory_feed_submitter import submit_inventory_feed

import requests

st.set_page_config(page_title="Amazon Parent Rebuilder", layout="wide")
st.title("🧩 Amazon Parent Rebuilder — Unified Bulk Mode")

# === SETTINGS ===
CHECK_INTERVAL = 60  # seconds between polling checks
MAX_WAIT_MINUTES = 30
AMZ_ENDPOINT = "https://sellingpartnerapi-na.amazon.com"

# === UI ===
st.markdown("Paste Parent SKUs below (one per line):")
parents_text = st.text_area("Parent SKUs", height=200, placeholder="GYROBABY-PARENT\nDINOBABY-PARENT")

inject_from_title = st.checkbox("Inject keywords from title", value=True)
include_parent_update = st.checkbox("Include parent partial updates", value=True)
include_inventory_sync = st.checkbox("Sync inventory after rebuild", value=True)

brand_name = st.text_input("Brand Name", "NOFO VIBES")
item_type_keyword = st.text_input("Item Type Keyword", "infant-and-toddler-bodysuits")
variation_theme_display = st.text_input("Variation Theme", "SIZE/COLOR")

# Load your base description/bullets
DESCRIPTION = """
<p>Celebrate the arrival of your little one with our adorable Custom Baby Onesie®, the perfect baby shower gift that will be cherished for years to come. Soft cotton, beautiful printing, and a whole lot of NOFO vibes.</p>
"""
BULLETS = [
    "🎨 High-Quality Printing: vibrant, long-lasting colors using direct-to-garment printing.",
    "🎖️ Proudly Veteran-Owned: support a small, USA-based business.",
    "👶 Comfortable & Safe: crafted from soft cotton for all-day wear.",
    "🎁 Perfect Baby Shower Gift: thoughtful, funny, and memorable.",
    "📏 Wide Range: available in various colors and sizes for newborns and infants."
]

if st.button("🚀 Run Full Rebuild"):
    PARENTS = [p.strip() for p in parents_text.splitlines() if p.strip()]
    if not PARENTS:
        st.error("Please enter at least one parent SKU.")
        st.stop()

    token = get_amazon_access_token()

    # === 1️⃣ Build unified message pools ===
    delete_messages, create_messages, parent_messages, inventory_rows = [], [], [], []

    for parent_sku in PARENTS:
        base_name = re.sub(r"-PARENT$", "", parent_sku.strip(), flags=re.IGNORECASE)
        title_val = f"{base_name.replace('-', ' ').strip()} - Baby Bodysuit"
        kws = extract_keywords_from_title(title_val) if inject_from_title else []

        desc = injected_description(DESCRIPTION, kws)
        bullets = injected_bullets(kws, BULLETS)
        gen_kw = injected_generic_keywords(kws)

        # Example: new variations
        variations = [
            ("NB", "White Short Sleeve"),
            ("03M", "White Long Sleeve"),
            ("36M", "Pink Short Sleeve"),
        ]

        # Build DELETE + CREATE messages
        for code, var in variations:
            child_sku = f"{base_name}-{code}-{var.replace(' ', '').upper()}"
            # DELETE
            delete_messages.append({
                "messageId": 0,
                "sku": child_sku,
                "operationType": "DELETE",
                "productType": "LEOTARD"
            })
            # CREATE
            create_messages.append({
                "messageId": 0,
                "sku": child_sku,
                "operationType": "UPDATE",
                "productType": "LEOTARD",
                "requirements": "LISTING",
                "attributes": {
                    "item_name": [{"value": f"{title_val} - {var}"}],
                    "brand": [{"value": brand_name}],
                    "item_type_keyword": [{"value": item_type_keyword}],
                    "product_description": [{"value": desc}],
                    "bullet_point": [{"value": b} for b in bullets],
                    "generic_keywords": [{"value": gen_kw}],
                    "parentage_level": [{"value": "child"}],
                    "child_parent_sku_relationship": [{
                        "child_relationship_type": "variation",
                        "parent_sku": parent_sku
                    }],
                    "size": [{"value": var}],
                    "color": [{"value": "multi"}],
                    "material": [{"value": "Cotton"}],
                    "country_of_origin": [{"value": "US"}],
                    "condition_type": [{"value": "new_new"}],
                }
            })
            # Inventory line
            inventory_rows.append(child_sku)

        # PARENT refresh
        parent_messages.append({
            "messageId": 0,
            "sku": parent_sku,
            "operationType": "UPDATE",
            "productType": "LEOTARD",
            "requirements": "LISTING",
            "attributes": {
                "item_name": [{"value": title_val}],
                "brand": [{"value": brand_name}],
                "item_type_keyword": [{"value": item_type_keyword}],
                "product_description": [{"value": desc}],
                "bullet_point": [{"value": b} for b in bullets],
                "generic_keywords": [{"value": gen_kw}],
                "parentage_level": [{"value": "parent"}],
                "variation_theme": [{"name": variation_theme_display}],
            }
        })

    # === Helper to submit and poll feeds ===
    def submit_json_feed(messages, feed_label):
        if not messages:
            return None
        for i, msg in enumerate(messages, start=1):
            msg["messageId"] = i
        payload = {
            "header": {
                "sellerId": st.secrets["SELLER_ID"],
                "version": "2.0",
                "issueLocale": "en_US"
            },
            "messages": messages
        }
        # Step 1: Create doc
        doc_res = requests.post(
            f"{AMZ_ENDPOINT}/feeds/2021-06-30/documents",
            headers={"x-amz-access-token": token, "Content-Type": "application/json"},
            json={"contentType": "application/json"}
        )
        doc_res.raise_for_status()
        doc = doc_res.json()

        # Step 2: Upload content
        requests.put(
            doc["url"],
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        ).raise_for_status()

        # Step 3: Submit feed
        feed_res = requests.post(
            f"{AMZ_ENDPOINT}/feeds/2021-06-30/feeds",
            headers={"x-amz-access-token": token, "Content-Type": "application/json"},
            json={
                "feedType": "JSON_LISTINGS_FEED",
                "marketplaceIds": [st.secrets["MARKETPLACE_ID"]],
                "inputFeedDocumentId": doc["feedDocumentId"]
            }
        )
        feed_res.raise_for_status()
        feed_id = feed_res.json()["feedId"]
        st.markdown(f"**📡 {feed_label} Feed ID:** `{feed_id}`")
        return feed_id

    def poll_feed(feed_id, label):
        start = time.time()
        while True:
            time.sleep(CHECK_INTERVAL)
            res = requests.get(
                f"{AMZ_ENDPOINT}/feeds/2021-06-30/feeds/{feed_id}",
                headers={"x-amz-access-token": token}
            )
            res.raise_for_status()
            data = res.json()
            status = data.get("processingStatus")
            if status in ("DONE", "FATAL", "CANCELLED"):
                elapsed = time.time() - start
                st.markdown(f"✅ **{label} Feed {status}** in {elapsed/60:.1f} min")
                return data
            else:
                st.markdown(f"⏳ {label} Feed still {status}...")
            if (time.time() - start) > MAX_WAIT_MINUTES * 60:
                st.error(f"Timeout waiting for {label} Feed")
                return None

    # === 2️⃣ Execute unified feeds ===
    st.markdown("### 🗑️ Submitting DELETE feed...")
    del_id = submit_json_feed(delete_messages, "DELETE")
    del_status = poll_feed(del_id, "DELETE") if del_id else None

    st.markdown("### 🧱 Submitting CREATE feed...")
    create_id = submit_json_feed(create_messages, "CREATE")
    create_status = poll_feed(create_id, "CREATE") if create_id else None

    if include_parent_update:
        st.markdown("### 🏷️ Submitting PARENT update feed...")
        parent_id = submit_json_feed(parent_messages, "PARENT")
        parent_status = poll_feed(parent_id, "PARENT") if parent_id else None
    else:
        parent_id, parent_status = None, None

    if include_inventory_sync:
        st.markdown("### 🧾 Submitting INVENTORY feed...")
        try:
            inv_id = submit_inventory_feed(
                inventory_rows,
                token,
                st.secrets["MARKETPLACE_ID"],
                st.secrets["SELLER_ID"]
            )
            inv_status = poll_feed(inv_id, "INVENTORY")
        except Exception as e:
            st.error(f"Inventory sync failed: {e}")
            inv_id, inv_status = None, None
    else:
        inv_id, inv_status = None, None

    st.success("🎉 Bulk rebuild complete!")

    summary = [
        ["DELETE", del_id],
        ["CREATE", create_id],
        ["PARENT", parent_id],
        ["INVENTORY", inv_id],
    ]
    st.table(summary)
