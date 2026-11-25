"""Phase 0 census candidate collector (throwaway).
Routes: GitHub legacy code search (gh api search/code), Sourcegraph public stream API.
Writes smoke/census/raw/candidates.jsonl  (one line per hit, with route+query)."""
import json, subprocess, sys, time, urllib.parse, urllib.request, os

OUT = os.path.join(os.path.dirname(__file__), '..', 'raw', 'candidates.jsonl')
GH_QUERIES = [
  ('flagd', '"flagd.dev/schema/v0/flags.json" extension:json'),
  ('flagd', '"defaultVariant" "ENABLED" "variants" extension:json'),
  ('flagd', '"defaultVariant" "DISABLED" "variants" extension:json'),
  ('flagd', 'filename:.flagd.json'),
  ('flagd', '"fractional" "defaultVariant" extension:json'),
  ('flagd', '"targeting" "defaultVariant" "state" extension:json'),
  ('flipt', '"VARIANT_FLAG_TYPE" extension:yml'),
  ('flipt', '"VARIANT_FLAG_TYPE" extension:yaml'),
  ('flipt', '"BOOLEAN_FLAG_TYPE" extension:yml'),
  ('flipt', '"BOOLEAN_FLAG_TYPE" extension:yaml'),
  ('flipt', 'filename:features.yml flags'),
  ('flipt', 'filename:features.yaml flags'),
  ('flipt', '"distributions" "rollout" "variants" extension:yml'),
  ('flipt', '"distributions" "rollout" "variants" extension:yaml'),
  ('flipt', '"namespace" "flags" "rollouts" extension:yml'),
  ('goff',  '"defaultRule" "variations" extension:yaml'),
  ('goff',  '"defaultRule" "variations" extension:yml'),
  ('goff',  '"defaultRule" "percentage" extension:yaml'),
  ('goff',  '"defaultRule" "percentage" extension:yml'),
  ('goff',  'filename:goff extension:yaml'),
  ('goff',  '"targeting" "query" "variation" "defaultRule" extension:yaml'),
]
SG_QUERIES = [
  ('flagd', 'flagd.dev/schema/v0/flags.json count:all patterntype:keyword'),
  ('flagd', 'defaultVariant AND ENABLED AND variants file:\\.json$ count:all patterntype:keyword'),
  ('flagd', 'defaultVariant AND DISABLED AND variants file:\\.json$ count:all patterntype:keyword'),
  ('flagd', 'file:\\.flagd\\.json$ count:all'),
  ('flipt', 'VARIANT_FLAG_TYPE file:\\.ya?ml$ count:all'),
  ('flipt', 'BOOLEAN_FLAG_TYPE file:\\.ya?ml$ count:all'),
  ('flipt', 'distributions AND rollout AND variants file:\\.ya?ml$ count:all patterntype:keyword'),
  ('flipt', 'namespace AND flags AND rollouts file:\\.ya?ml$ count:all patterntype:keyword'),
  ('flipt', 'file:(^|/)([^/]*\\.)?features\\.ya?ml$ count:all'),
  ('goff',  'defaultRule AND variations file:\\.ya?ml$ count:all patterntype:keyword'),
  ('goff',  'defaultRule AND percentage file:\\.ya?ml$ count:all patterntype:keyword'),
]

def gh_search(q):
    hits = []
    for page in range(1, 11):
        for attempt in range(6):
            p = subprocess.run(['gh', 'api', '-X', 'GET', 'search/code', '-f', 'q=' + q, '-f', 'per_page=100', '-f', 'page=%d' % page],
                               capture_output=True, text=True)
            if p.returncode == 0: break
            if any(x in (p.stdout + p.stderr).lower() for x in ('rate limit', 'secondary', 'http 503', 'shards failed')):
                time.sleep(30); continue
            print('ERR', q, page, p.stderr[:200], file=sys.stderr); return hits, None
        else:
            return hits, None
        d = json.loads(p.stdout)
        total = d.get('total_count')
        for it in d.get('items', []):
            ref = urllib.parse.parse_qs(urllib.parse.urlparse(it['url']).query).get('ref', [''])[0]
            r = it['repository']
            hits.append(dict(repo=r['full_name'], path=it['path'], ref=ref, fork=r.get('fork'), description=r.get('description')))
        if len(d.get('items', [])) < 100: break
        time.sleep(7)
    return hits, total

def sg_search(q):
    url = 'https://sourcegraph.com/.api/search/stream?' + urllib.parse.urlencode({'q': q, 'display': '5000'})
    req = urllib.request.Request(url, headers={'Accept': 'text/event-stream', 'User-Agent': 'census-script'})
    hits = []; ev = None
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            line = raw.decode('utf-8', 'replace').rstrip('\n')
            if line.startswith('event:'): ev = line[6:].strip()
            elif line.startswith('data:') and ev == 'matches':
                for m in json.loads(line[5:]):
                    if m.get('type') in ('content', 'path'):
                        repo = m['repository']
                        if not repo.startswith('github.com/'): continue
                        hits.append(dict(repo=repo[len('github.com/'):], path=m['path'], ref=m.get('commit', ''), fork=None, description=None))
    return hits, len(hits)

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    global GH_QUERIES
    if which == 'gh-retry':
        GH_QUERIES = [q for q in GH_QUERIES if q[1] in sys.argv[2:]]; which = 'gh'
    with open(OUT, 'a') as f:
        if which in ('all', 'gh'):
            for fmt, q in GH_QUERIES:
                hits, total = gh_search(q)
                print('gh', fmt, repr(q), 'total_count=%s fetched=%d' % (total, len(hits)), flush=True)
                for h in hits: f.write(json.dumps(dict(route='github-code-search', fmt_hint=fmt, query=q, total_count=total, **h)) + '\n')
                time.sleep(7)
        if which in ('all', 'sg'):
            for fmt, q in SG_QUERIES:
                try: hits, total = sg_search(q)
                except Exception as e: print('sg ERR', q, e, flush=True); continue
                print('sg', fmt, repr(q), 'fetched=%d' % len(hits), flush=True)
                for h in hits: f.write(json.dumps(dict(route='sourcegraph', fmt_hint=fmt, query=q, total_count=total, **h)) + '\n')
main()
