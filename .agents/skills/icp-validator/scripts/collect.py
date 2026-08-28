#!/usr/bin/env python3
"""icp-validator collector: fetch public homepages, derive an ICP from customers,
score prospects. Stdlib only, Python 3.9+. All network I/O lives here."""

import argparse
import csv
import io
import ipaddress
import json
import os
import re
import socket
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

VERSION = "1.0"
UA = "Mozilla/5.0 (compatible; icp-validator/1.0; +https://github.com/mogaeduard/gtm-skillathon)"
REQ_TIMEOUT = 6
SIZE_CAP = 1536 * 1024
MAX_WORKERS = 16

# ---------------------------------------------------------------- safety

PERSONAL_HEADER_RE = re.compile(
    r"email|e-mail|phone|telefon|linkedin|contact|first_?name|last_?name|nume|prenume|persoan", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
LINKEDIN_IN_RE = re.compile(r"linkedin\.com/in/", re.I)
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
SHELL_META_RE = re.compile(r"[;&|`$<>(){}\[\]'\"\\\s]")

def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def refuse(msg):
    print("REFUSED: " + msg)
    sys.exit(2)

def canonicalize(raw):
    """-> (host, url) or raises ValueError with a reason."""
    v = (raw or "").strip()
    if not v:
        raise ValueError("empty domain")
    if SHELL_META_RE.search(v):
        raise ValueError("shell metacharacters or whitespace in domain")
    if "://" in v:
        scheme = v.split("://", 1)[0].lower()
        if scheme not in ("http", "https"):
            raise ValueError("non-http(s) scheme: " + scheme)
        rest = v.split("://", 1)[1]
    else:
        rest = v
    rest = rest.split("/")[0].split("?")[0].split("#")[0]
    if "@" in rest:
        raise ValueError("credentials/@ in host")
    host = rest.lower()
    if ":" in host:
        host, _, port = host.partition(":")
        if port and not port.isdigit():
            raise ValueError("bad port")
    if not host:
        raise ValueError("empty host")
    try:
        ipaddress.ip_address(host)
        raise ValueError("IP literal not allowed")
    except ValueError as e:
        if "not allowed" in str(e):
            raise
    if host == "localhost" or host.endswith(".local") or host.endswith(".localhost"):
        raise ValueError("localhost/.local not allowed")
    if "." not in host:
        raise ValueError("hostname without a dot")
    if not re.match(r"^[a-z0-9.-]+$", host):
        raise ValueError("invalid characters in host")
    return host, "https://" + host

def dedupe_key(host):
    return host[4:] if host.startswith("www.") else host

def is_url(path):
    return (path or "").lower().startswith(("http://", "https://"))

def download(url):
    """-> CSV text. Exits 2 on any failure (nothing fetched == refused class)."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "text/csv,text/plain,*/*"})
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read(2 * 1024 * 1024)
        return raw.decode("utf-8-sig", "replace")
    except Exception as e:
        print("INPUT ERROR: could not download %s: %s" % (url, e))
        sys.exit(2)

def read_csv(path, limit):
    """-> (rows, refused). Path or http(s) URL. Exits 2 on personal data or all-refused."""
    if is_url(path):
        text = download(path)
    else:
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                text = f.read()
        except OSError as e:
            print("ERROR: cannot read %s: %s" % (path, e))
            sys.exit(2)
    rdr = csv.DictReader(io.StringIO(text, newline=""))
    headers = rdr.fieldnames or []
    rows = list(rdr)

    for h in headers:
        if h and PERSONAL_HEADER_RE.search(h):
            refuse("personal data column/value detected (%s)" % h)
    for row in rows:
        for k, v in row.items():
            if not isinstance(v, str):
                continue
            if EMAIL_RE.search(v) or LINKEDIN_IN_RE.search(v) or PHONE_RE.search(v):
                refuse("personal data column/value detected (%s)" % (k or "?"))

    lower = {}
    for h in headers:
        if h:
            lower[h.strip().lower()] = h
    dom_col = lower.get("domain") or lower.get("website")
    comp_col = lower.get("company")
    if not dom_col or not comp_col:
        refuse("missing required columns company,domain in %s" % path)

    out, refused, seen = [], [], set()
    for row in rows:
        company = (row.get(comp_col) or "").strip()
        raw = (row.get(dom_col) or "").strip()
        try:
            host, url = canonicalize(raw)
        except ValueError as e:
            refused.append({"company": company, "input": raw, "reason": str(e)})
            continue
        key = dedupe_key(host)
        if key in seen:
            refused.append({"company": company, "input": raw, "reason": "duplicate host (%s)" % key})
            continue
        seen.add(key)
        rec = {"company": company or host, "domain": host, "url": url}
        for c in ("status", "deal_size", "days_to_close", "retention_months", "revenue",
                  "industry", "employees", "country", "retention", "sales_cycle"):
            if c in lower:
                rec[c] = (row.get(lower[c]) or "").strip()
        out.append(rec)
        if len(out) >= limit:
            break
    if not out:
        refuse("no valid domains in %s" % path)
    return out, refused

# ---------------------------------------------------------------- fetch

class NetError(Exception):
    pass

def fetch(url):
    """-> page dict. Never raises."""
    t0 = time.time()
    page = {"url": url, "final_url": None, "http_status": None, "bytes": 0,
            "retrieved_at": utcnow(), "elapsed_ms": 0, "error": None, "html": ""}
    net_fail = False
    for attempt_url in (url, url.replace("https://", "http://", 1)):
        try:
            req = urllib.request.Request(attempt_url, headers={
                "User-Agent": UA, "Accept": "text/html,*/*",
                "Accept-Language": "en,ro;q=0.8"})
            with urllib.request.urlopen(req, timeout=REQ_TIMEOUT) as r:
                raw = r.read(SIZE_CAP)
                page["final_url"] = r.geturl()
                page["http_status"] = r.getcode()
                page["bytes"] = len(raw)
                enc = "utf-8"
                ct = r.headers.get("Content-Type", "")
                m = re.search(r"charset=([\w-]+)", ct or "", re.I)
                if m:
                    enc = m.group(1)
                try:
                    page["html"] = raw.decode(enc, "replace")
                except LookupError:
                    page["html"] = raw.decode("utf-8", "replace")
                page["error"] = None
                page["elapsed_ms"] = int((time.time() - t0) * 1000)
                return page
        except urllib.error.HTTPError as e:
            page["http_status"] = e.code
            page["final_url"] = attempt_url
            page["error"] = "HTTP %s" % e.code
            try:
                raw = e.read(SIZE_CAP)
                page["bytes"] = len(raw)
                page["html"] = raw.decode("utf-8", "replace")
            except Exception:
                pass
            break
        except (urllib.error.URLError, socket.timeout, socket.error, OSError) as e:
            net_fail = True
            page["error"] = "%s: %s" % (type(e).__name__, e)
        except Exception as e:  # pragma: no cover
            page["error"] = "%s: %s" % (type(e).__name__, e)
            break
    page["elapsed_ms"] = int((time.time() - t0) * 1000)
    page["net_fail"] = net_fail and page["http_status"] is None
    return page

SECONDARY_RE = re.compile(r"about|despre|company|team|echipa|careers|cariere|jobs|joburi", re.I)
CAREER_RE = re.compile(r"careers|cariere|jobs|joburi", re.I)
ABOUT_RE = re.compile(r"about|despre|company|team|echipa", re.I)
LINK_RE = re.compile(r"<a\b[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)

def pick_secondary(html, base_url, host):
    careers, abouts = [], []
    for href, text in LINK_RE.findall(html or "")[:800]:
        label = re.sub(r"<[^>]+>", " ", text)
        hay = href + " " + label
        if not SECONDARY_RE.search(hay):
            continue
        try:
            absu = urllib.parse.urljoin(base_url, href.strip())
        except Exception:
            continue
        p = urllib.parse.urlparse(absu)
        if p.scheme not in ("http", "https"):
            continue
        if dedupe_key((p.hostname or "").lower()) != dedupe_key(host):
            continue
        if CAREER_RE.search(hay):
            careers.append(absu)
        elif ABOUT_RE.search(hay):
            abouts.append(absu)
    for lst in (careers, abouts):
        for u in lst:
            if u.rstrip("/") != (base_url or "").rstrip("/"):
                return u, bool(lst is careers)
    return None, False

# ---------------------------------------------------------------- extract

SCRIPT_RE = re.compile(r"<(script|style|noscript|svg|template)\b.*?</\1>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

def strip_text(html):
    h = SCRIPT_RE.sub(" ", html or "")
    h = re.sub(r"<!--.*?-->", " ", h, flags=re.S)
    h = re.sub(r"<(nav|header|footer)\b.*?</\1>", " ", h, flags=re.I | re.S)
    h = TAG_RE.sub(" ", h)
    h = h.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'")
    h = re.sub(r"&[a-zA-Z#0-9]{2,8};", " ", h)
    return WS_RE.sub(" ", h).strip()

def tag_texts(html, tag, limit=10):
    out = []
    for m in re.finditer(r"<%s\b[^>]*>(.*?)</%s>" % (tag, tag), html or "", re.I | re.S):
        t = WS_RE.sub(" ", TAG_RE.sub(" ", m.group(1))).strip()
        if t:
            out.append(t[:200])
        if len(out) >= limit:
            break
    return out

TECH_SIGS = [
    ("wordpress", r"wp-content"), ("wix", r"parastorage"), ("webflow", r"webflow"),
    ("shopify", r"shopify"), ("nextjs", r"/_next/"), ("react", r"react"),
    ("vue", r"vue(?:\.min)?\.js|__vue__|data-v-"), ("angular", r"ng-version|angular"),
    ("gtm", r"googletagmanager\.com"), ("ga", r"google-analytics|gtag"),
    ("hubspot", r"hs-scripts|hubspot"), ("intercom", r"intercom"), ("crisp", r"crisp\.chat"),
    ("hotjar", r"hotjar"), ("stripe", r"js\.stripe\.com"), ("cloudflare", r"cdn-cgi"),
    ("recaptcha", r"recaptcha"),
]
TECH_SIGS = [(n, re.compile(p, re.I)) for n, p in TECH_SIGS]

JOB_KW_RE = re.compile(r"engineer|developer|inginer|programator|devops|qa|data|product manager|designer", re.I)
RO_CITY_RE = re.compile(r"rom[aâ]nia|bucure[sș]ti|bucharest|cluj|timi[sș]oara|ia[sș]i|bra[sș]ov|sibiu|oradea|constan[tț]a", re.I)
SIZE_RE = re.compile(r"(\d{2,5})\+?\s*(?:employees|angaja[tț]i|people|oameni|specialists|engineers)", re.I)

TAXONOMY = [
    ("saas_product", r"platform|saas|software product|app\b|automation|api"),
    ("agency_outsourcing", r"agency|agenție|outsourcing|custom software|software development services|nearshore|dedicated team|we build"),
    ("igaming", r"igaming|casino|betting|gaming platform"),
    ("fintech", r"fintech|payments|banking|lending|crowdfunding"),
    ("ecommerce", r"e-?commerce|shop|magazin"),
    ("martech", r"marketing|cro|conversion|analytics|seo|campaign"),
    ("cybersecurity", r"security|securitate|antivirus|threat"),
    ("hr_payroll", r"payroll|hr software|salarizare|recruit"),
    ("consulting", r"consulting|consultanță|advisory"),
    ("education", r"course|training|academy|bootcamp|school|student"),
    ("hardware_iot", r"iot|hardware|embedded|device"),
    ("nonprofit_community", r"ong|nonprofit|non-profit|voluntar|community|comunitate"),
]
TAXONOMY = [(n, re.compile(p, re.I)) for n, p in TAXONOMY]

BANDS = ["1-10", "11-50", "51-200", "201-1000", "1000+"]

def band_of(n):
    if n is None:
        return None
    if n <= 10:
        return "1-10"
    if n <= 50:
        return "11-50"
    if n <= 200:
        return "51-200"
    if n <= 1000:
        return "201-1000"
    return "1000+"

def extract(rec, home, secondary, secondary_is_careers):
    html = (home.get("html") or "") if home else ""
    shtml = (secondary.get("html") or "") if secondary else ""
    both = html + "\n" + shtml
    text = strip_text(html)
    stext = strip_text(shtml)
    all_text = (text + " " + stext).strip()

    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = WS_RE.sub(" ", TAG_RE.sub(" ", m.group(1))).strip()[:300] if m else ""
    md = re.search(r'<meta[^>]+name=["\']description["\'][^>]*content=["\']([^"\']*)', html, re.I) \
        or re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*name=["\']description["\']', html, re.I)
    meta_description = WS_RE.sub(" ", md.group(1)).strip()[:500] if md else ""
    lm = re.search(r'<html[^>]+lang=["\']([A-Za-z-]+)', html, re.I)
    lang = lm.group(1).lower() if lm else None

    tech = sorted({name for name, rx in TECH_SIGS if rx.search(both)})
    job_hits = len(JOB_KW_RE.findall(stext)) if stext else 0
    cities = sorted({c.lower() for c in RO_CITY_RE.findall(all_text)}) if False else \
        sorted({m0.group(0).lower() for m0 in RO_CITY_RE.finditer(all_text)})
    sm = SIZE_RE.search(all_text)
    size_n = int(sm.group(1)) if sm else None
    langs = sorted({l.lower() for l in re.findall(r'hreflang=["\']([A-Za-z-]+)', both)} | ({lang} if lang else set()))

    basis = " ".join([title, meta_description] + tag_texts(html, "h1", 10)) + " " + all_text[:4000]
    cat = {}
    for name, rx in TAXONOMY:
        hits = len(rx.findall(basis))
        if hits:
            cat[name] = hits

    text_chars = len(all_text)
    out = {
        "company": rec["company"], "domain": rec["domain"],
        "pages": [p for p in (home, secondary) if p],
        "title": title, "meta_description": meta_description, "lang": lang,
        "h1": tag_texts(html, "h1", 10), "h2": tag_texts(html, "h2", 10),
        "text_excerpt": all_text[:1500], "text_chars": text_chars,
        "signals": {
            "hiring": {"careers_page_found": bool(secondary_is_careers),
                       "job_keyword_hits": job_hits},
            "tech": tech,
            "location": {"romania": bool(cities), "cities": cities},
            "size_hint": {"number": size_n, "band": band_of(size_n)},
            "languages": langs,
            "category_tags": cat,
        },
        "insufficient_evidence": bool((not home) or home.get("http_status") is None
                                      or home.get("http_status", 0) >= 400 or text_chars < 300),
        "error": (home or {}).get("error"),
    }
    return out

def collect_one(rec, deadline):
    if time.time() > deadline:
        return {"company": rec["company"], "domain": rec["domain"], "pages": [],
                "text_chars": 0, "insufficient_evidence": True, "error": "budget exceeded",
                "signals": {"hiring": {"careers_page_found": False, "job_keyword_hits": 0},
                            "tech": [], "location": {"romania": False, "cities": []},
                            "size_hint": {"number": None, "band": None},
                            "languages": [], "category_tags": {}},
                "title": "", "meta_description": "", "lang": None, "h1": [], "h2": [],
                "text_excerpt": ""}
    home = fetch(rec["url"])
    sec, is_careers = (None, False)
    if home.get("html") and time.time() < deadline:
        u, is_careers = pick_secondary(home["html"], home.get("final_url") or rec["url"], rec["domain"])
        if u:
            sec = fetch(u)
            if not sec.get("html"):
                is_careers = False
    return extract(rec, home, sec, is_careers)

def strip_html(companies):
    for c in companies:
        for p in c.get("pages", []):
            p.pop("html", None)
            p.pop("net_fail", None)
    return companies

# ---------------------------------------------------------------- ICP

def top_tag(c):
    cat = c.get("signals", {}).get("category_tags") or {}
    if not cat:
        return None
    return sorted(cat.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

def is_hiring(c):
    h = c.get("signals", {}).get("hiring", {})
    return bool(h.get("careers_page_found")) or h.get("job_keyword_hits", 0) > 0

def _nums(rows, key):
    out = []
    for r in rows:
        v = (r.get(key) or "").strip().replace(",", "").replace(" ", "")
        v = re.sub(r"[^0-9.\-]", "", v)
        try:
            out.append(float(v))
        except ValueError:
            pass
    return out

WIN_RE = re.compile(r"deal|won|client|partener|partner", re.I)

def _dist(rows, key, top=5):
    """Top values with shares, or 'not in input' when < 5 non-empty values."""
    vals = [(r.get(key) or "").strip() for r in rows]
    vals = [v for v in vals if v]
    if len(vals) < 5:
        return "not in input"
    return {k: round(v / len(vals), 3) for k, v in Counter(vals).most_common(top)}

def _band_dist(rows, key="employees"):
    v = _nums(rows, key)
    if len(v) < 5:
        return "not in input"
    c = Counter(band_of(int(x)) for x in v)
    return {k: round(n / len(v), 3) for k, n in c.most_common()}

def _ret_nums(rows):
    # ponytail: 0-1 or percent, split at 1.5 -- no CRM reports 150% retention as 1.5
    return [x / 100.0 if x > 1.5 else x for x in _nums(rows, "retention")]

def derive_icp(companies, rows):
    n = len(companies)

    ret, deals = _ret_nums(rows), _nums(rows, "deal_size")
    good, good_idx = "not in input", []
    if len(ret) >= 5 and len(deals) >= 5:
        med = statistics.median(deals)
        names = []
        for i, r in enumerate(rows):
            rv, dv = _ret_nums([r]), _nums([r], "deal_size")
            if rv and dv and rv[0] >= 0.9 and dv[0] >= med:
                good_idx.append(i)
                names.append(r.get("company") or "")
        good = {"rule": "retention >= 0.9 and deal_size >= median(deal_size)",
                "median_deal_size": round(med, 2), "n_good": len(names), "companies": names}

    derived_from, src = "all_customers", companies
    sub = [companies[i] for i in good_idx if i < len(companies)]
    if len(sub) >= 3:
        derived_from, src = "good_customers", sub

    companies = src
    ev = [c for c in companies if not c.get("insufficient_evidence")]
    ne = len(ev)
    def share(pred):
        return round(sum(1 for c in ev if pred(c)) / ne, 3) if ne else 0.0

    tag_counts = Counter(t for t in (top_tag(c) for c in ev) if t)
    tag_share = {k: round(v / ne, 3) for k, v in tag_counts.items()} if ne else {}
    bands = Counter(c["signals"]["size_hint"]["band"] for c in ev
                    if c["signals"]["size_hint"]["band"])
    tech = Counter(t for c in ev for t in c["signals"]["tech"])
    langs = Counter(l for c in ev for l in c["signals"]["languages"])

    if ne < 5:
        conf = "insufficient (n<5 with evidence)"
    elif ne < 10:
        conf = "low"
    elif ne < 20:
        conf = "medium"
    else:
        conf = "high"

    statuses = [(r.get("status") or "").strip() for r in rows]
    statuses = [s for s in statuses if s]
    win_rate = (round(sum(1 for s in statuses if WIN_RE.search(s)) / len(statuses), 3)
                if len(statuses) >= 5 else "not in input")

    def mm(key):
        v = _nums(rows, key)
        if len(v) < 5:
            return "not in input"
        return {"mean": round(statistics.mean(v), 2), "median": round(statistics.median(v), 2),
                "n": len(v)}

    if len(ret) >= 5:
        retention = {"mean": round(statistics.mean(ret), 3),
                     "median": round(statistics.median(ret), 3), "n": len(ret)}
    else:
        retention = mm("retention_months")
    sc = _nums(rows, "sales_cycle") or _nums(rows, "days_to_close")
    sales_cycle = ({"mean": round(statistics.mean(sc), 2),
                    "median": round(statistics.median(sc), 2), "n": len(sc)}
                   if len(sc) >= 5 else "not in input")

    return {
        "n_customers": n, "n_with_evidence": ne, "icp_confidence": conf,
        "derived_from": derived_from, "good_customers": good,
        "category_share": dict(sorted(tag_share.items(), key=lambda kv: -kv[1])),
        "top_tags": [k for k, _ in tag_counts.most_common(2)],
        "share_romania": share(lambda c: c["signals"]["location"]["romania"]),
        "share_hiring": share(is_hiring),
        "size_band_share": {k: round(v / ne, 3) for k, v in bands.items()} if ne else {},
        "modal_size_band": bands.most_common(1)[0][0] if bands else None,
        "tech_share": {k: round(v / ne, 3) for k, v in tech.most_common()} if ne else {},
        "tech_union": sorted(tech),
        "language_share": {k: round(v / ne, 3) for k, v in langs.most_common()} if ne else {},
        "majority_languages": ([k for k, v in langs.items() if ne and v / ne >= 0.5]
                               or [k for k, _ in langs.most_common(1)]),
        "majority_romania": bool(ne and share(lambda c: c["signals"]["location"]["romania"]) >= 0.5),
        "majority_hiring": bool(ne and share(is_hiring) >= 0.5),
        "crm": {"win_rate": win_rate, "deal_size": mm("deal_size"),
                "days_to_close": mm("days_to_close"), "sales_cycle": sales_cycle,
                "retention": retention, "revenue": mm("revenue"),
                "industry": _dist(rows, "industry"), "country": _dist(rows, "country"),
                "employees": _band_dist(rows)},
    }

def score(prospect, icp):
    if prospect.get("insufficient_evidence"):
        return None, [], "insufficient evidence"
    comps = []
    pt = top_tag(prospect)
    if pt and pt in icp["top_tags"]:
        comps.append({"name": "category", "points": 40, "max": 40,
                      "because": "top tag '%s' is a customer top-2 tag" % pt})
    elif pt and icp["category_share"].get(pt, 0) >= 0.20:
        comps.append({"name": "category", "points": 20, "max": 40,
                      "because": "top tag '%s' has %s customer share" % (pt, icp["category_share"].get(pt))})
    else:
        comps.append({"name": "category", "points": 0, "max": 40,
                      "because": "top tag '%s' not in customer mix" % pt})

    ro = prospect["signals"]["location"]["romania"]
    comps.append({"name": "location", "points": 15 if ro == icp["majority_romania"] else 0, "max": 15,
                  "because": "romania=%s vs customer majority %s" % (ro, icp["majority_romania"])})

    hr = is_hiring(prospect)
    comps.append({"name": "hiring", "points": 15 if hr == icp["majority_hiring"] else 0, "max": 15,
                  "because": "hiring=%s (job_keyword_hits=%s) vs customer majority %s"
                             % (hr, prospect["signals"]["hiring"]["job_keyword_hits"], icp["majority_hiring"])})

    ps, cs = set(prospect["signals"]["tech"]), set(icp["tech_union"])
    jac = len(ps & cs) / len(ps | cs) if (ps or cs) else 0.0
    comps.append({"name": "tech", "points": int(round(10 * jac)), "max": 10,
                  "because": "tech overlap %s (jaccard %.2f)" % (sorted(ps & cs) or "none", jac)})

    pb, mb = prospect["signals"]["size_hint"]["band"], icp["modal_size_band"]
    pts = 0
    if pb and mb:
        if pb == mb:
            pts = 10
        elif abs(BANDS.index(pb) - BANDS.index(mb)) == 1:
            pts = 5
    comps.append({"name": "size", "points": pts, "max": 10,
                  "because": "band %s vs customer modal band %s" % (pb, mb)})

    pl = set(prospect["signals"]["languages"])
    ml = set(icp["majority_languages"])
    comps.append({"name": "language", "points": 10 if (pl & ml) else 0, "max": 10,
                  "because": "languages %s vs customer majority %s" % (sorted(pl), sorted(ml))})

    fit = sum(c["points"] for c in comps)
    verdict = "fit" if fit >= 80 else ("maybe" if fit >= 50 else "unfit")
    return fit, comps, verdict

# ---------------------------------------------------------------- selftest

def selftest():
    for bad in ("localhost", "10.0.0.1", "user@host.com", "http://127.0.0.1/x",
                "ftp://example.com", "no-dot", "exa mple.com", "a;b.com"):
        try:
            canonicalize(bad)
            raise AssertionError("should have refused: %s" % bad)
        except ValueError:
            pass
    h1, u1 = canonicalize("WWW.Example.com/path?q=1#f")
    assert (h1, u1) == ("www.example.com", "https://www.example.com"), (h1, u1)
    h2, _ = canonicalize("https://example.com")
    assert dedupe_key(h1) == dedupe_key(h2) == "example.com"

    assert PERSONAL_HEADER_RE.search("Email") and PERSONAL_HEADER_RE.search("first_name")
    assert PERSONAL_HEADER_RE.search("persoana de contact")
    assert EMAIL_RE.search("ana@zitec.ro") and LINKEDIN_IN_RE.search("https://linkedin.com/in/x")
    assert PHONE_RE.search("+40 721 234 567")

    assert [band_of(x) for x in (5, 30, 120, 500, 5000, None)] == \
        ["1-10", "11-50", "51-200", "201-1000", "1000+", None]

    def synth(tag, ro, hiring, tech, band, langs, chars=1000):
        n = {"1-10": 5, "11-50": 30, "51-200": 120, "201-1000": 500, "1000+": 5000}.get(band)
        return {"company": tag, "domain": tag + ".com", "text_chars": chars,
                "insufficient_evidence": chars < 300, "pages": [],
                "signals": {"hiring": {"careers_page_found": hiring, "job_keyword_hits": 3 if hiring else 0},
                            "tech": tech, "location": {"romania": ro, "cities": ["cluj"] if ro else []},
                            "size_hint": {"number": n, "band": band}, "languages": langs,
                            "category_tags": {tag: 5}}}

    custs = [synth("saas_product", True, True, ["gtm", "react"], "51-200", ["en"]) for _ in range(4)]
    custs.append(synth("fintech", True, True, ["gtm"], "51-200", ["en"]))
    icp = derive_icp(custs, [{} for _ in custs])
    assert icp["n_with_evidence"] == 5 and icp["icp_confidence"] == "low", icp["icp_confidence"]
    assert icp["top_tags"][0] == "saas_product" and icp["modal_size_band"] == "51-200"
    assert icp["majority_romania"] and icp["majority_hiring"]

    perfect = synth("saas_product", True, True, ["gtm", "react"], "51-200", ["en"])
    fit, comps, verdict = score(perfect, icp)
    assert fit == 100 and verdict == "fit", (fit, comps)
    adj = synth("saas_product", True, True, ["gtm", "react"], "201-1000", ["en"])
    assert score(adj, icp)[0] == 95, score(adj, icp)[0]
    worst = synth("igaming", False, False, ["wix"], "1-10", ["de"])
    f2, _, v2 = score(worst, icp)
    assert f2 == 0 and v2 == "unfit", (f2, v2)
    none_p = synth("saas_product", True, True, [], "51-200", ["en"], chars=10)
    assert score(none_p, icp) == (None, [], "insufficient evidence")

    icp4 = derive_icp(custs[:4], [{}] * 4)
    assert icp4["icp_confidence"] == "insufficient (n<5 with evidence)"
    assert icp4["crm"]["win_rate"] == "not in input"
    rows = [{"status": "won", "deal_size": "1000", "days_to_close": "10"} for _ in range(4)]
    rows.append({"status": "lost", "deal_size": "2000", "days_to_close": "20"})
    icp5 = derive_icp(custs, rows)
    assert icp5["crm"]["win_rate"] == 0.8, icp5["crm"]["win_rate"]
    assert icp5["crm"]["deal_size"]["median"] == 1000.0
    assert icp5["crm"]["retention"] == "not in input" and icp5["crm"]["revenue"] == "not in input"

    html = ('<html lang="ro"><head><title>Zitec</title>'
            '<meta name="description" content="Software development services"></head>'
            '<body><h1>Custom software</h1><script>var x=1</script>'
            '<a href="/cariere">Cariere</a><a href="/despre">Despre</a>'
            '<p>Suntem in Bucuresti, 250 angajati.</p>'
            '<script src="https://www.googletagmanager.com/gtm.js"></script></body></html>')
    rec = {"company": "Zitec", "domain": "zitec.com", "url": "https://zitec.com"}
    page = {"url": "https://zitec.com", "final_url": "https://zitec.com", "http_status": 200,
            "bytes": len(html), "retrieved_at": utcnow(), "elapsed_ms": 1, "error": None, "html": html}
    e = extract(rec, page, None, False)
    assert e["title"] == "Zitec" and e["lang"] == "ro"
    assert "var x=1" not in e["text_excerpt"]
    assert e["signals"]["location"]["romania"] and "gtm" in e["signals"]["tech"]
    assert e["signals"]["size_hint"]["band"] == "201-1000", e["signals"]["size_hint"]
    assert "agency_outsourcing" in e["signals"]["category_tags"]
    u, careers = pick_secondary(html, "https://zitec.com", "zitec.com")
    assert u == "https://zitec.com/cariere" and careers, (u, careers)

    # --- CRM extras + good-customer rule (a) -------------------------------
    hdr = "company,domain,industry,employees,country,revenue,retention,sales_cycle,deal_size,status\n"
    body = ["c%d,c%d.com,SaaS,%d,RO,%d,%s,%d,%d,won\n"
            % (i, i, 30 * (i + 1), 100000 * (i + 1), ("95%" if i < 3 else "0.4"), 10 + i,
               1000 * (i + 1))
            for i in range(6)]
    csv6 = hdr + "".join(body)
    orig_dl = globals()["download"]
    globals()["download"] = lambda u: csv6
    try:
        rows6, _ = read_csv("https://example.com/sheet.csv", 20)   # (c) URL branch taken
    finally:
        globals()["download"] = orig_dl
    assert len(rows6) == 6 and rows6[0]["industry"] == "SaaS", rows6[:1]
    custs6 = [synth("saas_product", True, True, ["gtm"], "51-200", ["en"]) for _ in range(6)]
    i6 = derive_icp(custs6, rows6)
    crm = i6["crm"]
    assert crm["industry"] == {"SaaS": 1.0} and crm["country"] == {"RO": 1.0}, crm
    assert crm["employees"] == {"51-200": 0.833, "11-50": 0.167}, crm["employees"]
    assert crm["revenue"]["median"] == 350000.0, crm["revenue"]
    assert crm["retention"]["n"] == 6 and crm["sales_cycle"]["median"] == 12.5, crm
    g = i6["good_customers"]
    assert g["n_good"] == 0 and i6["derived_from"] == "all_customers", g  # 95% only on cheap deals
    rows6b = [dict(r, retention="0.95") for r in rows6]
    i6b = derive_icp(custs6, rows6b)
    assert i6b["good_customers"]["companies"] == ["c3", "c4", "c5"], i6b["good_customers"]
    assert i6b["derived_from"] == "good_customers" and i6b["n_customers"] == 6
    assert i6b["n_with_evidence"] == 3, i6b["n_with_evidence"]

    # --- (b) same shape, 3 rows -> not in input ----------------------------
    globals()["download"] = lambda u: hdr + "".join(body[:3])
    try:
        rows3, _ = read_csv("https://example.com/sheet3.csv", 20)
    finally:
        globals()["download"] = orig_dl
    i3 = derive_icp(custs6[:3], rows3)
    assert i3["good_customers"] == "not in input" and i3["derived_from"] == "all_customers"
    for k in ("industry", "country", "employees", "revenue", "retention", "sales_cycle"):
        assert i3["crm"][k] == "not in input", (k, i3["crm"][k])

    print("SELFTEST OK")
    return 0

# ---------------------------------------------------------------- main

def _pct(x):
    return "%d%%" % round(100.0 * x) if isinstance(x, (int, float)) else str(x)

def _shares(d, limit=4):
    if not isinstance(d, dict) or not d:
        return "not observed"
    items = sorted(d.items(), key=lambda kv: -kv[1])[:limit]
    return ", ".join("%s %s" % (k, _pct(v)) for k, v in items)

# Denylist adapted from the outbound pipeline's domain resolver: these hosts are
# directories, social networks, press and job boards, never a company's own site.
EXCLUDE_HOSTS = set("""
facebook.com linkedin.com instagram.com tiktok.com youtube.com twitter.com x.com t.co
wikipedia.org google.com bing.com duckduckgo.com apple.com microsoft.com adobe.com
indeed.com glassdoor.com ejobs.ro hipo.ro bestjobs.ro olx.ro emag.ro listafirme.ro termene.ro
risco.ro mfinante.gov.ro anaf.ro tripadvisor.com booking.com crunchbase.com g2.com capterra.com
trustpilot.com producthunt.com github.com gitlab.com discord.com discord.gg slack.com reddit.com
medium.com substack.com forbes.ro zf.ro profit.ro hotnews.ro digi24.ro adevarul.ro startupcafe.ro
wall-street.ro ziare.com stirileprotv.ro capital.ro gravatar.com w3.org schema.org creativecommons.org
googletagmanager.com google-analytics.com gstatic.com cloudflare.com jsdelivr.net unpkg.com
goo.gl bit.ly lnkd.in forms.gle about.google maps.google.com policies.google.com blog.google
wa.me whatsapp.com telegram.me t.me vimeo.com flickr.com pinterest.com spotify.com paypal.com
mailchimp.com sendgrid.com stripe.com amazonaws.com azurewebsites.net vercel.app netlify.app
hubspot.com intercom.io crisp.chat typeform.com calendly.com eventbrite.com meetup.com luma.com
""".split())

def _excluded(host):
    for ex in EXCLUDE_HOSTS:
        if host == ex or host.endswith("." + ex):
            return True
    return False

def discover(list_url, limit, outdir):
    """Extract company domains from one public list page (customers, sponsors, portfolio,
    directory). Keyless: one GET, then link and logo-label extraction."""
    page = fetch(list_url)
    if not page.get("http_status"):
        print("DISCOVERY FAILED: could not fetch %s (%s)" % (list_url, page.get("error")))
        return [], page
    html_body = page.get("html") or ""
    src_host = urllib.parse.urlparse(page.get("final_url") or list_url).netloc.lower().replace("www.", "")
    found, order = {}, []
    for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', html_body, re.S | re.I):
        url, inner = m.group(1), m.group(2)
        host = urllib.parse.urlparse(url).netloc.lower().replace("www.", "")
        if not host or host == src_host or host.endswith("." + src_host) or _excluded(host):
            continue
        # brightdata.es / brightdata.jp off brightdata.com are the same brand, not prospects
        if host.split(".")[0] == src_host.split(".")[0]:
            continue
        label = re.search(r'alt="([^"]{2,60})"', inner)
        label = label.group(1) if label else re.sub(r"<[^>]+>", " ", inner)
        label = re.sub(r"\s+", " ", label).strip(" .,|-")
        if not label or len(label) > 60 or re.search(r"@|\+\d|linkedin\.com/in/", label):
            continue
        # call-to-action link text is not a company name; fall back to the domain root
        if re.search(r"ticket|register|apply|read more|learn more|click|here|sign up|book|buy|"
                     r"contact|home|menu|more$", label, re.I):
            label = host.split(".")[0]
        if host not in found:
            found[host] = re.sub(r"\s+logo$", "", label, flags=re.I) or host.split(".")[0]
            order.append(host)
    rows = [{"company": found[h], "domain": h} for h in order[:limit]]
    path = os.path.join(outdir, "discovered.csv")
    os.makedirs(outdir, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["company", "domain"])
        for r in rows:
            w.writerow([r["company"], r["domain"]])
    # provenance lives beside the CSV: the input file itself stays free of any
    # column the personal-data guard would have to reason about.
    with open(os.path.join(outdir, "discovery.json"), "w", encoding="utf-8") as f:
        json.dump({"source_url": page.get("final_url") or list_url,
                   "retrieved_at": page.get("retrieved_at"),
                   "http_status": page.get("http_status"),
                   "found": len(rows), "companies": rows}, f, indent=2)
    print("DISCOVERED %d companies from %s (retrieved %s) -> %s"
          % (len(rows), page.get("final_url") or list_url, page.get("retrieved_at"), path))
    return rows, page

def write_openers_input(icp, ranked, companies_by_domain, offer_path, outdir):
    """Slim file so the drafting step never has to read the big JSON."""
    offer_name, offer_lines = "the offer", []
    try:
        with open(offer_path, "r", encoding="utf-8") as f:
            raw = [ln.strip() for ln in f if ln.strip()]
        if raw:
            first = raw[0].lstrip("# ").strip()
            offer_name = first.split(":", 1)[1].strip() if ":" in first else first
            offer_lines = [ln for ln in raw[1:] if not ln.lower().startswith("surse")][:4]
    except Exception:
        pass
    top = []
    for r in ranked:
        if r.get("fit") is None or len(top) >= 3:
            continue
        c = companies_by_domain.get(r["domain"]) or {}
        excerpt = c.get("text_excerpt") or ""
        quotes = [q.strip() for q in re.split(r"(?<=[.!?])\s+", excerpt) if 40 <= len(q.strip()) <= 180][:3]
        te = r.get("top_evidence") or {}
        top.append({"company": r["company"], "domain": r["domain"], "fit": r["fit"],
                    "evidence_url": te.get("url"), "retrieved_at": te.get("retrieved_at"),
                    "title": (c.get("title") or "")[:140],
                    "quote_candidates": quotes,
                    "signals": {"hiring": bool(((c.get("signals") or {}).get("hiring") or {}).get("careers_page_found")), "romania": bool(((c.get("signals") or {}).get("location") or {}).get("romania"))}})
    path = os.path.join(outdir, "openers-input.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"offer_name": offer_name, "offer_lines": offer_lines,
                   "icp_confidence": icp.get("icp_confidence"), "top3": top}, f,
                  ensure_ascii=False, indent=2)
    return path

def write_reports(icp, ranked, refused, outdir, meta):
    """Write the two deterministic markdown reports. The agent only adds openers."""
    icp_path = os.path.join(outdir, "icp-actual.md")
    fit_path = os.path.join(outdir, "prospect-fit.md")
    crm = icp.get("crm") or {}
    with open(icp_path, "w", encoding="utf-8") as f:
        f.write("# YOUR ACTUAL ICP\n\n")
        f.write("Derived from %d customer companies, %d with sufficient public web evidence. "
                "Confidence: %s. Derived from: %s.\n\n"
                % (icp.get("n_customers", 0), icp.get("n_with_evidence", 0),
                   icp.get("icp_confidence", "unknown"), icp.get("derived_from", "all_customers")))
        f.write("| Trait | What the customers actually show |\n| --- | --- |\n")
        f.write("| Business line | %s |\n" % _shares(icp.get("category_share")))
        f.write("| Based in Romania | %s |\n" % _pct(icp.get("share_romania", 0)))
        f.write("| Hiring signals | %s |\n" % _pct(icp.get("share_hiring", 0)))
        f.write("| Size band | %s |\n" % (icp.get("modal_size_band") or "not observed"))
        f.write("| Tech stack | %s |\n" % _shares(icp.get("tech_share"), 5))
        f.write("| Site language | %s |\n" % _shares(icp.get("language_share"), 3))
        f.write("\n## From your CRM\n\n| Metric | Value |\n| --- | --- |\n")
        for label, key in (("Win rate", "win_rate"), ("Deal size", "deal_size"),
                           ("Sales cycle (days)", "sales_cycle"), ("Retention", "retention"),
                           ("Revenue", "revenue"), ("Industry", "industry"),
                           ("Country", "country"), ("Employees", "employees")):
            v = crm.get(key, "not in input")
            if isinstance(v, dict):
                v = _shares(v) if all(isinstance(x, float) for x in v.values()) else json.dumps(v, ensure_ascii=False)
            f.write("| %s | %s |\n" % (label, v))
        f.write("\n## Limitations\n\n")
        f.write("- Every trait above is read from the customers' own public websites, fetched at %s. "
                "Nothing is inferred from private data.\n" % meta.get("finished", ""))
        f.write("- Revenue, deal size, sales cycle and retention appear only if those columns exist "
                "in the customers file. `not in input` means the CRM did not provide them.\n")
        f.write("- Employee counts are only counted when a site states them in text; "
                "`not observed` means no site did.\n")
        if icp.get("n_with_evidence", 0) < 5:
            f.write("- Fewer than five customers had usable evidence, so this profile is weak. "
                    "Treat every fit score as low confidence.\n")
    with open(fit_path, "w", encoding="utf-8") as f:
        f.write("# Prospect fit\n\nScores are computed by the collector and are not adjusted by hand. "
                "ICP confidence: %s (n=%d).\n\n" % (icp.get("icp_confidence"), icp.get("n_with_evidence", 0)))
        f.write("| Rank | Company | Domain | Fit | Verdict | Points | Evidence | Retrieved at |\n")
        f.write("| ---: | --- | --- | ---: | --- | --- | --- | --- |\n")
        rank = 0
        insufficient = []
        for r in ranked:
            if r.get("fit") is None:
                insufficient.append(r)
                continue
            rank += 1
            pts = "; ".join("%s %d/%d (%s)" % (c["name"], c["points"], c["max"], c["because"])
                            for c in r.get("components", []))
            te = r.get("top_evidence") or {}
            f.write("| %d | %s | %s | %d | %s | %s | %s | %s |\n"
                    % (rank, r["company"], r["domain"], r["fit"], r["verdict"], pts,
                       te.get("url", "none"), te.get("retrieved_at", "none")))
        f.write("\n**%d prospects with fit 80 or more.**\n"
                % sum(1 for r in ranked if (r.get("fit") or 0) >= 80))
        f.write("\n## Insufficient evidence\n\n")
        if insufficient:
            for r in insufficient:
                f.write("- %s (%s): %s. Not ranked, no fit score assigned.\n"
                        % (r["company"], r["domain"], r.get("error") or "no usable page text"))
        else:
            f.write("None: every prospect returned a usable page.\n")
        ref = (refused or {}).get("prospects") or []
        ref_c = (refused or {}).get("customers") or []
        f.write("\n## Refused before any fetch\n\n")
        if ref or ref_c:
            for r in list(ref) + list(ref_c):
                f.write("- %s (%s): %s\n" % (r.get("company", "?"), r.get("input", "?"), r.get("reason", "?")))
        else:
            f.write("None.\n")
    return icp_path, fit_path

def main():
    ap = argparse.ArgumentParser(description="icp-validator collector")
    ap.add_argument("--customers")
    ap.add_argument("--prospects")
    ap.add_argument("--out", default="out")
    ap.add_argument("--max-customers", type=int, default=12)
    ap.add_argument("--max-prospects", type=int, default=12)
    ap.add_argument("--budget", type=float, default=20.0)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--offer", default="demo/input/offer.md")
    ap.add_argument("--discover-from", help="public list page (customers/sponsors/portfolio/directory) to source prospects from")
    ap.add_argument("--discover-limit", type=int, default=10)
    a = ap.parse_args()

    if a.selftest:
        try:
            return selftest()
        except AssertionError as e:
            print("SELFTEST FAILED: %s" % e)
            return 1
    if not a.customers or not (a.prospects or a.discover_from):
        ap.error("--customers and one of --prospects / --discover-from are required")

    started = utcnow()
    t0 = time.time()
    deadline = t0 + a.budget
    cust_rows, cust_ref = read_csv(a.customers, a.max_customers)
    if a.discover_from:
        found, dpage = discover(a.discover_from, a.discover_limit, a.out)
        if dpage.get("net_fail"):
            print('NO NETWORK: this run needs internet access. In Codex, click "Allow once" '
                  'on the network prompt and re-run the same command.')
            return 3
        if not found:
            print("DISCOVERY FOUND NOTHING on %s. Pass --prospects with a CSV instead." % a.discover_from)
            return 2
        pros_rows, pros_ref = read_csv(os.path.join(a.out, "discovered.csv"), a.max_prospects)
    else:
        pros_rows, pros_ref = read_csv(a.prospects, a.max_prospects)

    all_rows = [("customer", r) for r in cust_rows] + [("prospect", r) for r in pros_rows]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        results = list(ex.map(lambda kr: collect_one(kr[1], deadline), all_rows))

    # no-network detection: every first-wave request failed at the socket level, fast.
    elapsed = time.time() - t0
    net_fails = 0
    for c in results:
        pages = c.get("pages") or []
        if pages and pages[0].get("net_fail"):
            net_fails += 1
    if results and net_fails == len(results) and elapsed <= 3.0:
        print('NO NETWORK: this run needs internet access. In Codex, click "Allow once" '
              'on the network prompt and re-run the same command.')
        return 3

    customers = results[:len(cust_rows)]
    prospects = results[len(cust_rows):]
    strip_html(results)

    icp = derive_icp(customers, cust_rows)
    ranked = []
    for p in prospects:
        fit, comps, verdict = score(p, icp)
        item = {"company": p["company"], "domain": p["domain"], "fit": fit,
                "verdict": verdict, "components": comps,
                "top_evidence": ({"url": p["pages"][0].get("final_url") or p["pages"][0]["url"],
                                  "retrieved_at": p["pages"][0]["retrieved_at"]}
                                 if (p.get("pages") and p["pages"][0].get("http_status")) else None),
                "insufficient_evidence": p.get("insufficient_evidence", True),
                "error": p.get("error")}
        if icp["n_with_evidence"] < 5:
            item["fit_confidence"] = "low (ICP derived from n<5)"
        ranked.append(item)
    ranked.sort(key=lambda x: (x["fit"] is None, -(x["fit"] or 0), x["company"]))

    os.makedirs(a.out, exist_ok=True)
    ev_path = os.path.join(a.out, "evidence.json")
    fit_path = os.path.join(a.out, "fit.json")
    with open(ev_path, "w", encoding="utf-8") as f:
        json.dump({"meta": {"started": started, "finished": utcnow(), "budget_s": a.budget,
                            "version": VERSION, "python": sys.version.split()[0],
                            "elapsed_s": round(time.time() - t0, 2),
                            "input_sources": {"customers": a.customers, "prospects": a.prospects}},
                   "customers": customers, "prospects": prospects,
                   "refused": {"customers": cust_ref, "prospects": pros_ref}},
                  f, ensure_ascii=False, indent=2)
    with open(fit_path, "w", encoding="utf-8") as f:
        json.dump({"icp": icp, "prospects": ranked}, f, ensure_ascii=False, indent=2)

    by_domain = dict((c["domain"], c) for c in prospects)
    icp_md, fit_md = write_reports(icp, ranked,
                                   {"customers": cust_ref, "prospects": pros_ref}, a.out,
                                   {"finished": utcnow()})

    op_in = write_openers_input(icp, ranked, by_domain, a.offer, a.out)

    print("rank | company | domain | fit | verdict | top evidence")
    for i, r in enumerate(ranked, 1):
        te = r["top_evidence"]
        eviden = "%s (%s)" % (te["url"], te["retrieved_at"]) if te else (r["error"] or "no evidence")
        print("%-4d | %-24s | %-26s | %-4s | %-20s | %s"
              % (i, r["company"][:24], r["domain"][:26],
                 r["fit"] if r["fit"] is not None else "-", r["verdict"], eviden))
    print("ICP n=%d confidence=%s" % (icp["n_with_evidence"], icp["icp_confidence"]))
    print("%d prospects with fit >= 80" % sum(1 for r in ranked if (r["fit"] or 0) >= 80))
    print(ev_path)
    print(fit_path)
    print(icp_md)
    print(fit_md)
    print(op_in)
    return 0

if __name__ == "__main__":
    sys.exit(main())
