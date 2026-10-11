from pathlib import Path
import hashlib,json,struct
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parent
icons=json.loads((ROOT/"icon-map.json").read_text())
def read_font(path):
    d=path.read_bytes()
    n=struct.unpack_from(">H",d,4)[0]
    tables={}
    for i in range(n):
        tag,checksum,offset,size=struct.unpack_from(">4sIII",d,12+16*i)
        tables[tag.decode()]=d[offset:offset+size]
    cmap=tables["cmap"]; chosen=None
    for i in range(struct.unpack_from(">H",cmap,2)[0]):
        platform,encoding,off=struct.unpack_from(">HHI",cmap,4+i*8)
        fmt=struct.unpack_from(">H",cmap,off)[0]
        if fmt==12: chosen=(fmt,off);break
        if fmt==4: chosen=(fmt,off)
    fmt,off=chosen
    def glyph(cp):
        if fmt==12:
            groups=struct.unpack_from(">I",cmap,off+12)[0]
            for i in range(groups):
                start,end,gid=struct.unpack_from(">III",cmap,off+16+i*12)
                if start<=cp<=end:return gid+cp-start
            return 0
        count=struct.unpack_from(">H",cmap,off+6)[0]//2
        end=off+14;start=end+count*2+2;delta=start+count*2;ro=delta+count*2
        for i in range(count):
            a=struct.unpack_from(">H",cmap,start+2*i)[0];b=struct.unpack_from(">H",cmap,end+2*i)[0]
            if a<=cp<=b:
                shift=struct.unpack_from(">h",cmap,delta+2*i)[0];r=struct.unpack_from(">H",cmap,ro+2*i)[0]
                if not r:return (cp+shift)&65535
                gid=struct.unpack_from(">H",cmap,ro+2*i+r+2*(cp-a))[0]
                return (gid+shift)&65535 if gid else 0
        return 0
    metrics=struct.unpack_from(">H",tables["hhea"],34)[0]
    def advance(cp):
        return struct.unpack_from(">H",tables["hmtx"],min(glyph(cp),metrics-1)*4)[0]
    return glyph,advance,struct.unpack_from(">H",tables["head"],18)[0]
out=[]
for filename in ["jetbrains.ttf","cascadia.ttf","iosevka.ttf"]:
    p=ROOT/"fonts"/filename
    glyph,advance,upm=read_font(p)
    check_chars="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789áéíóúñ¿¡"+''.join(x["nerd"] for x in icons.values())
    missing=[hex(ord(c)) for c in check_chars if not glyph(ord(c))]
    base=advance(ord("M"))
    widths={role:advance(int(item["code"],16)) for role,item in icons.items()}
    assert not missing,(filename,missing)
    assert set(widths.values())=={base},(filename,widths,base)
    out.append({"file":filename,"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"units_per_em":upm,"advance_units":base,"cell_width_at_16px":16*base/upm,"mapped_icons":len(icons),"missing_glyphs":missing,"icons_match_ascii_advance":True})
(ROOT/"font-verification.json").write_text(json.dumps({"checks":out,"scope":"Font cmap presence and hmtx advances; actual terminal cell rendering remains NOT_DEMONSTRATED."},indent=2)+"\n")
# Exact native-font specimen, not an AI typography approximation.
image=Image.new("RGB",(1800,920),"#07090c")
draw=ImageDraw.Draw(image)
label=ImageFont.truetype(str(ROOT/"fonts/jetbrains.ttf"),25,layout_engine=ImageFont.Layout.BASIC)
small=ImageFont.truetype(str(ROOT/"fonts/jetbrains.ttf"),18,layout_engine=ImageFont.Layout.BASIC)
draw.text((35,25),"ISyCode · comparación de fuentes reales",font=label,fill="#f2f6fa")
draw.text((35,65),"Mismo texto · 26 px · iconos Octicons / Seti · sin círculos de estado",font=small,fill="#a9b7c5")
sample=["Configuración · ISyCode","Proveedor  NVIDIA NIM","Modelo     GLM 5.3","src/hello_world.py","0 O 1 l I  {} [] != =>","áéíóú ñ ¿qué cambió?"]
roles=["settings","shield","folder","terminal","copy","skills","check","warning","clock"]
names={"settings":"Configuración","shield":"Permisos","folder":"Archivos","terminal":"Comandos","copy":"Copiar","skills":"Skills disponibles","check":"Completado","warning":"Requiere atención","clock":"En curso"}
for i,(filename,title) in enumerate([("jetbrains.ttf","JetBrains Mono NL"),("cascadia.ttf","Cascadia Code"),("iosevka.ttf","Iosevka Term")]):
    x=35+i*595
    draw.line((x,122,x+550,122),fill="#485965")
    draw.text((x,135),title,font=label,fill="#31dced")
    font=ImageFont.truetype(str(ROOT/"fonts"/filename),26,layout_engine=ImageFont.Layout.BASIC)
    for j,line in enumerate(sample):draw.text((x,194+j*39),line,font=font,fill="#eaf0f5")
    draw.line((x,448,x+550,448),fill="#33414d")
    for j,role in enumerate(roles):
        color="#7fe39d" if role=="check" else "#f2c068" if role=="warning" else "#eaf0f5"
        draw.text((x,469+j*41),icons[role]["nerd"]+"  "+names[role],font=font,fill=color)
draw.text((35,865),"Elección de Danny: Ubuntu Sans Mono · Unicode · 14 px · interlineado 1.3 (en el comparador).",font=small,fill="#a9b7c5")
image.save(ROOT/"font-specimen.png")
print(json.dumps(out))
