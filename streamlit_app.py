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
)

from inventory_feed_submitter import (
    submit_inventory_feed,
    check_inventory_feed_status,
    download_inventory_processing_report,
)

# ============================
# Page / Constants
# ============================
st.set_page_config(page_title="Amazon Parent Rebuilder — Unified Bulk", layout="wide")
st.title("🧩 Amazon Parent Rebuilder — Unified Bulk Mode")

AMZ_ENDPOINT = "https://sellingpartnerapi-na.amazon.com"
CHECK_INTERVAL = 60          # seconds between polling checks
MAX_WAIT_MINUTES = 30        # fail-safe timeout for each feed phase

# ============================
# UI Inputs
# ============================
st.markdown("Paste **Parent SKUs** (one per line):")
parents_text = st.text_area(
    "Parent SKUs",
    height=200,
    placeholder="GYROBABY-PARENT\nDINOBABY-PARENT\nSNACKBABY-PARENT",
)

# Optional: paste exact old child SKUs to delete. If blank, we'll delete the children we plan to recreate.
st.markdown("*(Optional)* Paste **OLD Child SKUs to delete** (one per line). If left empty, we'll delete the same SKUs we plan to create to ensure a clean slate.")
old_children_text = st.text_area(
    "Old child SKUs (optional)",
    height=160,
    placeholder="GYROBABY-03M-WH-SS\nGYROBABY-36M-PK-SS\n..."
)

cols = st.columns(4)
with cols[0]:
    inject_from_title = st.checkbox("Inject keywords from title", value=True)
with cols[1]:
    include_parent_update = st.checkbox("Include PARENT partial update", value=True)
with cols[2]:
    include_inventory_sync = st.checkbox("Sync inventory afterward", value=True)
with cols[3]:
    default_qty = st.number_input("Inventory quantity", value=999, min_value=0, step=1)

brand_name = st.text_input("Brand Name", "NOFO VIBES")
item_type_keyword = st.text_input("Item Type Keyword", "infant-and-toddler-bodysuits")
variation_theme_display = st.text_input("Variation Theme (display string)", "SIZE/COLOR")

DESCRIPTION = st.text_area(
    "Base Description (HTML OK)",
    value=(
        "<p>Celebrate the arrival of your little one with our adorable Custom Baby Onesie®, "
        "the perfect baby shower gift that will be cherished for years to come. Soft cotton, "
        "beautiful printing, and a whole lot of NOFO vibes.</p>"
    ),
    height=140,
)

BULLETS = st.text_area(
    "Base Bullets (one per line)",
    value="\n".join([
        "🎨 High-Quality Printing: vibrant, long-lasting colors using direct-to-garment printing.",
        "🎖️ Proudly Veteran-Owned: support a small, USA-based business.",
        "👶 Comfortable & Safe: crafted from soft cotton for all-day wear.",
        "🎁 Perfect Baby Shower Gift: thoughtful, funny, and memorable.",
        "📏 Wide Range: available in various colors and sizes for newborns and infants."
    ]),
    height=150
).splitlines()

# ============================
# Full Variation Matrix (your production set)
# ============================
VARIATIONS = [
    "Newborn White Short Sleeve", "Newborn White Long Sleeve", "Newborn Natural Short Sleeve",
    "0-3M White Short Sleeve", "0-3M White Long Sleeve", "0-3M Pink Short Sleeve", "0-3M Blue Short Sleeve",
    "3-6M White Short Sleeve", "3-6M White Long Sleeve", "3-6M Blue Short Sleeve", "3-6M Pink Short Sleeve",
    "6M Natural Short Sleeve", "6-9M White Short Sleeve", "6-9M White Long Sleeve", "6-9M Pink Short Sleeve",
    "6-9M Blue Short Sleeve", "12M White Short Sleeve", "12M White Long Sleeve", "12M Natural Short Sleeve",
    "12M Pink Short Sleeve", "12M Blue Short Sleeve", "18M White Short Sleeve", "18M White Long Sleeve",
    "18M Natural Short Sleeve", "24M White Short Sleeve", "24M White Long Sleeve", "24M Natural Short Sleeve"
]

