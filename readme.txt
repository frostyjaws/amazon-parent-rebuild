# Amazon Parent Rebuild (Keep Parent, Replace Children)

Streamlit + SP-API tool to:
- **Delete old children** under an existing parent
- **Create new children** with updated bullets/description/keywords/swatch mapping
- (Optional) **Update the parent row** (PartialUpdate) for top-level bullets/description

## Quick Start (Streamlit Cloud, no local setup)
1. Create GitHub repo (private): `amazon-parent-rebuild`
2. Add:
   - `streamlit_app.py`
   - `requirements.txt`
   - (optional) `.streamlit/secrets.toml` (or set these in Streamlit Cloud → Secrets)
3. Deploy on https://share.streamlit.io
   - Repository: `YOUR_GH_USERNAME/amazon-parent-rebuild`
   - Branch: `main`
   - Main file: `streamlit_app.py`
   - Add Secrets (if not committed): same keys as `.streamlit/secrets.toml`

## How to Use
1. Paste **Parent SKUs** (one per line).
2. Paste/confirm **variation lines** (`Size Sleeve Color`, last token = color).
3. (Optional) Paste existing child SKUs to delete; otherwise we delete only the newly planned children.
4. (Optional) Add **swatch mapping**: `Color,https://url` lines.
5. Build:
   - **DELETE TSV** (children only)
   - **CREATE TSV** (children only)
   - **PARENT UPDATE TSV** (optional)
6. Submit feeds to Amazon and monitor status / download processing report.

## Feed Types
- Uses `_POST_FLAT_FILE_LISTINGS_DATA_` (tab-delimited UTF-8).

## Notes
- Column set is minimal-but-sufficient. Add columns to `BASE_COLS` and row dicts as needed.
- Parent update uses `PartialUpdate` by default (safe). Switch to `Create or Replace (FullUpdate)` if you intend a full overwrite.

---
