---
type: external
title: github-pages-publish-dir — GitHub Pages branch-deploy folder restriction
description: GitHub Pages branch-deploy folder dropdown hardcodes `/(root)` and
  `/docs` only; arbitrary names like `/talks` require switching source to GitHub
  Actions
status: active
timestamp: '2026-05-30'
---

# github-pages-publish-dir — GitHub Pages branch-deploy folder restriction

## Summary
GitHub Pages "Deploy from a branch" mode does NOT let you pick an arbitrary
subfolder as the publish root. The folder dropdown offers exactly two
choices: `/(root)` or `/docs`. Custom folder names (e.g. `talks/`,
`slides/`, `site/`) are not selectable. The escape hatch is GitHub Actions
("Deploy with GitHub Actions" source), which can publish any path — but
needs a workflow file.

## Key facts

- **Folder dropdown options:** `/(root)` and `/docs` only — hard-coded in
  the GitHub Pages UI.
- **URL mapping:** `/docs/foo.html` on `main` → `https://<user>.github.io/<repo>/foo.html`
  (the `/docs/` prefix is stripped).
- **First deploy lag:** ~1–2 minutes from Save → live URL. Subsequent
  pushes deploy within ~30s.
- **No `_config.yml` needed** if you're just serving static HTML/PDF/GIF;
  Jekyll runs by default but processes plain HTML as-is.
- **`.html` is served directly** — no Pages-only restriction on extensions.
- **For arbitrary folder names** switch source to "GitHub Actions" and
  use `actions/deploy-pages@v4` with a workflow that uploads the
  target path as the artifact. More work, more flexibility.
- **Mu2eBO use:** `docs/foils_talk.html` → `https://oksuzian.github.io/Mu2eBO/foils_talk.html`.
- **Pages branch = main only** in default config: pushing `docs/` to a
  feature branch (e.g. `fix-closed-loop-failure-modes`) does NOT update
  the live deck. The push succeeds, GitHub stores it, but Pages keeps
  serving the `main`/`docs` snapshot until the branch merges. Easy
  gotcha during PR-staged work.
- **Marp `![bg left:N%](img.gif)` gotcha:** the bg-image directive
  renders the GIF as a *background panel*, which on Marp's default
  theme causes the global `footer:` text to render only over the
  non-background portion of the slide (the right N%). Fix: use a
  plain CSS grid (`<div style="display:grid; grid-template-columns:
  60% 40%">`) for two-column layouts instead of `bg left:` when the
  footer must span the whole slide.

## Cross-links
- Related: [slack-file-upload-flow](/external/slack-file-upload-flow.md) (parallel pattern of "external
  hosting workflow we set up once and forget")
- External: [GitHub Pages docs](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)

## Open questions / TODO
- Test whether enabling Pages also requires the repo to be public, or
  if private repos with Pro/Team can serve Pages too.
