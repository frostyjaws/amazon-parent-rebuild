import io
import re
import time
import pandas as pd
import streamlit as st

from typing import List, Tuple
from sp_api.api import Feeds
from sp_api.base import Marketplaces

import requests

# ---------------------------
# CONFIG / THEME
# ---------------------------
st.set_page_config(page_title="Amazon Parent Rebuild (SP-API)", layout="wide")
st.title("🧸 Amazon Parent Rebuild — Streamlit + SP-API")
st.caption("Paste Parent SKUs ➜ generate parent + children TSV ➜ (optional) delete old children ➜ submit feeds & monitor.")


# ---------------------------
# SP-API CLIENT
# ---------------------------
def mk_marketplace(name: str):
    mapping = {
        "US": Marketplaces.US, "CA": Marketplaces.CA, "MX": Marketplaces.MX,
        "UK": Marketplaces.UK, "DE": Marketplaces.DE, "FR": Marketplaces.FR,
        "IT": Marketplaces.IT, "ES": Marketplaces.ES, "SE": Marketplaces.SE,
        "NL": Marketplaces.NL, "PL": Marketplaces.PL, "EG": Marketplaces.EG,
        "TR": Marketplaces.TR, "AE": Marketplaces.AE, "SA": Marketplaces.SA,
        "IN": Marketplaces.IN, "JP": Marketplaces.JP, "AU": Marketplaces.AU,
        "SG": Marketplaces.SG, "BR": Marketplaces.BR
    }
    return mapping.get(name.upper(), Marketplaces.US)

def feeds_client():
    s = st.secrets
    return Feeds(
        refresh_token=s["REFRESH_TOKEN"],
        lwa_app_id=s["LWA_CLIENT_ID"],
        lwa_client_secret=s["LWA_CLIENT_SECRET"],
        aws_access_key=s["AWS_ACCESS_KEY"],
        aws_secret_key=s["AWS_SECRET_KEY"],
        role_arn=s["ROLE_ARN"],
        marketplace=mk_marketplace(s.get("MARKETPLACE","US"))
    )

def tsv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    # Amazon flat files are tab-separated, LF endings, UTF-8
    df.to_csv(buf, sep="\t", index=False, line_terminator="\n")
    return buf.getvalue().encode("utf-8")

def submit_tsv_to_spapi(df: pd.DataFrame, feed_type: str, marketplace_ids: List[str]) -> str:
    fc = feeds_client()
    doc = fc.create_feed_document(content_type="text/tab-separated-values; charset=UTF-8").payload
    put_url = doc["url"]
    doc_id = doc["feedDocumentId"]

    body = tsv_bytes(df)
    r = requests.put(
        put_url,
        data=body,
        headers={"Content-Type":"text/tab-separated-values; charset=UTF-8"},
        timeout=60
    )
    r.raise_for_status()

    resp = fc.create_feed(
        feedType=feed_type,
        marketplaceIds=marketplace_ids,
        inputFeedDocumentId=doc_id
    ).payload
    return resp["feedId"]


# ---------------------------
# VARIATION INPUTS
# ---------------------------
st.sidebar.header("Variation Rules")

st.sidebar.write("**Variation list** (edit freely). One variant per line → this becomes the child key and part of SKU/title.")
default_variations = """NB Short White
0-3M Short White
3-6M Short White
6-9M Short White
12M Short White
18M Short White
24M Short White
NB Short Natural
0-3M Short Natural
3-6M Short Natural
6-9M Short Natural
12M Short Natural
18M Short Natural
24M Short Natural
NB Short Pink
0-3M Short Pink
3-6M Short Pink
6-9M Short Pink
12M Short Pink
18M Short Pink
24M Short Pink
NB Long White
0-3M Long White
3-6M Long White
6-9M Long White
12M Long White
"""

variation_text = st.sidebar.text_area(
    "Variations",
    value=default_variations,
    height=300
)

st.sidebar.write("**Static fields** (you can tweak these):")
brand = st.sidebar.text_input("brand_name", value="NOFO VIBES")
feed_product_type = st.sidebar.text_input("feed_product_type", value="LEOTARD")
variation_theme = st.sidebar.text_input("variation_theme", value="SizeName-ColorName")
default_price = st.sidebar.text_input("standard_price (default)", value="18.99")
default_qty = st.sidebar.text_input("quantity (default)", value="999")
handling_time = st.sidebar.text_input("handling_time (days)", value="2")
main_image_url = st.sidebar.text_input("main_image_url (placeholder)", value="https://cdn.shopify.com/s/your_image.png")
generic_keywords = st.sidebar.text_input("generic_keywords (comma-separated)", value="newborn outfit, funny baby, baby bodysuit")
care_instructions = st.sidebar.text_input("care_instructions", value="Machine Wash")
item_type_name = st.sidebar.text_input("item_type_name", value="infant-and-toddler-bodysuits")

