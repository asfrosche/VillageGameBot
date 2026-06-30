# ShadowBOT — BOTC Module

A Discord bot module for **Blood on the Clocktower** — role lookups, jinxes, scripts, fabled, and night orders.

## Commands

| Command | Description |
|---|---|
| `/role <name>` | Look up a role by name or alias. Shows ability, team, edition, reminders. Interactive buttons for jinxes, night order, and aliases. |
| `/jinx <name>` | Show jinxes for a role. |
| `/fabled <name>` | Look up a fabled character. |
| `/scripts` | View Trouble Brewing, Bad Moon Rising, and Sects & Violets as full-script images with role icons. |
| `/nightorder` | Display the first-night and other-night order for each edition. |
| `/help` | Show this help message. |

## Data

Role data is sourced from [bra1n/townsquare](https://github.com/bra1n/townsquare). Icons from [tomozbot/botc-icons](https://github.com/tomozbot/botc-icons). Jinxes and fabled from the same upstream.

## Usage

```python
from utils import botc

role = botc.get_role("washerwoman")   # name or alias
jinxes = botc.get_jinxes_for_role("alchemist")
fabled = botc.get_fabled("djinn")
```
