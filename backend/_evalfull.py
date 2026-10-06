import json, httpx
r = httpx.post("http://localhost:8000/api/eval/run", json={}, timeout=2400)
print("HTTP", r.status_code)
if r.status_code != 200:
    print(r.text[:300]); raise SystemExit(1)
d = r.json()
print("通过:", d.get("passed"), "/", d.get("total"))
print("\nmetrics:")
print(json.dumps(d.get("metrics"), ensure_ascii=False, indent=2))