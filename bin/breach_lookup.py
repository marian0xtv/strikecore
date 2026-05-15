#!/usr/bin/env python3
"""
StrikeCore Breach Aggregator Client — Dehashed, SnusBase, LeakPeek integration.

Queries multiple breach aggregator APIs for phone numbers linked to a target.
The Facebook 533M breach (2019) is the primary source for FB_ID → phone.
"""

import base64, json, os, re, sys, time, urllib.request, urllib.parse, urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

class BreachAggregator:
    """Query breach aggregator APIs for phone/contact data."""
    
    def __init__(self):
        self.dehashed_email = os.environ.get("DEHASHED_EMAIL", "")
        self.dehashed_key = os.environ.get("DEHASHED_API_KEY", "")
        self.snusbase_key = os.environ.get("SNUSBASE_API_KEY", "")
        self.leakpeek_key = os.environ.get("LEAKPEEK_API_KEY", "")
        self.results = []
    
    def _request(self, url, headers=None, data=None):
        hdrs = {"User-Agent": "StrikeCore/2.0"}
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, data=data, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read()), r.status
        except urllib.error.HTTPError as e:
            return {"error": e.read().decode(errors="ignore")[:300]}, e.code
        except Exception as e:
            return {"error": str(e)}, 0

    # ── Dehashed ──
    
    def dehashed_search(self, query_type, query_value):
        """Search Dehashed. query_type: email, username, phone, name, address, etc."""
        if not self.dehashed_email or not self.dehashed_key:
            return {"error": "DEHASHED_EMAIL and DEHASHED_API_KEY not set"}
        
        auth = base64.b64encode(f"{self.dehashed_email}:{self.dehashed_key}".encode()).decode()
        url = f"https://api.dehashed.com/search?query={query_type}:{urllib.parse.quote(query_value)}"
        
        data, status = self._request(url, headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
        })
        
        if status == 200 and "entries" in data:
            entries = data.get("entries", [])
            phones = []
            for entry in entries:
                phone = entry.get("phone", "")
                if phone and len(re.sub(r'\D', '', phone)) >= 10:
                    phones.append({
                        "phone": phone,
                        "source": entry.get("database_name", "unknown"),
                        "name": entry.get("name", ""),
                        "email": entry.get("email", ""),
                        "username": entry.get("username", ""),
                    })
                    self.results.append({"phone": phone, "source": f"dehashed:{entry.get('database_name','')}", "confidence": "HIGH"})
            return {"status": "ok", "total": data.get("total", 0), "phones": phones, "entries": entries[:10]}
        
        return data

    # ── SnusBase ──
    
    def snusbase_search(self, query_type, query_value):
        """Search SnusBase. query_type: email, username, name, hash, password, etc."""
        if not self.snusbase_key:
            return {"error": "SNUSBASE_API_KEY not set"}
        
        payload = json.dumps({
            "terms": [query_value],
            "types": [query_type],
            "wildcard": False,
        }).encode()
        
        data, status = self._request(
            "https://api.snusbase.com/data/search",
            headers={
                "Auth": self.snusbase_key,
                "Content-Type": "application/json",
            },
            data=payload,
        )
        
        if status == 200 and "results" in data:
            results = data.get("results", {})
            phones = []
            for db_name, entries in results.items():
                for entry in entries:
                    phone = entry.get("phone", "") or entry.get("phone_number", "")
                    if phone and len(re.sub(r'\D', '', phone)) >= 10:
                        phones.append({
                            "phone": phone,
                            "source": db_name,
                            "email": entry.get("email", ""),
                            "name": entry.get("name", ""),
                        })
                        self.results.append({"phone": phone, "source": f"snusbase:{db_name}", "confidence": "HIGH"})
            return {"status": "ok", "phones": phones}
        
        return data

    # ── LeakPeek ──
    
    def leakpeek_search(self, query_type, query_value):
        """Search LeakPeek. query_type: email, username, phone, etc."""
        if not self.leakpeek_key:
            return {"error": "LEAKPEEK_API_KEY not set"}
        
        url = f"https://leakpeek.com/api/search?key={self.leakpeek_key}&type={query_type}&query={urllib.parse.quote(query_value)}"
        data, status = self._request(url)
        
        if status == 200:
            phones = []
            for entry in data if isinstance(data, list) else data.get("results", []):
                phone = entry.get("phone", "") or entry.get("phone_number", "")
                if phone:
                    phones.append({"phone": phone, "source": "leakpeek"})
                    self.results.append({"phone": phone, "source": "leakpeek", "confidence": "HIGH"})
            return {"status": "ok", "phones": phones}
        return data

    # ── Main search ──
    
    def full_search(self, name=None, emails=None, usernames=None, fb_id=None):
        """Run all available APIs with all target identifiers."""
        print(f"\n{'='*60}")
        print(f"  BREACH AGGREGATOR SEARCH")
        print(f"{'='*60}")
        
        available = []
        if self.dehashed_email and self.dehashed_key:
            available.append("Dehashed")
        if self.snusbase_key:
            available.append("SnusBase")
        if self.leakpeek_key:
            available.append("LeakPeek")
        
        if not available:
            print(f"\n  NO API KEYS CONFIGURED!")
            print(f"  Set one or more of these environment variables:")
            print(f"    export DEHASHED_EMAIL=your@email.com")
            print(f"    export DEHASHED_API_KEY=your_key")
            print(f"    export SNUSBASE_API_KEY=your_key")
            print(f"    export LEAKPEEK_API_KEY=your_key")
            print(f"\n  Pricing:")
            print(f"    Dehashed: $5/month — best for Facebook breach (FB_ID search)")
            print(f"    SnusBase: $30/month — comprehensive, fast")
            print(f"    LeakPeek: $4.49/week — good coverage")
            return self.results
        
        print(f"  Available APIs: {', '.join(available)}")
        
        queries = []
        if emails:
            for email in emails:
                queries.append(("email", email))
        if usernames:
            for username in usernames:
                queries.append(("username", username))
        if name:
            queries.append(("name", name))
        if fb_id:
            # Dehashed supports direct database-specific queries
            queries.append(("username", fb_id))  # FB ID sometimes indexed as username
        
        for qtype, qval in queries:
            print(f"\n  Searching: {qtype}={qval}")
            
            if "Dehashed" in available:
                print(f"    [Dehashed] ", end="", flush=True)
                result = self.dehashed_search(qtype, qval)
                if "phones" in result and result["phones"]:
                    for p in result["phones"]:
                        print(f"\n      *** PHONE: {p['phone']} (source: {p['source']}, name: {p.get('name','')}) ***")
                elif "error" in result:
                    print(f"error: {str(result['error'])[:100]}")
                else:
                    print(f"no phone data (total entries: {result.get('total', 0)})")
                time.sleep(2)
            
            if "SnusBase" in available:
                print(f"    [SnusBase] ", end="", flush=True)
                result = self.snusbase_search(qtype, qval)
                if "phones" in result and result["phones"]:
                    for p in result["phones"]:
                        print(f"\n      *** PHONE: {p['phone']} (source: {p['source']}) ***")
                elif "error" in result:
                    print(f"error: {str(result['error'])[:100]}")
                else:
                    print(f"no phone data")
                time.sleep(2)
            
            if "LeakPeek" in available:
                print(f"    [LeakPeek] ", end="", flush=True)
                result = self.leakpeek_search(qtype, qval)
                if "phones" in result and result["phones"]:
                    for p in result["phones"]:
                        print(f"\n      *** PHONE: {p['phone']} ***")
                elif "error" in result:
                    print(f"error: {str(result['error'])[:100]}")
                else:
                    print(f"no phone data")
                time.sleep(2)
        
        # Summary
        print(f"\n{'='*60}")
        if self.results:
            print(f"  PHONES FOUND: {len(self.results)}")
            seen = set()
            for r in self.results:
                if r["phone"] not in seen:
                    seen.add(r["phone"])
                    print(f"    [{r['confidence']}] {r['phone']} — {r['source']}")
        else:
            print(f"  No phones found in breach databases")
        print(f"{'='*60}")
        
        return self.results


def main():
    if len(sys.argv) < 2:
        print("Usage: breach_lookup.py TARGET_NAME [options]")
        print("  email=EMAIL    (repeatable)")
        print("  username=USER  (repeatable)")
        print("  fb_id=ID")
        print("")
        print("Example:")
        print("  breach_lookup.py 'Luigi Savino' email=luigi.savino.95@gmail.com fb_id=1439591776")
        sys.exit(1)
    
    name = sys.argv[1]
    emails, usernames, fb_id = [], [], None
    
    for arg in sys.argv[2:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            if k == "email": emails.append(v)
            elif k == "username": usernames.append(v)
            elif k == "fb_id": fb_id = v
    
    agg = BreachAggregator()
    agg.full_search(name=name, emails=emails, usernames=usernames, fb_id=fb_id)


if __name__ == "__main__":
    main()
