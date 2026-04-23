#!/usr/bin/env python3
"""
Mulk OLX — Interaktiv Telegram Bot (Wizard uslubi)
====================================================
Har bir filtr tanlanganidan keyin keyingisi avtomatik chiqadi.
"""

import json, re, ssl, time, hashlib, codecs, requests, threading, random
import urllib.request as ulr
from datetime import datetime, timedelta
from pathlib import Path

TOKEN   = "8669371925:AAF6uCLmZ_urgNfxS3iAMRvRNmrG_SAJuO0"
TG_BASE = f"https://api.telegram.org/bot{TOKEN}"

FILTERS_FILE = Path(__file__).parent / "user_filters.json"
SEEN_FILE    = Path(__file__).parent / "seen_ads.json"
CONFIG_FILE  = Path(__file__).parent / "config.json"
ID_FILE      = Path(__file__).parent / "id_counter.json"  # MUL-XXXX uchun

def next_mul_id():
    """Keyingi MUL-XXXX ID ni qaytaradi va saqlab qo'yadi."""
    data = json.loads(ID_FILE.read_text()) if ID_FILE.exists() else {"counter": 0}
    data["counter"] += 1
    ID_FILE.write_text(json.dumps(data))
    return f"MUL-{data['counter']:04d}"

def load_config():
    return json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}

# Toshkent tumanlari
TUMANLAR = [
    ("0",  "🌍 Barchasi"),
    ("1",  "Bektemir"),
    ("2",  "Chilonzor"),
    ("3",  "Mirobod"),
    ("4",  "Mirzo Ulug'bek"),
    ("5",  "Sergeli"),
    ("6",  "Shayxontohur"),
    ("7",  "Olmazor"),
    ("8",  "Uchtepa"),
    ("9",  "Yakkasaroy"),
    ("10", "Yunusobod"),
    ("11", "Yashnobod"),
    ("12", "Zangiota"),
]
TUMAN_MAP  = {code: name for code, name in TUMANLAR}

# Har bir tuman uchun OLX da ishlatiladigan barcha nom variantlari
TUMAN_SRCH = {
    "bektemir":       ["bektemir","бектемир","bektimir"],
    "chilonzor":      ["chilonzor","chilanзор","чиланзар","чиланзарский","чиланзорский","chilanзar","chilanzar","chilangar"],
    "mirobod":        ["mirobod","мирабад","мирабадский","мираобод","mirobod","mirabad"],
    "mirzo ulug'bek": ["mirzo ulug","мирзо улугбек","мирзо-улугбек","мирзо улуг","mirzo-ulugbek","mirzo_ulugbek","мирзоулугбек","mirzoulugbek","mirzo ulugbek"],
    "sergeli":        ["sergeli","сергели","сергелийский","sergeley"],
    "shayxontohur":   ["shayxontohur","шайхантахур","шайхонтохур","шайхантахурский","shaykhantakhur","шайхантахурск","shayxantaxur","shayxantohur"],
    "olmazor":        ["olmazor","алмазар","алмазарский","olmazar","almazor","almaзар"],
    "uchtepa":        ["uchtepa","учтепа","учтепинский","uchtepа"],
    "yakkasaroy":     ["yakkasaroy","яккасарай","яккасарайский","yakkasarai","yakkasaraj","яккасар"],
    "yunusobod":      ["yunusobod","юнусабад","yunusabad","юнусабадский","yunusobo","юнусоба","ю-13","ю13","ю 13","юнусабад-","yunusob","yunusobod"],
    "yashnobod":      ["yashnobod","яшнабад","яшнободский","яшнабадский","yashnobo"],
    "zangiota":       ["zangiota","зангиата","зангиатинский","zangiata"],
}

# Wizard qadamlari tartibi
WIZARD_STEPS = [
    "tuman", "narx", "kvadrat", "xona", "etaj", "etajnost", "bino", "remont", "kun"
]

# ──────────────────────────────────────────────
# MA'LUMOTLAR
# ──────────────────────────────────────────────

def load_filters():
    return json.loads(FILTERS_FILE.read_text()) if FILTERS_FILE.exists() else {}

def save_filters(d):
    FILTERS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2))

def get_uf(uid):
    return load_filters().get(str(uid), {
        "tuman":"","narx_dan":None,"narx_gacha":None,
        "kvadrat_dan":None,"kvadrat_gacha":None,
        "xona_dan":None,"xona_gacha":None,
        "etaj_dan":None,"etaj_gacha":None,
        "etajnost_dan":None,"etajnost_gacha":None,
        "bino_turi":"barchasi","remont":"barchasi",
        "kun_soni":7,"faqat_egasidan":True,
    })

def set_uf(uid, key, val):
    d = load_filters()
    uid = str(uid)
    if uid not in d: d[uid] = get_uf(uid)
    d[uid][key] = val
    save_filters(d)

def load_seen():
    return set(json.loads(SEEN_FILE.read_text())) if SEEN_FILE.exists() else set()

def save_seen(s):
    SEEN_FILE.write_text(json.dumps(list(s)))

user_states    = {}  # {uid: step_name}
tuman_pending  = {}  # {uid: [tanlangan tuman nomlari]}
wizard_active  = {}  # {uid: True}
wizard_tokens  = {}  # {uid: "123456"} — har sessiya uchun noyob token

# ──────────────────────────────────────────────
# TELEGRAM
# ──────────────────────────────────────────────

def tg(method, **kw):
    try:
        r = requests.post(f"{TG_BASE}/{method}", timeout=30, **kw)
        d = r.json()
        if not d.get("ok"):
            print(f"⚠ TG {method}: {d.get('description','?')}")
        return d
    except Exception as e:
        print(f"⚠ TG {method}: {e}"); return {}

def send(chat_id, text, kb=None):
    p = {"chat_id":chat_id,"text":str(text)[:4090],"parse_mode":"HTML"}
    if kb: p["reply_markup"] = json.dumps(kb)
    return tg("sendMessage", json=p)

def edit(chat_id, mid, text, kb=None):
    p = {"chat_id":chat_id,"message_id":mid,"text":str(text)[:4090],"parse_mode":"HTML"}
    if kb: p["reply_markup"] = json.dumps(kb)
    tg("editMessageText", json=p)

def answer_cb(cbid, text=""):
    tg("answerCallbackQuery", json={"callback_query_id":cbid,"text":text})

def send_media(chat_id, photos, caption):
    cap = str(caption)[:1020]
    if photos:
        if len(photos)==1:
            r = tg("sendPhoto", json={"chat_id":chat_id,"photo":photos[0],"caption":cap,"parse_mode":"HTML"})
            if r.get("ok"): return
        else:
            media = [{"type":"photo","media":p,"caption":cap if i==0 else "","parse_mode":"HTML"} for i,p in enumerate(photos[:8])]
            r = tg("sendMediaGroup", json={"chat_id":chat_id,"media":media})
            if r.get("ok"): return
    send(chat_id, caption)

# ──────────────────────────────────────────────
# KLAVIATURALAR
# ──────────────────────────────────────────────

def main_kb(auto_on=None):
    cfg = load_config()
    if auto_on is None:
        auto_on = cfg.get("auto_search", True)
    auto_txt = "🟢 Auto: ON  ▶ O'chirish" if auto_on else "🔴 Auto: OFF ▶ Yoqish"
    interval  = cfg.get("auto_interval_min", 60)
    return {"inline_keyboard":[
        [{"text":"🔍 Qidirish",                    "callback_data":"search"}],
        [{"text":"⚙️ Filtrlarni sozlash",           "callback_data":"wizard_start"}],
        [{"text":"📋 Joriy filtrlar",               "callback_data":"show_filters"}],
        [{"text":"📊 Kunlik statistika",            "callback_data":"stats"}],
        [{"text":auto_txt,                          "callback_data":"toggle_auto"}],
        [{"text":f"⏱ Interval: {interval} daqiqa", "callback_data":"set_interval"}],
        [{"text":"🗑 Filtrlarni tozalash",          "callback_data":"reset"}],
    ]}