# ============================
# Amazon Feed Helpers
# ============================
def submit_json_feed(messages, feed_label, token):
    """Create a feed document, upload messages, submit, return feedId."""
    if not messages:
        return None

    # Remap message IDs 1..N
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

    # 1) Create document
    doc_res = requests.post(
        f"{AMZ_ENDPOINT}/feeds/2021-06-30/documents",
        headers={"x-amz-access-token": token, "Content-Type": "application/json"},
        json={"contentType": "application/json"},
    )
    doc_res.raise_for_status()
    doc = doc_res.json()

    # 2) Upload JSON to pre-signed URL
    up = requests.put(
        doc["url"],
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    up.raise_for_status()

    # 3) Submit feed
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
    feed_id = feed_res.json()["feedId"]
    st.markdown(f"**📡 {feed_label} Feed ID:** `{feed_id}`")
    return feed_id


def poll_feed_until_terminal(feed_id, label, token):
    """Polls a feed until DONE / FATAL / CANCELLED or timeout; returns (status, elapsed_seconds, raw_json)."""
    start = time.time()
    while True:
        time.sleep(CHECK_INTERVAL)
        res = requests.get(
            f"{AMZ_ENDPOINT}/feeds/2021-06-30/feeds/{feed_id}",
            headers={"x-amz-access-token": token},
        )
        res.raise_for_status()
        data = res.json()
        status = data.get("processingStatus")
        if status in ("DONE", "FATAL", "CANCELLED"):
            elapsed = time.time() - start
            st.markdown(f"✅ **{label} Feed {status}** in {elapsed/60:.1f} min")
            return status, elapsed, data
        else:
            st.markdown(f"⏳ {label} Feed still {status}...")

        if (time.time() - start) > MAX_WAIT_MINUTES * 60:
            st.error(f"⛔ Timeout waiting for {label} Feed")
            return "TIMEOUT", MAX_WAIT_MINUTES * 60, data


def download_processing_report_if_ready(feed_status_json, token):
    """If a processing report is available, download and return text, else None."""
    doc_id = feed_status_json.get("resultFeedDocumentId")
    if not doc_id:
        return None
    info = requests.get(
        f"{AMZ_ENDPOINT}/feeds/2021-06-30/documents/{doc_id}",
        headers={"x-amz-access-token": token},
    )
    info.raise_for_status()
    url = info.json().get("url")
    if not url:
        return None
    report = requests.get(url)
    report.raise_for_status()
    return report.text

# ============================
# Main Action — Unified Run
# ============================
if st.button("🚀 Run Full Rebuild (Unified Feeds)"):
    PARENTS = [p.strip() for p in parents_text.splitlines() if p.strip()]
    OLD_CHILDREN = [c.strip() for c in old_children_text.splitlines() if c.strip()]

    if not PARENTS:
        st.error("Please enter at least one parent SKU.")
        st.stop()

    token = get_amazon_access_token()

    delete_messages = []
    create_messages = []
    parent_messages = []
    inventory_rows = []

    # Build all messages for ALL parents
    for parent_sku in PARENTS:
        base_name = re.sub(r"-PARENT$", "", parent_sku.strip(), flags=re.IGNORECASE)
        title_val = f"{base_name.replace('-', ' ').strip()} - Baby Bodysuit"

        # Keyword injection payloads
        kws = extract_keywords_from_title(title_val) if inject_from_title else []
        desc = injected_description(DESCRIPTION, kws)
        bullets = injected_bullets(kws, BULLETS)
        gen_kw = injected_generic_keywords(kws)

        # PARENT partial update (one per parent)
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

        # CHILDREN: full variation matrix
        for var_str in VARIATIONS:
            size_val, color_val, sleeve_val = parse_variation(var_str)     # e.g., "0-3M", "White", "Short Sleeve"
            child_sku = sku_from_variation(base_name, size_val, color_val, sleeve_val)

            # DELETE messages: if user pasted OLD_CHILDREN, use those; else delete the ones we are about to create
            if OLD_CHILDREN:
                # only once, outside loop; but it’s safe to extend here because duplicates are remapped away later
                pass
            else:
                delete_messages.append({
                    "messageId": 0,
                    "sku": child_sku,
                    "operationType": "DELETE",
                    "productType": "LEOTARD",
                })

            # CREATE messages
            create_messages.append({
                "messageId": 0,
                "sku": child_sku,
                "operationType": "UPDATE",
                "productType": "LEOTARD",
                "requirements": "LISTING",
                "attributes": {
                    "item_name": [{"value": f"{title_val} - {size_val} {color_val} {sleeve_val}"}],
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
                    # Display theme label; actual dimensions are set by fields below
                    "variation_theme": [{"name": variation_theme_display}],
                    # Variation dimensions
                    "size": [{"value": size_val}],
                    "style": [{"value": sleeve_val}] if sleeve_val else [],
                    "color": [{"value": color_val}],
                    # Common attrs
                    "material": [{"value": "Cotton"}],
                    "country_of_origin": [{"value": "US"}],
                    "condition_type": [{"value": "new_new"}],
                    "supplier_declared_has_product_identifier_exemption": [{"value": True}],
                }
            })

            # Inventory target list
            inventory_rows.append(child_sku)

    # If OLD_CHILDREN provided, build delete messages from that instead (exact deletion)
    if OLD_CHILDREN:
        delete_messages = [{"messageId": 0, "sku": s, "operationType": "DELETE", "productType": "LEOTARD"} for s in OLD_CHILDREN]

    # ============================
    # SUBMIT UNIFIED FEEDS
    # ============================
    st.divider()
    results = []  # rows: [Feed Type, Feed ID, Status, Elapsed, Message Count]

    # DELETE
    st.markdown("### 🗑️ Submitting unified **DELETE** feed...")
    del_id = submit_json_feed(delete_messages, "DELETE", token)
    del_status, del_elapsed, del_raw = poll_feed_until_terminal(del_id, "DELETE", token)
    results.append(["DELETE", del_id, del_status, f"{del_elapsed/60:.1f} min", len(delete_messages)])

    # CREATE
    st.markdown("### 🧱 Submitting unified **CREATE** feed...")
    create_id = submit_json_feed(create_messages, "CREATE", token)
    create_status, create_elapsed, create_raw = poll_feed_until_terminal(create_id, "CREATE", token)
    results.append(["CREATE", create_id, create_status, f"{create_elapsed/60:.1f} min", len(create_messages)])

    # PARENT
    if include_parent_update:
        st.markdown("### 🏷️ Submitting unified **PARENT** update feed...")
        parent_id = submit_json_feed(parent_messages, "PARENT", token)
        parent_status, parent_elapsed, parent_raw = poll_feed_until_terminal(parent_id, "PARENT", token)
        results.append(["PARENT", parent_id, parent_status, f"{parent_elapsed/60:.1f} min", len(parent_messages)])
    else:
        parent_id, parent_status, parent_elapsed, parent_raw = None, "SKIPPED", 0, {}
        results.append(["PARENT", "-", parent_status, "-", "-"])

    # INVENTORY
    if include_inventory_sync:
        st.markdown("### 🧾 Submitting unified **INVENTORY** feed...")
        inv_id = submit_inventory_feed(inventory_rows, token, st.secrets["MARKETPLACE_ID"], st.secrets["SELLER_ID"])
        inv_status_json = check_inventory_feed_status(inv_id, token)
        # If inventory API returns the same schema, we poll similarly (some accounts mark it DONE almost instantly)
        # For consistency, poll using the same function:
        inv_status, inv_elapsed, inv_raw = poll_feed_until_terminal(inv_id, "INVENTORY", token)
        results.append(["INVENTORY", inv_id, inv_status, f"{inv_elapsed/60:.1f} min", len(inventory_rows)])
    else:
        inv_id, inv_status, inv_elapsed, inv_raw = None, "SKIPPED", 0, {}
        results.append(["INVENTORY", "-", inv_status, "-", "-"])

    st.success("🎉 Bulk rebuild complete!")

    # ============================
    # Diagnostics Summary (pandas)
    # ============================
    df = pd.DataFrame(results, columns=["Feed Type", "Feed ID", "Status", "Elapsed Time", "Message Count"])
    st.dataframe(df, use_container_width=True)

    # Compact JSON previews
    st.markdown("#### 🔍 Compact Diagnostics")
    with st.expander("View first few CREATE messages"):
        st.code(compact_json(create_messages[:3]), language="json")
    with st.expander("View first few DELETE messages"):
        st.code(compact_json(delete_messages[:5]), language="json")
    if include_parent_update:
        with st.expander("View first few PARENT messages"):
            st.code(compact_json(parent_messages[:2]), language="json")

    # Processing reports (if present)
    st.markdown("#### 🧾 Processing Reports (if available)")
    for label, fid, raw in [
        ("DELETE", del_id, del_raw),
        ("CREATE", create_id, create_raw),
        ("PARENT", parent_id, parent_raw if include_parent_update else {}),
    ]:
        if not fid:
            continue
        try:
            report_text = download_processing_report_if_ready(raw, token)
            if report_text:
                with st.expander(f"{label} feed report"):
                    st.text(report_text[:8000])  # keep viewable
        except Exception as e:
            st.warning(f"{label} report unavailable or failed to fetch: {e}")
