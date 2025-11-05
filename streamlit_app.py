# streamlit_app.py
# Amazon Parent Rebuild (Keep Parent, Replace Children) — Streamlit + SP-API
# - Paste Parent SKUs
# - Define variation list (size/sleeve/color lines)
# - Generate DELETE (children-only), CREATE (children-only), optional PARENT UPDATE rows
# - Submit via Feeds API and download processing reports
#
# Notes:
# - Use Streamlit Cloud "Secrets" for credentials, or a local .streamlit/secrets.toml (repo private).
# - Feed type used: _POST_FLAT_FILE_LISTINGS_DATA_ (tab-delimited)
# - TSV enc: UTF-8 with LF newlines
# - Minimal, reliable columns; you can add more anytime.

import io
import re
import gzip
import json
import time
import pandas as pd
import requests
import streamlit as st
from typing import List, Dict, Tuple

from sp_api.api import Feeds
from sp_api.base import Marketplaces, SellingApiException

# ---------------------------
# UI / PAGE
# ---------------------------
st.set_page_config(page_title="Amazon Parent Rebuild (Keep Parent, Replace Children)", layout="wide")
st.title("🧸 Amazon Parent Rebuild")
st.caption("Keep the existing parent, delete old children, create new children — with full bullet/keyword injections.")

# ---------------------------
# Helpers: Marketplace + SP-API client
# ---------------------------
def mk_marketplace(name: str):
    mapping = {
        "US": Marketplaces.US, "CA": Marketplaces.CA, "MX": Marketplaces.MX,
        "UK": Marketplaces.UK, "DE": Marketplaces.DE, "FR": Marketplaces.FR,
        "IT": Marketplaces.IT, "ES": Marketplaces.ES, "SE": Marketplaces.SE,
        "NL": Marketplaces.NL, "PL": Marketplaces.PL, "EG": Marketplaces.EG,
        "TR": Marketplaces.TR, "AE": Marketplaces.AE, "SA": Marketplaces.SA,
        "IN": Marketplaces.IN, "JP": Marketplaces.JP, "AU": Marketplaces.AU,
        "SG": Marketplaces.SG, "BR": Marketplaces.BR,
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
        timeout=120
    )
    r.raise_for_status()

    resp = fc.create_feed(
        feedType=feed_type,
        marketplaceIds=marketplace_ids,
        inputFeedDocumentId=doc_id
    ).payload
    return resp["feedId"]

# ---------------------------
# Sidebar: Global config
# ---------------------------
st.sidebar.header("Global Settings")

marketplace = st.sidebar.selectbox("Marketplace", ["US","CA","UK","DE","FR","IT","ES","SE","NL","PL","JP","AU","SG","MX","AE","SA","IN","EG","TR","BR"], index=0)
brand = st.sidebar.text_input("brand_name", value="NOFO VIBES")
feed_product_type = st.sidebar.text_input("feed_product_type", value="LEOTARD")
variation_theme = st.sidebar.text_input("variation_theme", value="SizeName-ColorName")
item_type_name = st.sidebar.text_input("item_type_name", value="infant-and-toddler-bodysuits")
care_instructions = st.sidebar.text_input("care_instructions", value="Machine Wash")
default_price = st.sidebar.text_input("standard_price (default)", value="18.99")
default_qty = st.sidebar.text_input("quantity (default)", value="999")
handling_time = st.sidebar.text_input("handling_time (days)", value="2")
main_image_url = st.sidebar.text_input("main_image_url (fallback)", value="https://cdn.shopify.com/s/your_image.png")
generic_keywords = st.sidebar.text_input("generic_keywords (comma-separated)", value="newborn outfit, funny baby, baby bodysuit")

inject_from_title = st.sidebar.checkbox("Inject keywords from title (pre-dash) into bullets", value=True)

st.sidebar.markdown("---")
st.sidebar.subheader("Swatch mapping (optional)")
st.sidebar.caption('Format: one per line → Color,https://url\nExample:\nWhite,https://.../white.png')
swatch_text = st.sidebar.text_area("color → swatch_url", value="White,https://example.com/swatch_white.png\nNatural,https://example.com/swatch_natural.png\nPink,https://example.com/swatch_pink.png", height=120)

def parse_swatches(txt: str) -> Dict[str, str]:
    m = {}
    for line in txt.splitlines():
        line = line.strip()
        if not line or "," not in line:
            continue
        k, v = line.split(",", 1)
        m[k.strip()] = v.strip()
    return m

SWATCHES = parse_swatches(swatch_text)