def tuman_kb_token(selected=None, token="x"):
    """Tuman klaviaturasi — 'Keyingisi' TEPA da, har doim ko'rinadi."""
    selected = selected or []
    sel_set  = {s.lower() for s in selected}
    rows2    = []

    # ➡️ Keyingisi — ENG TEPADA (har doim birinchi ko'rinadi)
    count = len(sel_set)
    done_txt = f"➡️ Keyingisi ({count} ta tanlandi) →" if count else "➡️ Keyingisi (Barchasi) →"
    rows2.append([{"text": done_txt, "callback_data": f"wt_{token}_done"}])

    # Tuman tugmalari — 2 ustunli
    singles = []
    for code, name in TUMANLAR:
        if code == "0": continue
        mark = "☑️ " if name.lower() in sel_set else ""
        singles.append({"text": f"{mark}{name}", "callback_data": f"wt_{token}_{code}"})
    for i in range(0, len(singles), 2):
        rows2.append(singles[i:i+2])

    rows2.append([{"text": "🗑 Barchasi (tozalash)", "callback_data": f"wt_{token}_0"}])
    return {"inline_keyboard": rows2}

def confirm_kb(step):
    return {"inline_keyboard": [[{"text": "✅ Tasdiqlash →", "callback_data": f"ok_{step}"}]]}

def xona_kb():
    return {"inline_keyboard":[
        [{"text":"🌍 Barchasi","callback_data":"wz_xona_0_0"}],
        [{"text":"1 xona","callback_data":"wz_xona_1_1"},{"text":"2 xona","callback_data":"wz_xona_2_2"}],
        [{"text":"3 xona","callback_data":"wz_xona_3_3"},{"text":"4 xona","callback_data":"wz_xona_4_4"}],
        [{"text":"5+ xona","callback_data":"wz_xona_5_99"}],
    ]}

def bino_kb():
    return {"inline_keyboard":[
        [{"text":"🌍 Barchasi",    "callback_data":"wz_bino_barchasi"}],
        [{"text":"🏗 Navastroyka", "callback_data":"wz_bino_navastroyka"}],
        [{"text":"🏠 Vtorichka",   "callback_data":"wz_bino_vtorichka"}],
    ]}

def remont_kb():
    return {"inline_keyboard":[
        [{"text":"🌍 Barchasi",  "callback_data":"wz_remont_barchasi"}],
        [{"text":"💎 Premium",   "callback_data":"wz_remont_premium"}],
        [{"text":"✅ Standart",  "callback_data":"wz_remont_standart"}],
        [{"text":"🔧 Minimal",   "callback_data":"wz_remont_minimal"}],
    ]}

def kun_kb():
    return {"inline_keyboard":[
        [{"text":"1 kun","callback_data":"wz_kun_1"},{"text":"3 kun","callback_data":"wz_kun_3"}],
        [{"text":"7 kun","callback_data":"wz_kun_7"},{"text":"14 kun","callback_data":"wz_kun_14"}],
        [{"text":"30 kun","callback_data":"wz_kun_30"}],
    ]}

def search_kb():
    return {"inline_keyboard":[
        [{"text":"🔍 Qidirish!","callback_data":"search"}],
        [{"text":"◀️ Bosh menu", "callback_data":"main_menu"}],
    ]}

# ──────────────────────────────────────────────
# WIZARD — KEYINGI QADAM
# ──────────────────────────────────────────────

def show_step(chat_id, step, mid=None):
    """Wizard ning keyingi qadamini ko'rsatadi."""
    def do(text, kb=None):
        if mid: edit(chat_id, mid, text, kb)
        else:   send(chat_id, text, kb)

    if step == "tuman":
        uid = str(chat_id)
        token = wizard_tokens.get(uid, "x")
        sel   = tuman_pending.get(uid, [])
        do("1️⃣ <b>Tumanni tanlang:</b>\n"
           "<i>Keraklilarini bosing, so'ng ➡️ Keyingisi bosing</i>",
           tuman_kb_token(sel, token))

    elif step == "narx":
        user_states[str(chat_id)] = "await_narx"
        do("2️⃣ <b>Narx oralig'i (USD):</b>\n\n"
           "Misol: <code>50000 150000</code>\n"
           "Cheksiz: <code>0</code>")

    elif step == "kvadrat":
        user_states[str(chat_id)] = "await_kvadrat"
        do("3️⃣ <b>Kvadrat metr (m²):</b>\n\n"
           "Misol: <code>50 120</code>\n"
           "Cheksiz: <code>0</code>")

    elif step == "xona":
        do("4️⃣ <b>Xona soni:</b>", xona_kb())

    elif step == "etaj":
        user_states[str(chat_id)] = "await_etaj"
        do("5️⃣ <b>Etaj oralig'i:</b>\n\n"
           "Misol: <code>2 8</code>\n"
           "Cheksiz: <code>0</code>")

    elif step == "etajnost":
        user_states[str(chat_id)] = "await_etajnost"
        do("6️⃣ <b>Binoning etajlari:</b>\n\n"
           "Misol: <code>5 16</code>\n"
           "Cheksiz: <code>0</code>")

    elif step == "bino":
        do("7️⃣ <b>Bino turi:</b>", bino_kb())

    elif step == "remont":
        do("8️⃣ <b>Remont holati:</b>", remont_kb())

    elif step == "kun":
        do("9️⃣ <b>Necha kunlik e'lonlar:</b>", kun_kb())

    elif step == "done":
        f = get_uf(str(chat_id))
        do(f"✅ <b>Filtrlar saqlandi!</b>\n\n{filters_text(f)}", search_kb())

def next_step(chat_id, current_step, mid=None):
    """Joriy qadamdan keyingi qadamga o'tadi."""
    idx = WIZARD_STEPS.index(current_step) if current_step in WIZARD_STEPS else -1
    next_idx = idx + 1
    if next_idx < len(WIZARD_STEPS):
        show_step(chat_id, WIZARD_STEPS[next_idx], mid)
    else:
        show_step(chat_id, "done", mid)

# ──────────────────────────────────────────────
# FILTRLAR MATNI
# ──────────────────────────────────────────────

def filters_text(f):
    def rng(a, b, pref="", suf=""):
        if a and b: return f"{pref}{a} – {pref}{b}{suf}"
        if a: return f"{pref}{a}+ {suf}"
        if b: return f"– {pref}{b}{suf}"
        return "Barchasi"
    return (
        "📋 <b>Filtrlar:</b>\n"
        f"{'━'*24}\n"
        f"🗺 Tuman:     {f.get('tuman').replace(',',', ').title() if f.get('tuman') else 'Barchasi'}\n"
        f"💰 Narx:      {rng(f.get('narx_dan'), f.get('narx_gacha'), '$')}\n"
        f"📐 Kvadrat:   {rng(f.get('kvadrat_dan'), f.get('kvadrat_gacha'), '', ' m²')}\n"
        f"🚪 Xona:      {rng(f.get('xona_dan'), f.get('xona_gacha'))}\n"
        f"🏢 Etaj:      {rng(f.get('etaj_dan'), f.get('etaj_gacha'))}\n"
        f"🏗 Etajnost:  {rng(f.get('etajnost_dan'), f.get('etajnost_gacha'))}\n"
        f"🏛 Bino:      {f.get('bino_turi','barchasi')}\n"
        f"🔨 Remont:    {f.get('remont','barchasi')}\n"
        f"📅 Kun soni:  {f.get('kun_soni',7)} kun\n"
        f"👤 Egasidan:  ✅ Ha\n"
        f"{'━'*24}"
    )

# ──────────────────────────────────────────────
# OLX SCRAPING
# ──────────────────────────────────────────────

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode    = ssl.CERT_NONE

HDR = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,uz;q=0.8",
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer":         "https://www.olx.uz/",
}

def fetch(url):
    for i in range(3):
        try:
            req = ulr.Request(url, headers=HDR)
            with ulr.urlopen(req, timeout=20, context=SSL_CTX) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"  Urinish {i+1}: {e}")
            time.sleep(2)
    return None

