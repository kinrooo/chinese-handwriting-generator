# Font policy

## Offline bundled pool

The Skill bundles six Chinese fonts from pinned upstream revisions. Each font retains its own SIL Open Font License 1.1 text, metadata, upstream revision, and SHA-256 record under `assets/fonts/`.

| Font | Role in the pool | License |
|---|---|---|
| Ma Shan Zheng | thick, forceful title lettering | OFL-1.1 |
| Long Cang | textured, casual handwriting | OFL-1.1 |
| Zhi Mang Xing | flowing semi-cursive script | OFL-1.1 |
| Liu Jian Mao Cao | expressive cursive writing | OFL-1.1 |
| ZCOOL KuaiLe | playful display handwriting | OFL-1.1 |
| Xiaolai | rounded everyday handwriting and broad-glyph fallback | OFL-1.1 |

This pool covers the main visual roles previously explored in the two reference projects while remaining independent of their hosting or availability. No online font download occurs at runtime.

The code license of a repository does not automatically license its TTF/OTF assets. Fonts previously seen in the reference web project and test directories are therefore not redistributed unless their font-specific license is independently verifiable. Local users may still load an authorized copy through `--font` or `--font-dir`.

## Reference-project migration

The earlier web font list (`青叶手写体`, `云烟体`, `华阳手写体`, `神韵英子楷书`, and `李国夫手写体`) and Handright's demonstration font are not vendored. Their surrounding code licenses did not establish a complete, font-specific redistribution chain; one inspected file also carried an all-rights-reserved/commercial-authorization notice.

The built-in pool is a licensed functional replacement, not a byte-for-byte mirror:

- Xiaolai and Long Cang cover everyday, informal handwriting roles.
- Zhi Mang Xing covers semi-cursive/regular-script transitions.
- Liu Jian Mao Cao covers fast cursive writing.
- Ma Shan Zheng covers bold calligraphic lettering.
- ZCOOL KuaiLe covers playful display lettering.

This preserves multi-style recommendation and batch diversity even if either reference repository or service disappears, without republishing ambiguous font files.

## Font inspection

Inspect the bundled pool before generation:

```bash
python3 scripts/handwriting_cli.py inspect-font \
  --text '长风破浪会有时，直挂云帆济沧海。'
```

Inspect only external fonts:

```bash
python3 scripts/handwriting_cli.py inspect-font \
  --font-dir /path/to/authorized-fonts \
  --text '长风破浪会有时，直挂云帆济沧海。'
```

The glyph test compares rendered masks against a known missing-glyph sentinel. It is a practical coverage check, not a licensing determination.

## External-font rules

Use only:

1. a font the user supplies and is authorized to use;
2. a font with an explicit OFL, Apache, or other redistributable license;
3. a system font for local-only output when its terms permit that use.

Do not copy an external font into the Skill, ZIP output, or another environment merely because it is accessible locally or appears in a code repository.

## Integrity and manifests

- `assets/fonts/fonts-manifest.json` pins the Google Fonts snapshot, upstream revisions, font hashes, and license hashes.
- The loader rejects missing, modified, duplicate, path-escaping, or unregistered bundled font files before rendering.
- Minimal manifests identify bundled fonts using stable IDs and relative paths, without machine-specific absolute paths.
- Full manifests also record resolved paths for audit use.
- External fonts are marked `user-provided-or-unverified`; the Skill never invents a license assertion.
