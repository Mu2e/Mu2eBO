---
type: external
title: mu2e-exp-website-docroot — local filesystem path of mu2e-exp.fnal.gov
description: '`https://mu2e-exp.fnal.gov` docroot is NFS-mounted at `/web/sites/m/mu2e-exp.fnal.gov/htdocs/`;
  readable without Shibboleth login'
status: active
timestamp: '2026-05-29'
---

# mu2e-exp-website-docroot — local filesystem path of mu2e-exp.fnal.gov

## Summary
The public Mu2e site `https://mu2e-exp.fnal.gov` is Shibboleth-protected
(SSO via `idp.fnal.gov`) and Cloudflare-fronted, but its docroot is
NFS-mounted on the gpvm cluster. You can read site content directly
from the filesystem without authenticating through HTTPS — useful for
grepping the at-work pages, scraping documents, or sanity-checking a
broken link.

## Key facts

- **Docroot:** `/web/sites/m/mu2e-exp.fnal.gov/htdocs/`
- **Adjacent dirs:**
  - `cgi-bin/` — server-side scripts
  - `data/` — non-htdocs data store
  - `logs/` — Apache access/error logs (read-restricted)
- **Permissions:** owner `nobody:nobody`, mode `2750`, but ACLs (`+`
  suffix in `ls -la`) extend read access to authorized users — `cat`
  and `find` work for any user with mu2e ACL membership.
- **URL → path mapping:** `https://mu2e-exp.fnal.gov/atwork/foo.shtml`
  → `/web/sites/m/mu2e-exp.fnal.gov/htdocs/atwork/foo.shtml`.
- **Why HTTPS requires login but files don't:** the Shibboleth/Mellon
  gate is enforced at the Apache layer (`303 → /mellon/login`); the
  NFS export is a separate access path.
- **All FNAL experiment websites follow the same `/web/sites/<letter>/<host>/`
  pattern** (e.g. `/web/sites/` lists 102 entries). The old
  `/afs/fnal.gov/files/expwww/mu2e/` AFS path is gone.

## Cross-links
- Related: [open-knowledge-format](/external/open-knowledge-format.md)
- External: [Mu2e public site](https://mu2e-exp.fnal.gov)

## Open questions / TODO
- None.