def parse_state(html):
    # Escaped belgilarni to'g'ri qamrab oluvchi regex
    m = re.search(r'window\.__PRERENDERED_STATE__\s*=\s*"((?:[^"\\]|\\.)*)"', html)
    if not m:
        print("  ⚠ __PRERENDERED_STATE__ topilmadi!")
        return {}
    raw = m.group(1)
    print(f"  __PRERENDERED_STATE__ topildi, uzunlik={len(raw)}")
    # Eng ishonchli usul: JSON string sifatida decode qilish
    try:
        unescaped = json.loads('"' + raw + '"')
        result = json.loads(unescaped)
        print(f"  ✅ Dekodlash (json.loads x2) muvaffaqiyatli")
        return result
    except Exception as e:
        print(f"  ✗ json.loads x2: {e}")
    # Zaxira: codecs
    for name, dec in [
        ("latin1", lambda r: codecs.decode(r, 'unicode_escape').encode('latin-1').decode('utf-8')),
        ("unicode", lambda r: r.encode().decode('unicode_escape')),
    ]:
        try:
            result = json.loads(dec(raw))
            print(f"  ✅ Dekodlash ({name}) muvaffaqiyatli")
            return result
        except Exception as e:
            print(f"  ✗ {name}: {e}")
    return {}

def build_url(page=1):
    # OLX.uz — barcha kvartira e'lonlari (private filter Python darajasida)
    p = ["search[order]=created_at:desc"]
    if page > 1:
        p.append(f"page={page}")
    return "https://www.olx.uz/nedvizhimost/kvartiry/?" + "&".join(p)

UZS_RATE      = 12800   # zaxira kurs (CBU dan olinmasa ishlatiladi)
_uzs_rate_date = None   # oxirgi yangilanish sanasi

def get_uzs_rate():
    """Markaziy bank (CBU) dan joriy USD kursini oladi. Kuniga 1 marta yangilanadi."""
    global UZS_RATE, _uzs_rate_date
    today = datetime.now().strftime("%Y-%m-%d")
    if _uzs_rate_date == today:
        return UZS_RATE
    try:
        r = requests.get(
            "https://cbu.uz/oz/arkhiv-kursov-valyut/json/USD/",
            timeout=10
        )
        data = r.json()
        if data and isinstance(data, list):
            rate = float(data[0].get("Rate", UZS_RATE))
            UZS_RATE       = rate
            _uzs_rate_date = today
            print(f"💱 CBU dollar kursi: {rate:.2f} UZS/USD ({today})")
    except Exception as e:
        print(f"⚠ CBU kurs olishda xato: {e} — avvalgi kurs {UZS_RATE} ishlatiladi")
    return UZS_RATE

def _price_info(raw_ad):
    """(uzs_val, usd_val, is_usd) qaytaradi"""
    price = raw_ad.get("price", {}) or {}
    reg   = price.get("regularPrice", {}) or {}
    dv    = price.get("displayValue", "") or ""
    cur   = str(reg.get("currency", "")).upper()
    try:   val = float(reg.get("value") or 0)
    except: val = 0.0

    # 1. regularPrice.currency = USD → narx to'g'ridan-to'g'ri USD
    if "USD" in cur or "UE" in cur:
        return 0, val, True

    # 2. displayValue da "у.е." yoki "$" bor → narx USD da yozilgan
    if any(x in dv for x in ["USD", "у.е", "у.е.", "$"]):
        # BARCHA raqamlarni birlashtirish: "50 000 у.е." → "50000" → 50000.0
        nums_str = re.sub(r'[^\d]', '', dv)
        try:
            v = float(nums_str)
            # Mantiqiy tekshiruv: USD narx 500 dan 10_000_000 gacha bo'lishi kerak
            if 500 < v < 10_000_000:
                return 0, v, True
        except: pass

    # 3. regularPrice.value bor → bu UZS, CBU kursi bilan USD ga aylantirish
    if val > 0:
        rate = get_uzs_rate()
        # Kichik son (< 50_000) USD bo'lishi mumkin (OLX ba'zan shunday saqlaydi)
        if val < 50_000:
            return 0, val, True   # USD sifatida qabul qilamiz
        usd = val / rate
        return int(val), usd, False

    return 0, 0, False

def parse_price(raw_ad):
    if not raw_ad.get("price"): return "Narx ko'rsatilmagan"
    if raw_ad["price"].get("free"): return "Bepul"
    uzs, usd, is_usd = _price_info(raw_ad)
    if usd > 0:
        # Har doim y.e. (USD) da ko'rsatamiz
        usd_str = f"${int(usd):,}".replace(",", " ") + " y.e."
        if is_usd:
            return usd_str          # Asl narx USD da
        else:
            rate = get_uzs_rate()
            return f"≈{usd_str} (kurs: {int(rate):,})"  # UZS dan konvertatsiya
    dv = (raw_ad.get("price",{}) or {}).get("displayValue","") or ""
    return dv if dv else "Narx ko'rsatilmagan"

def extract_price_usd(raw_ad):
    """Filtrlash uchun USD raqamini qaytaradi.
    Faqat ASAL narx USD da bo'lsa qaytaradi (UZS konvertatsiya emas)."""
    _, usd, is_usd = _price_info(raw_ad)
    # Faqat OLX da y.e. deb ko'rsatilgan narxlar
    if usd > 0 and is_usd:
        return usd
    # UZS narxli e'lonlar uchun ham CBU kursi bilan qaytaramiz
    if usd > 0:
        return usd
    return None

def parse_param(params, key):
    for p in params:
        if p.get("key") == key:
            v = p.get("value", {})
            return v.get("key", v.get("label", str(v))) if isinstance(v,dict) else str(v)
    return None

def get_phone(ad):
    for src in [ad.get("contact",{}).get("name",""), ad.get("user",{}).get("name","")]:
        if src and re.search(r'\d{7,}', re.sub(r'\s','',src)):
            d = re.sub(r'\D','',src)
            if len(d) >= 9:
                if not d.startswith("998"): d = "998" + d[-9:]
                return f"+{d}"
    return ""

def get_photos(ad):
    result = []
    for p in ad.get("photos",[])[:8]:
        if isinstance(p,str):
            result.append(re.sub(r';s=\d+x\d+',';s=960x1280',p))
        elif isinstance(p,dict):
            u = p.get("link","")
            if "{width}" in u: u = u.replace("{width}","960")
            if u: result.append(u)
    return result

def parse_ad(raw):
    params = raw.get("params",[])
    loc    = raw.get("location",{}) or {}
    up     = raw.get("urlPath", raw.get("url",""))
    url    = f"https://www.olx.uz{up}" if up.startswith("/") else up
    # lastRefreshTime — boost/yangilash vaqti (muhimroq), createdTime zaxira
    ct     = raw.get("lastRefreshTime","") or raw.get("createdTime","") or ""
    try:    dt = datetime.fromisoformat(ct.replace("Z","+00:00")).replace(tzinfo=None)
    except: dt = None
    desc_raw = raw.get("description","") or ""
    desc = re.sub(r'<br\s*/?>', '\n', desc_raw, flags=re.IGNORECASE)
    desc = re.sub(r'<[^>]+>','',desc).strip()[:300]
    city = (loc.get("cityNormalizedName") or loc.get("city","") or "").lower()
    reg  = (loc.get("regionNormalizedName") or loc.get("region","") or "").lower()
    city_name = loc.get("cityName") or loc.get("city","") or ""
    reg_name  = loc.get("regionName") or loc.get("region","") or ""
    # Tuman: subregionName yoki subregion maydoni (OLX.uz da district)
    sub_name  = (loc.get("subRegionName") or loc.get("subregionName") or
                 loc.get("districtName") or loc.get("district") or
                 loc.get("cityDistrict") or "")
    olx_raw_id = str(raw.get("id",""))
    olx_id     = f"OLX-{olx_raw_id}" if olx_raw_id else hashlib.md5(url.encode()).hexdigest()[:10]
    # Area — har xil param kalitlarni sinash
    area = (parse_param(params,"m") or parse_param(params,"total_area") or
            parse_param(params,"square") or parse_param(params,"area"))
    return {
        "id":        olx_id,
        "olx_id":    olx_id,
        "title":     raw.get("title","—"),
        "desc":      desc,
        "price":     parse_price(raw),
        "price_usd": extract_price_usd(raw),
        "city":      city,
        "region":    reg,
        "subregion": sub_name.lower(),
        "location":  f"{city_name} {sub_name} {reg_name}".strip() or city or reg,
        "url_slug":  up.lower(),   # /nedvizhimost/.../mirzo-ulugbek/ — tuman uchun
        "date":      dt,
        "date_str":  ct[:10] if ct else "?",
        "url":       url,
        "phone":     get_phone(raw),
        "photos":    get_photos(raw),
        "is_biz":    raw.get("isBusiness", False),
        "is_usd":    _price_info(raw)[2],   # OLX da asl narx USD da bo'lsa True
        "rooms":     parse_param(params,"rooms"),
        "floor":     parse_param(params,"floor"),
        "floors":    parse_param(params,"building_floors"),
        "area":      area,
        "market":    parse_param(params,"type_of_market"),
        "cond":      parse_param(params,"builttype"),
    }