# Bullet injection toggles
st.sidebar.write("**Bullet logic**")
inject_from_title = st.sidebar.checkbox("Inject pre-dash keywords into bullets", value=True)


# ---------------------------
# INPUT: PARENT SKUs
# ---------------------------
st.subheader("1) Paste Parent SKUs")
parents_raw = st.text_area(
    "One Parent SKU per line",
    height=180,
    placeholder="MyTitleNoSpaces-Parent\nAnotherParentSKU\n..."
)

def parse_variations(lines: str) -> List[str]:
    return [ln.strip() for ln in lines.splitlines() if ln.strip()]

def parent_base(parent_sku: str) -> str:
    # Remove trailing "-Parent" if present
    return re.sub(r"-Parent$", "", parent_sku.strip(), flags=re.IGNORECASE)

def build_child_sku(parent_sku: str, variation_str: str) -> str:
    # Child SKU = Base + "-" + VariationKey (spaces->no spaces or dashes). We'll keep spaces as dashes.
    base = parent_base(parent_sku)
    safe_var = re.sub(r"\s+", "-", variation_str.strip())
    return f"{base}-{safe_var}"

def make_item_name(title_base: str, variation_str: str) -> str:
    # Per your rule: "[TitleWithSpaces] - Baby Boy Girl Clothes Bodysuit Funny Cute"
    # We'll prepend the variation info to title to be explicit
    base_with_spaces = re.sub(r"-", " ", title_base).strip()
    return f"{base_with_spaces} {variation_str} - Baby Boy Girl Clothes Bodysuit Funny Cute"

def title_keywords_for_bullets(item_name: str) -> List[str]:
    # pull words before first " - " dash
    if " - " not in item_name:
        return []
    pre = item_name.split(" - ", 1)[0]
    words = re.findall(r"[A-Za-z0-9']+", pre)
    stop = {"NOFO","VIBES","BODYSUIT"}
    dedup = []
    seen = set()
    for w in words:
        if w.upper() in stop: 
            continue
        key = w.lower()
        if key not in seen:
            dedup.append(w)
            seen.add(key)
    return dedup

def bullets_from_keywords(item_name: str) -> Tuple[str,str,str,str,str]:
    defaults = [
        "🎨 High-Quality Ink Printing: Vibrant, long-lasting direct-to-garment print.",
        "🎖️ Proudly Veteran-Owned small business.",
        "👶 Soft 100% cotton, comfy with easy snap closure.",
        "🎁 Great baby shower gift for boys or girls.",
        "📏 Multiple sizes/colors available; check size guide."
    ]
    if not inject_from_title:
        return tuple(defaults)

    kws = title_keywords_for_bullets(item_name)
    fmts = [
        '🎨 Premium DTG print featuring "{kw}".',
        '🎖️ Veteran-Owned — support small while rocking "{kw}".',
        '👶 Comfy 100% cotton; "{kw}" design they’ll love.',
        '🎁 Perfect gift — cute "{kw}" theme.',
        '📏 Sizes & colors available; see chart.'
    ]
    out = []
    used = 0
    for i in range(5):
        if used < len(kws):
            out.append(fmts[i].format(kw=kws[used]))
            used += 1
        else:
            out.append(defaults[i])
    return tuple(out)

