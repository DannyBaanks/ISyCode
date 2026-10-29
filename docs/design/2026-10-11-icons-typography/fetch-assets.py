from pathlib import Path
import datetime,hashlib,json,urllib.request,shutil
ROOT=Path(__file__).resolve().parent
NF_REF="ab5d1281ae5a9d4b1fde2d12e45e2e2d6a608620"
HEADERS={"User-Agent":"ISyCode-design-research"}
def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=45).read()
def save(url,name):
    target=ROOT/name
    if target.exists(): raise RuntimeError("Preserve existing file: "+str(target))
    data=fetch(url)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(data)
    records.append({"url":url,"file":name,"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data)})
records=[]
tabler_ref=json.loads(fetch("https://api.github.com/repos/tabler/tabler-icons/commits/main"))["sha"]
nf="https://raw.githubusercontent.com/ryanoasis/nerd-fonts/"+NF_REF+"/"
tabler="https://raw.githubusercontent.com/tabler/tabler-icons/"+tabler_ref+"/"
for source,name in [
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
 ("readme.md","sources/nerd-fonts-README.md"),
]:
    save(nf+source,name)
for name in ["settings","shield-check","plug-connected","code","sparkles","folder","message","terminal-2","copy","clock","check","alert-triangle","x","player-pause","search","bulb","arrows-split","book"]:
    save(tabler+"icons/outline/"+name+".svg","icons/tabler/"+name+".svg")
save(tabler+"LICENSE","licenses/tabler-MIT.txt")
save(tabler+"README.md","sources/tabler-README.md")
for source,name in [
 ("/usr/share/fonts/truetype/ubuntu/UbuntuSansMono[wght].ttf","fonts/ubuntu-current.ttf"),
 ("/usr/share/doc/fonts-ubuntu/copyright","licenses/ubuntu-font-copyright.txt")]:
    target=ROOT/name
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists(): raise RuntimeError("Preserve existing file")
    shutil.copyfile(source,target)
    data=target.read_bytes()
    records.append({"local_source":source,"file":name,"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data)})
(ROOT/"asset-sources.json").write_text(json.dumps({"created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"nerd_fonts_ref":NF_REF,"tabler_ref":tabler_ref,"assets":records},indent=2)+"\n")
glyphs=json.loads((ROOT/"sources/glyphnames.json").read_text())
print(json.dumps({"nerd_ref":NF_REF,"tabler_ref":tabler_ref,"files":len(records),"bytes":sum(x["bytes"] for x in records),"glyph_entries":len(glyphs),"octicon_examples":{k:v for k,v in glyphs.items() if k in ["oct-gear","oct-shield","oct-plug","oct-code","oct-sparkle","oct-file_directory","oct-comment","oct-terminal","oct-copy","oct-clock","oct-check","oct-alert","oct-x","oct-search","oct-light_bulb","oct-git_branch","oct-book"]}},ensure_ascii=False))