def num_ok(val, lo, hi):
    if not val: return True
    try:
        n = float(re.sub(r'[^\d.]','',str(val)))
        if lo and n < lo: return False
        if hi and n > hi: return False
    except: pass
    return True

ARENDA_WORDS = [
    "arenda","ijara","аренда","сдаётся","сдам","сдаю",
    "снять","посуточно","sutkalik","kunlik","oylik"
]

def matches(ad, f):
    # Arenda e'lonlarini chiqarib tashlash
    title_low = ad["title"].lower()
    desc_low  = (ad.get("desc") or "").lower()
    if any(w in title_low for w in ARENDA_WORDS):
        return False
    # Tavsifda ham arenda so'zlarini tekshiramiz
    if any(w in desc_low for w in ["arenda","ijara","аренда","сдаётся","сдам","сдаю"]):
        return False

    # Faqat egasidan
    if f.get("faqat_egasidan", True) and ad["is_biz"]:
        return False

    # Shahar: Toshkent (agar city/region bo'sh bo'lsa, o'tkazib yuboramiz — ba'zi e'lonlarda bo'lmaydi)
    city_str = (ad["city"] + " " + ad["region"] + " " + ad.get("location","")).lower()
    if city_str.strip():
        has_tashkent = any(x in city_str for x in ["tashkent","toshkent","ташкент","тошкент"])
        if not has_tashkent:
            return False

    # Tuman — bir yoki bir nechta (vergul bilan ajratilgan)
    tuman_raw = (f.get("tuman") or "").strip()
    if tuman_raw and tuman_raw.lower() != "barchasi":
        tumanlar = [t.strip() for t in tuman_raw.split(",") if t.strip()]
        # URL slug, subregion va boshqa barcha maydonlarni ham tekshiramiz
        text = " ".join([
            ad.get("title","") or "",
            ad.get("desc","") or "",
            ad.get("location","") or "",
            ad.get("city","") or "",
            ad.get("region","") or "",
            ad.get("subregion","") or "",
            ad.get("url_slug","") or "",  # /mirzo-ulugbek/ kabi URL qismi
        ]).lower()
        # Kamida bitta tuman mos kelsa o'tkazamiz
        matched = False
        for tuman in tumanlar:
            kws = TUMAN_SRCH.get(tuman.lower(), [tuman])
            if any(k.lower() in text for k in kws):
                matched = True
                break
        if not matched:
            return False

    # Sana — sana mavjud bo'lsa tekshiramiz
    if ad["date"]:
        if ad["date"] < datetime.now() - timedelta(days=f.get("kun_soni", 7)):
            return False

    # Narx filtri (USD da, faqat agar narx ma'lum bo'lsa)
    usd = ad.get("price_usd")
    if usd is not None:
        nd, ng = f.get("narx_dan"), f.get("narx_gacha")
        if nd and usd < nd: return False
        if ng and usd > ng: return False

    # Raqamli filtrlar
    if not num_ok(ad["rooms"],  f.get("xona_dan"),     f.get("xona_gacha")):     return False
    if not num_ok(ad["area"],   f.get("kvadrat_dan"),  f.get("kvadrat_gacha")):  return False
    if not num_ok(ad["floor"],  f.get("etaj_dan"),     f.get("etaj_gacha")):     return False
    if not num_ok(ad["floors"], f.get("etajnost_dan"), f.get("etajnost_gacha")): return False

    # Bino turi — OLX field + sarlavhada ham qidirish
    bino = (f.get("bino_turi") or "barchasi").lower()
    if bino != "barchasi":
        all_text = " ".join([
            ad.get("market","") or "",
            ad.get("title","") or "",
            ad.get("desc","") or "",
        ]).lower()
        if bino == "navastroyka":
            nav_kw = ["new","yangi","новостр","первичн","primary","novostro",
                      "navastro","yangi qur","новый дом","новостройка","сдан"]
            if ad["market"] and not any(x in all_text for x in nav_kw):
                return False
        if bino == "vtorichka":
            vtor_kw = ["second","vtor","втор","вторичн","secondary","eski","б/у","бу "]
            if ad["market"] and not any(x in all_text for x in vtor_kw):
                return False

    # Remont — OLX field + sarlavhada ham qidirish
    remont = (f.get("remont") or "barchasi").lower()
    if remont != "barchasi":
        rem_text = " ".join([
            ad.get("cond","") or "",
            ad.get("title","") or "",
            ad.get("desc","") or "",
        ]).lower()
        # Agar OLX da remont ma'lumoti umuman yo'q bo'lsa — o'tkazib yuboramiz
        if ad["cond"]:
            if remont == "premium" and not any(x in rem_text for x in [
                "euro","евро","premium","люкс","lux","евроремонт","отличн","хорош","yaxshi"
            ]): return False
            if remont == "standart" and not any(x in rem_text for x in [
                "good","хорош","standart","норм","средн","normal","oddiy","обычн"
            ]): return False
            if remont == "minimal" and not any(x in rem_text for x in [
                "cosm","косм","minimal","требует","без ремонт","talab","eski","старый","черн"
            ]): return False

    return True

def why_filtered(ad, f, cutoff):
    """E'lon nima sababdan filtrlangani haqida qisqa sabab qaytaradi."""
    t = ad["title"].lower()
    d = (ad.get("desc") or "").lower()
    if any(w in t for w in ARENDA_WORDS) or any(w in d for w in ["arenda","ijara","аренда","сдаётся","сдам","сдаю"]):
        return "arenda"
    if ad["is_biz"] and f.get("faqat_egasidan", True):
        return "agentlik"
    city_str = (ad["city"] + " " + ad["region"] + " " + ad.get("location","")).lower()
    if city_str.strip():
        if not any(x in city_str for x in ["tashkent","toshkent","ташкент","тошкент"]):
            return "shahar≠toshkent"
    tuman_raw = (f.get("tuman") or "").strip()
    if tuman_raw and tuman_raw.lower() != "barchasi":
        tumanlar = [t2.strip() for t2 in tuman_raw.split(",") if t2.strip()]
        text = " ".join([
            ad.get("title","") or "", ad.get("desc","") or "",
            ad.get("location","") or "", ad.get("city","") or "",
            ad.get("region","") or "", ad.get("subregion","") or "",
            ad.get("url_slug","") or "",
        ]).lower()
        ok = False
        for tuman in tumanlar:
            kws = TUMAN_SRCH.get(tuman.lower(), [tuman])
            if any(k.lower() in text for k in kws):
                ok = True; break
        if not ok:
            return f"tuman≠{tuman_raw[:20]}"
    if ad["date"] and ad["date"] < cutoff:
        return f"eski({ad['date_str']})"
    usd = ad.get("price_usd")
    if usd is not None:
        nd, ng = f.get("narx_dan"), f.get("narx_gacha")
        if nd and usd < nd: return f"narx<{nd}(usd={int(usd)})"
        if ng and usd > ng: return f"narx>{ng}(usd={int(usd)})"
    if not num_ok(ad["rooms"],  f.get("xona_dan"),     f.get("xona_gacha")):     return f"xona={ad['rooms']}"
    if not num_ok(ad["area"],   f.get("kvadrat_dan"),  f.get("kvadrat_gacha")):  return f"area={ad['area']}"
    if not num_ok(ad["floor"],  f.get("etaj_dan"),     f.get("etaj_gacha")):     return f"etaj={ad['floor']}"
    if not num_ok(ad["floors"], f.get("etajnost_dan"), f.get("etajnost_gacha")): return f"etajnost={ad['floors']}"
    return "boshqa_filtr"

