import json, re

STOP_WORDS = {"NOFO", "VIBES", "BODYSUIT", "ONESIE"}

def extract_keywords_from_title(title):
    pre = title.split(" - ", 1)[0] if " - " in title else title
    words = [w for w in re.findall(r"[A-Za-z0-9']+", pre) if w]
    seen, out = set(), []
    for w in words:
        if w.upper() in STOP_WORDS: continue
        lw = w.lower()
        if lw not in seen:
            seen.add(lw)
            out.append(w)
    return out

def injected_bullets(kws, base):
    tpls = [
        "🎨 Premium DTG print: '{kw}'",
        "🎖️ Veteran-Owned small biz — '{kw}' design",
        "👶 100% cotton comfort — '{kw}'",
        "🎁 Great baby shower gift: '{kw}'",
        "📏 Many sizes & colors available."
    ]
    out = []
    for i in range(5):
        out.append(tpls[i].format(kw=kws[i]) if i < len(kws) else base[i])
    return out

def injected_description(base, kws):
    return base if not kws else base + " " + f"<p>Design theme: {', '.join(kws[:3])}.</p>"

def injected_generic_keywords(kws):
    return ", ".join(kws[:10])

def compact_json(obj):
    return json.dumps(obj, indent=2)

def parse_variation(v):
    parts = v.split()
    if len(parts) >= 3:
        size, color, sleeve = parts[0], parts[1], " ".join(parts[2:])
    elif len(parts) == 2:
        size, color, sleeve = parts[0], parts[1], ""
    else:
        size, color, sleeve = parts[0], "", ""
    return size, color.capitalize(), sleeve.title()

def _size_code(s):
    return {"Newborn":"NB","0-3M":"03M","3-6M":"36M","6-9M":"69M","6M":"06M","12M":"12M","18M":"18M","24M":"24M"}.get(s,s)

def _color_code(c):
    return {"White":"WH","Natural":"NA","Pink":"PK","Blue":"BL"}.get(c.capitalize(),"XX")

def _sleeve_code(s):
    return "LS" if "Long" in s else "SS"

def sku_from_variation(base, size, color, sleeve):
    return f"{base}-{_size_code(size)}-{_color_code(color)}-{_sleeve_code(sleeve)}"

def validate_messages(msgs, must_have_attr, label):
    probs=[]
    for i,m in enumerate(msgs,1):
        pre=f"[{label} #{i}]"
        for k in ("sku","operationType","productType"):
            if k not in m:
                probs.append(f"{pre} missing key '{k}'")
        if m.get("operationType")=="UPDATE" and must_have_attr:
            if "attributes" not in m or not m["attributes"]:
                probs.append(f"{pre} missing attributes for UPDATE")
        if m.get("productType")!="LEOTARD":
            probs.append(f"{pre} productType must be LEOTARD")
    return probs
