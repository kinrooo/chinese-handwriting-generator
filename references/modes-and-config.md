# Modes and configuration

All examples use public-domain classical Chinese poetry. No previously tested personal names or simulated identity data are part of the Skill.

## Generation modes

### `render`

Generate `N` variants of one short line. With no font argument, the six bundled OFL fonts are used automatically.

```bash
python3 scripts/handwriting_cli.py render \
  --text '明月松间照，清泉石上流。' --variants 12 \
  --preset natural --trend up --angle 0.8:3.8 \
  --output out/poem-line --zip
```

### `batch`

Generate one or more variants for each TXT, JSON, or CSV record. Extract XLS/XLSX data to JSON/CSV with spreadsheet-capable tooling first; this keeps Office parsing out of the renderer.

```bash
python3 scripts/handwriting_cli.py batch \
  --input examples/poems.json --field text --variants 2 \
  --font-policy balanced --output out/poems --zip
```

Accepted inputs:

- TXT: one non-empty text per line.
- JSON: a list of strings, a list of objects, or an object containing `records`.
- CSV: select a column with `--field`; otherwise the first column is used.

### `page`

Lay out long text on white, lined, grid, or custom paper. Export page PNGs and optionally a PDF.

```bash
python3 scripts/handwriting_cli.py page \
  --input examples/poems.txt --paper lined \
  --page-size 2480x3508 --dpi 300 \
  --output out/poetry-page --pdf
```

### `compare`

Generate one sample per eligible font for `subtle`, `natural`, and `strong`, then create a contact sheet.

```bash
python3 scripts/handwriting_cli.py compare \
  --text '海上生明月，天涯共此时。' \
  --output out/font-comparison \
  --preview-title '诗词手写字体对比'
```

### `scan`

Post-process an image or directory. Presets are `clean-scan`, `photocopy`, and `phone-scan`. Always retain the clean master.

```bash
python3 scripts/handwriting_cli.py scan \
  --input out/poetry-page/page_001.png --preset photocopy \
  --output out/poetry-page-scanned --seed 20260823
```

## Font-pool behavior

- No `--font` or `--font-dir`: use all bundled OFL fonts offline.
- Explicit `--font` or `--font-dir`: use only those authorized fonts.
- Explicit fonts plus `--include-bundled-fonts`: merge both pools.
- `balanced`: choose among the least-used eligible fonts and avoid adjacent repeats where possible.
- `random`: choose reproducibly from eligible fonts using the master seed.
- `fixed`: use the first eligible font.

## Customization dimensions

| Layer | High-level controls | Advanced controls |
|---|---|---|
| Input | text/list/record field, variants per item | record IDs, manual page breaks |
| Fonts | bundled/external pool | fixed/random/balanced policy, glyph fallback |
| Variation | subtle/natural/strong | font-size, spacing, baseline, glyph rotation sigmas |
| Stroke | ink color and opacity | per-stroke depth variance |
| Trend | up/flat/down | whole-text angle range, x/y placement jitter |
| Shape | size and density | width/height scaling ranges |
| Layout | canvas/page size, margins | line spacing, safe crop, paper template |
| Paper | white/transparent/lined/grid/custom | background image and line rhythm |
| Randomness | fresh or reproducible | master seed and stable record-derived seeds |
| Scan | clean scan/photocopy/phone scan | contrast, blur, noise, vignette, skew, JPEG quality |
| Output | PNG/PDF, preview, ZIP | manifest level, filename privacy, alpha retention |

Contact-sheet titles and labels are preview-only metadata, never watermarks on individual images. Use `--preview-title '中文手写预览'` to localize the title or `--hide-preview-labels` for an unlabeled sheet.

## Presets

- `subtle`: tidy, restrained variation.
- `natural`: default for short lines and mixed batches.
- `strong`: broader variation for comparison; visually inspect every result.
- `note`: calmer perturbation and consistent line rhythm for full pages.

Use `--style-config style.json` to override advanced numeric ranges. The JSON object may contain: `font_size`, `word_spacing`, `line_spacing_sigma`, `font_size_sigma`, `word_spacing_sigma`, `perturb_x_sigma`, `perturb_y_sigma`, `perturb_theta_sigma`, `angle`, `width_scale`, `height_scale`, `x_jitter`, `y_jitter`, `ink_rgb`, `ink_alpha`, and `ink_depth_sigma`. A range is a two-element list; fixed values may be numbers.

Start with a preset and change one high-level dimension at a time. `--synthetic-test-data` only records a declaration in the manifest; it never changes pixels or adds a watermark.
