# Blind Auction — Brief Plan

**Status:** Plan only — nothing built yet.

## Concept
Alive players bid on an item **anonymously** via a button on the auction board. Every click (vote/bid) appends a line to a **paginated, scrollable log embed**. When the timer ends, the highest bidder is revealed, pays their bid from their RC balance, and gets the item (shop item auto-granted; named item handed over by an Overseer).

## Locked decisions
1. **Amount visibility:** argument on start — `.auc start <item> <duration> <mode>` where `mode = sealed | visible`.
   - `sealed` (default): board shows only `✅ Anon #N placed a bid`, logging amounts saved internally.
   - `visible`: board shows `Anon #N bid <amount>`.
2. **Initiation:** **no quorum.** `.auc start` opens the auction immediately. (Question answered: none needed.)
3. **Ties:** impossible by rule — every accepted bid must **strictly exceed** the current high, so the winning amount is always unique. No tie-break logic.
4. **Reveal:** winner's real name + amount only. **No alias lists revealed.**
5. **Restart resilience:** live auction is **persisted** and **rehydrated on bot boot**.
6. **Stock:** shop items are always stocked — no sold-out fallback logic.
7. **Escrow (funds locked while leading):** the moment a bid is placed, that amount is **removed from the bidder's RC balance and held**. If someone outbids them, they are **refunded in full** and the new leader's bid is held instead (e.g. A bids 100 → hold 100 from A; B bids 150 → hold 150 from B, refund A 100; A bids 200 → hold 200 from A, refund B 150). Bid money can never be spent elsewhere. On close the winner keeps the escrow (no second charge); on cancel everyone is refunded.

## Commands
| Command | Access | Effect |
| --- | --- | --- |
| `.auc status` | Everyone | Show current auction board |
| `.auc start <item> <duration> <sealed\|visible>` | Alive player | Open an auction immediately |
| `.auc bid <amount>` | Alive player | Keyboard fallback for bidding |
| `.auc extend <time>` | Overseer | Add time |
| `.auc close` | Overseer | Force-close (same resolution as timer) |
| `.auc cancel` | Overseer | Void an open auction (refunds all escrow) |
| `.auc alias <player>` | Overseer | Reveal one player's alias (investigative) |

`.auc start` accepts either a free-text item name or a shop item; shop items auto-grant on close, named items ping the Overseer role.

## Flow
1. `.auc start` posts the board embed in the AuctionHouse channel: item, duration, mode, and the (empty) paginated bid log.
2. Alive players click the **Bid** button → amount modal → a log line is appended (`Anon #N bid 100` or `Anon #N placed a bid`). Aliases are assigned on first bid.
3. Each bid is validated: bidder is alive, their RC is resolvable, **balance covers the amount**, and amount exceeds the current high.
4. On acceptance: previous leader (if any) is **refunded in full**, the new bid amount is **escrowed** from the bidder's RC.
5. Timer expires (or `.auc close`): bidding locks, highest bidder wins, embed flips to `[CLOSED]` reveal (winner + amount). The winner keeps their escrow; losers were already refunded when outbid. `.auc cancel` refunds the current escrow.
6. Prize: shop item → granted to winner's RC inventory automatically; named item → Overseer role pinged to hand it over.

## Board UI (one embed to rule them all)
- **⬅️ ➡️ buttons** paginate the bid-log pages.
- **Bid button** opens an amount modal; every action logs a line into the same paginated embed.
- Bot edits its own message in place; no chance spam in rolechats.

## Data
- **In-memory** `Auction` (guild, item, type, mode, ends_at, min_bid, bids, aliases, reserved) while running.
- **Persisted row** per guild (guild_id, item, mode, ends_at, bids, reserved) → rehydrated on `on_ready` after a restart.

## Config (guild data, `.aucset …` admin command)
- `auction_channel_id` (board lives here)
- `auction_min_bid` (default 50), `auction_min_increment` (default 25)
- `auction_default_duration`

## Edge cases
- Bot restart → auction reloaded (incl. who holds escrow), counts resumes.
- Player outbid mid-auction → escrow refunded immediately at the moment they are outbid.
- Player loses Alive role → fresh bids rejected.
- No AuctionHouse channel configured → `.auc start` warns and refuses.

## Tests
`cogs/tests/test_auction_cog.py` (+ mirror in `testing/tests/`): mode rendering (sealed vs visible), escrow hold/refund on leader change, solvency rejection, strict-increase rule, close keeps winner escrow without double charge, cancel refund, shop auto-grant, restart rehydrate, config guards.

## Out of scope (v1)
- Multiple concurrent auctions per guild.
- Proxy bids, buy-now pricing, partial refunds.
- Alias reveal/history UI.