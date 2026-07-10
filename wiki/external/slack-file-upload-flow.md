# slack-file-upload-flow — uploading binary files to Slack from this project

**Type:** external
**Status:** active
**Updated:** 2026-05-31

## Summary
The claudeai-proxy Slack MCP server has text/search/canvas/reaction tools
but **no `files_upload`**. For binary uploads (e.g. GIF animation for
`gp_predicted_foils_cloud.gif`) we must hit the Slack Web API directly
with a bot token. Slack also deprecated the single-step `files.upload`
endpoint in March 2025 — the modern flow is three calls
(`getUploadURLExternal` → POST bytes → `completeUploadExternal`).
Documenting the working recipe so future sessions don't re-derive.

## Key facts

- **Bot token lives at** `~/.slack_bot_token` (mode 600). Created via a
  one-off Slack app installed in the `mu2e` workspace; bot user
  `U0B6XLZH9DG`. Scopes required: `files:write`, `chat:write`,
  `im:write` (last one needed for [[slack-bot-dm-channel-not-found]]).

- **Three-step upload (Slack Web API, post-March-2025):**
  ```bash
  TOKEN=$(cat ~/.slack_bot_token)
  FILE=/path/to/file.gif
  SIZE=$(stat -c%s "$FILE")
  # 1. mint a presigned upload URL + file_id
  R=$(curl -sS -G "https://slack.com/api/files.getUploadURLExternal" \
       -H "Authorization: Bearer $TOKEN" \
       --data-urlencode "filename=$(basename $FILE)" \
       --data-urlencode "length=$SIZE")
  URL=$(echo "$R"  | python3 -c "import sys,json;print(json.load(sys.stdin)['upload_url'])")
  FID=$(echo "$R"  | python3 -c "import sys,json;print(json.load(sys.stdin)['file_id'])")
  # 2. POST the raw bytes
  curl -sS --data-binary @"$FILE" "$URL"
  # 3. share to a channel (requires conversations.open for DM — see incidents)
  curl -sS -H "Authorization: Bearer $TOKEN" \
       -H "Content-Type: application/json; charset=utf-8" \
       -d "{\"files\":[{\"id\":\"$FID\",\"title\":\"my title\"}],\"channel_id\":\"$CID\"}" \
       https://slack.com/api/files.completeUploadExternal
  ```

- **Step 2 success signal**: a literal `OK - <bytes>` text response from
  `files.slack.com/upload/v1/...`. No JSON.

- **Step 3 failure mode**: `{"ok":false,"error":"channel_not_found"}` if
  the bot doesn't share a conversation with the target channel — see
  [[slack-bot-dm-channel-not-found]] for the conversations.open
  workaround. The file IS already in Slack storage after step 2; only
  the *share* fails — re-running step 3 alone is safe.

- **`charset=utf-8` is load-bearing** on step 3's Content-Type. Without
  it Slack returns a `missing_charset` warning AND silently drops the
  channel binding. Without `; charset=utf-8` we got "ok":true but no
  delivery.

- **Building step-3 JSON with embedded newlines:** the `initial_comment`
  needs real `\n` characters (multi-paragraph status messages). The
  reliable pattern is `export MSG=$'...\n...'` then read via
  `os.environ['MSG']` inside a `python3 -c` heredoc that builds the
  JSON. **Gotcha:** `python3 -c '...' MSG="..."` (trailing var=val args)
  does NOT inject into the child env — `os.environ['MSG']` raises
  KeyError. Must use `export` BEFORE the python3 call. Hit this once
  2026-05-31 building the foilsX07 status post.

## Cross-links
- Related: [[slack-bot-dm-channel-not-found]], [[github-pages-publish-dir]]
- External: [Slack Web API files.getUploadURLExternal](https://api.slack.com/methods/files.getUploadURLExternal),
  [files.completeUploadExternal](https://api.slack.com/methods/files.completeUploadExternal)
- Token file: `~/.slack_bot_token`

## Open questions / TODO
- Wire the official `slack` MCP server into `~/.claude.json` so future
  sessions can upload via tool-call rather than curl (token already in
  place; just needs `mcpServers` entry).
- Rotate the current xoxb token; it was pasted in a chat transcript.
