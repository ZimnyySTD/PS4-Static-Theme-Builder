from __future__ import annotations
import json, os, re, shutil, struct, subprocess, sys, uuid, zipfile
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

try:
    from PIL import Image, ImageTk, ImageOps, ImageDraw
except Exception:
    Image = ImageTk = ImageOps = ImageDraw = None

APP = "PS4 Static Theme Studio"
# Names are the exact literals the PS4 looks for in texture/content_icon/.
CONTENT_SLOTS = [
    "browser", "disc", "discoverlay", "folder", "gallery", "library",
    "livefromps", "shareplay", "tvvideo", "usbmusic"
]
FUNCTION_SLOTS = ["community", "event", "friend", "message", "notification", "party", "power", "setting", "trophy"]
THEME_COLORS = ["Blue", "Pink", "Red", "Navy", "Dark Gray", "Gold", "Light Steel Blue", "Purple"]
THEME_COLOR_VALUES = list(range(8))
IMAGE_SLOTS = {
    "Home background": ("texture/background/homescreen.png", (1920,1080), ("png","jpg","jpeg")),
    "Function screen background": ("texture/background/functionscreen.png", (1920,1080), ("png","jpg","jpeg")),
    "Theme preview": ("texture/preview.png", (740,416), ("png","jpg","jpeg")),
    "Theme icon (icon0)": ("sce_sys/icon0.png", (512,512), ("png","jpg","jpeg")),
    "Package image (pic1)": ("sce_sys/pic1.png", (1920,1080), ("png","jpg","jpeg")),
}
AUDIO_SLOTS = {
    "Home background music": ("sound/bgm_home.at9", ".at9"),
    "Decide sound": ("sound/se_decide.vag", ".vag"),
    "Cursor sound": ("sound/se_cursor.vag", ".vag"),
    "Cancel sound": ("sound/se_cancel.vag", ".vag"),
}

def safe_folder(s):
    return re.sub(r'[^\w.-]+', '_', s.strip(), flags=re.UNICODE).strip("._") or "PS4_Theme"

TITLE_ID_RE = re.compile(r"^[A-Z]{4}[0-9]{5}$")
CONTENT_ID_RE = re.compile(r"^[A-Z0-9]{6}-[A-Z]{4}[0-9]{5}_00-[A-Z0-9]{16}$")

def make_title_id(name):
    """Create a valid XXXXYYYYY Title ID from the theme name."""
    token = re.sub(r"[^A-Z0-9]", "", name.upper())
    digest = sum((i + 1) * ord(ch) for i, ch in enumerate(token)) if token else 1
    return f"CUSA{(digest % 100000):05d}"

def make_content_id(name, title_id="CUSA00000"):
    # Canonical custom-theme layout: XXXXXX-TITLEID_00-16-character label.
    title_id = title_id.strip().upper() if TITLE_ID_RE.fullmatch(title_id.strip().upper()) else "CUSA00000"
    label = re.sub(r"[^A-Z0-9]", "", name.upper())[:16]
    label = (label or "THEME").ljust(16, "0")
    return f"UP9000-{title_id}_00-{label}"

def sfo_build(entries):
    """Build a PARAM.SFO binary using the documented PSF 1.1 table layout."""
    # entries: name -> (format, value, max_len); format 0x0204 utf8, 0x0404 uint32
    keys = bytearray()
    data = bytearray()
    index = []
    ordered = sorted(entries.items())
    for key, (fmt, value, max_len) in ordered:
        key_off = len(keys)
        keys += key.encode("utf-8") + b"\0"
        if fmt == 0x0404:
            raw = struct.pack("<I", int(value))
            used_len = 4
        else:
            text = str(value).encode("utf-8")
            raw = text[:int(max_len)-1].ljust(int(max_len)-1, b"\0") + b"\0"
            used_len = min(len(text) + 1, int(max_len))
        data_off = len(data)
        index.append((key_off, fmt, used_len, max(int(max_len), len(raw)), data_off))
        data += raw
        while len(data) % 4:
            data += b"\0"
    header_size = 0x14
    index_size = len(index) * 0x10
    key_start = header_size + index_size
    data_start = (key_start + len(keys) + 3) & ~3
    out = bytearray(struct.pack("<4sIIII", b"\0PSF", 0x00000101, key_start, data_start, len(index)))
    for key_off, fmt, length, max_len, data_off in index:
        out += struct.pack("<HHIII", key_off, fmt, length, max_len, data_off)
    out += keys
    while len(out) < data_start:
        out += b"\0"
    out += data
    return bytes(out)