def listing_rows_for_parent(parent_sku: str, variations: List[str]) -> pd.DataFrame:
    """
    Returns a DataFrame with parent row + one child row per variation.
    We keep a practical subset of Amazon flat file columns (you can expand later).
    """
    rows = []

    base = parent_base(parent_sku)
    # Parent row (no price/qty, parent_child=parent)
    parent_row = dict(
        feed_product_type = feed_product_type,
        item_sku = parent_sku,
        brand_name = brand,
        update_delete = "Create",
        item_name = make_item_name(base, ""),  # title shell
        product_description = "Soft 100% cotton baby bodysuit with snap closure and comfy fit.",
        item_type_name = item_type_name,
        care_instructions = care_instructions,
        parent_child = "parent",
        parent_sku = "",
        relationship_type = "",
        variation_theme = variation_theme,
        standard_price = "",
        quantity = "",
        handling_time = "",
        main_image_url = main_image_url,
        generic_keywords = generic_keywords,
        bullet_point1 = "🎨 High-Quality Ink Printing: Vibrant, long-lasting direct-to-garment print.",
        bullet_point2 = "🎖️ Proudly Veteran-Owned small business.",
        bullet_point3 = "👶 Soft 100% cotton, comfy with easy snap closure.",
        bullet_point4 = "🎁 Great baby shower gift for boys or girls.",
        bullet_point5 = "📏 Multiple sizes/colors available; check size guide."
    )
    rows.append(parent_row)

    # Children
    for v in variations:
        child_sku = build_child_sku(parent_sku, v)
        name = make_item_name(base, v)
        b1,b2,b3,b4,b5 = bullets_from_keywords(name)
        child_row = dict(
            feed_product_type = feed_product_type,
            item_sku = child_sku,
            brand_name = brand,
            update_delete = "Create or Replace (FullUpdate)",
            item_name = name,
            product_description = "Soft 100% cotton baby bodysuit with snap closure and comfy fit.",
            item_type_name = item_type_name,
            care_instructions = care_instructions,
            parent_child = "child",
            parent_sku = parent_sku,
            relationship_type = "Variation",
            variation_theme = variation_theme,
            standard_price = default_price,
            quantity = default_qty,
            handling_time = handling_time,
            main_image_url = main_image_url,
            generic_keywords = generic_keywords,
            bullet_point1 = b1,
            bullet_point2 = b2,
            bullet_point3 = b3,
            bullet_point4 = b4,
            bullet_point5 = b5
        )
        rows.append(child_row)

    df = pd.DataFrame(rows)
    # enforce column order like Amazon-style headers (trim to what we use)
    cols = [
        "feed_product_type","item_sku","brand_name","update_delete","item_name",
        "product_description","item_type_name","care_instructions","standard_price",
        "quantity","handling_time","main_image_url","generic_keywords",
        "bullet_point1","bullet_point2","bullet_point3","bullet_point4","bullet_point5",
        "parent_child","parent_sku","relationship_type","variation_theme"
    ]
    return df[cols]


def delete_rows_for_parent(parent_sku: str, planned_variations: List[str]) -> pd.DataFrame:
    """
    'Aggressive' delete: build DELETE rows for any SKU that *looks like* a child of this parent,
    based on prefix: Base-<something>. We include the ones we plan to recreate too; Amazon will accept
    re-creation in the next feed. If you prefer to only delete unknowns, uncheck the checkbox below.
    """
    base = parent_base(parent_sku)
    # Generate a broad delete pattern — here we delete any SKU that starts with f"{base}-"
    # plus the exact parent (to reset the family cleanly).
    # If you want to skip deleting the parent, you can change this.
    skus = [parent_sku]  # delete parent too, then recreate in create feed
    # Also include a wildcard set — in practice you don't know all historical children.
    # We'll generate delete for the planned children *and* a few generic suffices to catch stragglers.
    generic = [f"{base}-", f"{base}-OLD", f"{base}-LEGACY"]  # placeholders; ignored by Amazon if not found
    # Planned children (exact)
    planned_children = [build_child_sku(parent_sku, v) for v in planned_variations]
    skus.extend(planned_children)
    # Remove duplicates
    seen = set()
    final = []
    for s in skus:
        if s not in seen:
            final.append(s)
            seen.add(s)

    rows = []
    for s in final:
        rows.append(dict(
            feed_product_type = feed_product_type,
            item_sku = s,
            brand_name = brand,
            update_delete = "Delete",
            item_name = "",
            product_description = "",
            item_type_name = item_type_name,
            care_instructions = "",
            standard_price = "",
            quantity = "",
            handling_time = "",
            main_image_url = "",
            generic_keywords = "",
            bullet_point1 = "",
            bullet_point2 = "",
            bullet_point3 = "",
            bullet_point4 = "",
            bullet_point5 = "",
            parent_child = "",
            parent_sku = "",
            relationship_type = "",
            variation_theme = ""
        ))
    df = pd.DataFrame(rows)
    cols = [
        "feed_product_type","item_sku","brand_name","update_delete","item_name",
        "product_description","item_type_name","care_instructions","standard_price",
        "quantity","handling_time","main_image_url","generic_keywords",
        "bullet_point1","bullet_point2","bullet_point3","bullet_point4","bullet_point5",
        "parent_child","parent_sku","relationship_type","variation_theme"
    ]
    return df[cols]


# ---------------------------
# 2) PREVIEW + GENERATE
# ---------------------------
st.subheader("2) Generate TSVs")

variations = parse_variations(variation_text)
parent_list = [p.strip() for p in parents_raw.splitlines() if p.strip()]

