import tempfile, struct
from pathlib import Path
from app import sfo_build, make_gp4
s=sfo_build({"CATEGORY":(0x0204,"ac",4),"IRO_TAG":(0x0404,2,4)})
assert s[:4] == b"\0PSF"
magic,ver,keyoff,dataoff,n=struct.unpack("<4sIIII",s[:20])
assert n==2 and ver==0x101 and keyoff<dataoff
with tempfile.TemporaryDirectory() as td:
    p=Path(td); (p/"sce_sys").mkdir(); (p/"sce_sys"/"param.sfo").write_bytes(s)
    gp=p/"x.gp4"; make_gp4(p,gp,"IV0000-TEST00001_00-TESTTHEME0000000")
    assert b"pkg_ps4_theme" in gp.read_bytes()
print("SFO and GP4 smoke tests passed")