def make_gp4(image0: Path, out_file: Path, content_id: str):
    import xml.etree.ElementTree as ET
    root = ET.Element("psproject", {"fmt":"gp4","version":"1000"})
    volume = ET.SubElement(root,"volume")
    ET.SubElement(volume,"volume_type").text = "pkg_ps4_theme"
    ET.SubElement(volume,"volume_id").text = ""
    ET.SubElement(volume,"volume_ts").text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ET.SubElement(volume,"package", {"content_id":content_id,"passcode":"0"*32})
    files=ET.SubElement(root,"files",{"img_no":"0"})
    for p in sorted(image0.rglob("*")):
        if p.is_file():
            rel=p.relative_to(image0).as_posix()
            orig=str(p.resolve()).replace("/","\\")
            ET.SubElement(files,"file",{"targ_path":rel,"orig_path":orig})
    rd=ET.SubElement(root,"rootdir")
    for d in ["sce_sys","texture","sound","scene"]:
        ET.SubElement(rd,"dir",{"targ_name":d})
    ET.indent(root, space="  ")
    out_file.write_bytes(b'<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n'+ET.tostring(root,encoding="utf-8"))

class Studio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP)
        self.geometry("1100x790")
        self.minsize(900,680)
        self.configure(bg="#111722")
        self.images = {k:"" for k in IMAGE_SLOTS}
        self.content = {k:"" for k in CONTENT_SLOTS}
        self.function = {k:"" for k in FUNCTION_SLOTS}
        self.audio = {k:"" for k in AUDIO_SLOTS}
        self.project_path = None
        self._style()
        self._ui()
        self._refresh_tool_status()

    def _style(self):
        st=ttk.Style(self)
        try: st.theme_use("clam")
        except: pass
        st.configure(".",font=("Segoe UI",10))
        st.configure("TFrame",background="#111722")
        st.configure("Panel.TFrame",background="#1c2635")
        st.configure("TLabel",background="#111722",foreground="#edf2fa")
        st.configure("Muted.TLabel",background="#111722",foreground="#a8b4c7")
        st.configure("Panel.TLabel",background="#1c2635",foreground="#edf2fa")
        st.configure("TButton",padding=7)
        st.configure("Accent.TButton",background="#5878ed",foreground="white",padding=9)
        st.configure("TNotebook",background="#111722",borderwidth=0)
        st.configure("TNotebook.Tab",padding=(14,9))
        st.configure("TEntry",padding=6)
        st.configure("TCombobox",padding=5)

    def _ui(self):
        top=ttk.Frame(self,padding=(20,14)); top.pack(fill="x")
        ttk.Label(top,text="PS4 STATIC THEME STUDIO",font=("Segoe UI",18,"bold")).pack(anchor="w")
        ttk.Label(top,text="Build a static theme workspace, validate assets, and prepare a GP4 project",style="Muted.TLabel").pack(anchor="w",pady=(2,0))
        ttk.Label(top,text="Made by FernyOven",style="Muted.TLabel").pack(anchor="e",side="bottom")
        bar=ttk.Frame(self,padding=(18,0,18,10)); bar.pack(fill="x")
        ttk.Button(bar,text="New project",command=self.new_project).pack(side="left")
        ttk.Button(bar,text="Open project",command=self.open_project).pack(side="left",padx=6)
        ttk.Button(bar,text="Save project",command=self.save_project).pack(side="left")
        self.tool_label=ttk.Label(bar,text="",style="Muted.TLabel"); self.tool_label.pack(side="right")
        self.tabs=ttk.Notebook(self); self.tabs.pack(fill="both",expand=True,padx=18,pady=(0,12))
        self.meta_tab=ttk.Frame(self.tabs,padding=18)
        self.bg_tab=ttk.Frame(self.tabs,padding=18)
        self.icons_tab=ttk.Frame(self.tabs,padding=18)
        self.audio_tab=ttk.Frame(self.tabs,padding=18)
        self.look_tab=ttk.Frame(self.tabs,padding=18)
        self.export_tab=ttk.Frame(self.tabs,padding=18)
        for t,n in [(self.meta_tab,"Details"),(self.bg_tab,"Backgrounds"),(self.icons_tab,"Icons"),(self.audio_tab,"Audio"),(self.look_tab,"Appearance"),(self.export_tab,"Build & Export")]:
            self.tabs.add(t,text=n)
        self._meta_ui(); self._background_ui(); self._icons_ui(); self._audio_ui(); self._look_ui(); self._export_ui()

    def section(self,parent,title,desc):
        ttk.Label(parent,text=title,font=("Segoe UI",13,"bold")).pack(anchor="w",pady=(0,4))
        ttk.Label(parent,text=desc,style="Muted.TLabel",wraplength=900).pack(anchor="w",pady=(0,12))

    def _meta_ui(self):
        self.section(self.meta_tab,"Theme information","The Content ID is generated from the theme name. You can edit it if you need a specific identifier.")
        self.name=tk.StringVar(value="My PS4 Theme")
        self.version=tk.StringVar(value="01.00")
        self.author=tk.StringVar(value="")
        self.titleid=tk.StringVar(value=make_title_id(self.name.get()))
        self.cid=tk.StringVar(value=make_content_id(self.name.get(),self.titleid.get()))
        self._suppress_id_sync=False
        self.name.trace_add("write",lambda *_:self._sync_name_id())
        self.titleid.trace_add("write",lambda *_:self._sync_generated_ids())
        self.vars=[("Theme name",self.name),("Version",self.version),("Author / provider",self.author),("Title ID (CUSA + 5 digits)",self.titleid),("Content ID",self.cid)]
        grid=ttk.Frame(self.meta_tab); grid.pack(fill="x")
        for i,(label,var) in enumerate(self.vars):
            ttk.Label(grid,text=label,width=22).grid(row=i,column=0,sticky="w",pady=8)
            ttk.Entry(grid,textvariable=var).grid(row=i,column=1,sticky="ew",pady=8)
        grid.columnconfigure(1,weight=1)
        row=ttk.Frame(self.meta_tab); row.pack(anchor="w",pady=8)
        ttk.Button(row,text="Regenerate Content ID",command=self.regenerate_id).pack(side="left")
        ttk.Label(self.meta_tab,text="A locally generated ID is a project identifier, not a Sony-issued entitlement. Keep the same ID in PARAM.SFO and GP4.",style="Muted.TLabel",wraplength=850).pack(anchor="w",pady=10)

    def _sync_name_id(self):
        if getattr(self,"_suppress_id_sync",False):
            return
        name=self.name.get().strip()
        title=self.titleid.get().strip().upper()
        if not TITLE_ID_RE.fullmatch(title):
            title=make_title_id(name)
            self._suppress_id_sync=True
            self.titleid.set(title)
            self._suppress_id_sync=False
        self.cid.set(make_content_id(name,title))

    def _sync_generated_ids(self):
        if getattr(self,"_suppress_id_sync",False):
            return
        name=self.name.get().strip()
        title=(self.titleid.get().strip().upper())
        if not TITLE_ID_RE.fullmatch(title):
            return
        self.cid.set(make_content_id(name,title))

    def regenerate_id(self):
        title=make_title_id(self.name.get())
        self._suppress_id_sync=True
        self.titleid.set(title)
        self._suppress_id_sync=False
        self.cid.set(make_content_id(self.name.get(),title))

    def _browse_row(self,parent,label,key,desc,store,types=None):
        row=ttk.Frame(parent); row.pack(fill="x",pady=5)
        ttk.Label(row,text=label,width=29).pack(side="left")
        var=tk.StringVar(value=store.get(key,""))
        ttk.Entry(row,textvariable=var,state="readonly").pack(side="left",fill="x",expand=True,padx=8)
        def browse():
            ftypes=types or [("Images / audio","*.png *.jpg *.jpeg *.wav *.mp3 *.ogg *.at9 *.vag"),("All files","*.*")]
            p=filedialog.askopenfilename(title=f"Choose {label}",filetypes=ftypes)
            if p:
                store[key]=p; var.set(p); self.validate_one(label,p)
        ttk.Button(row,text="Browse",command=browse).pack(side="left")
        ttk.Button(row,text="Clear",command=lambda:(store.__setitem__(key,""),var.set(""))).pack(side="left",padx=(5,0))
        ttk.Label(parent,text=desc,style="Muted.TLabel").pack(anchor="w",padx=(29,0))

    def validate_one(self,label,path):
        if Image and label in [*IMAGE_SLOTS]:
            try:
                with Image.open(path) as im:
                    expected=IMAGE_SLOTS[label][1]
                    if im.size!=expected:
                        self.status_msg(f"{label}: {im.width}×{im.height}; export will resize to {expected[0]}×{expected[1]}.")
            except Exception as e: messagebox.showwarning("Image validation",str(e))

    def _background_ui(self):
        self.section(self.bg_tab,"Theme images","Static PS4 theme backgrounds use 1920×1080 images. The list preview is 740×416. Missing function background and listing assets are derived from the home background.")
        for label,(dest,size,exts) in IMAGE_SLOTS.items():
            self._browse_row(self.bg_tab,label,label,f"Target: {dest} · {size[0]}×{size[1]}",self.images,[(f"{'/'.join(exts).upper()} images"," ".join("*."+e for e in exts)),("All files","*.*")])
        ttk.Label(self.bg_tab,text="Image processing uses Pillow: images are center-cropped to fill the target size and saved as PNG. Install requirements for this feature.",style="Muted.TLabel").pack(anchor="w",pady=10)

    def _icons_ui(self):
        self.section(self.icons_tab,"Individual icon slots","Content icons are 512×512. Function icons are 128×128 and get matching 152×152 glow files. Leave slots empty to keep the PS4 system default icon.")
        canvas=tk.Canvas(self.icons_tab,bg="#111722",highlightthickness=0)
        sb=ttk.Scrollbar(self.icons_tab,orient="vertical",command=canvas.yview)
        body=ttk.Frame(canvas); body.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0),window=body,anchor="nw"); canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left",fill="both",expand=True); sb.pack(side="right",fill="y")
        for heading,slots,store in [("Content area icons",CONTENT_SLOTS,self.content),("Function area icons",FUNCTION_SLOTS,self.function)]:
            ttk.Label(body,text=heading,font=("Segoe UI",12,"bold")).pack(anchor="w",pady=(10,6))
            for slot in slots:
                self._browse_row(body,slot.replace("_"," ").title(),slot,"PNG preferred; converted to PNG at export.",store,[("Image files","*.png *.jpg *.jpeg"),("All files","*.*")])

    def _audio_ui(self):
        self.section(self.audio_tab,"Home music and system effects","The PS4 expects ATRAC9 .at9 for home BGM and VAG/PS-ADPCM .vag for effects. This build accepts already-converted files and validates the extensions; it does not pretend to convert arbitrary audio.")
        for label,(dest,ext) in AUDIO_SLOTS.items():
            self._browse_row(self.audio_tab,label,label,f"Required output: {dest} · accepted: {ext}",self.audio,[(f"{ext} files","*"+ext),("All files","*.*")])
        ttk.Label(self.audio_tab,text="Audio must be encoded for PS4 compatibility (commonly 48 kHz). Use the optional Sony at9tool for ATRAC9 conversion and a compatible VAG encoder for effects.",style="Muted.TLabel",wraplength=850).pack(anchor="w",pady=14)

    def _look_ui(self):
        self.section(self.look_tab,"Theme appearance","Set the system theme color and interface text/focus colors. Values are stored in theme.xml.")
        self.theme_color=tk.StringVar(value="Blue")
        self.font_color=tk.StringVar(value="#FFFFFFFF")
        self.shadow_color=tk.StringVar(value="#80000000")
        self.focus_color=tk.StringVar(value="#FF00BAFF")
        self.dimmer_color=tk.StringVar(value="#80000000")
        row=ttk.Frame(self.look_tab); row.pack(fill="x",pady=8)
        ttk.Label(row,text="System theme color",width=25).pack(side="left")
        ttk.Combobox(row,textvariable=self.theme_color,values=THEME_COLORS,state="readonly",width=25).pack(side="left")
        for label,var in [("Font color",self.font_color),("Font shadow color",self.shadow_color),("Focus color",self.focus_color),("Dimmer color",self.dimmer_color)]:
            r=ttk.Frame(self.look_tab); r.pack(fill="x",pady=6)
            ttk.Label(r,text=label,width=25).pack(side="left")
            ttk.Entry(r,textvariable=var,width=20).pack(side="left")
            ttk.Button(r,text="Choose",command=lambda v=var:self.pick_color(v)).pack(side="left",padx=8)
            ttk.Label(r,text="ARGB hex, e.g. #FFFFFFFF",style="Muted.TLabel").pack(side="left")
        self.bgm_enabled=tk.BooleanVar(value=True)
        ttk.Checkbutton(self.look_tab,text="Enable custom home BGM when a valid .at9 file is included",variable=self.bgm_enabled).pack(anchor="w",pady=12)

    def pick_color(self,var):
        c=colorchooser.askcolor()[1]
        if c: var.set("#FF"+c[1:].upper())

    def _export_ui(self):
        self.section(self.export_tab,"Validate and build","Builds the console-oriented theme directory (Image0), PARAM.SFO, theme.xml, GP4 project and a ZIP. A final installable PKG still requires the external PS4 Publishing Tools.")
        self.output=tk.StringVar(value=str(Path.home()/"PS4_Theme_Exports"))
        r=ttk.Frame(self.export_tab); r.pack(fill="x",pady=6)
        ttk.Entry(r,textvariable=self.output).pack(side="left",fill="x",expand=True)
        ttk.Button(r,text="Choose output",command=self.choose_output).pack(side="left",padx=7)
        self.report=tk.Text(self.export_tab,height=12,bg="#0c111a",fg="#dce6f7",insertbackground="white",relief="flat",wrap="word")
        self.report.pack(fill="both",expand=True,pady=12)
        actions=ttk.Frame(self.export_tab); actions.pack(fill="x")
        ttk.Button(actions,text="Validate project",command=self.validate_project).pack(side="left")
        ttk.Button(actions,text="Build theme + GP4 + ZIP",style="Accent.TButton",command=self.build).pack(side="left",padx=8)
        ttk.Button(actions,text="Open output folder",command=self.open_output).pack(side="right")

    def choose_output(self):
        p=filedialog.askdirectory()
        if p:self.output.set(p)

    def status_msg(self,msg):
        if hasattr(self,"report"):
            self.report.insert("end",msg+"\n"); self.report.see("end")

    def validate_project(self):
        self.report.delete("1.0","end")
        errors=[]; warnings=[]
        if not self.name.get().strip(): errors.append("Theme name is required.")
        if not re.fullmatch(r"\d{2}\.\d{2}",self.version.get().strip()): warnings.append("Version should normally look like 01.00.")
        cid=self.cid.get().strip()
        if not CONTENT_ID_RE.fullmatch(cid):
            errors.append("Content ID format must be XXXXXX-CUSA00000_00-16CHARACTERS.")
        titleid=self.titleid.get().strip().upper()
        if not TITLE_ID_RE.fullmatch(titleid):
            errors.append("Title ID must be 4 uppercase letters followed by 5 digits, such as CUSA00000.")
        if titleid not in cid:
            errors.append("Content ID must contain the same Title ID.")
        for label,var in [("Font color",self.font_color),("Font shadow color",self.shadow_color),("Focus color",self.focus_color),("Dimmer color",self.dimmer_color)]:
            if not re.fullmatch(r"#[0-9A-Fa-f]{8}",var.get().strip()):
                errors.append(f"{label} must be an 8-digit ARGB hex value, such as #FFFFFFFF.")
        if not self.images.get("Home background"): errors.append("Home background is required for a static theme.")
        for label,p in self.images.items():
            if p and not Path(p).is_file(): errors.append(f"Missing image file: {label}")
        for label,p in self.audio.items():
            if p:
                ext=AUDIO_SLOTS[label][1]
                if Path(p).suffix.lower()!=ext: errors.append(f"{label} must be {ext}")
                if not Path(p).is_file(): errors.append(f"Missing audio file: {label}")
        for label,p in [*self.content.items(),*self.function.items()]:
            if p and not Path(p).is_file(): errors.append(f"Missing icon file: {label}")
        for e in errors:self.status_msg("ERROR  "+e)
        for w in warnings:self.status_msg("WARN   "+w)
        if not errors:self.status_msg("PASS   Basic metadata and file checks passed.")
        if not Image:self.status_msg("WARN   Pillow not installed: install requirements.txt to resize/convert images.")
        self.status_msg(f"Assets selected: {sum(bool(x) for x in self.images.values())} backgrounds/listing images, {sum(bool(x) for x in self.content.values())+sum(bool(x) for x in self.function.values())} icons, {sum(bool(x) for x in self.audio.values())} audio files.")
        return not errors

    def _save_png(self,src,dest,size):
        if not Image: raise RuntimeError("Pillow is required. Run: pip install -r requirements.txt")
        dest.parent.mkdir(parents=True,exist_ok=True)
        with Image.open(src) as im:
            im=ImageOps.exif_transpose(im).convert("RGBA")
            im=ImageOps.fit(im,size,method=Image.Resampling.LANCZOS,centering=(0.5,0.5))
            # Console theme images are exported as RGB PNG for broad compatibility.
            bg=Image.new("RGB",size,(0,0,0)); bg.paste(im,mask=im.getchannel("A"))
            bg.save(dest,"PNG",optimize=True)

    def _xml(self,root):
        import xml.etree.ElementTree as ET
        theme=ET.Element("theme")
        label=re.sub(r"[^A-Za-z0-9_-]","-",self.name.get().strip())[:64].strip("-") or "custom-theme"
        values=[
            ("format-version","4.0"),("themecolor",str(THEME_COLORS.index(self.theme_color.get()))),
            ("label",label),
            ("fontcolor",self.font_color.get()),("fontshadowcolor",self.shadow_color.get()),
            ("focuscolor",self.focus_color.get()),
            ("homescreen-dimmer","#00FFFFFF"),("functionscreen-dimmer","#00FFFFFF"),
            ("titlename-dimmer","#00FFFFFF"),
            ("homebgm-enable","True" if self.bgm_enabled.get() and self.audio.get("Home background music") else "False")
        ]
        for k,v in values: ET.SubElement(theme,k).text=v
        ET.indent(theme,space="  ")
        (root/"theme.xml").write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n'+ET.tostring(theme,encoding="utf-8"))

    def _sfo(self,root):
        entries={
            "ATTRIBUTE":(0x0404,0,4),
            "CATEGORY":(0x0204,"ac",4),
            "CONTENT_ID":(0x0204,self.cid.get().strip(),48),
            "FORMAT":(0x0204,"obs",4),
            "TITLE":(0x0204,self.name.get().strip(),128),
            "TITLE_ID":(0x0204,self.titleid.get().strip().upper(),12),
            "VERSION":(0x0204,self.version.get().strip(),8),
            "IRO_TAG":(0x0404,2,4),
            "CONTENT_VER":(0x0204,self.version.get().strip(),8),
        }
        pubinfo=f"c_date={datetime.now().strftime('%Y%m%d')}"
        if self.audio.get("Home background music"):
            pubinfo += ",bgmhome_loud=-36.48"
        entries["PUBTOOLINFO"]=(0x0204,pubinfo,512)
        p=root/"sce_sys"/"param.sfo"; p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(sfo_build(entries))
        return p

    def build(self):
        if not self.validate_project(): 
            messagebox.showerror("Validation failed","Fix the errors listed in the validation panel."); return
        if not Image:
            messagebox.showerror("Missing dependency","Install Pillow first:\n\npip install -r requirements.txt"); return
        out=Path(self.output.get())/safe_folder(self.name.get())
        image0=out/"Image0"
        try:
            if out.exists(): shutil.rmtree(out)
            (image0/"sce_sys").mkdir(parents=True)
            (image0/"texture"/"background").mkdir(parents=True)
            (image0/"texture"/"content_icon").mkdir(parents=True)
            (image0/"texture"/"function_icon").mkdir(parents=True)
            (image0/"sound").mkdir(parents=True)
            # Home wallpaper is mandatory; absent function screen falls back to home.
            home=self.images["Home background"]
            self._save_png(home,image0/"texture/background/homescreen.png",(1920,1080))
            func=self.images.get("Function screen background") or home
            self._save_png(func,image0/"texture/background/functionscreen.png",(1920,1080))
            # Use home image as default theme listing art and icon if not separately supplied.
            preview=self.images.get("Theme preview") or home
            icon=self.images.get("Theme icon (icon0)") or home
            pic1=self.images.get("Package image (pic1)") or home
            self._save_png(preview,image0/"texture/preview.png",(740,416))
            self._save_png(icon,image0/"sce_sys/icon0.png",(512,512))
            self._save_png(pic1,image0/"sce_sys/pic1.png",(1920,1080))
            for slot,p in self.content.items():
                if p:self._save_png(p,image0/f"texture/content_icon/{slot}.png",(512,512))
            for slot,p in self.function.items():
                if p:
                    self._save_png(p,image0/f"texture/function_icon/{slot}.png",(128,128))
                    self._save_png(p,image0/f"texture/function_icon/{slot}_glow.png",(152,152))
            for label,p in self.audio.items():
                if p:
                    dest=image0/AUDIO_SLOTS[label][0]; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,dest)
            self._xml(image0)
            self._sfo(image0)
            gp4=out/(safe_folder(self.name.get())+".gp4")
            make_gp4(image0,gp4,self.cid.get().strip())
            manifest={
                "name":self.name.get(),"version":self.version.get(),"author":self.author.get(),
                "content_id":self.cid.get(),"title_id":self.titleid.get(),
                "theme_color":self.theme_color.get(),"image0":"Image0",
                "gp4":gp4.name,"package_type":"pkg_ps4_theme",
                "packaging_note":"Open GP4 in a compatible Orbis Publishing Tools GUI and build. Proprietary Sony tools are not included."
            }
            (out/"project.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
            readme=f"""PS4 STATIC THEME BUILD

Theme: {self.name.get()}
Version: {self.version.get()}
Author: {self.author.get()}
Content ID: {self.cid.get()}

OUTPUT
- Image0/: theme image tree
- Image0/theme.xml: theme descriptor
- Image0/sce_sys/param.sfo: generated SFO metadata
- {gp4.name}: GP4 project manifest
- project.json: Studio project metadata

BUILD
Open the GP4 in a compatible PS4 Publishing Tools / orbis-pub-gen installation and build the package.
This application does not bundle proprietary Sony publishing binaries.
Ensure your local toolchain supports volume_type pkg_ps4_theme and verify the output with the corresponding package checker before installing.

FORMAT
Home/function background 1920x1080; preview 740x416; icon0 512x512;
content icons 512x512; function icons 128x128 + generated 152x152 glow.
Home music must be ATRAC9 .at9; effects must be .vag. Files are copied as-is.
"""
            (out/"BUILD_README.txt").write_text(readme,encoding="utf-8")
            zipfile_path=out.parent/(out.name+"_theme_build.zip")
            with zipfile.ZipFile(zipfile_path,"w",zipfile.ZIP_DEFLATED) as z:
                for f in out.rglob("*"):
                    if f.is_file(): z.write(f,f.relative_to(out.parent))
            self.status_msg("")
            self.status_msg("BUILD COMPLETE")
            self.status_msg(str(out))
            self.status_msg("GP4: "+str(gp4))
            self.status_msg("ZIP: "+str(zipfile_path))
            self.status_msg("NOTE: GP4 generated; final PKG build requires compatible external publishing tools.")
            messagebox.showinfo("Build complete",f"Theme folder, PARAM.SFO, GP4 and ZIP created.\n\n{out}\n\n{zipfile_path}")
        except Exception as e:
            messagebox.showerror("Build failed",str(e)); self.status_msg("BUILD FAILED: "+str(e))

    def _refresh_tool_status(self):
        candidates=["orbis-pub-cmd.exe","orbis-pub-gen.exe","orbis-pub-sfo.exe","at9tool.exe"]
        found=[x for x in candidates if (Path("tools")/x).exists()]
        self.tool_label.configure(text="Tools: "+(", ".join(found) if found else "external package tools not configured"))

    def save_project(self):
        p=filedialog.asksaveasfilename(defaultextension=".json",filetypes=[("Theme project","*.json")])
        if not p:return
        data={"name":self.name.get(),"version":self.version.get(),"author":self.author.get(),"content_id":self.cid.get(),"title_id":self.titleid.get(),
              "images":self.images,"content":self.content,"function":self.function,"audio":self.audio,
              "appearance":{"theme_color":self.theme_color.get(),"font_color":self.font_color.get(),"shadow_color":self.shadow_color.get(),"focus_color":self.focus_color.get(),"dimmer_color":self.dimmer_color.get(),"bgm_enabled":self.bgm_enabled.get()}}
        Path(p).write_text(json.dumps(data,indent=2),encoding="utf-8")
        self.project_path=p; self.status_msg("Project saved: "+p)

    def open_project(self):
        p=filedialog.askopenfilename(filetypes=[("Theme project","*.json")])
        if not p:return
        try:
            d=json.loads(Path(p).read_text(encoding="utf-8"))
            self._suppress_id_sync=True
            for k,v in [("name","name"),("version","version"),("author","author"),("title_id","titleid"),("content_id","cid")]:
                getattr(self,v).set(d.get(k,""))
            self._suppress_id_sync=False
            for k in self.images:self.images[k]=d.get("images",{}).get(k,"")
            for k in self.content:self.content[k]=d.get("content",{}).get(k,"")
            for k in self.function:self.function[k]=d.get("function",{}).get(k,"")
            for k in self.audio:self.audio[k]=d.get("audio",{}).get(k,"")
            a=d.get("appearance",{})
            for k,var in [("theme_color",self.theme_color),("font_color",self.font_color),("shadow_color",self.shadow_color),("focus_color",self.focus_color),("dimmer_color",self.dimmer_color)]:
                if k in a:var.set(a[k])
            self.bgm_enabled.set(a.get("bgm_enabled",True))
            self.project_path=p; self.status_msg("Project loaded: "+p)
            messagebox.showinfo("Project loaded","Project settings loaded. Browse paths are preserved; if files moved, reselect them.")
        except Exception as e:messagebox.showerror("Open failed",str(e))

    def new_project(self):
        if messagebox.askyesno("New project","Clear the current project?"):
            title=make_title_id("My PS4 Theme")
            self._suppress_id_sync=True
            self.name.set("My PS4 Theme"); self.version.set("01.00"); self.author.set(""); self.titleid.set(title)
            self.cid.set(make_content_id("My PS4 Theme",title))
            self._suppress_id_sync=False
            self.images={k:"" for k in IMAGE_SLOTS}; self.content={k:"" for k in CONTENT_SLOTS}; self.function={k:"" for k in FUNCTION_SLOTS}; self.audio={k:"" for k in AUDIO_SLOTS}
            self.status_msg("New project created.")

    def open_output(self):
        p=Path(self.output.get())
        p.mkdir(parents=True,exist_ok=True)
        if sys.platform=="win32": os.startfile(p)
        elif sys.platform=="darwin": subprocess.Popen(["open",str(p)])
        else: subprocess.Popen(["xdg-open",str(p)])

if __name__=="__main__":
    Studio().mainloop()
