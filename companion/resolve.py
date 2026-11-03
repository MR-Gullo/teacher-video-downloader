"""Find a single current HLS master without persisting signed media URLs."""
import concurrent.futures, hashlib, http.client, ipaddress, re, socket, ssl
from urllib.parse import urljoin, urlsplit

LIMIT=24

def public_addresses(url):
    try:
        p=urlsplit(url)
        if p.scheme not in ('https','http') or not p.hostname or p.username or p.password:return []
        addresses=socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM)
        if not addresses or not all(ipaddress.ip_address(a[4][0].split('%')[0]).is_global for a in addresses):return []
        return list(dict.fromkeys(a[4][0] for a in addresses))
    except (ValueError,OSError):return []

def public_target(url):
    return bool(public_addresses(url))

class PinnedConnection(http.client.HTTPConnection):
    def __init__(self,host,port,address,secure):
        super().__init__(host,port,timeout=8);self.address=address;self.secure=secure
    def connect(self):
        sock=socket.create_connection((self.address,self.port),self.timeout)
        try:self.sock=ssl.create_default_context().wrap_socket(sock,server_hostname=self.host) if self.secure else sock
        except Exception:sock.close();raise

def fetch(url):
    # Resolve once, then connect only to that validated address. Redirects repeat
    # validation and TLS still verifies the original hostname. Never use proxies.
    for _ in range(4):
        addresses=public_addresses(url)
        if not addresses:return None
        p=urlsplit(url);connection=PinnedConnection(p.hostname,p.port or (443 if p.scheme=='https' else 80),addresses[0],p.scheme=='https')
        try:
            target=p.path or '/'
            if p.query:target+='?'+p.query
            connection.request('GET',target,headers={'User-Agent':'Mozilla/5.0','Accept':'application/vnd.apple.mpegurl, application/x-mpegURL, */*'})
            response=connection.getresponse()
            if response.status in (301,302,303,307,308):
                location=response.getheader('Location')
                if not location:return None
                url=urljoin(url,location);continue
            if response.status!=200:return None
            body=response.read(1024*1024+1)
            if len(body)>1024*1024:return None
            return body.decode('utf-8','replace'),url
        except (OSError,ValueError,http.client.HTTPException):return None
        finally:connection.close()
    return None

def parse(url,body):
    if not body or not body.lstrip().startswith('#EXTM3U'):return None
    if re.search(r'#EXT-X-(?:SESSION-)?KEY\s*:[^\r\n]*METHOD=(?!NONE(?:,|\s|$))',body,re.I):return None
    lines=[x.strip() for x in body.splitlines()];children=[]
    for i,line in enumerate(lines):
        if line.startswith('#EXT-X-STREAM-INF:'):
            h=re.search(r'RESOLUTION=(\d+)x(\d+)',line,re.I)
            for nextline in lines[i+1:]:
                if nextline and not nextline.startswith('#'):
                    children.append((urljoin(url,nextline),min(int(h.group(1)),int(h.group(2))) if h else None));break
    durations=[float(x) for x in re.findall(r'#EXTINF:\s*([0-9.]+)',body)]
    return {'children':children,'duration':sum(durations) if durations and '#EXT-X-ENDLIST' in body else None}

def resolve(candidates,duration,limit=720,fetcher=fetch):
    if not isinstance(candidates,list) or not isinstance(duration,(int,float)) or not 10<=duration<=86400:return None
    urls=list(dict.fromkeys(x for x in candidates[:LIMIT] if isinstance(x,str) and len(x)<=8192 and re.search(r'\.m3u8(?:[?#]|$)',x,re.I)))
    if not urls:return None
    def get(items):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(fetcher,items))
        return {u:(v if isinstance(v,tuple) else (v,u)) for u,v in zip(items,results)}
    docs=get(urls)
    records={u:parse(final,body) for u,(body,final) in docs.items()}
    # Fetch bounded master variants, including the playing 1080p rendition, so
    # an observed playing playlist can be proven to belong to the master even
    # when the desired 720p rendition was never requested by the page.
    children=list(dict.fromkeys(child for r in records.values() if r for child,_ in r['children']))
    if len(children)>LIMIT:return None
    missing=[u for u in children if u not in docs]
    docs.update(get(missing));records.update({u:parse(final,body) for u,(body,final) in docs.items() if u not in records})
    observed={hashlib.sha256(body.encode()).digest() for u,(body,_) in docs.items() if u in urls and body and records.get(u) and records[u]['duration'] and abs(records[u]['duration']-duration)<=max(4,duration*.005)}
    if not observed:return None
    matches=[]
    for master in urls:
        record=records.get(master)
        if not record or not record['children']:continue
        linked=[];eligible=[]
        for child,resolution in record['children']:
            item=records.get(child);body=docs.get(child,(None,None))[0]
            if not item or not item['duration'] or not body or abs(item['duration']-duration)>max(4,duration*.005):continue
            fingerprint=hashlib.sha256(body.encode()).digest();linked.append(fingerprint)
            if resolution and resolution<=limit:eligible.append((resolution,fingerprint))
        if eligible and any(h in observed for h in linked):matches.append((master,frozenset(eligible)))
    if len(matches)==1:return matches[0][0]
    # Alias masters are equivalent only when their validated capped variants
    # have the same resolutions and byte-identical playlists.
    if matches and len({variants for _,variants in matches})==1:return matches[0][0]
    return None
