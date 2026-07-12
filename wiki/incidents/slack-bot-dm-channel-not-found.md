# slack-bot-dm-channel-not-found — bot can't share to a user's MCP DM channel

**Type:** incident
**Status:** resolved
**Updated:** 2026-05-29 (private-channel case added)

## Summary
A freshly installed Slack bot (the mu2e-workspace bot at user
`U0B6XLZH9DG`) cannot post or share files to the DM channel a *human
user* sees with the claudeai-proxy MCP user (channel `D738B2DRV` for
U725NHNHG). Step 3 of [[slack-file-upload-flow]] returns
`{"ok":false,"error":"channel_not_found"}` even though the file was
uploaded cleanly in step 2.

## Root cause
Slack DM channels are per-pair. The `D738B2DRV` channel belongs to the
user↔claudeai-proxy pair; the new bot is a different Slack user, so it
has no membership in that DM channel and the API treats it as
non-existent. **Bots must mint their own DM channel** with the target
user before they can share to it.

## Fix
Call `conversations.open` first to get the bot's own DM channel ID,
then use that as `channel_id` in `files.completeUploadExternal`:

```bash
TOKEN=$(cat ~/.slack_bot_token)
CID=$(curl -sS -H "Authorization: Bearer $TOKEN" \
       -H "Content-Type: application/json; charset=utf-8" \
       -d '{"users":"U725NHNHG"}' \
       https://slack.com/api/conversations.open \
     | python3 -c "import sys,json;print(json.load(sys.stdin)['channel']['id'])")
echo "bot DM channel: $CID"
# now share the already-uploaded file_id to that channel:
curl -sS -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json; charset=utf-8" \
     -d "{\"files\":[{\"id\":\"$FID\"}],\"channel_id\":\"$CID\"}" \
     https://slack.com/api/files.completeUploadExternal
```

For U725NHNHG this minted `D0B6ZFVG265` (different D-prefix than the
claudeai-proxy DM `D738B2DRV`). The user sees the bot upload in a
*separate* DM thread from the claudeai-proxy bot.

## Key facts
- **`im:write` scope required** on the bot for conversations.open to
  succeed; otherwise it returns `missing_scope`.
- **The file is NOT lost after the failed share** — `file_id` from step
  1 persists in Slack storage. Re-running step 3 alone with the correct
  channel_id is safe and cheap.
- **Public channels are an alternative**: if the bot is `invite`d to a
  public channel, posting/sharing there works without conversations.open.
- **Private channels also need `/invite`**: the same `channel_not_found`
  surfaces on `files.completeUploadExternal` to a private channel the bot
  isn't a member of (confirmed 2026-05-29 on `#mu2e-bo` / `C0B71NQNUM8`).
  conversations.open does NOT help here — it only mints DM channels, not
  private group memberships. Fix: the channel owner runs
  `/invite @<bot-display-name>` (bot user `U0B6XLZH9DG` for this
  project). User-MCP `slack_send_message` works without invite because
  it acts as the user, not the bot.
- **Workspace ownership matters**: the bot installed by the user's own
  Slack app belongs to the human team admin, so DMs go user→bot
  directly. No multi-hop relay needed.

## Cross-links
- Related: [[slack-file-upload-flow]], [[claude-bash-no-ssh-agent]]
- External: [conversations.open](https://api.slack.com/methods/conversations.open)
