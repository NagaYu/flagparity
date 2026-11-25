"""Phase 0 census: download candidate bytes, apply DECISIONS.md D-1..D-3, write inventory.
Downloaded files are untrusted data: only parsed with json / yaml.safe_load_all, never executed."""
import json, os, sys, hashlib, re, subprocess, time, urllib.parse, urllib.request, csv, datetime
from concurrent.futures import ThreadPoolExecutor
import yaml

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
RAW = os.path.join(BASE, 'raw'); FILES = os.path.join(BASE, 'files')
os.makedirs(FILES, exist_ok=True)
TODAY = datetime.date.today().isoformat()

# ---------------- D-1 identification ----------------
def is_flagd(obj):
    if not isinstance(obj, dict) or not isinstance(obj.get('flags'), dict): return False
    for v in obj['flags'].values():
        if isinstance(v, dict) and v.get('state') in ('ENABLED', 'DISABLED') and isinstance(v.get('variants'), dict) and 'defaultVariant' in v:
            return True
    return False

def is_flagd_array(obj):  # out of scope variant (flags as array) -- recorded, not counted
    if not isinstance(obj, dict) or not isinstance(obj.get('flags'), list): return False
    return any(isinstance(v, dict) and v.get('state') in ('ENABLED', 'DISABLED') and isinstance(v.get('variants'), dict) and 'defaultVariant' in v for v in obj['flags'])

FLIPT_TOP = {'version', 'namespace', 'flags', 'segments'}
def is_flipt(obj):
    if not isinstance(obj, dict) or not isinstance(obj.get('flags'), list): return False
    if not set(obj.keys()) <= FLIPT_TOP: return False
    for it in obj['flags']:
        if isinstance(it, dict) and isinstance(it.get('key'), str) and (
            it.get('type') in ('VARIANT_FLAG_TYPE', 'BOOLEAN_FLAG_TYPE') or isinstance(it.get('variants'), list)
            or isinstance(it.get('rules'), list) or isinstance(it.get('rollouts'), list)):
            return True
    return False

def is_goff(obj):
    if not isinstance(obj, dict): return False
    return any(isinstance(v, dict) and isinstance(v.get('variations'), dict) and isinstance(v.get('defaultRule'), dict) for v in obj.values())

def is_goff_legacy(obj):
    if not isinstance(obj, dict): return False
    return any(isinstance(v, dict) and {'true', 'false', 'default'} <= set(map(str, v.keys())) for v in obj.values())

def identify(path, data):
    ext = os.path.splitext(path)[1].lower()
    try: text = data.decode('utf-8')
    except UnicodeDecodeError: return 'unparseable', None
    if ext == '.json':
        try: obj = json.loads(text)
        except Exception: return 'unparseable', None
        if is_flagd(obj): return 'flagd', obj
        if is_flagd_array(obj): return 'out:flagd-array', obj
        if is_flipt(obj): return 'out:flipt-json', obj
        if is_goff(obj): return 'out:goff-json', obj
        return 'no-match', None
    if ext in ('.yml', '.yaml'):
        try: docs = [d for d in yaml.safe_load_all(text)]
        except Exception: return 'unparseable', None
        docs = [d for d in docs if d is not None]
        hits = set()
        for d in docs:
            if is_flipt(d): hits.add('flipt')
            if is_goff(d): hits.add('goff')
            if is_flagd(d): hits.add('out:flagd-yaml')
            if is_goff_legacy(d): hits.add('out:goff-legacy')
        main = hits & {'flipt', 'goff'}
        if len(main) > 1: return 'ambiguous', None
        if main:
            fmt = main.pop(); return fmt, (docs if len(docs) > 1 else docs[0])
        if hits: return sorted(hits)[0], None
        return 'no-match', None
    if ext == '.toml': return 'out:toml', None
    return 'no-match', None