def do_search(uid, f, _kun_override=None):
    seen     = load_seen()
    results  = []
    kun_soni = _kun_override or f.get("kun_soni", 7)
    cutoff   = datetime.now() - timedelta(days=kun_soni)
    max_page = 20
    print(f"  🔍 Qidiruv: oxirgi {kun_soni} kun")
    # Filter stats
    stats = {"jami":0, "korsgan":0, "arenda":0, "agentlik":0,
             "shahar":0, "tuman":0, "eski":0, "narx":0, "raqam":0}

    for page in range(1, max_page + 1):
        url  = build_url(page)
        html = fetch(url)
        if not html:
            print(f"  Sahifa {page}: yuklanmadi, to'xtatilmoqda")
            break
        print(f"  Sahifa {page}: HTML {len(html)} bayt")

        state = parse_state(html)
        if not state:
            print(f"  Sahifa {page}: ⚠ __PRERENDERED_STATE__ topilmadi")
            break

        # Turli yo'llarni sinash
        raw_ads = []
        for path in [
            ["listing","listing","ads"],
            ["listing","ads"],
            ["ads"],
        ]:
            node = state
            for k in path:
                node = node.get(k, {}) if isinstance(node, dict) else {}
            if isinstance(node, list) and node:
                raw_ads = node
                print(f"  ✅ Yo'l: {' → '.join(path)} → {len(raw_ads)} ta e'lon")
                break

        print(f"  Sahifa {page}: {len(raw_ads)} ta e'lon olindi")

        if not raw_ads:
            print("  → E'lonlar topilmadi, to'xtatilmoqda")
            break

        page_old  = 0
        page_match = 0
        for raw in raw_ads:
            stats["jami"] += 1
            ad = parse_ad(raw)
            if ad["id"] in seen:
                continue
            stats["korsgan"] += 1
            ok = matches(ad, f)
            if not ok:
                why = why_filtered(ad, f, cutoff)
                # Stats guruhlash
                if "arenda"    in why: stats["arenda"]   += 1
                elif "agentlik" in why: stats["agentlik"] += 1
                elif "shahar"   in why: stats["shahar"]   += 1
                elif "tuman"    in why: stats["tuman"]    += 1
                elif "eski"     in why: stats["eski"] += 1; page_old += 1
                elif "narx"     in why: stats["narx"]     += 1
                else:                  stats["raqam"]    += 1
                print(f"    [-] {ad['title'][:45]}  [{why}]  url={ad['url_slug'][-40:]}")
            else:
                print(f"    [+] {ad['title'][:45]}  narx={ad['price']}  tuman={ad.get('subregion','')} slug={ad.get('url_slug','')[-30:]}")
                results.append(ad)
                page_match += 1

        print(f"  → Sahifa {page}: {page_match} mos | {page_old} eski")
        # Agar sahifaning 80%+ i eski bo'lsa, keyingi sahifada yangi e'lon yo'q
        if raw_ads and page_old / len(raw_ads) > 0.80:
            print(f"  → Ko'p eski e'lonlar, qidirish to'xtatilmoqda")
            break
        time.sleep(1.5)

    # Filter statistikasini chiqarish
    print(f"\n📊 Filter statistika: {stats}")

    # Agar natija kam bo'lsa — kun_soni ni avtomatik kengaytirish
    if not results and not _kun_override:
        for wider_days in [15, 30]:
            if wider_days > kun_soni:
                print(f"  📅 Natija yo'q → {wider_days} kunga kengaytiramiz...")
                return do_search(uid, f, _kun_override=wider_days)

    return results

# ──────────────────────────────────────────────
# AMOCRM INTEGRATSIYA
# ──────────────────────────────────────────────

def _num(val):
    """Qiymatdan raqam ajratish"""
    try: return float(re.sub(r'[^\d.]', '', str(val or "")))
    except: return None

def amocrm_lead_exists(base, headers, olx_url):
    """AmoCRM da bu OLX URL bilan lead allaqachon bormi? Duplicate oldini olish."""
    try:
        r = requests.get(f"{base}/leads",
                         params={"query": olx_url, "limit": 1},
                         headers=headers, timeout=10)
        if r.status_code == 200:
            leads = r.json().get("_embedded", {}).get("leads", [])
            if leads:
                print(f"  ⏩ AmoCRM: bu e'lon allaqachon bor (Lead #{leads[0]['id']}), o'tkazildi")
                return True
    except Exception as e:
        print(f"  ⚠ AmoCRM duplicate tekshiruv: {e}")
    return False

def push_to_amocrm(ad):
    """E'lonni AmoCRM ga lead + kontakt sifatida yuboradi."""
    cfg    = load_config()
    domain = (cfg.get("amocrm_domain") or "").strip()
    token  = (cfg.get("amocrm_token")  or "").strip()
    if not domain or not token:
        return False

    base    = f"https://{domain}/api/v4"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ── Duplicate tekshiruv — qayta yuborilmasin ──
    if amocrm_lead_exists(base, headers, ad["url"]):
        return True  # Allaqachon bor, lekin xato emas

    # ── Maxsus maydonlar (custom fields) ─────
    # ID lar amocrm_setup.py dan olindi
    cfields = []

    # Туман (ID: 1286101, textarea)
    loc = ad.get("location","") or ad.get("city","") or ""
    if loc:
        cfields.append({"field_id": 1286101, "values": [{"value": loc}]})

    # Хона/Сотих (ID: 1286103, textarea) — "3 xona | 80 m²"
    xona_sotix = []
    if ad.get("rooms"): xona_sotix.append(f"{ad['rooms']} xona")
    if ad.get("area"):  xona_sotix.append(f"{ad['area']} m²")
    if xona_sotix:
        cfields.append({"field_id": 1286103, "values": [{"value": " | ".join(xona_sotix)}]})

    # Площадь м² (ID: 1460576, numeric)
    area_n = _num(ad.get("area"))
    if area_n: cfields.append({"field_id": 1460576, "values": [{"value": area_n}]})

    # Этаж (ID: 1460716, numeric)
    floor_n = _num(ad.get("floor"))
    if floor_n: cfields.append({"field_id": 1460716, "values": [{"value": floor_n}]})

    # Этажность (ID: 1460802, numeric)
    floors_n = _num(ad.get("floors"))
    if floors_n: cfields.append({"field_id": 1460802, "values": [{"value": floors_n}]})

    # Кол-во комнат (ID: 1460828, numeric)
    rooms_n = _num(ad.get("rooms"))
    if rooms_n: cfields.append({"field_id": 1460828, "values": [{"value": rooms_n}]})

    # OLX havolasi (ID: 1615735, text)
    cfields.append({"field_id": 1615735, "values": [{"value": ad["url"]}]})

    # Ориентир (ID: 1573071, text) — joylashuv
    if loc: cfields.append({"field_id": 1573071, "values": [{"value": loc}]})

    # ── 1. Lead yaratish ──────────────────────
    price_val = int(ad.get("price_usd") or 0)
    mul_id    = ad.get("mul_id") or ad.get("olx_id","")
    lead_name = f"{mul_id} | {ad['title']}"[:255]
    lead_body = [{
        "name":        lead_name,
        "price":       price_val,
        "pipeline_id": cfg.get("amocrm_pipeline_id") or 10512362,
        "status_id":   cfg.get("amocrm_status_id")   or 84329458,
        "custom_fields_values": cfields,
    }]

    try:
        r = requests.post(f"{base}/leads", json=lead_body, headers=headers, timeout=15)
        if r.status_code not in (200, 201):
            print(f"  ⚠ AmoCRM lead xato {r.status_code}: {r.text[:150]}")
            return False
        lead_id = r.json()["_embedded"]["leads"][0]["id"]
        print(f"  ✅ AmoCRM: Lead #{lead_id} → Дети bosqichi")
    except Exception as e:
        print(f"  ⚠ AmoCRM lead: {e}"); return False

    # ── 2. Kontakt + telefon ──────────────────
    if ad.get("phone"):
        try:
            cb = [{"name": "OLX egasi", "custom_fields_values": [{
                "field_code": "PHONE",
                "values": [{"value": ad["phone"], "enum_code": "MOB"}]
            }]}]
            rc = requests.post(f"{base}/contacts", json=cb, headers=headers, timeout=15)
            if rc.status_code in (200, 201):
                cid = rc.json()["_embedded"]["contacts"][0]["id"]
                requests.post(
                    f"{base}/leads/{lead_id}/links",
                    json=[{"to_entity_id": cid, "to_entity_type": "contacts"}],
                    headers=headers, timeout=15
                )
                print(f"  ✅ AmoCRM: Kontakt #{cid} ({ad['phone']}) ulandi")
        except Exception as e:
            print(f"  ⚠ AmoCRM kontakt: {e}")

    # ── 3. Izoh — tavsif + rasm linklari ─────
    note_parts = [
        f"🆔 ID: {mul_id}",
        f"📌 OLX: {ad['url']}",
        f"💰 Narx: {ad['price']}",
        f"📅 Sana: {ad.get('date_str','')}",
    ]
    if ad.get("desc"): note_parts.append(f"\n📝 {ad['desc'][:300]}")
    if ad.get("photos"):
        note_parts.append("\n📸 Rasmlar:\n" + "\n".join(ad["photos"][:4]))
    try:
        requests.post(
            f"{base}/leads/{lead_id}/notes",
            json=[{"note_type": "common", "params": {"text": "\n".join(note_parts)}}],
            headers=headers, timeout=15
        )
    except Exception as e:
        print(f"  ⚠ AmoCRM note: {e}")

    return True