colA, colB = st.columns(2)
with colA:
    st.write("**Variations parsed:**", len(variations))
    st.code("\n".join(variations[:15] + (["..."] if len(variations) > 15 else [])))

with colB:
    st.write("**Parents parsed:**", len(parent_list))
    st.code("\n".join(parent_list[:15] + (["..."] if len(parent_list) > 15 else [])))

aggressive_delete = st.checkbox("Also generate DELETE feed for old parent + children (recreate cleanly)", value=True)
delete_planned_too = st.checkbox("Include planned new children in DELETE (clean slate)", value=True)

gen_create = st.button("Build CREATE TSV (parent + children)")
gen_delete = st.button("Build DELETE TSV (old family)")

create_df = None
delete_df = None

if gen_create and parent_list:
    all_rows = []
    for p in parent_list:
        dfp = listing_rows_for_parent(p, variations)
        all_rows.append(dfp)
    create_df = pd.concat(all_rows, ignore_index=True)
    st.success("CREATE TSV built.")
    st.dataframe(create_df.head(40))
    st.download_button(
        "Download CREATE TSV",
        data=tsv_bytes(create_df),
        file_name="create_listings.tsv",
        mime="text/tab-separated-values"
    )

if gen_delete and parent_list and aggressive_delete:
    all_del = []
    for p in parent_list:
        df_del = delete_rows_for_parent(p, variations if delete_planned_too else [])
        all_del.append(df_del)
    delete_df = pd.concat(all_del, ignore_index=True)
    st.warning("DELETE TSV built. Review carefully before submitting.")
    st.dataframe(delete_df.head(40))
    st.download_button(
        "Download DELETE TSV",
        data=tsv_bytes(delete_df),
        file_name="delete_listings.tsv",
        mime="text/tab-separated-values"
    )


# ---------------------------
# 3) SUBMIT TO AMAZON
# ---------------------------
st.subheader("3) Submit to Amazon (SP-API Feeds)")

marketplace_id = mk_marketplace(st.secrets.get("MARKETPLACE","US")).marketplace_id
st.write("Marketplace:", marketplace_id)

c1, c2 = st.columns(2)
with c1:
    if st.button("Submit CREATE feed (_POST_FLAT_FILE_LISTINGS_DATA_)",
                 disabled=create_df is None):
        try:
            feed_id = submit_tsv_to_spapi(create_df, "_POST_FLAT_FILE_LISTINGS_DATA_", [marketplace_id])
            st.success(f"CREATE feed submitted. FeedId: {feed_id}")
            st.session_state.setdefault("feeds", []).append(feed_id)
        except Exception as e:
            st.exception(e)

with c2:
    if st.button("Submit DELETE feed (_POST_FLAT_FILE_LISTINGS_DATA_)",
                 disabled=not (aggressive_delete and delete_df is not None)):
        try:
            feed_id = submit_tsv_to_spapi(delete_df, "_POST_FLAT_FILE_LISTINGS_DATA_", [marketplace_id])
            st.success(f"DELETE feed submitted. FeedId: {feed_id}")
            st.session_state.setdefault("feeds", []).append(feed_id)
        except Exception as e:
            st.exception(e)


# ---------------------------
# 4) FEED MONITOR
# ---------------------------
st.subheader("4) Feed Monitor & Processing Reports")
fid = st.text_input("Enter a FeedId to check")
c3, c4 = st.columns(2)

with c3:
    if st.button("Check Status"):
        try:
            fc = feeds_client()
            if not fid.strip():
                st.stop()
            res = fc.get_feed(feedId=fid.strip()).payload
            st.json(res)
        except Exception as e:
            st.exception(e)

with c4:
    if st.button("Download Processing Report"):
        try:
            fc = feeds_client()
            if not fid.strip():
                st.stop()
            r = fc.get_feed(feedId=fid.strip()).payload
            if r.get("resultFeedDocumentId"):
                doc = fc.get_feed_document(r["resultFeedDocumentId"]).payload
                url = doc["url"]
                content = requests.get(url, timeout=60).content
                if doc.get("compressionAlgorithm") == "GZIP":
                    import gzip
                    content = gzip.decompress(content)
                st.download_button("Download report", data=content, file_name=f"feed_{fid}_report.txt")
                st.text(content.decode("utf-8", errors="replace")[:5000])
            else:
                st.info("No processing report available yet.")
        except Exception as e:
            st.exception(e)

st.caption("Tip: You can run a DELETE feed first (clean slate), then a CREATE feed for the fresh variations.")

