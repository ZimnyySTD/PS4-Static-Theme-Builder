# PS4 Static Theme Studio 2.0

Made by FernyOven

Python desktop editor for assembling PS4 static-theme assets and generating a theme folder, `PARAM.SFO`, `theme.xml`, GP4 manifest and ZIP.

## Run
- Python 3.10+
- Install: `python -m pip install -r requirements.txt`
- Start: `python app.py`

## What it builds
- PS4 theme image tree under `Image0/`
- `texture/background/homescreen.png` and `functionscreen.png` (1920×1080)
- `texture/preview.png` (740×416)
- `sce_sys/icon0.png` (512×512), `sce_sys/pic1.png` (1920×1080)
- Per-slot content icons (512×512)
- Per-slot function icons (128×128) and glow variants (152×152)
- Optional `sound/bgm_home.at9`, `se_decide.vag`, `se_cursor.vag`, `se_cancel.vag`
- `theme.xml`, `sce_sys/param.sfo`, `.gp4`, `project.json`, build README and ZIP

## Image handling
- PNG files are checked and re-encoded as PS4-compatible RGBA PNG textures.
- Background and icon dimensions are validated exactly; function glow files are generated at 152x152 from the 128x128 source without cropping.
- Required dimensions: home/function 1920x1080, preview 740x416, icon0 512x512, pic1 1920x1080, content icons 512x512, function icons 128x128 and glow 152x152.

## Packaging
The generated GP4 uses the canonical `pkg_ps4_theme` volume type and matching Content ID. PARAM.SFO uses `CATEGORY=ac` and `IRO_TAG=2`, the metadata pair used by static themes. Open the GP4 in compatible Orbis Publishing Tools / `orbis-pub-gen` and build the PKG. Sony publishing binaries are proprietary and are not bundled.

## Audio
This app copies already-converted `.at9` and `.vag` files. It does not convert arbitrary MP3/WAV files. Use a compatible ATRAC9 encoder and VAG/PS-ADPCM encoder; the PS4 theme documentation specifies 48 kHz audio.

## Notes
- Title IDs use the PS4 format `CUSA` plus five digits. The Content ID is generated as `UP9000-CUSA00000_00-16CHARACTERS` and must contain the selected Title ID.
- Generated IDs are local project identifiers, not Sony-issued IDs or entitlements.
- Empty icon slots are omitted so the system's defaults can remain.
- Function background falls back to the home background if omitted.
- The project does not create dynamic RAF scenes.
- The output is a build workspace and GP4 manifest, not a guarantee of installability on every firmware/toolchain. Verify the built PKG with the matching package checker.

## References
- ConsoleMods PS4 Custom Themes: https://consolemods.org/wiki/PS4:Custom_Themes
- PS4 Developer Wiki Themes: https://www.psdevwiki.com/ps4/Themes
- PS4 Ultimate Theme Creator reference format: https://github.com/Imxnxl/PS4-Ultimate-Theme-Creator
- PSF/SFO format: https://www.psdevwiki.com/ps4/Param.sfo
