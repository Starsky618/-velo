# VELO web font subsets

The `*.woff` files here are page-scoped web subsets of open-licensed CJK
fonts, generated 2026-08-05 for the v3 route-journal design system.

- `velo-sans-zh-regular-v1.woff` — body text, weight 400
- `velo-sans-zh-medium-v1.woff` — emphasis/body strong, weight 500
- `velo-serif-zh-bold-v1.woff` — display headings only, weight 700

## Sources (both SIL Open Font License 1.1; see `OFL.txt`)

- Sans: Noto Sans SC variable (`ofl/notosanssc/NotoSansSC[wght].ttf` from
  <https://github.com/google/fonts>), instantiated at wght=400 and wght=500
  with `fontTools.varLib.instancer`.
- Serif: Noto Serif SC variable (`ofl/notoserifsc/NotoSerifSC[wght].ttf`),
  instantiated at wght=700.

Earlier v1 sans subsets came from Adobe Source Han Sans CN 2.005R; the v3
pipeline switched to the google/fonts Noto builds (same glyph repertoire,
single-file variable source). The derivative family names are declared only
in CSS (`VELO Sans`, `VELO Serif`); internal font names are untouched.

## Scope

- Sans subsets: every visible character of the Chinese and English public
  pages (home, company, privacy, Garmin privacy) as of 2026-08-05, including
  Latin letters, digits, and punctuation.
- Serif subset: characters used inside `h1`–`h3` headings across those pages
  only. If new heading copy ships, regenerate.

## Regenerate

```sh
# 1. collect glyph sets (all visible text -> sans; heading text -> serif)
#    see scripts used 2026-08-05; an html.parser walk over the pages works.
# 2. instantiate + subset
python3 -m fontTools.varLib.instancer NotoSansSC[wght].ttf wght=400 -o sans400.ttf
pyftsubset sans400.ttf --text-file=sans-chars.txt --flavor=woff \
  --output-file=velo-sans-zh-regular-v1.woff
```

Always keep `font-display: swap` and preload only the headline subset on the
homepage; never block first paint on a full CJK file.
