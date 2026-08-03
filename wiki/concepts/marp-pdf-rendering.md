---
type: concept
title: Marp PDF rendering gotchas
description: marp-cli PDF needs explicit `CHROME_PATH` (or it falls to Firefox +
  "Unknown system error -122"); CSS-grid side-by-side escapes the slide rect — use
  borderless `<table>` instead
status: active
timestamp: '2026-07-12'
updated_note: no-input-file stdin hang
---

# Marp PDF rendering gotchas

## Summary
Two non-obvious failures when rendering `docs/*_talk.md` decks to PDF via
`npx @marp-team/marp-cli`. Both bit during the
[bo-prodtarget](/projects/bo-prodtarget.md) methodology deck and cost ~30 min each.

## Key facts

- **A marp invocation that loses its input-file argument hangs forever on stdin**
  (2026-07-12): it prints `Currently waiting data from stdin stream` and blocks — as a
  background task it looks "running" indefinitely with rc never returned. There is no
  timeout. Always pass the `.md` path explicitly and check the task log for the stdin
  banner if a render produces no output within ~2 min.
- **NEVER run two `npx @marp-team/marp-cli` invocations concurrently** (2026-07-11):
  they race on the shared npx cache (`~/.npm/_npx/<hash>/node_modules`) and one dies
  at npm level with `ENOTEMPTY: directory not empty, rename ... accepts` before marp
  even starts. Compounding trap: `npx marp ... | tail -2` REPORTS rc=0 (pipeline exit
  = tail's), so the render looks successful with zero outputs written. Serialize
  renders; check `ls | wc` of the output dir, or echo `${PIPESTATUS[0]}`/`marp rc=$?`
  without a pipe.
- **Stale-verification-PNG trap** (2026-07-11): session scratchpad dirs persist across
  compaction — a failed PNG render + `Read` of the output dir served WEEK-OLD slide
  PNGs from an earlier verification pass, which looked exactly like a "marp rendered
  stale content" bug (it hadn't rendered anything). Before reading verification PNGs,
  `rm` the old ones (named paths) or render into a fresh dir, and sanity-check the
  PNG mtimes against the render timestamp.

- **Slide-overflow proofing recipe**: render per-slide PNGs and READ them —
  `CHROME_PATH=<chrome> marp deck.md --allow-local-files --images png -o out/slide.png`.
  **`--allow-local-files` is REQUIRED for PNG/PDF** or Chrome silently drops
  every local image (slide renders text-only — easily misread as a layout bug;
  browser-viewed HTML is unaffected). Overflow fixes that worked (2026-07-08,
  foilsflash deck): per-slide `<style scoped>` blocks (`table { font-size:14px }`,
  `section { font-size:21px }`, `small { line-height:1.25; display:block }` —
  without display:block the 14px small inherits the 24px line boxes) + shrink
  `![h:NNNpx]` images.
- **Plain HTML renders (no Chrome involved) intermittently HANG in foreground
  Bash** (2× seen: 2026-07-04 and 2026-07-07; the same deck rendered fine
  seconds earlier/later; killed by timeout SIGTERM at 2-3 min). Not
  CHROME_PATH-related. Recipe: re-run the identical command in background —
  both times it then completed in seconds. Don't diagnose; just background it.
- **Browser binary**: marp-cli's bundled Chromium auto-download path on this
  cluster (`/exp/mu2e/...`) silently falls back to Firefox, which then dies
  at `Unknown system error -122: Unknown system error -122, close` when
  writing PDF (HTML output works). **Fix**: export
  `CHROME_PATH=/nashome/o/oksuzian/.cache/puppeteer/chrome/linux-144.0.7559.96/chrome-linux64/chrome`
  before invoking marp-cli. The puppeteer cache is populated once by some
  prior `npx puppeteer` run; if it disappears, run any puppeteer command
  again to repopulate.
- **`[[wiki-link]]` markdown inside slides breaks PDF render** (root cause
  of the recurring `-122 close` from 2026-06-09): marp's PDF pipeline
  treats `[[name]]` as a local-file reference and Chrome's resource
  fetch returns the cryptic `Unknown system error -122: Unknown system
  error -122, close`. HTML output silently swallows it; PDF output dies.
  **Fix**: strip `[[wiki-link]]` syntax from any slide markdown destined
  for marp PDF — write the bare page name in prose instead. The earlier
  CHROME_PATH/PUPPETEER_CACHE_DIR speculation was a red herring; those
  workarounds appeared to help only because re-edits sometimes happened
  to remove a wiki-link by coincidence.
- **Image height ceiling on a slide with H2 + caption div**: marp 16:9 with
  `section { font-size: 24px }` leaves ~580px body after the H2 header and
  footer. Once a slide also carries a ~3-line `<div>` caption beneath the
  image, the practical image cap is **~h:400px** (or **~h:340px** if the
  caption is denser). Going taller (h:430 / h:480) renders fine in HTML but
  the caption gets pushed off the bottom or overlaps the footer in PDF.
  Observed 2026-06-09 in `docs/foils_talk.md` (saturation_foils_v3all,
  saturation_foilsf09_10_qlnei, saturation_foilsg). Rule of thumb: prefer
  `h:NNNpx` (bounds vertically) over `w:NN%` (unbounded vertically) any
  time the image is the tallest element on the slide.
- **Tighter ceiling for "H2 + intro prose + caption" slides**: the foilsg slide
  (`## Next campaign:` + hypothesis + design + picker line + image + caption
  div) has substantially less vertical budget than a "H2 + image + caption"
  slide. **h:340px clips off-page in HTML viewer** (reported 2026-06-11);
  reduced to **h:300px**. Inference: when the slide has >4 lines of body text
  before the image, treat the image cap as ~h:300, not h:340.
- **Multi-panel matplotlib figures: author them WIDE (~2.2–2.3:1), not tall, then size by `h:` (2026-06-17).** The pt6d geometry sketch first shipped at `figsize=(13,9.5)` (≈1.37:1); at any readable scale it overflowed the 16:9 body vertically. Reshaping to `figsize=(15,6.6)` (→1937×842 px, 2.30:1) let it sit at **`h:452px`** under a "H2 + image + 3-line `<small>` caption" slide on the **22px-font** prodtarget6d deck (vs the ~h:400 cap noted above for 24px decks — the lower base font buys ~50px). A wide figure at a given `h:` is narrower-than-the-body, so the caption keeps its rows; a tall figure at the same `h:` eats them. Generate slide figures at ≥2:1 and let `h:` bound the height.
- **Verify slide fit by rendering a temp PDF and Reading the page — the HTML viewer LIES about footer collisions (2026-06-17).** `marp ... --html` output scrolls, so a caption overlapping the footer/pagination looks fine in the browser but clips in PDF. Workflow: `marp <md> -o $(mktemp -d)/check.pdf --pdf --allow-local-files`, then `Read` that PDF at `pages: <N>` (geometry slide = page 3) and eyeball the heading→figure→caption→footer stack. Catches the exact off-by-one-line caption/footer collision that width-sizing and HTML preview both hide.
- **errno -122 / OSError 122 ("Disk quota exceeded") root cause is per-user
  CEPHFS quota on `/exp/mu2e/data/users/oksuzian` — 2.0 TB cap (2026-06-14).**
  Initial 2026-06-13 hypothesis blamed `/nashome` near-full at 96%; WRONG.
  The actual binding limit is a per-user cephfs xattr quota
  `ceph.quota.max_bytes=2147483648000` (= 2.0 TB exactly). When this is
  exceeded ANY write to `/exp/mu2e/data/users/oksuzian/**` fails with
  errno -122, INCLUDING:
  - `npx`/`npm` cache writes (the marp render failure)
  - `pipeline.py list-outputs` (writes `<cfg>/state/pot_only_outputs.txt`
    at line 698-699 — first thing it does after listing /pnfs)
  - Likely the **rc=120 poll deaths** (cephfs writeback EDQUOT propagating
    to subprocess fd state under memory pressure — same `-122` errno that
    npm reported, same root volume); see
    [pipeline-poll-rc120-atexit-death](/incidents/pipeline-poll-rc120-atexit-death.md).
  **Diagnostic commands:**
  `getfattr -n ceph.quota.max_bytes /exp/mu2e/data/users/oksuzian`
  → max_bytes (cap)
  `getfattr -n ceph.dir.rbytes /exp/mu2e/data/users/oksuzian`
  → current usage (instant, no `du` walk needed — cephfs maintains this xattr).
  `df -h` is USELESS here: shows 17% used because it reports the
  volume-wide 80 TB filesystem, not the per-user quota.
  **Fix when blocked:** free space in `/exp/mu2e/data/users/oksuzian/*` before
  any harvest/render. NOT a `~/.npm` cache problem; relocating the npm cache
  to `/tmp` (the 2026-06-13 workaround) only worked because /tmp is not on
  the cephfs quota.
  Per-subdir size walk:
  `for d in /exp/mu2e/data/users/oksuzian/*/; do b=$(getfattr -n
  ceph.dir.rbytes --only-values "$d" 2>/dev/null); awk -v b="$b" 'BEGIN{printf
  "%.2f GB  '"$d"'\n", b/1024/1024/1024}'; done | sort -rn`
  (Distinct from [jobsub-disk-quota-stderr-swallowed](/incidents/jobsub-disk-quota-stderr-swallowed.md), which is OSError 122
  inside jobsub_lite RCDS publish to /pnfs — same errno, different volume.)
  - **Workaround when even the /tmp cache redirect still fails** (observed
    2026-06-13, npm errno -122 persisting after `npm_config_cache=/tmp/...`
    AND `HOME=/exp/mu2e/data/users/oksuzian`): bypass `npx` entirely and
    invoke the cached marp binary directly:
    `CHROME_PATH=... /nashome/o/oksuzian/.npm/_npx/<hash>/node_modules/.bin/marp
    --html --allow-local-files <md> -o <html>`. The marp-cli tarball is
    already extracted under `~/.npm/_npx/<16-hex-hash>/`; `npx -y` only adds
    a "resolve + verify + maybe-download" wrapper that itself hits the
    failing write path. Find the hash with
    `find ~/.npm/_npx -name 'marp-cli' -type d`. The bin symlink target
    is `../@marp-team/marp-cli/marp-cli.js`. Worked when both `npm_config_cache`
    and `HOME` redirects to writable volumes still produced 0-byte npm log
    files — i.e., npm/npx itself was the failure surface, not the cache write.
- **Confirmed on foilsflash deck (2026-06-30):** the cloud slide (`docs/foilsflash_talk.md`,
  H2 + image + 1-line `<small>` caption, 24px font) overflowed at `w:64-70%` (image ran into the
  footer, caption clipped) exactly as the `w:%`-is-vertically-unbounded rule predicts; fixed at
  **`h:440px`** with the cloud regenerated wide (`figsize=(12,6.8)`, single colorbar). Verified
  fit by rendering per-slide PNGs (faster than the temp-PDF method): `CHROME_PATH=<bundled
  puppeteer chrome> marp --html --allow-local-files --images png <md>` → `Read` each
  `<name>.00N.png`. Delete the numbered PNGs afterward (named `rm`, not wildcard).
- **CSS grid escapes slide rect**: `<div style="display: grid;
  grid-template-columns: 65% 35%">` for side-by-side image+caption layouts
  renders the caption *outside* the 16:9 slide rectangle in PDF (overlaps
  the page footer). HTML output looks fine; PDF doesn't. **Fix**: use a
  borderless `<table>` instead — `<table style="border-collapse: collapse;
  border: none;"><tr style="border: none;"><td style="border: none;
  width: 65%;">...</td><td style="border: none; width: 35%;">...</td>
  </tr></table>`. Tables are inline-flow and reliably constrained by the
  slide section.

## Cross-links
- Related: [refresh-foils-slides](/drivers/refresh-foils-slides.md) (the equivalent script for foils deck;
  does not yet set CHROME_PATH — relied on a different cache state)
- Source files: `docs/prodtarget_talk.md`, `docs/foils_talk.md`

## Open questions / TODO
- Bake `CHROME_PATH` into `tools/refresh_foils_slides.sh` and any future
  `refresh_prodtarget_slides.sh` so the next session doesn't re-hit the
  Firefox fallback.