def format_cap(ad, idx):
    phone = f"☎️ {ad['phone']}" if ad["phone"] else "☎️ Ko'rsatilmagan"
    extra = []
    if ad.get("rooms"):  extra.append(f"🚪 {ad['rooms']} xona")
    if ad.get("area"):   extra.append(f"📐 {ad['area']} m²")
    if ad.get("floor"):  extra.append(f"🏢 {ad['floor']}-etaj")
    if ad.get("floors"): extra.append(f"🏗 {ad['floors']}-etajli")
    cap = (
        f"🏠 <b>{idx}. {ad['title']}</b>\n"
        f"{'━'*24}\n"
        f"🆔 <b>{ad.get('mul_id', ad.get('olx_id',''))}</b>\n"
        f"💰 <b>Narx:</b> {ad['price']}\n"
        f"📍 <b>Joy:</b> {ad['location']}\n"
        f"📅 <b>Sana:</b> {ad['date_str']}\n"
    )
    if extra: cap += "ℹ️ " + "  |  ".join(extra) + "\n"
    cap += f"{'━'*24}\n📞 {phone}\n"
    if ad.get("desc"): cap += f"\n📝 <i>{ad['desc'][:200]}</i>\n"
    cap += f"\n🔗 <a href='{ad['url']}'>Ko'rish →</a>"
    return cap

# ──────────────────────────────────────────────
# AVTOMATIK QIDIRUV (24/7)
# ──────────────────────────────────────────────

def send_ads_to_user(chat_id, ads):
    """Topilgan e'lonlarni Telegram + AmoCRM ga yuboradi."""
    cfg_data   = load_config()
    amo_active = bool(cfg_data.get("amocrm_domain") and cfg_data.get("amocrm_token"))
    amo_count  = 0
    seen       = load_seen()

    for i, ad in enumerate(ads, 1):
        ad["mul_id"] = next_mul_id()
        send_media(chat_id, ad["photos"], format_cap(ad, i))
        seen.add(ad["id"])
        if amo_active and push_to_amocrm(ad):
            amo_count += 1
        time.sleep(0.8)

    save_seen(seen)
    result_msg = f"✅ <b>{len(ads)}</b> ta yangi e'lon yuborildi."
    if amo_active:
        result_msg += f"\n📊 AmoCRM: <b>{amo_count}</b> ta lead qo'shildi."
    send(chat_id, result_msg)


def auto_search_loop():
    """Fon rejimida ishlaydi: har N daqiqada yangi e'lonlarni qidiradi."""
    print("🔄 Avtomatik qidiruv fon rejimi ishga tushdi")
    # Birinchi ishga tushishda biroz kutamiz (bot tayyor bo'lsin)
    time.sleep(30)

    while True:
        try:
            cfg_data = load_config()
            if not cfg_data.get("auto_search", True):
                time.sleep(60)
                continue

            interval_min = int(cfg_data.get("auto_interval_min", 60))
            chat_id      = cfg_data.get("telegram_chat_id", "")

            if not chat_id:
                time.sleep(60)
                continue

            now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
            print(f"\n🔄 Auto-qidiruv: {now_str}")

            f    = get_uf(str(chat_id))
            ads  = do_search(str(chat_id), f)

            if ads:
                send(chat_id,
                     f"🔔 <b>Avtomatik qidiruv ({now_str})</b>\n"
                     f"<b>{len(ads)}</b> ta yangi e'lon topildi!")
                time.sleep(0.5)
                send_ads_to_user(chat_id, ads)
            else:
                print(f"  → Yangi e'lon yo'q")

        except Exception as e:
            print(f"⚠ Auto-qidiruv xato: {e}")

        # Keyingi qidiruv uchun kutish
        cfg_data     = load_config()
        interval_min = int(cfg_data.get("auto_interval_min", 60))
        print(f"  ⏳ Keyingi qidiruv {interval_min} daqiqadan keyin...")
        time.sleep(interval_min * 60)


# ──────────────────────────────────────────────
# HANDLER — QIDIRISH
# ──────────────────────────────────────────────

def handle_stats(chat_id):
    """OLX da oxirgi 7 kunda nechta kvartira e'loni qo'shilganini hisoblaydi."""
    send(chat_id, "⏳ <b>Statistika hisoblanmoqda...</b>\n(3-5 sahifa tekshiriladi)")

    from collections import defaultdict
    daily   = defaultdict(lambda: {"jami":0, "chastniy":0, "agentlik":0, "sotish":0, "arenda":0})
    total   = 0
    pages   = 5

    for page in range(1, pages + 1):
        html = fetch(build_url(page))  # stats uchun
        if not html: break
        state   = parse_state(html)
        raw_ads = state.get("listing",{}).get("listing",{}).get("ads",[])
        if not raw_ads: break

        for raw in raw_ads:
            ad  = parse_ad(raw)
            day = ad["date_str"] if ad["date_str"] and ad["date_str"] != "?" else "Noma'lum"
            title_low = ad["title"].lower()
            is_arenda = any(w in title_low for w in ARENDA_WORDS)

            daily[day]["jami"] += 1
            if ad["is_biz"]:     daily[day]["agentlik"] += 1
            else:                daily[day]["chastniy"]  += 1
            if is_arenda:        daily[day]["arenda"]    += 1
            else:                daily[day]["sotish"]    += 1
            total += 1

        time.sleep(1.0)

    if not daily:
        send(chat_id, "❌ Ma'lumot olib bo'lmadi.", main_kb()); return

    # Eng oxirgi 7 kunni chiqaramiz
    sorted_days = sorted(daily.keys(), reverse=True)[:7]
    today = datetime.now().strftime("%Y-%m-%d")

    lines = ["📊 <b>OLX.uz — Kvartira e'lonlari statistikasi</b>",
             f"<i>(so'nggi {pages} sahifa = ~{total} ta e'lon asosida)</i>",
             "━━━━━━━━━━━━━━━━━━━━━━"]

    for day in sorted_days:
        d = daily[day]
        label = "📅 Bugun" if day == today else f"📅 {day}"
        lines.append(
            f"{label}\n"
            f"  Jami: <b>{d['jami']}</b>  |  "
            f"🏠 Sotish: <b>{d['sotish']}</b>  |  "
            f"🔑 Arenda: <b>{d['arenda']}</b>\n"
            f"  👤 Egasidan: <b>{d['chastniy']}</b>  |  "
            f"🏢 Agentlik: <b>{d['agentlik']}</b>"
        )

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    # Kunlik o'rtacha
    sotish_days = [daily[d]["sotish"] for d in sorted_days]
    chastniy_days = [daily[d]["chastniy"] for d in sorted_days]
    if sotish_days:
        avg_sotish   = sum(sotish_days) / len(sotish_days)
        avg_chastniy = sum(chastniy_days) / len(chastniy_days)
        lines.append(
            f"📈 <b>O'rtacha (kuniga):</b>\n"
            f"  Sotish: ~<b>{avg_sotish:.0f}</b> ta  |  "
            f"Egasidan: ~<b>{avg_chastniy:.0f}</b> ta"
        )

    send(chat_id, "\n".join(lines), main_kb())


