# streamlit_app.py
import streamlit as st
import json
import time
import re
import pandas as pd
import requests

# --- Robust imports: prefer helpers/*, else local files ---
try:
    import helpers.auth as A
    import helpers.util as U
except ModuleNotFoundError:
    import auth as A
    import util as U

# Back-compat alias: some older code referenced injected_desc_
injected_desc_ = U.injected_description

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

    # Create feed document
    doc = requests.post(
        f"{AMZ_ENDPOINT}/feeds/2021-06-30/documents",
        headers={"x-amz-access-token": token, "Content-Type": "application/json"},
        json={"contentType": "application/json"}
    ).json()

    # Upload payload
    requests.put(
        doc["url"],
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    ).raise_for_status()

    # Create feed
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
        r = requests.get(
            f"{AMZ_ENDPOINT}/feeds/2021-06-30/feeds/{feed_id}",
            headers={"x-amz-access-token": token}
        )
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
    if not doc_id:
        return None
    info = requests.get(
        f"{AMZ_ENDPOINT}/feeds/2021-06-30/documents/{doc_id}",
        headers={"x-amz-access-token": token}
    ).json()
    url = info.get("url")
    if not url:
        return None
    rep = requests.get(url)
    rep.raise_for_status()
    return rep.text

# ---------------- Action ----------------
if st.button("🚀 Run Full Rebuild (PATCH)"):
    parents = [p.strip() for p in parents_text.splitlines() if p.strip()]
    old_children = [c.strip() for c in old_children_text.splitlines() if c.strip()]
    if not parents:
        st.error("Enter at least one parent SKU.")
        st.stop()

    token = A.get_amazon_access_token()

    delete_msgs = []
    create_msgs = []
    parent_msgs = []
    inventory_rows = []

    for parent_sku in parents:
        base = re.sub(r"-PARENT$", "", parent_sku.strip(), flags=re.I)
        title_val = f"{base.replace('-', ' ').strip()} - Baby Bodysuit"

        # Use the correct function; alias exists for safety
        kws = U.extract_keywords_from_title(title_val) if inject_from_title else []
        desc = U.injected_description(DESCRIPTION, kws)
        bullets = U.injected_bullets(kws, BULLETS)

        # parent patch (optional)
        if include_parent_update:
            parent_attrs = U.required_core_attrs_for_parent(
                title_val=title_val,
                brand=brand_name,
                item_type_keyword=item_type_keyword,
                desc_html=desc,
                bullets=bullets,
                variation_theme_display=variation_theme_display,
            )
            parent_msgs.append(
                U.build_patch_message(message_id=0, sku=parent_sku, product_type="LEOTARD", attributes=parent_attrs)
            )

        # build children
        for v in VARIATIONS:
            size, color, sleeve = U.parse_variation(v)
            child_sku = U.sku_from_variation(base, size, color, sleeve)

            # DELETE old (only if user didn't provide an explicit list)
            if not old_children:
                delete_msgs.append({
                    "messageId": 0,
                    "sku": child_sku,
                    "operationType": "DELETE",
                    "productType": "LEOTARD"
                })

            # Child attributes with REQUIRED fields + per-variant price
            lp = U.PRICE_MAP.get(v, 29.99)
            child_attrs = U.required_core_attrs_for_child(
                title_val=f"{title_val} - {size} {color} {sleeve}".strip(),
                size=size, color=color, sleeve=sleeve,
                brand=brand_name, item_type_keyword=item_type_keyword,
                desc_html=desc, bullets=bullets,
                list_price=lp
            )
            # attach parent link + variation theme (already set, but include relationship)
            child_attrs["child_parent_sku_relationship"] = [{
                "child_relationship_type": "variation",
                "parent_sku": parent_sku
            }]

            create_msgs.append(
                U.build_patch_message(message_id=0, sku=child_sku, product_type="LEOTARD", attributes=child_attrs)
            )
            inventory_rows.append(child_sku)

    # explicit deletions override automatic
    if old_children:
        delete_msgs = [{
            "messageId": 0, "sku": s, "operationType": "DELETE", "productType": "LEOTARD"
        } for s in old_children]

    # ---------- VALIDATE ----------
    problems = []
    problems += U.validate_messages_patch(create_msgs, "CREATE")
    if include_parent_update:
        problems += U.validate_messages_patch(parent_msgs, "PARENT")
    # DELETEs aren't PATCH, skip validator

    if problems:
        st.error("❌ Validation failed — nothing submitted.")
        with st.expander("See errors"):
            for p in problems:
                st.write(p)
        with st.expander("Sample CREATE (first 3)"):
            st.code(U.compact_json(create_msgs[:3]), language="json")
        st.stop()

    # ---------- SUBMIT ----------
    results = []

    st.markdown("### 🗑️ Submitting DELETE feed…")
    del_id = submit_json_feed(delete_msgs, "DELETE", token)
    del_status, del_json = poll_feed_until_terminal(del_id, "DELETE", token)
    results.append(["DELETE", del_id, del_status, len(delete_msgs)])

    st.markdown("### 🧱 Submitting CREATE (PATCH) feed…")
    create_id = submit_json_feed(create_msgs, "CREATE", token)
    create_status, create_json = poll_feed_until_terminal(create_id, "CREATE", token)
    results.append(["CREATE", create_id, create_status, len(create_msgs)])

    if include_parent_update:
        st.markdown("### 🏷️ Submitting PARENT (PATCH) feed…")
        parent_id = submit_json_feed(parent_msgs, "PARENT", token)
        parent_status, parent_json = poll_feed_until_terminal(parent_id, "PARENT", token)
        results.append(["PARENT", parent_id, parent_status, len(parent_msgs)])
    else:
        results.append(["PARENT", "-", "SKIPPED", 0])

    if include_inventory_sync:
        from inventory_feed_submitter import submit_inventory_feed
        st.markdown("### 🧾 Submitting INVENTORY feed…")
        inv_id = submit_inventory_feed(
            inventory_rows, token, st.secrets["MARKETPLACE_ID"], st.secrets["SELLER_ID"], quantity=default_qty
        )
        inv_status, inv_json = poll_feed_until_terminal(inv_id, "INVENTORY", token)
        results.append(["INVENTORY", inv_id, inv_status, len(inventory_rows)])
    else:
        results.append(["INVENTORY", "-", "SKIPPED", 0])

    st.success("🎉 Bulk rebuild complete!")
    st.dataframe(pd.DataFrame(results, columns=["Feed", "Feed ID", "Status", "Count"]), use_container_width=True)

    st.markdown("#### 🔍 Diagnostics")
    with st.expander("First 3 CREATE messages (compact)"):
        st.code(U.compact_json(create_msgs[:3]), language="json")
    if include_parent_update:
        with st.expander("First 2 PARENT messages (compact)"):
            st.code(U.compact_json(parent_msgs[:2]), language="json")
    with st.expander("First 5 DELETE messages (compact)"):
        st.code(U.compact_json(delete_msgs[:5]), language="json")
