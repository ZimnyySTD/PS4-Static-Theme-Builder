import tempfile, struct
from pathlib import Path
from app import sfo_build, make_gp4, make_content_id, make_title_id, CONTENT_SLOTS, TITLE_ID_RE, CONTENT_ID_RE

title_id = make_title_id("My PS4 Theme")
assert TITLE_ID_RE.fullmatch(title_id)
cid = make_content_id("My PS4 Theme", title_id)
assert CONTENT_ID_RE.fullmatch(cid)
assert title_id in cid
assert {"gallery","shareplay","livefromps","tvvideo","usbmusic","discoverlay"} <= set(CONTENT_SLOTS)

s=sfo_build({
    "CATEGORY":(0x0204,"ac",4),
    "CONTENT_ID":(0x0204,cid,48),
    "IRO_TAG":(0x0404,2,4),
    "PROVIDER":(0x0204,"Test Author",128),
})
assert s[:4] == b"\0PSF"
magic,ver,keyoff,dataoff,n=struct.unpack("<4sIIII",s[:20])
assert n==4 and ver==0x101 and keyoff<dataoff
assert b"Test Author" in s
assert keyoff % 4 == 0
assert dataoff % 4 == 0
with tempfile.TemporaryDirectory() as td:
    p=Path(td); (p/"sce_sys").mkdir(); (p/"sce_sys"/"param.sfo").write_bytes(s)
    gp=p/"x.gp4"; make_gp4(p,gp,"IV0000-TEST00001_00-TESTTHEME0000000","Test Theme","Test Author")
    gp_text=gp.read_text(encoding="utf-8")
    assert b"pkg_ps4_theme" in gp.read_bytes()
    assert "Test Author" in gp_text
    assert "chunk_info" not in gp_text
    assert 'storage_type' not in gp_text
print("SFO and GP4 smoke tests passed")
