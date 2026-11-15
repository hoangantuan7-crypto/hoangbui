# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

The repository holds three unrelated projects. The default branch is `delivery/completed-assets`, and all work is merged there through PRs. Most current work is in `zalo-order-bot/`.

| Folder | What it is |
|---|---|
| `zalo-order-bot/` | Python bot that reads Zalo messages through a self-hosted ZaloCRM and reports to Telegram (main project) |
| `inventory-app/` | Static PWA for stock-taking by barcode (vanilla JS), deployed to GitHub Pages |
| `src/`, `tests/` (root) | CapCut SFX/overlay asset generators (numpy/scipy/pillow + ffmpeg) |

User-facing text, README files, comments and bot messages are written in **Vietnamese**. Keep that style.

## Commands

```sh
# zalo-order-bot: stdlib only, no install needed to run tests
cd zalo-order-bot
python3 -m unittest discover -s tests                     # all tests
python3 -m unittest discover -s tests -p test_groups.py   # one file
```
Run single files through `discover -s tests`. Tests import each other as top-level modules, for example `from test_room import FakeTG` and `tests_helpers`. So `python -m unittest tests.test_x` fails.

```sh
# inventory-app (CI runs this before deploying Pages)
node --test inventory-app/tests/categorize.test.js
cd inventory-app && python3 -m http.server 8000

# root CapCut generators
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

## zalo-order-bot architecture

**Deployment.** The bot runs as the `order-bot` service in `docker-compose.zalocrm.yml`, inside the user's ZaloCRM folder on a local Mac using Docker via Colima. `install-zalocrm.sh` is the only supported way to configure it. The script is interactive but can also be driven by env vars, and it must stay **bash 3.2 compatible** (macOS), so no `mapfile` and no `${x,,}`. It writes ZaloCRM's `app_settings` straight into Postgres, because the ZaloCRM UI has bugs, and writes `ORDER_BOT_*` vars into `.env`. Start only `up -d app order-bot`, never the other compose services. Users update with:
`cd ~/zcrm && git -C ~/hoangbui pull -q && cp -r ~/hoangbui/zalo-order-bot . && bash zalo-order-bot/install-zalocrm.sh`.

**Two entry points.**
- `bot/crm_main.py`: the production mode. `CRMBot` reads Zalo **read-only** and never sends Zalo messages. All output goes to Telegram.
- `bot/main.py` + `bot/zalo.py`: the older Zalo Bot Platform mode.

`bot/handlers.py` (`handle_message`, order commands) is shared by both modes.

**Data flow in CRM mode.** The ZaloCRM webhook never fired on the user's build. Instead, `poll_tick` calls the ZaloCRM public API (`X-API-Key`) every `POLL_SECONDS`, and each new message goes to `CRMBot.handle_event`. That method:
1. Dedupes by message id (`seen_messages`). The same group seen through two shop nicks is deduped again by `grpmsg:` key, and `key()` merges groups by `externalThreadId`.
2. Decides whether the shop or a customer is speaking. ZaloCRM records replies sent from the shop's phone as `sender_type='contact'`, so the bot also matches sender names against `SHOP_NAMES`, `STAFF_NAMES` and `SHOP_UIDS`, plus the staff list managed with `/nhanvien`.
3. Checks the group class in `groups.py`, set with `/nhom`: `khach` (follow), `noibo` and `boqua` (ignore), `congviec`, or `thongtin`. Messages in a `congviec` (internal work) group go to `handle_internal`: `schedule.py` parses Vietnamese dates/times ("9h sáng mai", "thứ 7", "20/11") into `schedules` rows `L<n>`, and `check_schedules`/`send_agenda` in the scheduler remind the responsible department bot (`/lich` command). A group whose name starts with "THÔNG TIN KHÁCH HÀNG" is `thongtin` automatically. Messages in a `thongtin` group go to `customer_info.py`, which takes text or a photo (Claude vision, else Tesseract OCR) and appends rows to a Google Sheet through the Apps Script web app in `google-sheet/AppsScript.gs`. OCR rows are always marked "Cần kiểm tra", and rows without a valid 10-digit phone are dropped.
4. Updates reply tracking (`followup.py`, `conv_state`) and routes the message to a department (`departments.route`, by no-accent keywords). It then creates a lead `K<n>` and reports it.

**Telegram: five bots, one store.** `bots = {"dieuphoi": ..., "sale", "ketoan", "kho", "kythuat"}`. Each bot has its own token (`TELEGRAM_TOKEN_*`) and its own long-poll thread (`telegram_loop`). All bots share one SQLite `Store`.
- Chat keys look like `"<botname>:<chat_id>"`.
- A chat is paired with `/batdau <PAIR_CODE> [bộ phận|phong]`.
- `dept_bots.ALLOWED` limits which commands each department bot accepts.
- In the "phòng" group, the dispatcher mentions the responsible bot (`assign_in_room`). Problems are DMed privately (`report_problem`).
- Meetings come from `meeting.py`. Free-form department questions go to `ai_assistant.py`, which falls back to raw numbers when there is no API key.

**Threads.** The HTTP server, scheduler, poller and one loop per Telegram bot all share one `Store`. `db.py` wraps sqlite in `_LockedConnection` (an RLock, with results materialized). Keep every DB access going through it.

**Text matching.** Vietnamese text is compared after `text.norm()` (lowercase, accents removed). Keywords, aliases and group-class keys are stored in that form.

**AI is optional.** Everything must still work without `ANTHROPIC_API_KEY` and without the `anthropic`, `pillow` or `tesseract` packages. The Dockerfile installs them on a best-effort basis. Models: `ai_parser.py`/`ai_assistant.py` use `claude-opus-5-5`, and photo reading uses `CLAUDE_VISION_MODEL` (default `claude-haiku-5-5`).

**Adding a config var** means touching three places: `main()` in `crm_main.py`, the `order-bot` environment block in `docker-compose.zalocrm.yml` (as `ORDER_BOT_*`), and `install-zalocrm.sh` if users need to set it.

**Secrets.** The installer reads secrets with hidden input and never prints the pairing code. Keep it that way. Never ask the user to paste tokens or keys into chat.

`.github/workflows/zalo-bot.yml` is an SSH installer for a remote server. It is unused now, because ZaloCRM runs on the user's own machine.
