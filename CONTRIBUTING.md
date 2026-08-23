# Contributing

Thanks for improving the Skill. Keep every contribution offline-capable, reproducible, and safe to publish.

## Before opening a change

1. Use only public-domain poetry or similarly non-personal text in examples, tests, screenshots, and manifests.
2. Do not commit real or simulated identity datasets, spreadsheets, private fonts, generated manifests, absolute local paths, or output archives.
3. Preserve backward-compatible CLI behavior where practical. Explicit external font arguments must not silently change their pool.
4. Run the full test suite and inspect representative output images.

## Adding a font

A font is accepted only when its official upstream provides an explicit redistribution license. A code repository license does not automatically cover its font files.

Each bundled font must include:

- the original binary, unmodified unless the change is documented;
- its exact copyright and full font-license text;
- an official upstream URL pinned to a tag or commit;
- SHA-256 hashes for the font and license;
- a distinct visual role and useful Chinese glyph coverage;
- a new entry in `assets/fonts/fonts-manifest.json` and `THIRD_PARTY_NOTICES.md`.

Do not add unlicensed fonts or rely on “free download”, “free commercial use”, or a parent repository's MIT/BSD license as proof of font redistribution rights. Do not use Git LFS as the only source for the core offline font pool.

## Verification

```bash
python3 -m py_compile scripts/handwriting_cli.py
python3 -m unittest discover -s tests -v
python3 scripts/handwriting_cli.py inspect-font \
  --input examples/poems.json --field text
```

If rendering behavior changes, compare contact sheets rather than asserting cross-platform pixel hashes; Pillow and FreeType rasterization may differ between environments.