# ---------------- D-3 provenance ----------------
PROVIDER_OWNERS = {'open-feature', 'flipt-io', 'go-feature-flag', 'thomaspoignant'}
TUTORIAL_RE = re.compile(r'demo|example|sample|tutorial|playground|workshop|quickstart|quick-start|starter|getting-started|poc|lab|kata|learn|course|template|boilerplate|hello', re.I)
FIXTURE_RE = re.compile(r'(^|/)(test|tests|testdata|fixture|fixtures|__tests__|spec|e2e)(/|$)', re.I)
OFFICIAL_SAMPLE_REPOS = set()  # filled from docs (see DECISIONS.md census record); owner-agnostic official sample collections

def provenance(repo, path, desc):
    owner, name = repo.split('/', 1)
    if owner.lower() in PROVIDER_OWNERS: return 'sample:provider-owned'
    if repo.lower() in OFFICIAL_SAMPLE_REPOS: return 'sample:official-sample'
    dirs = '/'.join(path.split('/')[:-1])
    if TUTORIAL_RE.search(name) or TUTORIAL_RE.search(desc or '') or TUTORIAL_RE.search(dirs):
        return 'sample:tutorial'
    return 'non-sample'

# ---------------- download ----------------
def fetch(c):
    ref = c['ref'] or 'HEAD'
    url = 'https://raw.githubusercontent.com/%s/%s/%s' % (c['repo'], ref, urllib.parse.quote(c['path']))
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'census-script'}), timeout=60) as r:
                return c, r.read(), url, None
        except urllib.error.HTTPError as e:
            if e.code == 404: return c, None, url, 'http404'
            err = 'http%d' % e.code
        except Exception as e:
            err = type(e).__name__
        time.sleep(2)
    return c, None, url, err

def repo_meta(repo, cache):
    if repo in cache: return cache[repo]
    p = subprocess.run(['gh', 'api', 'repos/' + repo], capture_output=True, text=True)
    if p.returncode != 0:
        cache[repo] = {'error': p.stderr.strip()[:120]}
    else:
        d = json.loads(p.stdout)
        cache[repo] = dict(fork=d.get('fork'), archived=d.get('archived'), description=d.get('description'), stars=d.get('stargazers_count'),
                           full_name=d.get('full_name'), pushed_at=d.get('pushed_at'))
    return cache[repo]