# ---------------------------
# Inputs: Parents & Variations
# ---------------------------
st.subheader("1) Paste Parent SKUs (keep parent, replace children)")
parents_raw = st.text_area("Parent SKUs (one per line)", height=140, placeholder="MYTITLE-Parent\nANOTHER-PARENT\n...")

st.subheader("2) Define Variations")
st.caption("One variation per line → e.g. `NB Short White`, `0-3M Long Pink` (last token = Color; earlier tokens = Size/Sleeve).")
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
12M Long White"""
variation_text = st.text_area("Variation Lines", value=default_variations, height=220)

def parse_list_block(txt: str) -> List[str]:
    return [ln.strip() for ln in txt.splitlines() if ln.strip()]

PARENTS = parse_list_block(parents_raw)
VARIATIONS = parse_list_block(variation_text)

col_a, col_b = st.columns(2)
with col_a:
    st.write(f"**Parsed Parents:** {len(PARENTS)}")
    st.code("\n".join(PARENTS[:15] + (["..."] if len(PARENTS) > 15 else [])))
with col_b:
    st.write(f"**Parsed Variations:** {len(VARIATIONS)}")
    st.code("\n".join(VARIATIONS[:18] + (["..."] if len(VARIATIONS) > 18 else [])))

# Optional helper: user can paste exact existing child SKUs to delete
st.markdown("**(Optional)** Paste existing child SKUs to delete (one per line). If empty, we’ll delete the planned children only.")
old_children_raw = st.text_area("Existing child SKUs to delete (optional)", height=120, placeholder="MYTITLE-0-3M-Short-White\nMYTITLE-3-6M-Short-White\n...")

EXISTING_CHILDREN_MANUAL = parse_list_block(old_children_raw)

# ---------------------------
# Content generation helpers
# ---------------------------
STOP_WORDS = {"NOFO", "VIBES", "BODYSUIT"}

def parent_base(parent_sku: str) -> str:
    return re.sub(r"-Parent$", "", parent_sku.strip(), flags=re.IGNORECASE)

def build_child_sku(parent_sku: str, variation_str: str) -> str:
    base = parent_base(parent_sku)
    safe = re.sub(r"\s+", "-", variation_str.strip())
    return f"{base}-{safe}"

def split_variation(variation_str: str) -> Tuple[str, str]:
    # returns (size_token, color)
    parts = variation_str.strip().split()
    if not parts:
        return variation_str.strip(), ""
    color = parts[-1]
    size_token = " ".join(parts[:-1]).strip() or variation_str.strip()
    return size_token, color

def make_item_name(title_base: str, variation_str: str) -> str:
    base_with_spaces = re.sub(r"-", " ", title_base).strip()
    # Ensure a dash exists so pre-dash keyword injection works
    return f"{base_with_spaces} {variation_str} - Baby Boy Girl Clothes Bodysuit Funny Cute".strip()

def title_keywords_for_bullets(item_name: str) -> List[str]:
    if " - " not in item_name:
        return []
    pre = item_name.split(" - ", 1)[0]
    words = re.findall(r"[A-Za-z0-9']+", pre)
    out, seen = [], set()
    for w in words:
        if w.upper() in STOP_WORDS:
            continue
        key = w.lower()
        if key not in seen:
            out.append(w)
            seen.add(key)
    return out

def bullets_from_keywords(item_name: str, inject: bool) -> Tuple[str,str,str,str,str]:
    defaults = [
        "🎨 High-Quality Ink Printing: Vibrant, long-lasting direct-to-garment print.",
        "🎖️ Proudly Veteran-Owned small business.",
        "👶 Soft 100% cotton, comfy with easy snap closure.",
        "🎁 Great baby shower gift for boys or girls.",
        "📏 Multiple sizes/colors available; check size guide."
    ]
    if not inject:
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
    ki = 0
    for i in range(5):
        if ki < len(kws):
            out.append(fmts[i].format(kw=kws[ki]))
            ki += 1
        else:
            out.append(defaults[i])
    return tuple(out)

def injected_description(item_name: str) -> str:
    # Simple desc with keyword echo (non-spammy)
    kws = title_keywords_for_bullets(item_name)[:3]
    tail = f" Design: {', '.join(kws)}." if kws else ""
    return f"Soft 100% cotton baby bodysuit with snap closure and comfy fit.{tail}"

# ---------------------------
# Row builders
# ---------------------------
BASE_COLS = [
    "feed_product_type","item_sku","brand_name","update_delete","item_name",
    "product_description","item_type_name","care_instructions","standard_price",
    "quantity","handling_time","main_image_url","generic_keywords",
    "bullet_point1","bullet_point2","bullet_point3","bullet_point4","bullet_point5",
    "parent_child","parent_sku","relationship_type","variation_theme",
    "color_name","color_map","swatch_image_url","size_name"
]

def child_create_rows(parent_sku: str, variations: List[str]) -> pd.DataFrame:
    rows = []
    base = parent_base(parent_sku)
    for v in variations:
        size_token, color = split_variation(v)
        child_sku = build_child_sku(parent_sku, v)
        item_name = make_item_name(base, v)
        b1,b2,b3,b4,b5 = bullets_from_keywords(item_name, inject_from_title)
        desc = injected_description(item_name)
        swatch = SWATCHES.get(color, "")
        rows.append(dict(
            feed_product_type = feed_product_type,
            item_sku = child_sku,
            brand_name = brand,
            update_delete = "Create or Replace (FullUpdate)",
            item_name = item_name,
            product_description = desc,
            item_type_name = item_type_name,
            care_instructions = care_instructions,
            standard_price = default_price,
            quantity = default_qty,
            handling_time = handling_time,
            main_image_url = main_image_url,
            generic_keywords = generic_keywords,
            bullet_point1 = b1,
            bullet_point2 = b2,
            bullet_point3 = b3,
            bullet_point4 = b4,
            bullet_point5 = b5,
            parent_child = "child",
            parent_sku = parent_sku,
            relationship_type = "Variation",
            variation_theme = variation_theme,
            color_name = color,
            color_map = color,
            swatch_image_url = swatch,
            size_name = size_token
        ))
    return pd.DataFrame(rows)[BASE_COLS]

def child_delete_rows(parent_sku: str, planned_variations: List[str], explicit_children: List[str]) -> pd.DataFrame:
    # Delete EXACT skus (either user-provided list, or the planned children set)
    targets = []
    if explicit_children:
        targets.extend(explicit_children)
    else:
        for v in planned_variations:
            targets.append(build_child_sku(parent_sku, v))
    # de-dup
    seen, final = set(), []
    for s in targets:
        if s not in seen:
            final.append(s); seen.add(s)

    rows = []
    for sku in final:
        rows.append(dict(
            feed_product_type = feed_product_type,
            item_sku = sku,
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
            variation_theme = "",
            color_name = "",
            color_map = "",
            swatch_image_url = "",
            size_name = ""
        ))
    return pd.DataFrame(rows)[BASE_COLS]

def parent_update_row(parent_sku: str) -> pd.DataFrame:
    base = parent_base(parent_sku)
    # A gentle, safe “PartialUpdate” for parent; you can switch to Create or Replace if needed.
    # Parent rows should not set price/qty; keep generic info.
    item_name = f"{re.sub(r'-',' ', base).strip()} - Baby Boy Girl Clothes Bodysuit Funny Cute"
    b1,b2,b3,b4,b5 = bullets_from_keywords(item_name, inject_from_title)
    desc = injected_description(item_name)
    row = dict(
        feed_product_type = feed_product_type,
        item_sku = parent_sku,
        brand_name = brand,
        update_delete = "PartialUpdate",
        item_name = item_name,
        product_description = desc,
        item_type_name = item_type_name,
        care_instructions = care_instructions,
        standard_price = "",
        quantity = "",
        handling_time = "",
        main_image_url = main_image_url,
        generic_keywords = generic_keywords,
        bullet_point1 = b1,
        bullet_point2 = b2,
        bullet_point3 = b3,
        bullet_point4 = b4,
        bullet_point5 = b5,
        parent_child = "parent",
        parent_sku = "",
        relationship_type = "",
        variation_theme = variation_theme,
        color_name = "",
        color_map = "",
        swatch_image_url = "",
        size_name = ""
    )
    return pd.DataFrame([row])[BASE_COLS]

# ---------------------------
# Build TSVs
# ---------------------------
st.subheader("3) Build Feeds")

do_parent_update = st.checkbox("Include PARENT UPDATE row (refresh bullets/description/keywords at parent level)", value=True)

build_delete = st.button("Build DELETE TSV (children only)")
build_create = st.button("Build CREATE TSV (children only)")
build_parent  = st.button("Build PARENT UPDATE TSV")

CREATE_DF = None
DELETE_DF = None
PARENT_DF = None

if build_delete and PARENTS:
    all_del = []
    for p in PARENTS:
        df = child_delete_rows(p, VARIATIONS, EXISTING_CHILDREN_MANUAL)
        all_del.append(df)
    DELETE_DF = pd.concat(all_del, ignore_index=True)
    st.warning("DELETE TSV (children only) built.")
    st.dataframe(DELETE_DF.head(40))
    st.download_button("Download DELETE TSV", data=tsv_bytes(DELETE_DF), file_name="delete_children.tsv", mime="text/tab-separated-values")

if build_create and PARENTS:
    all_cr = []
    for p in PARENTS:
        df = child_create_rows(p, VARIATIONS)
        all_cr.append(df)
    CREATE_DF = pd.concat(all_cr, ignore_index=True)
    st.success("CREATE TSV (children only) built.")
    st.dataframe(CREATE_DF.head(40))
    st.download_button("Download CREATE TSV", data=tsv_bytes(CREATE_DF), file_name="create_children.tsv", mime="text/tab-separated-values")

if build_parent and PARENTS and do_parent_update:
    all_pa = []
    for p in PARENTS:
        all_pa.append(parent_update_row(p))
    PARENT_DF = pd.concat(all_pa, ignore_index=True)
    st.info("PARENT UPDATE TSV built.")
    st.dataframe(PARENT_DF.head(20))
    st.download_button("Download PARENT UPDATE TSV", data=tsv_bytes(PARENT_DF), file_name="parent_update.tsv", mime="text/tab-separated-values")

# ---------------------------
# Submit to Amazon
# ---------------------------
st.subheader("4) Submit to Amazon (SP-API Feeds)")

marketplace_id = mk_marketplace(marketplace).marketplace_id
st.write("Marketplace ID:", marketplace_id)

c1, c2, c3 = st.columns(3)
with c1:
    if st.button("Submit DELETE feed (_POST_FLAT_FILE_LISTINGS_DATA_)"):
        if DELETE_DF is None:
            st.error("Build DELETE TSV first.")
        else:
            try:
                fid = submit_tsv_to_spapi(DELETE_DF, "_POST_FLAT_FILE_LISTINGS_DATA_", [marketplace_id])
                st.success(f"DELETE feed submitted. FeedId: {fid}")
                st.session_state.setdefault("feeds", []).append(fid)
            except Exception as e:
                st.exception(e)

with c2:
    if st.button("Submit CREATE feed (_POST_FLAT_FILE_LISTINGS_DATA_)"):
        if CREATE_DF is None:
            st.error("Build CREATE TSV first.")
        else:
            try:
                fid = submit_tsv_to_spapi(CREATE_DF, "_POST_FLAT_FILE_LISTINGS_DATA_", [marketplace_id])
                st.success(f"CREATE feed submitted. FeedId: {fid}")
                st.session_state.setdefault("feeds", []).append(fid)
            except Exception as e:
                st.exception(e)

with c3:
    if st.button("Submit PARENT UPDATE feed (_POST_FLAT_FILE_LISTINGS_DATA_)"):
        if not do_parent_update:
            st.error("Toggle 'Include PARENT UPDATE row' first.")
        elif PARENT_DF is None:
            st.error("Build PARENT UPDATE TSV first.")
        else:
            try:
                fid = submit_tsv_to_spapi(PARENT_DF, "_POST_FLAT_FILE_LISTINGS_DATA_", [marketplace_id])
                st.success(f"PARENT UPDATE feed submitted. FeedId: {fid}")
                st.session_state.setdefault("feeds", []).append(fid)
            except Exception as e:
                st.exception(e)

# ---------------------------
# Monitor & Reports
# ---------------------------
st.subheader("5) Feed Monitor & Processing Reports")

fid = st.text_input("FeedId to check")
colx, coly = st.columns(2)

with colx:
    if st.button("Check Status"):
        try:
            if not fid.strip():
                st.stop()
            fc = feeds_client()
            res = fc.get_feed(feedId=fid.strip()).payload
            st.json(res)
        except Exception as e:
            st.exception(e)

with coly:
    if st.button("Download Processing Report"):
        try:
            if not fid.strip():
                st.stop()
            fc = feeds_client()
            meta = fc.get_feed(feedId=fid.strip()).payload
            doc_id = meta.get("resultFeedDocumentId")
            if not doc_id:
                st.info("No processing report yet.")
            else:
                doc = fc.get_feed_document(doc_id).payload
                url = doc["url"]
                content = requests.get(url, timeout=120).content
                if doc.get("compressionAlgorithm") == "GZIP":
                    content = gzip.decompress(content)
                st.download_button("Download report", data=content, file_name=f"feed_{fid}_report.txt")
                preview = content.decode("utf-8", errors="replace")[:6000]
                st.text(preview)
        except Exception as e:
            st.exception(e)

st.caption("Tip: Run DELETE (children) first, then CREATE (children). Include a PARENT UPDATE if you want to refresh top-level bullets/description/keywords.")
