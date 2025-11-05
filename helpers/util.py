import json
import re

def extract_keywords_from_title(title: str):
    if " - " in title:
        pre = title.split(" - ")[0]
    else:
        pre = title
    words = [w.strip() for w in re.split(r"\W+", pre) if w.strip()]
    blocked = {"NOFO", "VIBES", "BODYSUIT", "ONESIE"}
    kws = []
    for w in words:
        if w.upper() not in blocked and w.lower() not in [x.lower() for x in kws]:
            kws.append(w)
    return kws

def injected_bullets(keywords, base_bullets):
    out = []
    used = set()
    for i, b in enumerate(base_bullets):
        if i < len(keywords):
            kw = keywords[i]
            out.append(f"{b} Includes keyword: {kw}.")
            used.add(kw)
        else:
            out.append(b)
    return out

def injected_description(desc, keywords):
    if not keywords:
        return desc
    injected = ", ".join(keywords)
    return desc + f"<p>Keywords: {injected}</p>"

def injected_generic_keywords(keywords):
    return ", ".join(keywords[:10])

def compact_json(obj):
    return json.dumps(obj, indent=2)
