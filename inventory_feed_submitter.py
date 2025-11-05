import requests, csv, io
AMZ_ENDPOINT = "https://sellingpartnerapi-na.amazon.com"

def generate_inventory_feed(skus, quantity=999, latency=2):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    w.writerow(["sku", "quantity", "fulfillment_latency"])
    for s in skus: w.writerow([s, quantity, latency])
    return buf.getvalue()

def submit_inventory_feed(skus, token, marketplace, seller, quantity=999, latency=2):
    tsv = generate_inventory_feed(skus, quantity, latency)
    doc = requests.post(f"{AMZ_ENDPOINT}/feeds/2021-06-30/documents",
                        headers={"x-amz-access-token":token,"Content-Type":"application/json"},
                        json={"contentType":"text/tab-separated-values"}).json()
    requests.put(doc["url"], data=tsv.encode(), headers={"Content-Type":"text/tab-separated-values"}).raise_for_status()
    res = requests.post(f"{AMZ_ENDPOINT}/feeds/2021-06-30/feeds",
                        headers={"x-amz-access-token":token,"Content-Type":"application/json"},
                        json={"feedType":"POST_INVENTORY_AVAILABILITY_DATA","marketplaceIds":[marketplace],"inputFeedDocumentId":doc["feedDocumentId"]}).json()
    return res["feedId"]

def check_inventory_feed_status(fid, token):
    return requests.get(f"{AMZ_ENDPOINT}/feeds/2021-06-30/feeds/{fid}",
                        headers={"x-amz-access-token":token}).json()

def download_inventory_processing_report(feed, token):
    doc_id=feed.get("resultFeedDocumentId")
    if not doc_id: return "No report yet."
    info=requests.get(f"{AMZ_ENDPOINT}/feeds/2021-06-30/documents/{doc_id}",headers={"x-amz-access-token":token}).json()
    txt=requests.get(info["url"]).text
    return txt
