import streamlit as st
import json
import time
import re
import pandas as pd
import requests

from helpers.auth import get_amazon_access_token
from helpers.util import (
    extract_keywords_from_title,
    injected_bullets,
    injected_description,
    injected_generic_keywords,
    parse_variation,
    sku_from_variation,
    compact_json,
    validate_messages,
)

from inventory_feed_submitter import (
    submit_inventory_feed,
    check_inventory_feed_status,
    download_inventory_processing_report,
)

st.set_page_config(page_title="Amazon Parent Rebuilder", layout="wide")
st.title("🧩 Amazon Parent Rebuilder — Unified Bulk Mode")

AMZ_ENDPOINT = "https://sellingpartnerapi-na.amazon.com"
CHECK_INTERVAL = 60
MAX_WAIT_MINUTES = 30

# ---------------- UI ----------------
st.markdown("Paste **Parent SKUs** (one per line):")
parents_text = st.text_area("Parent SKUs", height=200)
st.markdown("*(Optional)* Old child SKUs to delete*")
old_children_text = st.text_area("Old child SKUs", height=160)

cols = st.columns(4)
with cols[0]:
    inject_from_title = st.checkbox("Inject keywords from title", value=True)
with cols[1]:
    include_parent_update = st.checkbox("Include PARENT update", value=True)
with cols[2]:
    include_inventory_sync = st.checkbox("Sync inventory", value=True)
with cols[3]:
    default_qty = st.number_input("Inventory quantity", value=999, min_value=0, step=1)

brand_name = st.text_input("Brand Name", "NOFO VIBES")
item_type_keyword = st.text_input("Item Type Keyword", "infant-and-toddler-bodysuits")
variation_theme_display = st.text_input("Variation Theme", "SIZE/COLOR")

