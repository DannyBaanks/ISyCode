from pathlib import Path
import concurrent.futures,datetime,hashlib,json,urllib.request,time
ROOT=Path(__file__).resolve().parent
NF_REF="ab5d1281ae5a9d4b1fde2d12e45e2e2d6a608620"
HEADERS={"User-Agent":"ISyCode-design-research"}
def fetch(url):
    for attempt in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=20).read()
        except (OSError, urllib.error.URLError):
            if attempt==2: raise
            time.sleep(1)
tabler_ref=json.loads(fetch("https://api.github.com/repos/tabler/tabler-icons/commits/main"))["sha"]
nf="https://raw.githubusercontent.com/ryanoasis/nerd-fonts/"+NF_REF+"/"
tb="https://raw.githubusercontent.com/tabler/tabler-icons/"+tabler_ref+"/"
pairs=[
 ("patched-fonts/JetBrainsMono/NoLigatures/JetBrainsMonoNLNerdFontMono-Regular.ttf","fonts/jetbrains.ttf"),
 ("patched-fonts/CascadiaCode/CaskaydiaCoveNerdFontMono-Regular.ttf","fonts/cascadia.ttf"),
 ("patched-fonts/IosevkaTerm/IosevkaTermNerdFontMono-Regular.ttf","fonts/iosevka.ttf"),
 ("patched-fonts/JetBrainsMono/NoLigatures/OFL.txt","licenses/jetbrains-OFL.txt"),
 ("patched-fonts/CascadiaCode/LICENSE","licenses/cascadia-OFL.txt"),
 ("patched-fonts/IosevkaTerm/LICENSE.md","licenses/iosevka-OFL.md"),
 ("patched-fonts/JetBrainsMono/NoLigatures/README.md","sources/jetbrains-README.md"),
 ("patched-fonts/CascadiaCode/README.md","sources/cascadia-README.md"),
 ("patched-fonts/IosevkaTerm/README.md","sources/iosevka-README.md"),
 ("LICENSE","licenses/nerd-fonts-LICENSE.txt"),
 ("src/glyphs/README.md","sources/nerd-glyphs-README.md"),
 ("license-audit.md","sources/nerd-license-audit.md"),
 ("glyphnames.json","sources/glyphnames.json"),
 ("readme.md","sources/nerd-fonts-README.md")]
records=[]
for source,name in pairs:
    target=ROOT/name
    assert target.is_file(),name
    data=target.read_bytes()
    records.append({"url":nf+source,"file":name,"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data),"provenance":"Downloaded by fetch-assets.py from pinned Nerd Fonts ref before interruption"})
assets=[(tb+"icons/outline/"+name+".svg","icons/tabler/"+name+".svg") for name in
 ["settings","shield-check","plug-connected","code","sparkles","folder","message","terminal-2","copy","clock","check","alert-triangle","x","player-pause","search","bulb","arrows-split","book"]]
assets += [(tb+"LICENSE","licenses/tabler-MIT.txt"),(tb+"README.md","sources/tabler-README.md")]
def complete(item):
    url,name=item
    data=fetch(url)
    target=ROOT/name
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists(): assert target.read_bytes()==data,"Preserve differing existing asset: "+name
    else: target.write_bytes(data)
    return {"url":url,"file":name,"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data),"provenance":"Source equality verified"}
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    for record in pool.map(complete,assets): records.append(record)
for source,name in [
 ("/usr/share/fonts/truetype/ubuntu/UbuntuSansMono[wght].ttf","fonts/ubuntu-current.ttf"),
 ("/usr/share/doc/fonts-ubuntu/copyright","licenses/ubuntu-font-copyright.txt")]:
    data=Path(source).read_bytes()
    target=ROOT/name
    if target.exists(): assert target.read_bytes()==data
    else: target.write_bytes(data)
    records.append({"local_source":source,"file":name,"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data)})
target=ROOT/"asset-sources.json"
assert not target.exists()
target.write_text(json.dumps({"created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"nerd_fonts_ref":NF_REF,"tabler_ref":tabler_ref,"assets":records},indent=2)+"\n")
print(json.dumps({"assets":len(records),"bytes":sum(x["bytes"] for x in records),"tabler_ref":tabler_ref}))