def handle_search(chat_id):
    uid = str(chat_id)
    user_states.pop(uid, None)
    f   = get_uf(uid)
    send(chat_id,
        "⏳ <b>Qidirilmoqda...</b>\n\n"
        f"{filters_text(f)}\n\n"
        "⏳ Iltimos kuting...")
    ads = do_search(uid, f)

    if not ads:
        f2   = get_uf(uid)
        tips = []
        if f2.get("tuman") and f2["tuman"] not in ("","barchasi"):
            tips.append(f"• Tuman: <b>{f2['tuman'].title()}</b> → <b>Barchasi</b> qiling")
        if f2.get("narx_dan") or f2.get("narx_gacha"):
            tips.append("• Narx oralig'ini kengaytiring yoki olib tashlang")
        if f2.get("kun_soni",7) <= 7:
            tips.append("• Kun sonini oshiring: <b>14–30 kun</b>")
        if f2.get("remont","barchasi") != "barchasi":
            tips.append("• Remont → <b>Barchasi</b> qiling")
        if f2.get("xona_dan") or f2.get("xona_gacha"):
            tips.append("• Xona soni → <b>Barchasi</b> qiling")
        tips.append("• 💡 OLX da xususiy egalardan kam e'lon bo'ladi")
        send(chat_id,
            "📭 <b>Mos e'lon topilmadi.</b>\n\n"
            "💡 <b>Maslahat:</b>\n" + "\n".join(tips),
            main_kb())
        return

    send(chat_id, f"🔔 <b>{len(ads)} ta e'lon topildi!</b>")
    time.sleep(0.5)
    send_ads_to_user(chat_id, ads)
    send(chat_id, "✅ Tayyor!", main_kb())

# ──────────────────────────────────────────────
# CALLBACK HANDLER
# ──────────────────────────────────────────────

def handle_cb(cb):
    data    = cb.get("data","")
    chat_id = cb["message"]["chat"]["id"]
    mid     = cb["message"]["message_id"]
    uid     = str(chat_id)
    answer_cb(cb["id"])

    # Hech narsa qilmaydigan tugma (separator uchun)
    if data == "noop":
        return

    # Asosiy
    if data == "main_menu":
        user_states.pop(uid, None)
        edit(chat_id, mid, "📌 <b>Asosiy menyu:</b>", main_kb())

    elif data == "search":
        handle_search(chat_id)

    elif data == "stats":
        handle_stats(chat_id)

    elif data == "show_filters":
        f = get_uf(uid)
        edit(chat_id, mid, filters_text(f), main_kb())

    elif data == "reset":
        d = load_filters(); d.pop(uid, None); save_filters(d)
        user_states.pop(uid, None)
        edit(chat_id, mid, "🗑 <b>Filtrlar tozalandi!</b>", main_kb())

    # ── Auto-qidiruv ON/OFF ────────────────────
    elif data == "toggle_auto":
        cfg_data = load_config()
        cur = cfg_data.get("auto_search", True)
        cfg_data["auto_search"] = not cur
        CONFIG_FILE.write_text(json.dumps(cfg_data, ensure_ascii=False, indent=2))
        status = "🟢 <b>Yoqildi!</b>" if not cur else "🔴 <b>O'chirildi!</b>"
        interval = cfg_data.get("auto_interval_min", 60)
        edit(chat_id, mid,
             f"🤖 <b>Avtomatik qidiruv:</b> {status}\n\n"
             f"⏱ Har <b>{interval} daqiqada</b> yangi e'lonlar qidiriladi.\n"
             f"Filtrlar saqlangan sozlamalar bo'yicha ishlaydi.",
             main_kb(auto_on=not cur))

    # ── Interval sozlash ──────────────────────
    elif data == "set_interval":
        user_states[uid] = "await_interval"
        edit(chat_id, mid,
             "⏱ <b>Qidiruv intervali (daqiqada):</b>\n\n"
             "Tavsiya: <code>30</code> yoki <code>60</code>\n"
             "Yozing (masalan: <code>45</code>):")

    # Wizard boshlash — yangi xabar yuboramiz (edit emas, doim yangi keyboard)
    elif data == "wizard_start":
        user_states.pop(uid, None)
        tuman_pending.pop(uid, None)
        wizard_active[uid]  = True
        wizard_tokens[uid]  = str(random.randint(100000, 999999))
        show_step(chat_id, "tuman")  # mid yo'q → yangi xabar!

    # ── Token-li tuman tugmalari: wt_{token}_{code} ──────────
    elif data.startswith("wt_"):
        parts = data.split("_")           # ["wt","123456","2"] yoki ["wt","123456","done"]
        if len(parts) < 3: return
        token = parts[1]
        code  = parts[2]
        # Token tekshiruvi — faqat JORIY sessiya token mos kelsa ishlaydi
        if wizard_tokens.get(uid) != token:
            return  # Eski sessiya tugmasi — e'tiborsiz
        # "Keyingisi" bosildi
        if code == "done":
            sel = tuman_pending.pop(uid, [])
            if sel:
                set_uf(uid, "tuman", ",".join(s.lower() for s in sel))
                edit(chat_id, mid, f"✅ Tuman: <b>{', '.join(sel)}</b>")
            else:
                set_uf(uid, "tuman", "")
                edit(chat_id, mid, "✅ Tuman: <b>🌍 Barchasi</b>")
            time.sleep(0.3)
            show_step(chat_id, "narx")
        # "Barchasi" bosildi
        elif code == "0":
            tuman_pending[uid] = []
            edit(chat_id, mid,
                 "1️⃣ <b>Tumanni tanlang:</b>\n"
                 "<i>Keraklilarini bosing, so'ng ➡️ Keyingisi bosing</i>",
                 tuman_kb_token([], token))
        # Tuman toggle
        else:
            name = TUMAN_MAP.get(code, "")
            if not name or name == "🌍 Barchasi": return
            sel = tuman_pending.get(uid, [])
            if name in sel: sel.remove(name)
            else: sel.append(name)
            tuman_pending[uid] = sel
            sel_str = ", ".join(sel) if sel else "hali tanlanmagan"
            edit(chat_id, mid,
                 f"1️⃣ <b>Tumanni tanlang:</b>\n"
                 f"<i>Keraklilarini bosing, so'ng ➡️ Keyingisi bosing</i>\n\n"
                 f"📍 Tanlangan: <b>{sel_str}</b>",
                 tuman_kb_token(sel, token))

    # wz_tuman_* va ok_tuman — eski versiyadan qolgan → e'tiborsiz
    elif data.startswith("wz_tuman_") or data == "ok_tuman":
        return

    # ── Xona ──────────────────────────────────
    elif data.startswith("wz_xona_") and wizard_active.get(uid):
        parts = data.replace("wz_xona_","").split("_")
        dan, gacha = int(parts[0]), int(parts[1])
        if dan == 0:
            set_uf(uid,"xona_dan",None); set_uf(uid,"xona_gacha",None)
            edit(chat_id, mid, "✅ Xona: <b>Barchasi</b>")
        else:
            set_uf(uid,"xona_dan",dan); set_uf(uid,"xona_gacha",gacha)
            label = f"{dan} xona" if dan==gacha else f"{dan}–{gacha} xona"
            edit(chat_id, mid, f"✅ Xona: <b>{label}</b>")
        time.sleep(0.3)
        show_step(chat_id, "etaj")

    # ── Bino ──────────────────────────────────
    elif data.startswith("wz_bino_") and wizard_active.get(uid):
        val = data.replace("wz_bino_","")
        set_uf(uid,"bino_turi",val)
        edit(chat_id, mid, f"✅ Bino turi: <b>{val}</b>")
        time.sleep(0.3)
        show_step(chat_id, "remont")

    # ── Remont ────────────────────────────────
    elif data.startswith("wz_remont_") and wizard_active.get(uid):
        val = data.replace("wz_remont_","")
        set_uf(uid,"remont",val)
        edit(chat_id, mid, f"✅ Remont: <b>{val}</b>")
        time.sleep(0.3)
        show_step(chat_id, "kun")

    # ── Kun ───────────────────────────────────
    elif data.startswith("wz_kun_") and wizard_active.get(uid):
        val = int(data.replace("wz_kun_",""))
        set_uf(uid,"kun_soni",val)
        edit(chat_id, mid, f"✅ Kun soni: <b>{val} kun</b>")
        time.sleep(0.3)
        wizard_active.pop(uid, None)  # Wizard tugadi
        show_step(chat_id, "done")

