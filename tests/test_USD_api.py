import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

URL = "https://brsapi.ir/Api/Market/Gold_Currency.php?key=BgbF9eDYAMyKLqm5haWIW82faLae6Xca"

# هدر با User-Agent مرورگر (برای جلوگیری از بلاک شدن توسط فایروال)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/118.0.0.0 Safari/537.36"
    )
}

def get_usd(url=URL, headers=HEADERS, timeout=10):
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))

    try:
        resp = session.get(url, headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as e:
        return {"error": f"Network error: {e}"}

    if resp.status_code == 403:
        return {"error": "Access forbidden (403). ممکن است IP یا User-Agent مسدود شده باشد."}
    if resp.status_code != 200:
        return {"error": f"Unexpected status code: {resp.status_code}", "body": resp.text[:500]}

    try:
        data = resp.json()
    except ValueError:
        return {"error": "Invalid JSON in response", "body": resp.text[:500]}

    # جستجو در بخش currency با اولویت symbol == "USD"
    currency_list = data.get("currency", [])
    usd = next((it for it in currency_list if it.get("symbol") == "USD"), None)

    # اگر با symbol پیدا نشد، تلاش دوم براساس name_en یا name
    if not usd:
        usd = next(
            (it for it in currency_list if it.get("name_en", "").lower().startswith("us") or it.get("name", "").find("دلار") != -1),
            None,
        )

    if not usd:
        return {"error": "USD not found in response", "available_symbols": [it.get("symbol") for it in currency_list]}

    # تلاش برای تبدیل قیمت به عدد (اگر رشته است)
    price_raw = usd.get("price")
    try:
        price = float(price_raw)
        # اگر واحد تومان و قیمت خیلی بزرگه و خواستی int:
        if price.is_integer():
            price = int(price)
    except Exception:
        price = price_raw  # همون مقدار خام

    return {
        "symbol": usd.get("symbol"),
        "name": usd.get("name"),
        "name_en": usd.get("name_en"),
        "price": price,
        "unit": usd.get("unit"),
        "date": usd.get("date"),
        "time": usd.get("time"),
    }

if __name__ == "__main__":
    result = get_usd()
    if "error" in result:
        print("خطا:", result["error"])
        if "body" in result:
            print("جزئیات:", result["body"])
        if "available_symbols" in result:
            print("نمادهای موجود:", result["available_symbols"])
    else:
        print(f"USD: {result['price']} {result['unit']} (تاریخ: {result['date']}، ساعت: {result['time']})")
