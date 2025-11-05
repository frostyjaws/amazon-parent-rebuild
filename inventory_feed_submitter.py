"""
inventory_feed_submitter.py
---------------------------
Submits simple quantity + handling time inventory feeds to Amazon SP-API.
Feed type: POST_INVENTORY_AVAILABILITY_DATA
"""

import requests
import csv
import io
from typing import List

def generate_inventory_feed(skus: List[str], quantity: int = 999, latency: int = 2) -> str:
    """
    Generate a flat-file TSV inventory feed for Amazon with quantity and fulfillment latency.
    """
    output = io.StringIO()
    writer = csv.writer(output, delimiter='\t', lineterminator='\n')
    writer.writerow(["sku", "quantity", "fulfillment_latency"])
    for sku in skus:
        writer.writerow([sku, quantity, latency])
    return output.getvalue()

def submit_inventory_feed(skus: List[str], access_token: str, marketplace_id: str, seller_id: str) -> str:
    """
    Submits the generated inventory feed to Amazon SP-API using POST_INVENTORY_AVAILABILITY_DATA.
    Returns the Feed ID.
    """
    feed_content = generate_inventory_feed(skus)

    # Step 1: Create the feed document
    doc_res = requests.post(
        "https://sellingpartnerapi-na.amazon.com/feeds/2021-06-30/documents",
        headers={
            "x-amz-access-token": access_token,
            "Content-Type": "application/json"
        },
        json={"contentType": "text/tab-separated-values"}
    )
    doc_res.raise_for_status()
    doc = doc_res.json()

    # Step 2: Upload TSV content
    upload = requests.put(
        doc["url"],
        data=feed_content.encode("utf-8"),
        headers={"Content-Type": "text/tab-separated-values"}
    )
    upload.raise_for_status()

    # Step 3: Submit feed
    feed_res = requests.post(
        "https://sellingpartnerapi-na.amazon.com/feeds/2021-06-30/feeds",
        headers={
            "x-amz-access-token": access_token,
            "Content-Type": "application/json"
        },
        json={
            "feedType": "POST_INVENTORY_AVAILABILITY_DATA",
            "marketplaceIds": [marketplace_id],
            "inputFeedDocumentId": doc["feedDocumentId"]
        }
    )
    feed_res.raise_for_status()
    return feed_res.json()["feedId"]

def check_inventory_feed_status(feed_id: str, access_token: str) -> dict:
    """
    Check processing status of an inventory feed.
    """
    res = requests.get(
        f"https://sellingpartnerapi-na.amazon.com/feeds/2021-06-30/feeds/{feed_id}",
        headers={
            "x-amz-access-token": access_token,
            "Content-Type": "application/json"
        }
    )
    res.raise_for_status()
    return res.json()

def download_inventory_processing_report(feed_status: dict, access_token: str) -> str:
    """
    Download the inventory feed processing report once it's ready.
    """
    doc_id = feed_status.get("resultFeedDocumentId")
    if not doc_id:
        return "Processing report not available yet."

    doc_info = requests.get(
        f"https://sellingpartnerapi-na.amazon.com/feeds/2021-06-30/documents/{doc_id}",
        headers={"x-amz-access-token": access_token}
    ).json()

    report = requests.get(doc_info["url"])
    report.raise_for_status()
    return report.text
