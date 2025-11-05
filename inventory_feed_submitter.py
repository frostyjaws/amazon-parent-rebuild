import requests
import csv
import io

AMZ_ENDPOINT = "https://sellingpartnerapi-na.amazon.com"

def generate_inventory_feed(skus, quantity=999, latency=2):
    """
    TSV payload:
      sku    quantity    fulfillment_latency
    """
    output = io.StringIO()
    writer = csv.writer(output, delimiter='\t', lineterminator='\n')
    writer.writerow(["sku", "quantity", "fulfillment_latency"])
    for sku in skus:
        writer.writerow([sku, quantity, latency])
    return output.getvalue()

def submit_inventory_feed(skus, access_token, marketplace_id, seller_id, quantity=999, latency=2):
    """
    Submit POST_INVENTORY_AVAILABILITY_DATA feed for provided SKUs.
    Returns feedId.
    """
    feed_content = generate_inventory_feed(skus, quantity=quantity, latency=latency)

    # 1) Create document
    doc_res = requests.post(
        f"{AMZ_ENDPOINT}/feeds/2021-06-30/documents",
        headers={"x-amz-access-token": access_token, "Content-Type": "application/json"},
        json={"contentType": "text/tab-separated-values"},
    )
    doc_res.raise_for_status()
    doc = doc_res.json()

    # 2) Upload TSV
    up = requests.put(
        doc["url"],
        data=feed_content.encode("utf-8"),
        headers={"Content-Type": "text/tab-separated-values"},
    )
    up.raise_for_status()

    # 3) Submit feed
    feed_res = requests.post(
        f"{AMZ_ENDPOINT}/feeds/2021-06-30/feeds",
        headers={"x-amz-access_token": access_token, "Content-Type": "application/json"},
        json={
            "feedType": "POST_INVENTORY_AVAILABILITY_DATA",
            "marketplaceIds": [marketplace_id],
            "inputFeedDocumentId": doc["feedDocumentId"],
        },
    )
    feed_res.raise_for_status()
    return feed_res.json()["feedId"]

def check_inventory_feed_status(feed_id: str, access_token: str) -> dict:
    """
    Returns feed status JSON.
    """
    res = requests.get(
        f"{AMZ_ENDPOINT}/feeds/2021-06-30/feeds/{feed_id}",
        headers={"x-amz-access-token": access_token, "Content-Type": "application/json"},
    )
    res.raise_for_status()
    return res.json()

def download_inventory_processing_report(feed_status: dict, access_token: str) -> str:
    """
    Downloads processing report text if available; else returns a note.
    """
    doc_id = feed_status.get("resultFeedDocumentId")
    if not doc_id:
        return "Processing report not available yet."

    doc_info = requests.get(
        f"{AMZ_ENDPOINT}/feeds/2021-06-30/documents/{doc_id}",
        headers={"x-amz-access-token": access_token},
    ).json()

    report = requests.get(doc_info["url"])
    report.raise_for_status()
    return report.text