DESCRIPTION = st.text_area(
    "Base Description",
    "<p>Celebrate your little one with our adorable Custom Baby Onesie® — soft, beautiful, and full of NOFO vibes.</p>",
    height=140,
)
BULLETS = st.text_area(
    "Base Bullets",
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

# ---------------- FEED HELPERS ----------------
def submit_json_feed(messages, feed_label, token):
    for i, msg in enumerate(messages, start=1):
        msg["messageId"] = i

    payload = {
        "header": {
            "sellerId": st.secrets["SELLER_ID"],
            "version": "2.0",
            "issueLocale": "en_US",
        },
        "messages": messages,
    }

    doc_res = requests.post(
        f"{AMZ_ENDPOINT}/feeds/2021-06-30/documents",
        headers={"x-amz-access-token": token, "Content-Type": "application/json"},
        json={"contentType": "application/json"},
    )
    doc_res.raise_for_status()
    doc = doc_res.json()

    requests.put(
        doc["url"],
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    ).raise_for_status()

    feed_res = requests.post(
        f"{AMZ_ENDPOINT}/feeds/2021-06-30/feeds",
        headers={"x-amz-access-token": token, "Content-Type": "application/json"},
        json={
            "feedType": "JSON_LISTINGS_FEED",
            "marketplaceIds": [st.secrets["MARKETPLACE_ID"]],
            "inputFeedDocumentId": doc["feedDocumentId"],
        },
    )
    feed_res.raise_for_status()
    fid = feed_res.json()["feedId"]
    st.markdown(f"**📡 {feed_label} Feed ID:** `{fid}`")
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
            elapsed = time.time() - start
            st.markdown(f"✅ **{label} Feed {status}** in {elapsed/60:.1f} min")
            return status, elapsed, data
        st.markdown(f"⏳ {label} Feed still {status}...")
        if (time.time() - start) > MAX_WAIT_MINUTES * 60:
            st.error(f"⛔ Timeout waiting for {label} Feed")
            return "TIMEOUT", MAX_WAIT_MINUTES * 60, data


def download_processing_report_if_ready(feed_json, token):
    doc_id = feed_json.get("resultFeedDocumentId")
    if not doc_id:
        return None
    info = requests.get(f"{AMZ_ENDPOINT}/feeds/2021-06-30/documents/{doc_id}",
                        headers={"x-amz-access-token": token})
    url = info.json().get("url")
    if not url:
        return None
    return requests.get(url).text

# ---------------- MAIN ACTION ----------------
if st.button("🚀 Run Full Rebuild"):
    PARENTS = [p.strip() for p in parents_text.splitlines() if p.strip()]
    OLD_CHILDREN = [c.strip() for c in old_children_text.splitlines() if c.strip()]
    if not PARENTS:
        st.error("Enter at least one parent SKU.")
        st.stop()

    token = get_amazon_access_token()
    delete_msgs, create_msgs, parent_msgs, inventory = [], [], [], []

    for parent in PARENTS:
        base = re.sub(r"-PARENT$", "", parent, flags=re.I)
        title_val = f"{base.replace('-', ' ')} - Baby Bodysuit"
        kws = extract_keywords_from_title(title_val) if inject_from_title else []
        desc = injected_description(DESCRIPTION, kws)
        bullets = injected_bullets(kws, BULLETS)
        gen_kw = injected_generic_keywords(kws)

        if include_parent_update:
            parent_msgs.append({
                "messageId": 0,
                "sku": parent,
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

        for v in VARIATIONS:
            size, color, sleeve = parse_variation(v)
            sku = sku_from_variation(base, size, color, sleeve)

            if not OLD_CHILDREN:
                delete_msgs.append({
                    "messageId": 0, "sku": sku,
                    "operationType": "DELETE", "productType": "LEOTARD"
                })

            create_msgs.append({
                "messageId": 0,
                "sku": sku,
                "operationType": "UPDATE",
                "productType": "LEOTARD",
                "requirements": "LISTING",
                "attributes": {
                    "item_name": [{"value": f"{title_val} - {size} {color} {sleeve}"}],
                    "brand": [{"value": brand_name}],
                    "item_type_keyword": [{"value": item_type_keyword}],
                    "product_description": [{"value": desc}],
                    "bullet_point": [{"value": b} for b in bullets],
                    "generic_keywords": [{"value": gen_kw}],
                    "parentage_level": [{"value": "child"}],
                    "child_parent_sku_relationship": [{
                        "child_relationship_type": "variation",
                        "parent_sku": parent
                    }],
                    "variation_theme": [{"name": variation_theme_display}],
                    "size": [{"value": size}],
                    "color": [{"value": color}],
                    "style": [{"value": sleeve}],
                    "material": [{"value": "Cotton"}],
                    "country_of_origin": [{"value": "US"}],
                    "condition_type": [{"value": "new_new"}],
                    "supplier_declared_has_product_identifier_exemption": [{"value": True}],
                }
            })
            inventory.append(sku)

    if OLD_CHILDREN:
        delete_msgs = [{"messageId": 0, "sku": s, "operationType": "DELETE", "productType": "LEOTARD"} for s in OLD_CHILDREN]

    # Validation
    probs = []
    probs += validate_messages(create_msgs, True, "CREATE")
    probs += validate_messages(delete_msgs, False, "DELETE")
    if include_parent_update:
        probs += validate_messages(parent_msgs, True, "PARENT")
    if probs:
        st.error("❌ Validation failed. Nothing sent.")
        for p in probs:
            st.write(p)
        st.stop()

    results = []
    del_id = submit_json_feed(delete_msgs, "DELETE", token)
    del_status, del_elapsed, del_json = poll_feed_until_terminal(del_id, "DELETE", token)
    results.append(["DELETE", del_id, del_status, f"{del_elapsed/60:.1f} min", len(delete_msgs)])

    create_id = submit_json_feed(create_msgs, "CREATE", token)
    create_status, create_elapsed, create_json = poll_feed_until_terminal(create_id, "CREATE", token)
    results.append(["CREATE", create_id, create_status, f"{create_elapsed/60:.1f} min", len(create_msgs)])

    if include_parent_update:
        parent_id = submit_json_feed(parent_msgs, "PARENT", token)
        parent_status, parent_elapsed, parent_json = poll_feed_until_terminal(parent_id, "PARENT", token)
        results.append(["PARENT", parent_id, parent_status, f"{parent_elapsed/60:.1f} min", len(parent_msgs)])
    else:
        results.append(["PARENT", "-", "SKIPPED", "-", "-"])

    if include_inventory_sync:
        inv_id = submit_inventory_feed(inventory, token, st.secrets["MARKETPLACE_ID"], st.secrets["SELLER_ID"], quantity=default_qty)
        inv_status, inv_elapsed, inv_json = poll_feed_until_terminal(inv_id, "INVENTORY", token)
        results.append(["INVENTORY", inv_id, inv_status, f"{inv_elapsed/60:.1f} min", len(inventory)])
    else:
        results.append(["INVENTORY", "-", "SKIPPED", "-", "-"])

    st.success("🎉 Rebuild Complete!")
    st.dataframe(pd.DataFrame(results, columns=["Feed", "ID", "Status", "Elapsed", "Count"]))