# ──────────────────────────────────────────────
# MATN HANDLER
# ──────────────────────────────────────────────

def handle_text(msg):
    chat_id = msg["chat"]["id"]
    text    = msg.get("text","").strip()
    uid     = str(chat_id)
    state   = user_states.get(uid)

    if text in ["/start","/menu","/help"]:
        user_states.pop(uid, None)
        wizard_active.pop(uid, None)
        send(chat_id,
            "👋 <b>Mulk OLX Bot!</b>\n\n"
            "OLX.uz dan faqat <b>egasidan</b> bo'lgan "
            "kvartira e'lonlarini topadi.\n\n"
            "Filtrlarni sozlab, <b>Qidirish</b> tugmasini bosing!",
            main_kb())
        return

    if not state:
        send(chat_id, "📌 Bosh menyu:", main_kb())
        return

    def parse_rng(t):
        nums = re.findall(r'\d+', t)
        if not nums or nums[0]=="0": return None, None
        if len(nums)==1: return int(nums[0]), None
        return int(nums[0]), int(nums[1])

    if state == "await_tuman":
        pass  # Endi tuman keyboard orqali tanlanadi, matn kiritish yo'q

    elif state == "await_narx":
        dan, gacha = parse_rng(text)
        set_uf(uid,"narx_dan",dan); set_uf(uid,"narx_gacha",gacha)
        user_states.pop(uid, None)
        s = f"${dan or '—'} – ${gacha or '—'}"
        send(chat_id, f"✅ Narx: <b>{s}</b>")
        time.sleep(0.3)
        show_step(chat_id, "kvadrat")

    elif state == "await_kvadrat":
        dan, gacha = parse_rng(text)
        set_uf(uid,"kvadrat_dan",dan); set_uf(uid,"kvadrat_gacha",gacha)
        user_states.pop(uid, None)
        s = f"{dan or '—'} – {gacha or '—'} m²"
        send(chat_id, f"✅ Kvadrat: <b>{s}</b>")
        time.sleep(0.3)
        show_step(chat_id, "xona")

    elif state == "await_etaj":
        dan, gacha = parse_rng(text)
        set_uf(uid,"etaj_dan",dan); set_uf(uid,"etaj_gacha",gacha)
        user_states.pop(uid, None)
        s = f"{dan or '—'} – {gacha or '—'}"
        send(chat_id, f"✅ Etaj: <b>{s}</b>")
        time.sleep(0.3)
        show_step(chat_id, "etajnost")

    elif state == "await_etajnost":
        dan, gacha = parse_rng(text)
        set_uf(uid,"etajnost_dan",dan); set_uf(uid,"etajnost_gacha",gacha)
        user_states.pop(uid, None)
        s = f"{dan or '—'} – {gacha or '—'}"
        send(chat_id, f"✅ Etajnost: <b>{s}</b>")

    elif state == "await_interval":
        nums = re.findall(r'\d+', text)
        user_states.pop(uid, None)
        if nums:
            mins = max(10, min(int(nums[0]), 1440))  # 10 daqiqa – 24 soat
            cfg_data = load_config()
            cfg_data["auto_interval_min"] = mins
            CONFIG_FILE.write_text(json.dumps(cfg_data, ensure_ascii=False, indent=2))
            send(chat_id,
                 f"✅ Interval: har <b>{mins} daqiqada</b> qidiradi.",
                 main_kb())
        else:
            send(chat_id, "❌ Raqam kiriting (masalan: 60)", main_kb())
        time.sleep(0.3)
        show_step(chat_id, "bino")

# ──────────────────────────────────────────────
# MAIN POLLING
# ──────────────────────────────────────────────

def run():
    print("="*45)
    print("🤖 Mulk OLX Bot ishga tushdi!")
    print(f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    print("="*45)

    # Avtomatik qidiruv fon threadini ishga tushirish
    cfg_data = load_config()
    auto_on  = cfg_data.get("auto_search", True)
    interval = cfg_data.get("auto_interval_min", 60)
    print(f"🔄 Auto-qidiruv: {'ON' if auto_on else 'OFF'} | Interval: {interval} daqiqa")

    auto_thread = threading.Thread(target=auto_search_loop, daemon=True)
    auto_thread.start()

    # ── Barcha eski kutayotgan xabarlarni kafolatli tozalash ──
    offset = 0
    try:
        skipped = 0
        while True:
            r = requests.get(f"{TG_BASE}/getUpdates",
                             params={"offset": offset, "timeout": 0, "limit": 100},
                             timeout=15)
            updates = r.json().get("result", [])
            if not updates:
                break
            offset = updates[-1]["update_id"] + 1
            skipped += len(updates)
        print(f"⏭ {skipped} ta eski xabar o'tkazib yuborildi | offset={offset}")
    except Exception as e:
        print(f"⚠ Startup tozalash xatosi: {e}")
        offset = 0

    while True:
        try:
            r = requests.get(f"{TG_BASE}/getUpdates",
                params={"offset":offset,"timeout":30}, timeout=35)
            updates = r.json().get("result",[])
            for u in updates:
                offset = u["update_id"] + 1
                if "callback_query" in u:
                    handle_cb(u["callback_query"])
                elif "message" in u and u["message"].get("text"):
                    handle_text(u["message"])
        except KeyboardInterrupt:
            print("\n⛔ Bot to'xtatildi."); break
        except Exception as e:
            print(f"⚠ {e}"); time.sleep(3)

def start_health_server():
    """Render uchun minimal HTTP server (bepul plan talab qiladi)."""
    import http.server, os
    port = int(os.environ.get("PORT", 8080))
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Mulk OLX Bot ishlayapti!")
        def log_message(self, *a): pass
    server = http.server.HTTPServer(("0.0.0.0", port), H)
    print(f"🌐 Health server port {port} da ishga tushdi")
    server.serve_forever()

if __name__ == "__main__":
    # Health server ni fon threadda ishga tushirish (Render uchun)
    ht = threading.Thread(target=start_health_server, daemon=True)
    ht.start()
    run()