def main():
    cands = [json.loads(l) for l in open(os.path.join(RAW, 'candidates.jsonl'))]
    # unique by (repo, path); keep all routes/queries; prefer a non-empty ref
    uniq = {}
    for c in cands:
        k = (c['repo'], c['path'])
        u = uniq.setdefault(k, dict(repo=c['repo'], path=c['path'], ref=c['ref'], routes=set(), queries=set(), fork=c.get('fork'), description=c.get('description')))
        u['routes'].add(c['route']); u['queries'].add(c['query'])
        if not u['ref'] and c['ref']: u['ref'] = c['ref']
        if c['route'] == 'github-code-search': u['fork'] = c.get('fork'); u['description'] = c.get('description'); u['ref'] = c['ref'] or u['ref']
    # only plausible extensions are fetched
    todo = [u for u in uniq.values() if os.path.splitext(u['path'])[1].lower() in ('.json', '.yml', '.yaml', '.toml')]
    print('candidates', len(cands), 'unique(repo,path)', len(uniq), 'fetchable', len(todo), flush=True)
    rows = []
    with ThreadPoolExecutor(12) as ex:
        for c, data, url, err in ex.map(fetch, todo):
            row = dict(repo=c['repo'], path=c['path'], ref=c['ref'] or 'HEAD', url=url, routes=';'.join(sorted(c['routes'])),
                       n_queries=len(c['queries']), fetched_at=TODAY, status=err or 'ok', sha256='', size='', format='', fork_hint=c.get('fork'), description=c.get('description'))
            if data is not None:
                h = hashlib.sha256(data).hexdigest(); row['sha256'] = h; row['size'] = len(data)
                fmt, _ = identify(c['path'], data); row['format'] = fmt
                if fmt in ('flagd', 'flipt', 'goff') or fmt.startswith('out:'):
                    ext = os.path.splitext(c['path'])[1].lower()
                    fn = os.path.join(FILES, h + ext)
                    if not os.path.exists(fn): open(fn, 'wb').write(data)
            rows.append(row)
    # repo metadata for repos that have any matched/out-of-scope file
    cache_fn = os.path.join(RAW, 'repo_meta.json')
    cache = json.load(open(cache_fn)) if os.path.exists(cache_fn) else {}
    need = sorted({r['repo'] for r in rows if r['format'] in ('flagd', 'flipt', 'goff') or r['format'].startswith('out:')})
    for i, repo in enumerate(need):
        repo_meta(repo, cache)
    json.dump(cache, open(cache_fn, 'w'), indent=1, sort_keys=True)
    for r in rows:
        m = cache.get(r['repo'], {})
        r['fork'] = m.get('fork', r['fork_hint']); r['archived'] = m.get('archived'); r['repo_error'] = m.get('error', '')
        r['description'] = m.get('description', r['description'])
        r['provenance'] = provenance(r['repo'], r['path'], r['description']) if r['format'] else ''
        r['fixture_path'] = bool(FIXTURE_RE.search(r['path']))
    rows.sort(key=lambda r: (r['repo'].lower(), r['path']))
    # ---- stricter provenance (post-data clarification, see DECISIONS.md Z-2). Only ever moves files toward 'sample'.
    mirror_fn = os.path.join(RAW, 'mirror_check.json')
    mirror = json.load(open(mirror_fn)) if os.path.exists(mirror_fn) else {}
    matched = [r for r in rows if r['format'] in ('flagd', 'flipt', 'goff')]
    for r in matched:
        owner, name = r['repo'].split('/', 1)
        if owner.lower() in PROVIDER_OWNERS or r['repo'] in mirror: continue
        hit = ''
        if owner.lower() == 'open-feature-forking': hit = 'open-feature/' + name
        else:
            for po in ('open-feature', 'flipt-io', 'thomaspoignant', 'go-feature-flag'):
                q = subprocess.run(['gh', 'api', 'repos/%s/%s' % (po, name), '-q', '.full_name'], capture_output=True, text=True)
                if q.returncode == 0 and q.stdout.strip(): hit = q.stdout.strip(); break
        mirror[r['repo']] = hit
    json.dump(mirror, open(mirror_fn, 'w'), indent=1, sort_keys=True)
    for r in rows:
        r['provenance_prereg'] = r['provenance']
        r['mirror_of'] = mirror.get(r['repo'], '')
        r['provenance_strict'] = ('sample:provider-mirror' if r['mirror_of'] and r['provenance'] == 'non-sample' else r['provenance'])
    grp = {}
    for r in matched: grp.setdefault(r['sha256'], []).append(r)
    for h, g in grp.items():
        if any(x['provenance_strict'].startswith('sample') for x in g):
            for x in g:
                if x['provenance_strict'] == 'non-sample': x['provenance_strict'] = 'sample:duplicate-of-sample'
    # D-2 counting: matched formats, not fork, dedupe by sha256 (first in sort order)
    seen = set()
    for r in rows:
        r['counted'] = False; r['exclusion'] = ''
        if r['format'] not in ('flagd', 'flipt', 'goff'): continue
        if r['fork']: r['exclusion'] = 'fork'; continue
        if r['repo_error']: r['exclusion'] = 'repo-meta-unavailable'; continue
        if r['sha256'] in seen: r['exclusion'] = 'duplicate-bytes'; continue
        seen.add(r['sha256']); r['counted'] = True
    cols = ['counted', 'format', 'provenance_prereg', 'provenance_strict', 'mirror_of', 'fixture_path', 'repo', 'path', 'ref', 'sha256', 'size', 'fetched_at', 'routes', 'n_queries', 'status', 'exclusion', 'fork', 'archived', 'description', 'url']
    with open(os.path.join(BASE, 'inventory.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore'); w.writeheader(); [w.writerow(r) for r in rows]
    print('wrote inventory', len(rows))
main()
