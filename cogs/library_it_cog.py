import os
from utils.paths import DB_DIR
import discord
from discord.ext import commands
from typing import Optional, List, Tuple
import re
import asyncio
from difflib import SequenceMatcher

from .library_cog import LIBRARIAN_IDS, EMBED_COLOR, EMBED_FOOTER_TEXT, EMBED_FOOTER_ICON, TEAMS, LibraryDatabase, GameSelectView, TeamSelectView, RoleDescriptionView, RoleSelectionView, InteractiveSearchView, StatsView, MissingIDPageView, RelationsView


class ItalianLibraryDatabase(LibraryDatabase):
    """
    Italian namespace clone of the roles library.

    Uses its own SQLite file so Italian stats are fully separated
    from the English library (`db/roles_library_it.db`).
    All DB logic is inherited from the refactored LibraryDatabase.
    """

    def __init__(self, db_path: str = os.path.join(DB_DIR, "roles_library_it.db")):
        super().__init__(db_path=db_path)

    def get_player_stats(self, player_id: int) -> dict:
        """Full stats for a player, counting sponsor games as played games too."""
        with self._connect() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(DISTINCT game_number) AS games_as_player,
                    SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) AS wins_as_player,
                    SUM(CASE WHEN team = 1 THEN 1 ELSE 0 END) AS village_total,
                    SUM(CASE WHEN team = 1 AND win = 1 THEN 1 ELSE 0 END) AS village_wins,
                    SUM(CASE WHEN team = 2 THEN 1 ELSE 0 END) AS evil_total,
                    SUM(CASE WHEN team = 2 AND win = 1 THEN 1 ELSE 0 END) AS evil_wins,
                    SUM(CASE WHEN team = 3 THEN 1 ELSE 0 END) AS rk_total,
                    SUM(CASE WHEN team = 3 AND win = 1 THEN 1 ELSE 0 END) AS rk_wins,
                    SUM(CASE WHEN team = 4 THEN 1 ELSE 0 END) AS neutral_total,
                    SUM(CASE WHEN team = 4 AND win = 1 THEN 1 ELSE 0 END) AS neutral_wins,
                    SUM(CASE WHEN team = 5 THEN 1 ELSE 0 END) AS bonus_total,
                    SUM(CASE WHEN team = 5 AND win = 1 THEN 1 ELSE 0 END) AS bonus_wins,
                    SUM(CASE WHEN mvp = 1 AND team != 5 THEN 1 ELSE 0 END) AS total_mvps,
                    SUM(CASE WHEN mvp = 1 AND team = 1 THEN 1 ELSE 0 END) AS village_mvps,
                    SUM(CASE WHEN mvp = 1 AND team = 2 THEN 1 ELSE 0 END) AS evil_mvps,
                    SUM(CASE WHEN mvp = 1 AND team = 3 THEN 1 ELSE 0 END) AS rk_mvps,
                    SUM(CASE WHEN mvp = 1 AND team = 4 THEN 1 ELSE 0 END) AS neutral_mvps
                FROM roles
                WHERE (player_id = ? OR sponsor_id = ?) AND count = 1
            """, (player_id, player_id))
            pr = cursor.fetchone()

            cursor.execute("""
                SELECT
                    COUNT(DISTINCT game_number) AS games_as_sponsor,
                    SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) AS wins_as_sponsor
                FROM roles
                WHERE sponsor_id = ? AND count = 1 AND team != 5
            """, (player_id,))
            sr = cursor.fetchone()

            cursor.execute("""
                SELECT COUNT(DISTINCT game_number)
                FROM (
                    SELECT game_number FROM roles
                    WHERE (player_id = ? OR sponsor_id = ?) AND count = 1 AND team != 5
                    UNION
                    SELECT game_number FROM game_hosts
                    WHERE host_id = ? AND count = 1
                )
            """, (player_id, player_id, player_id))
            total_participations = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT game_number) FROM roles WHERE count = 1 AND team != 5")
            total_games = cursor.fetchone()[0]

            cursor.execute("""
                SELECT game_number, win FROM roles
                WHERE (player_id = ? OR sponsor_id = ?) AND count = 1 AND team = 1
                ORDER BY game_number ASC
            """, (player_id, player_id))
            streak_rows = cursor.fetchall()

            cursor.execute("""
                SELECT win FROM roles
                WHERE (player_id = ? OR sponsor_id = ?) AND count = 1 AND team != 5
                ORDER BY game_number ASC
            """, (player_id, player_id))
            all_streak_rows = cursor.fetchall()

        games_as_player = pr["games_as_player"] or 0
        wins_as_player = pr["wins_as_player"] or 0
        games_as_sponsor = sr["games_as_sponsor"] or 0
        wins_as_sponsor = sr["wins_as_sponsor"] or 0

        longest_winstreak = current_streak = 0
        for row in streak_rows:
            if row["win"] == 1:
                current_streak += 1
                longest_winstreak = max(longest_winstreak, current_streak)
            else:
                current_streak = 0

        ws = ls = cws = cls = 0
        form_list = []
        for row in all_streak_rows:
            if row["win"] == 1:
                cws += 1
                cls = 0
                ws = max(ws, cws)
                form_list.append("W")
            else:
                cls += 1
                cws = 0
                ls = max(ls, cls)
                form_list.append("L")

        form_str = " ".join(form_list[-5:]) if form_list else ""

        team_stats = {
            TEAMS[1]: {"total": pr["village_total"] or 0, "wins": pr["village_wins"] or 0},
            TEAMS[2]: {"total": pr["evil_total"] or 0,   "wins": pr["evil_wins"] or 0},
            TEAMS[3]: {"total": pr["rk_total"] or 0,     "wins": pr["rk_wins"] or 0},
            TEAMS[4]: {"total": pr["neutral_total"] or 0,"wins": pr["neutral_wins"] or 0},
            TEAMS[5]: {"total": pr["bonus_total"] or 0,  "wins": pr["bonus_wins"] or 0},
        }

        return {
            "games_as_player": games_as_player,
            "games_as_sponsor": games_as_sponsor,
            "total_games": total_games,
            "total_participations": total_participations,
            "participation_rate": (total_participations / total_games * 100) if total_games else 0,
            "wins_as_player": wins_as_player,
            "wins_as_sponsor": wins_as_sponsor,
            "total_wins": wins_as_player,
            "winrate": (wins_as_player / games_as_player * 100) if games_as_player else 0,
            "team_stats": team_stats,
            "longest_winstreak": longest_winstreak,
            "ws": ws,
            "ls": ls,
            "cws": cws,
            "cls": cls,
            "form": form_str,
            "total_mvps": pr["total_mvps"] or 0,
            "village_mvps": pr["village_mvps"] or 0,
            "evil_mvps": pr["evil_mvps"] or 0,
            "rk_mvps": pr["rk_mvps"] or 0,
            "neutral_mvps": pr["neutral_mvps"] or 0,
        }

    def get_first_game_played(self, player_id: int):
        """Return (game_number, game_name) of the first counted game for a player (sponsor games included)."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT game_number, game_name FROM roles
                WHERE (player_id = ? OR sponsor_id = ?) AND count = 1 AND team != 5
                ORDER BY game_number ASC LIMIT 1
            """, (player_id, player_id))
            row = cursor.fetchone()
            return (row["game_number"], row["game_name"]) if row else (None, None)

    def get_games_played(self, player_id: int):
        """Return an ordered list of game numbers the player appeared in (sponsor games and games overseered as host included)."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT game_number FROM roles
                WHERE (player_id = ? OR sponsor_id = ?) AND count = 1 AND team != 5
                UNION
                SELECT game_number FROM game_hosts
                WHERE host_id = ? AND count = 1
                ORDER BY game_number ASC
            """, (player_id, player_id, player_id))
            return [row[0] for row in cursor.fetchall()]

    def get_player_game_history(self, player_id: int):
        """Return full ordered game history for a player, including games played as sponsor."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT game_number, game_name, role_id, role_name, team, win, mvp,
                       CASE WHEN player_id = ? THEN 'player' ELSE 'sponsor' END AS relation
                FROM roles
                WHERE (player_id = ? OR sponsor_id = ?) AND count = 1 AND team != 5
                ORDER BY game_number DESC
            """, (player_id, player_id, player_id))
            return [
                {
                    "game_number": row["game_number"],
                    "game_name": row["game_name"],
                    "role_id": row["role_id"],
                    "role_name": row["role_name"],
                    "team": row["team"],
                    "result": "🏆 Win" if row["win"] == 1 else "❌ Loss",
                    "mvp": row["mvp"] == 1,
                    "relation": row["relation"],
                }
                for row in cursor.fetchall()
            ]


# ============================================================================
# ITALIAN COMMANDS COG
# ============================================================================

class GameLibraryIT(commands.Cog):
    """Cog per la libreria di gioco italiana."""

    def __init__(self, bot):
        self.bot = bot
        self.db = ItalianLibraryDatabase()

    def is_librarian(self, user_id: int) -> bool:
        return user_id in LIBRARIAN_IDS

    def generate_missingid_embed(self, names, page, max_page):
        listed = "\n".join([f"• {n}" for n in names])
        return discord.Embed(
            title="Giocatori senza Discord ID",
            description=f"Pagina **{page + 1}/{max_page + 1}**\n\n{listed}",
            color=EMBED_COLOR,
        )

    # Guild and category where Italian library channels live.
    GUILD_ID = 1143965328443969586
    CATEGORY_ID = [1143968291346456700, 1546996387789414532]

    def get_game_info_from_channel(self, channel: discord.TextChannel) -> Optional[Tuple[int, str]]:
        """Parse game number and name from an Italian library channel name.
        Matches by category ID so renaming the category won't break this."""
        if not channel.category or channel.category.id not in self.CATEGORY_ID:
            return None
        try:
            parts = channel.name.split("│", 1)
            if len(parts) == 2:
                return (int(parts[0].strip()), parts[1].strip())
        except (ValueError, AttributeError):
            pass
        return None

    # -------------------------------------------------------------------------
    # libit group
    # -------------------------------------------------------------------------

    @commands.group(name="libit", invoke_without_command=True)
    async def libit(self, ctx):
        """Sfoglia la libreria di gioco (italiana)."""
        games = self.db.get_all_games()
        if not games:
            await ctx.send("❌ La libreria italiana è vuota!")
            return
        view = GameSelectView(games, self.db)
        await ctx.send(embed=view.get_embed(), view=view)

    @libit.command(name="add")
    async def libit_add(self, ctx, role_name: str, team: Optional[int] = None, *args):
        """
        Aggiungi un ruolo o host alla partita.

        RUOLO:  .libit add <nome_ruolo> <team> [@giocatore] [@sponsor]
        HOST:   .libit add host @host1 @host2 ...
        """
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ Non hai i permessi per usare questo comando!")
            return

        game_info = self.get_game_info_from_channel(ctx.channel)
        if not game_info:
            await ctx.send("❌ Questo comando deve essere usato in un canale della Libreria italiana!")
            return

        game_number, game_name = game_info

        # --- MODALITÀ HOST ---
        if role_name.lower() == "host":
            mention_ids = [int(i) for i in re.findall(r"<@!?(\d+)>", ctx.message.content)]
            if not mention_ids:
                await ctx.send("❌ Menziona almeno un host.")
                return
            if len(mention_ids) > 5:
                await ctx.send("❌ Massimo 5 host per partita.")
                return

            hosts = []
            for mid in mention_ids:
                try:
                    hosts.append(await ctx.guild.fetch_member(mid))
                except Exception:
                    pass

            if not hosts:
                await ctx.send("❌ Impossibile risolvere gli utenti menzionati.")
                return

            self.db.add_hosts(game_number, hosts)
            embed = discord.Embed(
                title="🎤 Host Aggiunti",
                description=", ".join(m.display_name for m in hosts),
                color=discord.Color.green(),
            )
            embed.add_field(name="Partita", value=f"{game_number} | {game_name}")
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)
            return

        # --- MODALITÀ RUOLO ---
        if team is None:
            await ctx.send("❌ Uso: .libit add <nome_ruolo> <team> [@giocatore] [@sponsor]")
            return

        if team not in TEAMS:
            await ctx.send(f"❌ Team non valido! Usa: {', '.join([f'{k}={v}' for k, v in TEAMS.items()])}")
            return

        role_id = self.db.get_next_role_id(game_number)
        mention_ids = [int(i) for i in re.findall(r"<@!?(\d+)>", ctx.message.content)]

        mentioned_members = []
        for mid in mention_ids:
            try:
                mentioned_members.append(await ctx.guild.fetch_member(mid))
            except Exception:
                pass

        player_name = player_id = sponsor_name = sponsor_id = None
        args_list = list(args)
        mention_idx = 0
        slots = []
        for arg in args_list:
            if arg.startswith("<@") and mention_idx < len(mentioned_members):
                m = mentioned_members[mention_idx]
                slots.append((getattr(m, 'display_name', m.name), m.id))
                mention_idx += 1
            else:
                slots.append((arg, None))

        if slots:
            player_name, player_id = slots[0]
        if len(slots) > 1:
            sponsor_name, sponsor_id = slots[1]

        description1 = None
        if ctx.message.reference:
            try:
                replied = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                description1 = replied.content
            except Exception:
                pass

        try:
            self.db.add_role(
                game_number=game_number, game_name=game_name, role_id=role_id,
                role_name=role_name, team=team, player_name=player_name,
                player_id=player_id, sponsor_name=sponsor_name,
                sponsor_id=sponsor_id, description1=description1,
            )

            embed = discord.Embed(
                title="✅ Ruolo Aggiunto",
                description=f"**{role_name}** (ID: {role_id})",
                color=discord.Color.green(),
            )
            embed.add_field(name="Partita", value=f"{game_number} | {game_name}")
            embed.add_field(name="Team", value=TEAMS[team])
            if player_name:
                embed.add_field(name="Giocatore", value=player_name)
            if sponsor_name:
                embed.add_field(name="Sponsor", value=sponsor_name)
            if description1:
                preview = description1[:200] + ("..." if len(description1) > 200 else "")
                embed.add_field(name="Descrizione", value=preview, inline=False)
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Errore nell'aggiungere il ruolo: `{e}`")

    @commands.group(name="libitadmin", invoke_without_command=True)
    async def libitadmin(self, ctx):
        """[ADMIN] Sfoglia e modifica la libreria italiana (solo librarian)."""
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ Non hai i permessi per usare questo comando!")
            return
        games = self.db.get_all_games()
        if not games:
            await ctx.send("❌ La libreria italiana è vuota!")
            return
        view = AdminGameSelectView(games, self.db, self.bot)
        await ctx.send(embed=view.get_embed(), view=view)


    def generate_team_pie_chart(self, team_counts: dict, game_number: int):
        import matplotlib.pyplot as plt
        teams = [TEAMS.get(tid, "Sconosciuto") for tid, cnt in team_counts.items() if cnt > 0]
        counts = [cnt for cnt in team_counts.values() if cnt > 0]
        plt.figure()
        plt.pie(counts, labels=teams, autopct="%1.1f%%")
        plt.title(f"Partita {game_number} — Distribuzione Team")
        file_path = f"game_it_{game_number}_distribution.png"
        plt.savefig(file_path)
        plt.close()
        return file_path

    @libit.command(name="summary")
    async def libit_summary(self, ctx, game_number: int):
        """Mostra il riepilogo della partita con grafico a torta."""
        summary = self.db.get_game_summary(game_number)
        if not summary or summary["total_roles"] == 0:
            await ctx.send("❌ Partita non trovata o vuota.")
            return

        team_lines = "".join(
            f"**{TEAMS[tid]}:** {summary['team_counts'].get(tid, 0)} ruoli\n"
            for tid in TEAMS
        )
        winner_names = [TEAMS[t] for t in summary["winning_teams"]]
        winner_text = ", ".join(winner_names) if winner_names else "Non impostato"

        embed = discord.Embed(title=f"📊 Riepilogo Partita {game_number}", color=EMBED_COLOR)
        embed.add_field(name="📦 Distribuzione Ruoli", value=team_lines, inline=False)
        embed.add_field(name="👥 Ruoli Totali", value=str(summary["total_roles"]))
        embed.add_field(name="🏆 Team Vincitore/i", value=winner_text)

        hosts = self.db.get_hosts_for_game(game_number)
        if hosts:
            embed.add_field(name="🎤 Host", value=", ".join(hosts), inline=False)

        chart_path = self.generate_team_pie_chart(summary["team_counts"], game_number)
        file = discord.File(chart_path, filename="distribution.png")
        embed.set_image(url="attachment://distribution.png")
        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)

        await ctx.send(embed=embed, file=file)
        if os.path.exists(chart_path):
            os.remove(chart_path)

    @libit.command(name="edit")
    async def libit_edit(self, ctx, field: str, game_number: int, role_id_or_value: str, *, value: str = None):
        """Modifica un campo del ruolo — Uso: .libit edit <campo> <partita#> <role_id> <valore>"""
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ Non hai i permessi!")
            return

        if field.lower() == "gamecount":
            try:
                count_value = int(role_id_or_value)
                if count_value not in [0, 1]:
                    await ctx.send("❌ Valore non valido per gamecount! Usa: 1 (sì) o 0 (no)")
                    return
                self.db.update_game_count(game_number, count_value)
                embed = discord.Embed(
                    title="✅ Conteggio Partita Aggiornato",
                    description=f"Tutti i ruoli della partita {game_number} impostati a count = {count_value}.",
                    color=discord.Color.green(),
                )
                embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
                await ctx.send(embed=embed)
                return
            except ValueError:
                await ctx.send("❌ Valore non valido!")
                return

        try:
            role_id = int(role_id_or_value)
        except ValueError:
            await ctx.send("❌ ID ruolo non valido!")
            return

        valid_fields = [
            "team", "player_name", "player_id", "sponsor_name", "sponsor_id",
            "description1", "description2", "description3", "description4",
            "role_name", "win", "count", "mvp",
        ]
        if field.lower() not in valid_fields:
            await ctx.send(f"❌ Campo non valido! Validi: {', '.join(valid_fields + ['gamecount'])}")
            return

        if field.lower() in ["description1", "description2", "description3", "description4"]:
            if ctx.message.reference:
                try:
                    replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                    value = replied_message.content
                except Exception:
                    if not value:
                        await ctx.send("❌ Impossibile recuperare il messaggio citato e nessun valore fornito!")
                        return
            elif not value:
                await ctx.send("❌ Fornisci un valore o cita un messaggio!")
                return
        elif not value:
            await ctx.send("❌ Fornisci un valore!")
            return

        try:
            if field.lower() in ["team", "player_id", "sponsor_id"]:
                value = int(value)
                if field.lower() == "team" and value not in TEAMS:
                    await ctx.send(f"❌ Team non valido! Usa: {', '.join([f'{k}={v}' for k, v in TEAMS.items()])}")
                    return
            elif field.lower() in ["win", "count", "mvp"]:
                value = int(value)
                if value not in [0, 1]:
                    await ctx.send(f"❌ Valore non valido per {field}! Usa: 1 (sì) o 0 (no)")
                    return

            self.db.update_field(game_number, role_id, field.lower(), value)

            embed = discord.Embed(
                title="✅ Ruolo Aggiornato",
                description=f"Campo **{field}** aggiornato per il ruolo ID {role_id} nella partita {game_number}.",
                color=discord.Color.green(),
            )
            if field.lower() in ["description1", "description2", "description3", "description4"]:
                preview = str(value)[:100] + ("..." if len(str(value)) > 100 else "")
                embed.add_field(name="Nuovo Valore (Anteprima)", value=f"```{preview}```")
            elif field.lower() == "mvp":
                embed.add_field(name="Nuovo Valore", value="⭐ MVP" if value == 1 else "— Non MVP")
            elif field.lower() in ["win", "count"]:
                embed.add_field(name="Nuovo Valore", value="✅ Sì" if value == 1 else "❌ No")
            else:
                embed.add_field(name="Nuovo Valore", value=str(value)[:1024])
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)
        except ValueError as e:
            await ctx.send(f"❌ Tipo di valore non valido! {e}")
        except Exception as e:
            await ctx.send(f"❌ Errore: {e}")

    @libit.command(name="delete")
    async def libit_delete(self, ctx, game_number: int, role_id: int):
        """Elimina un ruolo — Uso: .libit delete <partita#> <role_id>"""
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ Non hai i permessi!")
            return

        role = self.db.get_role_details(game_number, role_id)
        if not role:
            await ctx.send(f"❌ Ruolo ID {role_id} non trovato nella partita {game_number}!")
            return

        try:
            self.db.delete_role(game_number, role_id)
            embed = discord.Embed(
                title="✅ Ruolo Eliminato",
                description=f"Ruolo **{role['role_name']}** (ID: {role_id}) eliminato dalla partita {game_number}.",
                color=discord.Color.green(),
            )
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Errore: {e}")

    @libit.command(name="deletegame")
    async def libit_deletegame(self, ctx, game_number: int):
        """Elimina un'intera partita — Uso: .libit deletegame <partita#>"""
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ Non hai i permessi!")
            return

        game_data = next((g for g in self.db.get_all_games() if g[0] == game_number), None)
        if not game_data:
            await ctx.send(f"❌ Partita {game_number} non trovata!")
            return

        try:
            self.db.delete_game(game_number)
            embed = discord.Embed(
                title="✅ Partita Eliminata",
                description=f"Partita {game_number} ({game_data[1]}) e tutti i ruoli eliminati.",
                color=discord.Color.green(),
            )
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Errore: {e}")

    @libit.command(name="setwin")
    async def libit_setwin(self, ctx, game_number: int, *teams: int):
        """Imposta i vincitori — Uso: .libit setwin <partita#> <team1> [team2]..."""
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ Non hai i permessi!")
            return

        invalid_teams = [t for t in teams if t not in TEAMS]
        if invalid_teams:
            await ctx.send(f"❌ Team non validi: {', '.join(map(str, invalid_teams))}\nValidi: {', '.join([f'{k}={v}' for k, v in TEAMS.items()])}")
            return

        try:
            self.db.set_winners(game_number, list(teams))
            team_names = [TEAMS[t] for t in teams] if teams else ["Nessuno"]
            embed = discord.Embed(
                title="✅ Vincitori Impostati",
                description=f"Vincitori impostati per la partita {game_number}.",
                color=discord.Color.green(),
            )
            embed.add_field(name="Team Vincitore/i", value=", ".join(team_names))
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Errore: {e}")

    @libit.command(name="search")
    async def libit_search(self, ctx, *args):
        """Cerca ruoli (fuzzy). Supporta: .libit search, .libit search <n>, .libit search <partita#>, .libit search <partita#> <n>"""
        if not args:
            view = InteractiveSearchView(self.db)
            embed = discord.Embed(
                title="🔍 Cerca nella Libreria (IT)",
                description=(
                    "Cerca per:\n"
                    "• Nome ruolo (fuzzy)\n"
                    "• Numero partita\n"
                    "• Numero partita + nome ruolo\n\n"
                    "Esempi:\n"
                    "`.libit search dottore`\n"
                    "`.libit search 12`\n"
                    "`.libit search 12 dottore`"
                ),
                color=EMBED_COLOR,
            )
            await ctx.send(embed=embed, view=view)
            return

        if len(args) == 1 and args[0].isdigit():
            game_number = int(args[0])
            game = next((g for g in self.db.get_all_games() if g[0] == game_number), None)
            if not game:
                await ctx.send("❌ Partita non trovata.")
                return
            view = TeamSelectView(game_number, game[1], self.db)
            await ctx.send(embed=view.get_embed(), view=view)
            return

        if args[0].isdigit():
            game_number = int(args[0])
            query = " ".join(args[1:]).strip()
            if not query:
                await ctx.send("❌ Fornisci un nome ruolo da cercare.")
                return
            roles = [r for r in self.db.search_roles_fuzzy(query) if r["game_number"] == game_number]
        else:
            query = " ".join(args).strip()
            roles = self.db.search_roles_fuzzy(query)

        def score(name):
            return SequenceMatcher(None, query.lower(), (name or "").lower()).ratio()

        roles.sort(
            key=lambda r: max(score(r["role_name"]), score(r["player_name"] or ""), score(r["sponsor_name"] or "")),
            reverse=True,
        )

        if not roles:
            await ctx.send("❌ Nessun ruolo corrispondente trovato.")
            return

        if len(roles) == 1:
            role = roles[0]
            team_roles = self.db.get_roles_by_team(role["game_number"], role["team"])
            index = next(i for i, r in enumerate(team_roles) if r[0] == role["role_id"])
            view = RoleDescriptionView(role["game_number"], role["game_name"], team_roles, index, self.db)
            await ctx.send(embed=view.get_embed(), view=view)
            return

        view = RoleSelectionView(roles, self.db)
        await ctx.send(embed=view.get_embed(), view=view)

    @libit.command(name="idsearch")
    async def libit_idsearch(self, ctx, game_number: int, role_id: int):
        """Vai direttamente a un ruolo per ID — Uso: .libit idsearch <partita#> <role_id>"""
        role_data = self.db.get_role_details(game_number, role_id)
        if not role_data:
            await ctx.send(f"❌ Ruolo ID {role_id} non trovato nella partita {game_number}!")
            return
        roles = self.db.get_roles_by_team(game_number, role_data["team"])
        index = next(i for i, r in enumerate(roles) if r[0] == role_id)
        view = RoleDescriptionView(game_number, role_data["game_name"], roles, index, self.db)
        await ctx.send(embed=view.get_embed(), view=view)

    @libit.command(name="migrateaccount")
    async def libit_migrateaccount(self, ctx, old_identifier: str, new_member: discord.Member):
        """
        Sposta le statistiche da un vecchio account (nome O id) a un nuovo account Discord.

        Esempi:
        .libit migrateaccount "VecchioNome" @NuovoUtente
        .libit migrateaccount 123456789 @NuovoUtente
        """
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ Non hai i permessi!")
            return

        db = self.db
        old_id = None

        if old_identifier.isdigit():
            old_id = int(old_identifier)
        else:
            matches = db.find_accounts_by_name(old_identifier)
            if len(matches) == 0:
                await ctx.send("❌ Nessun account trovato con quel nome.")
                return

            if len(matches) > 1:
                msg = "⚠️ Trovati più account. Rispondi con il numero:\n\n"
                for i, (pid, pname) in enumerate(matches, start=1):
                    msg += f"**{i}.** {pname} (`{pid}`)\n"
                await ctx.send(msg)

                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel and m.content.isdigit()

                try:
                    reply = await self.bot.wait_for("message", check=check, timeout=30)
                    choice = int(reply.content)
                    if choice < 1 or choice > len(matches):
                        await ctx.send("❌ Selezione non valida.")
                        return
                    old_id = matches[choice - 1][0]
                except asyncio.TimeoutError:
                    await ctx.send("⌛ Tempo scaduto. Migrazione annullata.")
                    return
            else:
                old_id = matches[0][0]

        if old_id == new_member.id:
            await ctx.send("❌ Account sorgente e destinazione sono uguali.")
            return

        old_player_rows, old_sponsor_rows = db.get_account_stat_counts(old_id)
        if old_player_rows == 0 and old_sponsor_rows == 0:
            await ctx.send("⚠️ Attenzione: l'account sorgente non ha statistiche registrate.")

        new_player_rows, new_sponsor_rows = db.get_account_stat_counts(new_member.id)
        if new_player_rows > 0 or new_sponsor_rows > 0:
            await ctx.send("⚠️ L'account destinazione ha già delle statistiche.\nUsa `.libit mergeaccount`.")
            return

        db.migrate_account_by_id(old_id, new_member.id, new_member.display_name)
        await ctx.send(f"✅ Migrazione completata → **{new_member.display_name}** ha ora le vecchie statistiche.")

    @libit.command(name="mergeaccount")
    async def libit_mergeaccount(self, ctx, source_input: str, target_input: str):
        """Unisci due account. Le statistiche sorgente vengono assorbite dalla destinazione."""
        db = self.db

        async def resolve_account(user_input, label):
            if ctx.message.mentions:
                for m in ctx.message.mentions:
                    if user_input in [m.mention, str(m.id)]:
                        return m.id, m.display_name
            if user_input.isdigit():
                return int(user_input), f"User-{user_input}"
            matches = db.find_accounts_by_name(user_input)
            if not matches:
                await ctx.send(f"❌ Nessuna corrispondenza trovata per `{user_input}`")
                return None, None
            if len(matches) == 1:
                return matches[0][0], matches[0][1]
            msg = f"🔎 Più corrispondenze per **{label}** `{user_input}`:\n\n"
            for i, (pid, pname) in enumerate(matches[:10], 1):
                msg += f"{i}. **{pname}** ({pid})\n"
            msg += "\nRispondi con il numero."
            await ctx.send(msg)

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel and m.content.isdigit()

            try:
                reply = await self.bot.wait_for("message", check=check, timeout=30)
                idx = int(reply.content) - 1
                if 0 <= idx < len(matches):
                    return matches[idx][0], matches[idx][1]
            except Exception:
                pass
            await ctx.send("❌ Selezione fallita.")
            return None, None

        source_id, source_name = await resolve_account(source_input, "SORGENTE")
        if not source_id:
            return

        target_id, target_name = await resolve_account(target_input, "DESTINAZIONE")
        if not target_id:
            return

        if source_id == target_id:
            await ctx.send("❌ Account sorgente e destinazione sono uguali.")
            return

        try:
            db.merge_accounts(source_id, target_id, target_name)
            await ctx.send(f"✅ Unione completata!\nSpostate le statistiche di **{source_name}** → **{target_name}**")
        except Exception as e:
            await ctx.send("❌ Unione fallita. Contatta un admin.")
            print("Merge error (IT):", e)

    @libit.command(name="syncname")
    async def libit_syncname(self, ctx, member: discord.Member, scope: str = "both"):
        """
        Sincronizza il nome salvato per un singolo account.

        Uso:
        .libit syncname @Utente
        .libit syncname @Utente player
        .libit syncname @Utente sponsor
        .libit syncname @Utente both
        """
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ Non hai i permessi!")
            return

        scope = scope.lower()
        include_player = scope in ("player", "both")
        include_sponsor = scope in ("sponsor", "both")

        if not include_player and not include_sponsor:
            await ctx.send("❌ Il parametro scope deve essere uno tra: `player`, `sponsor`, `both`.")
            return

        updated_player, updated_sponsor = self.db.sync_account_name(
            member.id, member.display_name,
            include_player=include_player, include_sponsor=include_sponsor,
        )

        if updated_player == 0 and updated_sponsor == 0:
            await ctx.send(f"ℹ️ Nessuna statistica trovata per **{member.display_name}** (per player_id / sponsor_id).")
            return

        parts = []
        if include_player:
            parts.append(f"{updated_player} righe giocatore")
        if include_sponsor:
            parts.append(f"{updated_sponsor} righe sponsor")

        await ctx.send(f"✅ Nome sincronizzato per **{member.display_name}** su {', '.join(parts)}.")

    @libit.command(name="bulksyncnames")
    async def libit_bulksyncnames(self, ctx):
        """Sincronizza in massa i nomi salvati per tutti gli account italiani."""
        if not self.is_librarian(ctx.author.id):
            await ctx.send("❌ Non hai i permessi!")
            return

        all_ids = self.db.get_all_account_ids()
        if not all_ids:
            await ctx.send("ℹ️ Nessun account con ID salvati trovato.")
            return

        await ctx.send(f"🔄 Sincronizzazione dei nomi per **{len(all_ids)}** account conosciuti in questo server...")

        total_player_updates = total_sponsor_updates = missing_members = 0

        for discord_id in all_ids:
            try:
                member = ctx.guild.get_member(discord_id) or await ctx.guild.fetch_member(discord_id)
            except Exception:
                member = None

            if not member:
                missing_members += 1
                continue

            up, us = self.db.sync_account_name(discord_id, member.display_name)
            total_player_updates += up
            total_sponsor_updates += us

        msg = (
            f"✅ Sincronizzazione completata.\n"
            f"Aggiornate **{total_player_updates}** righe giocatore e **{total_sponsor_updates}** righe sponsor.\n"
        )
        if missing_members:
            msg += f"⚠️ {missing_members} ID non trovati in questo server (gli utenti potrebbero aver lasciato il server)."

        await ctx.send(msg)

    @libit.command(name="help")
    async def libit_help(self, ctx):
        """Mostra l'aiuto per la libreria italiana."""
        embed = discord.Embed(
            title="📚 Libreria Partite — Aiuto (IT)",
            description="Sfoglia i ruoli, vedi le statistiche e gestisci la libreria italiana.",
            color=EMBED_COLOR,
        )

        embed.add_field(name="🔍 Navigazione & Ricerca", value=(
            "**`.libit`**\nApri il browser interattivo delle partite (IT)\n\n"
            "**`.libit browse`**\nBrowser interattivo (stesso di .libit)\n\n"
            "**`.libit search`**\nRicerca interattiva (ruoli, giocatori, sponsor)\n\n"
            "**`.libit search <nome_ruolo>`**\nRicerca fuzzy ruoli in tutte le partite italiane\n\n"
            "**`.libit search <partita#>`**\nVai direttamente a una partita\n\n"
            "**`.libit search <partita#> <nome_ruolo>`**\nCerca all'interno di una partita specifica\n\n"
            "**`.libit searchdisc <query>`**\nCerca nelle descrizioni dei ruoli\n\n"
            "**`.libit idsearch <partita#> <role_id>`**\nVai direttamente a un ruolo per ID\n\n"
            "**`.libit summary <partita#>`**\nRiepilogo partita + grafico a torta"
        ), inline=False)

        embed.add_field(name="📊 Statistiche (IT)", value=(
            "**`.statsit`** o **`.statsit @giocatore`**\nMostra le statistiche del giocatore (IT)\n\n"
            "**`.statsos`** o **`.statsos <nome|@ping>`**\nStatistiche overseer (partite gestite)\n\n"
            "**`.libit lbos`**\nClassifica overseer\n\n"
            "**`.winrateit`**\nMostra le winrate dei team (IT)\n\n"
            "**`.relationsit`** o **`.relationsit @giocatore`**\nLista completa di alleati, peggiori alleati e nemici (IT)"
        ), inline=False)

        embed.add_field(name="🎤 Overseer (IT)", value=(
            "**`.libit searchos <nome|@ping>`**\nCerca partite gestite da un overseer\n\n"
            "**`.libit statsos <nome|@ping>`**\nStatistiche dettagliate di un overseer\n\n"
            "**`.libit lbos`**\nClassifica di tutti gli overseer"
        ), inline=False)

        if self.is_librarian(ctx.author.id):
            embed.add_field(name="🔧 Gestione Ruoli", value=(
                "**`.libit add <nome_ruolo> <team> [@giocatore] [@sponsor]`**\nAggiungi un ruolo (cita per descrizione)\n\n"
                "**`.libit edit <campo> <partita#> <role_id> <valore>`**\n"
                "Modifica: team, role_name, player_name, player_id,\n"
                "sponsor_name, sponsor_id, description1-4, win, count, mvp\n\n"
                "**`.libit delete <partita#> <role_id>`**\nElimina un ruolo"
            ), inline=False)

            embed.add_field(name="🎮 Controllo Partita", value=(
                "**`.libit edit gamecount <partita#> <0|1>`**\nIncludi/escludi partita dalle statistiche\n\n"
                "**`.libit setwin <partita#> <team> [team2]...`**\nImposta team vincitore/i\n\n"
                "**`.libit deletegame <partita#>`**\nElimina un'intera partita"
            ), inline=False)

            embed.add_field(name="👤 Strumenti Account (IT)", value=(
                "**`.libit migrateaccount <vecchio_nome|vecchio_id> @nuovo_utente`**\nSposta le statistiche su un nuovo account\n\n"
                "**`.libit mergeaccount <sorgente> <target>`**\nUnisci due account\n\n"
                "**`.libit syncname @utente [player|sponsor|both]`**\nSincronizza il nome salvato per un singolo account\n\n"
                "**`.libit bulksyncnames`**\nSincronizzazione in massa dei nomi salvati"
            ), inline=False)

        team_info = " • ".join([f"**{id}** = {name}" for id, name in TEAMS.items()])
        embed.add_field(name="🎯 ID Team", value=team_info, inline=False)
        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
        await ctx.send(embed=embed)

    # -------------------------------------------------------------------------
    # Standalone Italian commands
    # -------------------------------------------------------------------------

    @commands.has_permissions(administrator=True)
    @commands.command(name="missingidsit")
    async def missing_ids_it(self, ctx):
        """Mostra i giocatori senza Discord ID assegnato (IT)."""
        if not self.db.get_all_games():
            await ctx.send("❌ La libreria italiana è vuota! Nessuna partita è stata ancora registrata.")
            return
        missing = self.db.get_players_missing_ids()
        if not missing:
            await ctx.send("✅ Tutti i giocatori hanno un ID assegnato.")
            return

        view = MissingIDPageView(self, missing, page=0)
        embed = self.generate_missingid_embed(view.visible_names, 0, view.max_page)
        await ctx.send(embed=embed, view=view)

    @commands.has_permissions(administrator=True)
    @commands.command(name="badnamesit")
    async def bad_names_it(self, ctx):
        """Mostra i nomi dei giocatori che causano errori nella paginazione (>100 caratteri)."""
        with self.db._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT player_name, LENGTH(player_name) AS len
                FROM roles
                WHERE player_name IS NOT NULL AND LENGTH(player_name) > 30
                ORDER BY len DESC
            """)
            rows = cursor.fetchall()

        if not rows:
            await ctx.send("✅ Nessun nome problematico trovato.")
            return

        lines = [f"[{row['len']} chars] {row['player_name']!r}" for row in rows]
        msg = f"⚠️ **{len(rows)} nome/i con più di 100 caratteri:**\n```\n" + "\n".join(lines) + "\n```"
        await ctx.send(msg)

    @commands.has_permissions(administrator=True)
    @commands.command(name="removebadnameit")
    async def remove_bad_name_it(self, ctx, *, player_name: str):
        """Rimuove player_name e player_id da tutte le righe con quel nome — Uso: .removebadnameit <nome>"""
        with self.db._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM roles WHERE player_name = ?", (player_name,))
            count = cursor.fetchone()[0]

        if count == 0:
            await ctx.send(f"❌ Nessuna riga trovata con il nome `{player_name[:200]}`.")
            return

        with self.db._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE roles SET player_name = NULL, player_id = NULL WHERE player_name = ?",
                (player_name,),
            )
            conn.commit()

        await ctx.send(f"✅ Nome rimosso da **{count}** righe.")

    @commands.command(name="statsit")
    async def statsit(self, ctx, *, member_input: str = None):
        """Statistiche giocatore (IT) — Uso: .statsit o .statsit @giocatore o .statsit NomeGiocatore"""
        member = None

        if not member_input:
            member = ctx.author
        else:
            mention_match = re.search(r"<@!?(\d+)>", member_input)
            if mention_match:
                try:
                    member = await ctx.guild.fetch_member(int(mention_match.group(1)))
                except Exception:
                    member = None

        if not member and member_input:
            lowered = member_input.lower()
            for m in ctx.guild.members:
                if m.display_name.lower() == lowered or m.name.lower() == lowered:
                    member = m
                    break

        if not member and member_input:
            matches = self.db.find_accounts_by_name(member_input)

            if len(matches) == 0:
                await ctx.send("❌ Nessun giocatore trovato con quel nome.")
                return

            if len(matches) > 1:
                msg = "⚠️ Trovate più corrispondenze. Rispondi con il numero:\n\n"
                for i, (pid, pname) in enumerate(matches, start=1):
                    msg += f"**{i}.** {pname} (`{pid}`)\n"
                await ctx.send(msg)

                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel and m.content.isdigit()

                try:
                    reply = await self.bot.wait_for("message", check=check, timeout=30)
                    choice = int(reply.content)
                    if choice < 1 or choice > len(matches):
                        await ctx.send("❌ Selezione non valida.")
                        return
                    chosen_id, chosen_name = matches[choice - 1]
                except asyncio.TimeoutError:
                    await ctx.send("⌛ Tempo scaduto.")
                    return
            else:
                chosen_id, chosen_name = matches[0]

            class FakeMember:
                def __init__(self, id, name, avatar):
                    self.id = id
                    self.display_name = name
                    self.display_avatar = avatar

            member = FakeMember(chosen_id, chosen_name, ctx.author.display_avatar)

        if not member:
            await ctx.send("❌ Impossibile trovare il giocatore.")
            return

        stats = self.db.get_player_stats(member.id)

        if stats["total_participations"] == 0:
            await ctx.send(f"❌ Nessuna statistica trovata per {member.display_name}!")
            return

        embed = discord.Embed(title=f"📊 {member.display_name}", color=EMBED_COLOR)
        embed.set_thumbnail(url=member.display_avatar.url)

        first_game_num, first_game_name = self.db.get_first_game_played(member.id)
        first_game_line = (
            f"**Prima Partita:** {first_game_num} — {first_game_name}\n"
            if first_game_num
            else "**Prima Partita:** Sconosciuta\n"
        )

        games_list = self.db.get_games_played(member.id)
        if len(games_list) >= 2:
            gaps = [games_list[i + 1] - games_list[i] for i in range(len(games_list) - 1)]
            avg_gap = sum(gaps) / len(gaps)
            total_from_start = max(games_list) - min(games_list) + 1
            participation_after_join = (len(games_list) / total_from_start) * 100
            avg_gap_line = f"**Gap Medio:** {avg_gap:.2f} partite\n**Partecipazione dopo l'ingresso:** {participation_after_join:.1f}%\n"
        else:
            avg_gap_line = "**Gap Medio:** Dati insufficienti\n"

        top_allies = self.db.get_top_allies2(member.id)
        ally_text = (
            "".join(f"• **{pname}** — {wr * 100:.1f}% WR ({wins}V / {games}P)\n"
                    for pid, pname, wins, games, wr in top_allies)
            or "*Nessun alleato trovato.*"
        )

        worst_allies = self.db.get_worst_allies2(member.id)
        worst_text = (
            "".join(f"• **{pname}** — {wr * 100:.1f}% WR ({wins}V / {games}P)\n"
                    for pid, pname, wins, games, wr in worst_allies)
            or "*Nessuna alleanza sfortunata trovata.*"
        )

        top_nemeses = self.db.get_top_nemeses2(member.id)
        nem_text = (
            "".join(f"• **{pname}** — {lr * 100:.1f}% Sconfitte ({losses}S / {games}P)\n"
                    for pid, pname, losses, games, lr in top_nemeses)
            or "*Nessun nemico trovato.*"
        )

        overall = first_game_line + avg_gap_line
        overall += f"**Partite:** {stats['games_as_player']} giocate · {stats['games_as_sponsor']} sponsorizzate\n"
        overall += f"**Vittorie:** {stats['wins_as_player']}V (giocatore) · {stats['wins_as_sponsor']}V (sponsor)\n"
        overall += f"**Winrate:** {stats['winrate']:.1f}% · **Partecipazioni:** {stats['total_participations']} ({stats['participation_rate']:.1f}%)\n"
        overall += f"**WS Village:** {stats.get('longest_winstreak', 0)}"

        embed.add_field(name="📈 Generali", value=overall, inline=False)

        # MVP breakdown
        total_mvps = stats.get("total_mvps", 0)
        mvp_parts = []
        if stats.get("village_mvps", 0): mvp_parts.append(f"🏘️ Village: {stats['village_mvps']}")
        if stats.get("evil_mvps", 0):    mvp_parts.append(f"😈 Evil: {stats['evil_mvps']}")
        if stats.get("rk_mvps", 0):      mvp_parts.append(f"🔪 RK: {stats['rk_mvps']}")
        if stats.get("neutral_mvps", 0): mvp_parts.append(f"⚖️ Neutral: {stats['neutral_mvps']}")
        mvp_value = f"**Totale:** ⭐ {total_mvps}\n" + ("\n".join(mvp_parts) if mvp_parts else "*Nessun dettaglio per team*")
        embed.add_field(name="⭐ MVP", value=mvp_value, inline=True)

        embed.add_field(
            name="📊 Strisce",
            value=(
                f"Migliori: {stats['ws']}V / {stats['ls']}S\n"
                f"Ora: +{stats['cws']} / -{stats['cls']}\n"
                f"Forma: {stats['form'] or '—'}"
            ),
            inline=True,
        )

        for team_name, team_data in stats["team_stats"].items():
            if team_data["total"] > 0 and team_name != "Bonus/Extra":
                team_winrate = team_data["wins"] / team_data["total"] * 100
                embed.add_field(
                    name=team_name,
                    value=f"{team_data['wins']}V/{team_data['total']}P ({team_winrate:.0f}%)",
                    inline=True,
                )

        embed.add_field(name="🟦 Top 5 Alleati", value=ally_text, inline=False)
        embed.add_field(name="🟥 Top 5 Nemici", value=nem_text, inline=False)
        embed.add_field(name="☠️ Peggiori Alleati", value=worst_text, inline=False)
        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)

        await ctx.send(embed=embed, view=StatsView(self.db, member))

    @commands.command(name="winrateit")
    async def winrateit(self, ctx):
        """Mostra le winrate dei team (IT)."""
        stats = self.db.get_winrate_stats()
        embed = discord.Embed(
            title="📊 Statistiche Winrate dei Team (IT)",
            description="Prestazioni generali in tutte le partite italiane",
            color=EMBED_COLOR,
        )
        for team_name, data in stats.items():
            embed.add_field(
                name=team_name,
                value=f"**Partite:** {data['total']}\n"
                      f"**Split:** {data['wins']}/{data['total_games']}\n"
                      f"**Vittorie:** {data['wins']}\n"
                      f"**Winrate:** {data['winrate']:.1f}%",
                inline=True,
            )
        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
        await ctx.send(embed=embed)

    @commands.command(name="relationsit")
    async def relationsit(self, ctx, member: discord.Member = None):
        """Lista completa di alleati, peggiori alleati e nemici (IT) — Uso: .relationsit [@giocatore]"""
        if member is None:
            member = ctx.author

        allies = self.db.get_all_allies2(member.id)
        worst_allies = self.db.get_all_worst_allies2(member.id)
        nemeses = self.db.get_all_nemeses2(member.id)

        if not allies and not worst_allies and not nemeses:
            await ctx.send(f"❌ Nessun dato di relazione trovato per {member.display_name}!")
            return

        def format_rows(rows, is_loss=False):
            return [(x[1], f"{x[2]}{'S' if is_loss else 'V'} / {x[3]}P", f"{x[4]*100:.1f}") for x in rows]

        view = RelationsView(
            ctx=ctx,
            player=member.display_name,
            allies=format_rows(allies),
            worst=format_rows(worst_allies),
            nemesis=format_rows(nemeses, is_loss=True)
        )

        embed = view.build_embed(f"Alleati di {member.display_name}", view.allies)
        await ctx.send(embed=embed, view=view)

    # -------------------------------------------------------------------------
    # Italian views — mirroring English views with Italian labels
    # -------------------------------------------------------------------------

    @libit.command(name="browse")
    async def libit_browse(self, ctx):
        """Apri il browser interattivo delle partite italiane."""
        games = self.db.get_all_games()
        if not games:
            await ctx.send("❌ La libreria italiana è vuota!")
            return
        view = ItalianGameSelectView(games, self.db)
        await ctx.send(embed=view.get_embed(), view=view)

    @libit.command(name="statsos")
    async def libit_statsos(self, ctx, *, member_input: str = None):
        """Statistiche overseer (IT) — Uso: .libit statsos o .libit statsos <nome> o .libit statsos @ping"""
        if not member_input:
            db_name = self.db.get_host_name_by_id(ctx.author.id)
            if not db_name:
                await ctx.send("❌ Non hai statistiche overseer registrate.")
                return
            sponsor_name = db_name
            avatar_url = ctx.author.display_avatar.url
        else:
            sponsor_name, avatar_url = await self._resolve_overseer_input_it(ctx, member_input)
            if not sponsor_name:
                return

        stats = self.db.get_overseer_stats(sponsor_name)

        if not stats or stats["total_games"] == 0:
            fuzzy = self.db.search_hosts_fuzzy(sponsor_name)
            if len(fuzzy) == 1:
                sponsor_name = fuzzy[0]
                stats = self.db.get_overseer_stats(sponsor_name)
            elif len(fuzzy) > 1:
                matches = "\n".join(f"**{i+1}.** {n}" for i, n in enumerate(fuzzy[:10]))
                await ctx.send(f"❌ Nessuna statistica overseer per '{sponsor_name}'.\n\nForse cercavi:\n{matches}")
                return

        if not stats or stats["total_games"] == 0:
            await ctx.send(f"❌ Nessuna statistica overseer per '{sponsor_name}'!")
            return

        history = self.db.get_overseer_game_history(sponsor_name)

        view = ItalianOverseerStatsView(self.db, stats, history, sponsor_name, avatar_url)
        await ctx.send(embed=view.get_embed(), view=view)

    @libit.command(name="searchos")
    async def libit_searchos(self, ctx, *, name: str = None):
        """Cerca partite gestite da un overseer (IT) — Uso: .libit searchos <nome> o .libit searchos @ping"""
        if not name:
            view = ItalianOverseerSearchView(self.db)
            embed = discord.Embed(
                title="🔍 Cerca per Overseer",
                description=(
                    "Cerca tutte le partite gestite da una persona specifica.\n\n"
                    "Esempi:\n"
                    "`.libit searchos NomeGiocatore`\n"
                    "`.libit searchos @Giocatore`"
                ),
                color=EMBED_COLOR,
            )
            await ctx.send(embed=embed, view=view)
            return

        sponsor_name, _ = await self._resolve_overseer_input_it(ctx, name)
        if not sponsor_name:
            await ctx.send(f"❌ Impossibile risolvere '{name}' come overseer!")
            return

        games = self.db.search_games_by_host_name(sponsor_name)
        if not games:
            await ctx.send(f"❌ Nessuna partita trovata per l'overseer '{sponsor_name}'!")
            return

        view = ItalianOverseerSearchSelectView(games, self.db)
        await ctx.send(embed=view.get_embed(), view=view)

    @libit.command(name="searchdisc")
    async def libit_searchdisc(self, ctx, *, query: str = ""):
        """Cerca nelle descrizioni dei ruoli (IT) — Uso: .libit searchdisc <query>"""
        if not query.strip():
            view = ItalianInteractiveSearchView(self.db)
            embed = discord.Embed(
                title="🔍 Cerca Descrizioni Ruoli",
                description=(
                    "Cerca in TUTTI i campi testuali dei ruoli:\n"
                    "• Nome ruolo, alias\n"
                    "• Descrizione, abilità\n"
                    "• Nome giocatore e sponsor\n"
                    "• Nome partita\n\n"
                    "**Sintassi di ricerca:**\n"
                    "• Parole = OR (corrispondenza qualsiasi)\n"
                    "• `\"virgolette\"` = sottostringa esatta\n"
                    "• Multiple `\"virgolette\"` = AND (tutte nello stesso ruolo)\n"
                    "• Fine con numero = filtra per partita\n\n"
                    "Esempi:\n"
                    "`.libit searchdisc teleport` — OR\n"
                    "`.libit searchdisc \"teleport\" \"visit\"` — AND\n"
                    "`.libit searchdisc teleport 87` — per partita"
                ),
                color=EMBED_COLOR,
            )
            await ctx.send(embed=embed, view=view)
            return

        game_number = None
        parts = query.rsplit(None, 1)
        if len(parts) == 2 and parts[1].isdigit():
            game_number = int(parts[1])
            query = parts[0]

        if not query.strip():
            await ctx.send("❌ Query non valida.")
            return

        phrases, tokens = self._parse_search_query_it((query,))

        if not phrases and not tokens:
            await ctx.send("❌ Query non valida.")
            return

        if phrases and not tokens:
            if len(phrases) == 1:
                roles = self.db.search_roles_deep_phrase(phrases[0], limit=500)
            else:
                role_sets = []
                for phrase in phrases:
                    role_sets.append(set(
                        (r["game_number"], r["role_id"])
                        for r in self.db.search_roles_deep_phrase(phrase, limit=500)
                    ))
                common_ids = role_sets[0]
                for rs in role_sets[1:]:
                    common_ids &= rs
                all_roles = []
                for phrase in phrases:
                    all_roles.extend(self.db.search_roles_deep_phrase(phrase, limit=500))
                roles = [r for r in all_roles
                         if (r["game_number"], r["role_id"]) in common_ids]
                seen = set()
                roles = [r for r in roles
                         if not ((r["game_number"], r["role_id"]) in seen
                                 or seen.add((r["game_number"], r["role_id"])))]
            roles.sort(key=lambda r: self._score_deep_match_it(r, phrases), reverse=True)
        elif tokens and not phrases:
            roles = self.db.search_roles_deep(tokens, limit=500)
        else:
            all_terms = phrases + tokens
            all_roles = []
            for term in all_terms:
                all_roles.extend(self.db.search_roles_deep_phrase(term, limit=500))
            term_matches = []
            for role_dict in all_roles:
                matched_all = True
                for term in all_terms:
                    if not self._check_role_matches_term_it(role_dict, term):
                        matched_all = False
                        break
                if matched_all:
                    term_matches.append(role_dict)
            seen = set()
            roles = []
            for r in term_matches:
                k = (r["game_number"], r["role_id"])
                if k not in seen:
                    seen.add(k)
                    roles.append(r)
            roles.sort(key=lambda r: self._score_deep_match_it(r, all_terms), reverse=True)

        if game_number is not None:
            roles = [r for r in roles if r["game_number"] == game_number]

        if not roles:
            await ctx.send("❌ Nessun ruolo corrispondente trovato.")
            return

        if len(roles) == 1:
            role = roles[0]
            team_roles = self.db.get_roles_by_team(role["game_number"], role["team"])
            index = next(i for i, r in enumerate(team_roles) if r[0] == role["role_id"])
            view = RoleDescriptionView(role["game_number"], role["game_name"], team_roles, index, self.db)
            await ctx.send(embed=view.get_embed(), view=view)
            return

        view = RoleSelectionView(roles, self.db)
        await ctx.send(embed=view.get_embed(), view=view)

    # -------------------------------------------------------------------------
    # Helper methods for Italian search
    # -------------------------------------------------------------------------

    async def _resolve_overseer_input_it(self, ctx, member_input: str):
        """Resolve ping, username, or nickname to (sponsor_name, avatar_url)."""
        member = None
        if ctx.guild:
            mention_match = re.search(r"<@!?(\d+)>", member_input)
            if mention_match:
                try:
                    member = await ctx.guild.fetch_member(int(mention_match.group(1)))
                except Exception:
                    member = None

            if not member:
                lowered = member_input.strip().lower()
                for m in ctx.guild.members:
                    if m.display_name.lower() == lowered or m.name.lower() == lowered:
                        member = m
                        break

        if member:
            db_name = self.db.get_host_name_by_id(member.id)
            if db_name:
                return db_name, member.display_avatar.url
            return member_input.strip(), member.display_avatar.url

        return member_input.strip(), None

    def _parse_search_query_it(self, args: tuple) -> Tuple[List[str], List[str]]:
        """Parse search args into quoted phrases and unquoted tokens."""
        raw = " ".join(args)
        if not raw.strip():
            return [], []
        phrases = []
        for match in re.finditer(r'"([^"]*)"', raw):
            phrases.append(match.group(1))
        for match in re.finditer(r"'([^']*)'", raw):
            phrases.append(match.group(1))
        remaining = re.sub(r'"[^"]*"', '', raw)
        remaining = re.sub(r"'[^']*'", '', remaining)
        tokens = [t for t in remaining.split() if t.strip()]
        return phrases, tokens

    def _score_deep_match_it(self, role: dict, terms: List[str]) -> float:
        """Score a role against a list of search terms."""
        TEAM_NAMES = {1: "Village", 2: "Evil", 3: "Random Killer", 4: "Neutral", 5: "Bonus/Extra"}
        fields = {
            "role_name": (role.get("role_name") or "").lower(),
            "player_name": (role.get("player_name") or "").lower(),
            "sponsor_name": (role.get("sponsor_name") or "").lower(),
            "game_name": (role.get("game_name") or "").lower(),
            "description1": (role.get("description1") or "").lower(),
            "description2": (role.get("description2") or "").lower(),
            "description3": (role.get("description3") or "").lower(),
            "description4": (role.get("description4") or "").lower(),
            "team": TEAM_NAMES.get(role.get("team"), "").lower(),
        }
        total_matches = 0
        fields_hit = set()
        for term in terms:
            t = term.lower()
            for fname, fval in fields.items():
                if t in fval:
                    total_matches += 1
                    fields_hit.add(fname)
                    if fname == "role_name":
                        total_matches += 2
        spread_bonus = len(fields_hit) * 0.5
        return total_matches + spread_bonus

    def _check_role_matches_term_it(self, role: dict, term: str) -> bool:
        """Check if a role matches a single search term across all text fields."""
        TEAM_NAMES = {1: "Village", 2: "Evil", 3: "Random Killer", 4: "Neutral", 5: "Bonus/Extra"}
        text_fields = [
            role.get("role_name") or "",
            role.get("player_name") or "",
            role.get("sponsor_name") or "",
            role.get("game_name") or "",
            role.get("description1") or "",
            role.get("description2") or "",
            role.get("description3") or "",
            role.get("description4") or "",
            TEAM_NAMES.get(role.get("team"), ""),
        ]
        combined = " ".join(text_fields).lower()
        return term.lower() in combined

    @libit.command(name="lbos")
    async def libit_lbos(self, ctx):
        """Classifica overseer (IT)."""
        all_stats = self.db.get_all_overseer_stats()
        if not all_stats:
            await ctx.send("❌ Nessun dato overseer trovato.")
            return
        view = ItalianOverseerLeaderboardView(all_stats)
        await ctx.send(embed=view.get_embed(), view=view)


# =============================================================================
# ITALIAN VIEWS — etichette in italiano
# =============================================================================


class ItalianGameSelectView(discord.ui.View):
    """Browser interattivo delle partite italiane."""

    def __init__(self, games: List[Tuple[int, str]], db, page: int = 0):
        super().__init__(timeout=300)
        self.games = games
        self.db = db
        self.page = page
        import math as _math
        self.max_page = _math.ceil(len(games) / 10) - 1

        if self.max_page > 0:
            self.prev_btn = discord.ui.Button(label="◀ Precedente", style=discord.ButtonStyle.primary, disabled=True)
            self.prev_btn.callback = self.prev_page
            self.add_item(self.prev_btn)

            self.next_btn = discord.ui.Button(label="Successiva ▶", style=discord.ButtonStyle.primary)
            self.next_btn.callback = self.next_page
            self.add_item(self.next_btn)

    def get_embed(self) -> discord.Embed:
        start_idx = self.page * 10
        end_idx = min(start_idx + 10, len(self.games))
        page_games = self.games[start_idx:end_idx]

        embed = discord.Embed(
            title="📚 Libreria Partite — Seleziona una Partita",
            description="Usa il campo qui sotto per inserire il numero della partita che vuoi visualizzare.",
            color=EMBED_COLOR,
        )

        games_text = ""
        for game_num, game_name in page_games:
            winners = self.db.get_winning_teams(game_num)
            winner_str = f" | 🏆 {', '.join(winners)}" if winners else ""
            games_text += f"**{game_num}** | {game_name.replace('-', ' ').title()}{winner_str}\n"

        embed.add_field(name="Partite Disponibili", value=games_text, inline=False)

        if self.max_page > 0:
            embed.set_footer(text=f"{EMBED_FOOTER_TEXT} | Pagina {self.page + 1}/{self.max_page + 1}", icon_url=EMBED_FOOTER_ICON)
        else:
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)

        return embed

    async def prev_page(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        await self.update_view(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.page = min(self.max_page, self.page + 1)
        await self.update_view(interaction)

    async def update_view(self, interaction: discord.Interaction):
        if self.max_page > 0:
            self.prev_btn.disabled = (self.page == 0)
            self.next_btn.disabled = (self.page == self.max_page)
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="🔢 Inserisci Numero Partita", style=discord.ButtonStyle.success, row=1)
    async def open_game_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ItalianGameNumberModal(self.games, self.db)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🔍 Cerca", style=discord.ButtonStyle.primary, row=1)
    async def open_search(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ItalianInteractiveSearchView(self.db)
        embed = discord.Embed(
            title="🔍 Cerca nella Libreria",
            description=(
                "Cerca per:\n"
                "• Nome ruolo (fuzzy)\n"
                "• Numero partita\n"
                "• Numero partita + nome ruolo\n\n"
                "Esempi:\n"
                "`.libit search dottore`\n"
                "`.libit search 12`\n"
                "`.libit search 12 dottore`"
            ),
            color=EMBED_COLOR,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class ItalianGameNumberModal(discord.ui.Modal, title="Inserisci Numero Partita"):
    """Modal per inserire il numero della partita."""

    def __init__(self, games: List[Tuple[int, str]], db):
        super().__init__()
        self.games = games
        self.db = db

    game_number = discord.ui.TextInput(
        label="Numero Partita",
        placeholder="Es: 42",
        required=True,
        max_length=5,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            game_num = int(self.game_number.value)
            game_data = next((g for g in self.games if g[0] == game_num), None)
            if game_data:
                view = ItalianTeamSelectView(game_num, game_data[1], self.db)
                await interaction.response.edit_message(embed=view.get_embed(), view=view)
            else:
                await interaction.response.send_message("❌ Partita non trovata! Inserisci un numero valido.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Inserisci un numero valido!", ephemeral=True)


class ItalianTeamSelectView(discord.ui.View):
    """Selezione team e navigazione ruoli."""

    def __init__(self, game_number: int, game_name: str, db, selected_team: int = 1):
        super().__init__(timeout=300)
        self.game_number = game_number
        self.game_name = game_name
        self.selected_team = selected_team
        self.db = db

    def get_embed(self) -> discord.Embed:
        roles_basic = self.db.get_roles_by_team(self.game_number, self.selected_team)

        if roles_basic:
            lines = []
            for role_id, role_name, player_name, count_flag in roles_basic:
                role_details = self.db.get_role_details(self.game_number, role_id)
                if role_details and role_details.get("count", 1):
                    is_mvp = bool(role_details.get("mvp"))
                    if role_details["win"]:
                        win_emoji = "🏆⭐" if is_mvp else "🏆"
                    else:
                        win_emoji = "❌⭐" if is_mvp else "❌"
                    emoji_part = f" {win_emoji}"
                else:
                    emoji_part = ""
                player_str = f" - {player_name}{emoji_part}" if player_name else ""
                lines.append(f"**{role_id}** - {role_name}{player_str}\n")
            role_list = "".join(lines)
            description = (
                f"**Team: {TEAMS[self.selected_team]}**\n\n"
                f"**Ruoli ({len(roles_basic)})**\n\n"
                f"{role_list}"
                f"\nSeleziona un team dal menu o inserisci un Role ID."
            )
        else:
            description = (
                f"**Team: {TEAMS[self.selected_team]}**\n\n"
                f"*Nessun ruolo trovato per questo team.*\n\n"
                f"Seleziona un team dal menu o inserisci un Role ID."
            )

        embed = discord.Embed(
            title=f"🎮 {self.game_number}-{self.game_name.replace('-', ' ').title()}",
            description=description,
            color=EMBED_COLOR,
        )

        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
        return embed

    async def rebuild_view(self, interaction: discord.Interaction):
        new_view = ItalianTeamSelectView(self.game_number, self.game_name, self.db, self.selected_team)
        await interaction.response.edit_message(embed=new_view.get_embed(), view=new_view)

    @discord.ui.select(
        placeholder="Seleziona un team...",
        options=[
            discord.SelectOption(label="Village", value="1", emoji="🏘️"),
            discord.SelectOption(label="Evil", value="2", emoji="😈"),
            discord.SelectOption(label="Random Killer", value="3", emoji="🔪"),
            discord.SelectOption(label="Neutral", value="4", emoji="⚖️"),
            discord.SelectOption(label="Bonus/Extra", value="5", emoji="⭐"),
        ],
        row=0,
    )
    async def team_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_team = int(select.values[0])
        await self.rebuild_view(interaction)

    @discord.ui.button(label="◀ Precedente", style=discord.ButtonStyle.secondary, row=1)
    async def prev_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected_team > 1:
            self.selected_team -= 1
        await self.rebuild_view(interaction)

    @discord.ui.button(label="Successivo ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected_team < 5:
            self.selected_team += 1
        await self.rebuild_view(interaction)

    @discord.ui.button(label="🔢 Inserisci Role ID", style=discord.ButtonStyle.success, row=2)
    async def open_role_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ItalianRoleIDModal(self.game_number, self.game_name, self.db))


class ItalianRoleIDModal(discord.ui.Modal, title="Inserisci Role ID"):
    """Modal per inserire Role ID."""

    def __init__(self, game_number: int, game_name: str, db):
        super().__init__()
        self.game_number = game_number
        self.game_name = game_name
        self.db = db

    role_id = discord.ui.TextInput(label="Role ID", placeholder="Inserisci il Role ID...", required=True, max_length=5)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            role_id = int(self.role_id.value)
            role_data = self.db.get_role_details(self.game_number, role_id)
            if role_data:
                roles = self.db.get_roles_by_team(self.game_number, role_data["team"])
                index = next(i for i, r in enumerate(roles) if r[0] == role_id)
                view = RoleDescriptionView(self.game_number, self.game_name, roles, index, self.db)
                await interaction.response.edit_message(embed=view.get_embed(), view=view)
            else:
                await interaction.response.send_message("❌ Ruolo non trovato! Inserisci un Role ID valido.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Inserisci un numero valido!", ephemeral=True)


class ItalianInteractiveSearchView(discord.ui.View):
    """Vista di ricerca interattiva per la libreria italiana."""

    def __init__(self, db):
        super().__init__(timeout=300)
        self.db = db
        self.selected_team = None

    @discord.ui.select(
        placeholder="Seleziona un team (opzionale)...",
        options=[
            discord.SelectOption(label="Village", value="1", emoji="🏘️"),
            discord.SelectOption(label="Evil", value="2", emoji="😈"),
            discord.SelectOption(label="Random Killer", value="3", emoji="🔪"),
            discord.SelectOption(label="Neutral", value="4", emoji="⚖️"),
            discord.SelectOption(label="Bonus/Extra", value="5", emoji="⭐"),
        ],
        row=0,
    )
    async def team_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_team = int(select.values[0])
        await interaction.response.send_message(
            f"✅ Team selezionato: {TEAMS[self.selected_team]}\nOra inserisci un numero di partita o un nome di ruolo usando i pulsanti sottostanti.",
            ephemeral=True,
        )

    @discord.ui.button(label="🔢 Inserisci Numero Partita", style=discord.ButtonStyle.primary, row=1)
    async def enter_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ItalianSearchGameModal(self))

    @discord.ui.button(label="📝 Inserisci Nome Ruolo", style=discord.ButtonStyle.primary, row=1)
    async def enter_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ItalianSearchRoleModal(self))

    @discord.ui.button(label="👤 Inserisci Nome Giocatore", style=discord.ButtonStyle.primary, row=2)
    async def enter_player_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ItalianSearchPlayerNameModal(self))

    @discord.ui.button(label="🆔 Inserisci Player ID", style=discord.ButtonStyle.primary, row=2)
    async def enter_player_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ItalianSearchPlayerIDModal(self))

    @discord.ui.button(label="💼 Inserisci Nome Sponsor", style=discord.ButtonStyle.primary, row=3)
    async def enter_sponsor_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ItalianSearchSponsorNameModal(self))

    @discord.ui.button(label="🔖 Inserisci Sponsor ID", style=discord.ButtonStyle.primary, row=3)
    async def enter_sponsor_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ItalianSearchSponsorIDModal(self))


class ItalianSearchGameModal(discord.ui.Modal, title="Inserisci Numero Partita"):
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    game_num = discord.ui.TextInput(label="Numero Partita", placeholder="Es: 42", required=True, max_length=5)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            game_num = int(self.game_num.value)
            game = next((g for g in self.parent_view.db.get_all_games() if g[0] == game_num), None)
            if not game:
                await interaction.response.send_message("❌ Partita non trovata.", ephemeral=True)
                return
            view = ItalianTeamSelectView(game_num, game[1], self.parent_view.db)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)
        except ValueError:
            await interaction.response.send_message("❌ Inserisci un numero valido!", ephemeral=True)


class ItalianSearchRoleModal(discord.ui.Modal, title="Inserisci Nome Ruolo"):
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    role_name = discord.ui.TextInput(label="Nome Ruolo", placeholder="Es: Dottore", required=True, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        query = self.role_name.value.strip()
        if not query:
            await interaction.response.send_message("❌ Inserisci un nome valido!", ephemeral=True)
            return
        roles = self.parent_view.db.search_roles_fuzzy(query)
        if not roles:
            await interaction.response.send_message("❌ Nessun ruolo trovato.", ephemeral=True)
            return
        if len(roles) == 1:
            role = roles[0]
            team_roles = self.parent_view.db.get_roles_by_team(role["game_number"], role["team"])
            index = next(i for i, r in enumerate(team_roles) if r[0] == role["role_id"])
            view = RoleDescriptionView(role["game_number"], role["game_name"], team_roles, index, self.parent_view.db)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)
            return
        view = RoleSelectionView(roles, self.parent_view.db)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class ItalianSearchPlayerNameModal(discord.ui.Modal, title="Inserisci Nome Giocatore"):
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    player_name = discord.ui.TextInput(label="Nome Giocatore", placeholder="Es: MarioRossi", required=True, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        query = self.player_name.value.strip()
        if not query:
            await interaction.response.send_message("❌ Inserisci un nome valido!", ephemeral=True)
            return
        roles = self.parent_view.db.search_roles_fuzzy(query)
        if not roles:
            await interaction.response.send_message("❌ Nessun ruolo trovato.", ephemeral=True)
            return
        if len(roles) == 1:
            role = roles[0]
            team_roles = self.parent_view.db.get_roles_by_team(role["game_number"], role["team"])
            index = next(i for i, r in enumerate(team_roles) if r[0] == role["role_id"])
            view = RoleDescriptionView(role["game_number"], role["game_name"], team_roles, index, self.parent_view.db)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)
            return
        view = RoleSelectionView(roles, self.parent_view.db)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class ItalianSearchPlayerIDModal(discord.ui.Modal, title="Inserisci Player ID"):
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    player_id = discord.ui.TextInput(label="Player ID", placeholder="Es: 123456789", required=True, max_length=20)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            pid = int(self.player_id.value)
            roles = self.parent_view.db.get_roles_by_player_id(pid)
            if not roles:
                await interaction.response.send_message("❌ Nessun ruolo trovato per questo ID.", ephemeral=True)
                return
            if len(roles) == 1:
                role = roles[0]
                team_roles = self.parent_view.db.get_roles_by_team(role["game_number"], role["team"])
                index = next(i for i, r in enumerate(team_roles) if r[0] == role["role_id"])
                view = RoleDescriptionView(role["game_number"], role["game_name"], team_roles, index, self.parent_view.db)
                await interaction.response.edit_message(embed=view.get_embed(), view=view)
                return
            view = RoleSelectionView(roles, self.parent_view.db)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)
        except ValueError:
            await interaction.response.send_message("❌ Inserisci un ID numerico valido!", ephemeral=True)


class ItalianSearchSponsorNameModal(discord.ui.Modal, title="Inserisci Nome Sponsor"):
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    sponsor_name = discord.ui.TextInput(label="Nome Sponsor", placeholder="Es: Sponsor1", required=True, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        query = self.sponsor_name.value.strip()
        if not query:
            await interaction.response.send_message("❌ Inserisci un nome valido!", ephemeral=True)
            return
        roles = self.parent_view.db.search_roles_fuzzy(query)
        if not roles:
            await interaction.response.send_message("❌ Nessun ruolo trovato.", ephemeral=True)
            return
        if len(roles) == 1:
            role = roles[0]
            team_roles = self.parent_view.db.get_roles_by_team(role["game_number"], role["team"])
            index = next(i for i, r in enumerate(team_roles) if r[0] == role["role_id"])
            view = RoleDescriptionView(role["game_number"], role["game_name"], team_roles, index, self.parent_view.db)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)
            return
        view = RoleSelectionView(roles, self.parent_view.db)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class ItalianSearchSponsorIDModal(discord.ui.Modal, title="Inserisci Sponsor ID"):
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    sponsor_id = discord.ui.TextInput(label="Sponsor ID", placeholder="Es: 123456789", required=True, max_length=20)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            sid = int(self.sponsor_id.value)
            roles = self.parent_view.db.get_roles_by_sponsor_id(sid)
            if not roles:
                await interaction.response.send_message("❌ Nessun ruolo trovato per questo ID.", ephemeral=True)
                return
            if len(roles) == 1:
                role = roles[0]
                team_roles = self.parent_view.db.get_roles_by_team(role["game_number"], role["team"])
                index = next(i for i, r in enumerate(team_roles) if r[0] == role["role_id"])
                view = RoleDescriptionView(role["game_number"], role["game_name"], team_roles, index, self.parent_view.db)
                await interaction.response.edit_message(embed=view.get_embed(), view=view)
                return
            view = RoleSelectionView(roles, self.parent_view.db)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)
        except ValueError:
            await interaction.response.send_message("❌ Inserisci un ID numerico valido!", ephemeral=True)


class ItalianOverseerSearchView(discord.ui.View):
    """Vista di ricerca interattiva per overseer."""

    def __init__(self, db):
        super().__init__(timeout=300)
        self.db = db

    @discord.ui.button(label="👤 Inserisci Nome Overseer", style=discord.ButtonStyle.primary, row=0)
    async def enter_overseer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ItalianOverseerSearchModal(self.db))


class ItalianOverseerSearchModal(discord.ui.Modal, title="Cerca per Nome Overseer"):
    def __init__(self, db):
        super().__init__()
        self.db = db

    overseer_name = discord.ui.TextInput(
        label="Nome Overseer",
        placeholder="Inserisci il nome dell'overseer...",
        required=True,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        name = self.overseer_name.value.strip()
        games = self.db.search_games_by_host_name(name)
        if not games:
            await interaction.response.send_message(f"❌ Nessuna partita trovata per l'overseer '{name}'!", ephemeral=True)
            return
        view = ItalianOverseerSearchSelectView(games, self.db)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class ItalianOverseerSearchSelectView(discord.ui.View):
    """Vista per selezionare da risultati di ricerca overseer."""

    def __init__(self, games: List[Tuple[int, str]], db, page: int = 0):
        super().__init__(timeout=300)
        self.games = games
        self.db = db
        self.page = page
        import math as _math
        self.max_page = _math.ceil(len(games) / 10) - 1

        if self.max_page > 0:
            self.prev_btn = discord.ui.Button(label="◀ Precedente", style=discord.ButtonStyle.primary, disabled=True)
            self.prev_btn.callback = self.prev_page
            self.add_item(self.prev_btn)

            self.next_btn = discord.ui.Button(label="Successiva ▶", style=discord.ButtonStyle.primary)
            self.next_btn.callback = self.next_page
            self.add_item(self.next_btn)

    def get_embed(self) -> discord.Embed:
        start_idx = self.page * 10
        end_idx = min(start_idx + 10, len(self.games))
        page_games = self.games[start_idx:end_idx]

        embed = discord.Embed(
            title="🔍 Risultati Ricerca Overseer",
            description=f"Trovate **{len(self.games)}** partite. Selezionane una per visualizzarla.",
            color=EMBED_COLOR,
        )

        games_text = ""
        for game_num, game_name in page_games:
            winners = self.db.get_winning_teams(game_num)
            winner_str = f" | 🏆 {', '.join(winners)}" if winners else ""
            games_text += f"**{game_num}** | {game_name.replace('-', ' ').title()}{winner_str}\n"

        embed.add_field(name="Partite Gestite", value=games_text, inline=False)

        if self.max_page > 0:
            embed.set_footer(text=f"{EMBED_FOOTER_TEXT} | Pagina {self.page + 1}/{self.max_page + 1}", icon_url=EMBED_FOOTER_ICON)
        else:
            embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)

        return embed

    async def prev_page(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        await self._update(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.page = min(self.max_page, self.page + 1)
        await self._update(interaction)

    async def _update(self, interaction: discord.Interaction):
        if self.max_page > 0:
            self.prev_btn.disabled = self.page == 0
            self.next_btn.disabled = self.page == self.max_page
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="🔢 Inserisci Numero Partita", style=discord.ButtonStyle.success, row=1)
    async def open_game_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ItalianOverseerGameNumberModal(self.games, self.db))


class ItalianOverseerGameNumberModal(discord.ui.Modal, title="Inserisci Numero Partita"):
    def __init__(self, games, db):
        super().__init__()
        self.games = games
        self.db = db

    game_number = discord.ui.TextInput(label="Numero Partita", placeholder="Es: 42", required=True, max_length=5)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            game_num = int(self.game_number.value)
            game_data = next((g for g in self.games if g[0] == game_num), None)
            if game_data:
                view = ItalianTeamSelectView(game_num, game_data[1], self.db)
                await interaction.response.edit_message(embed=view.get_embed(), view=view)
            else:
                await interaction.response.send_message("❌ Partita non trovata!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Inserisci un numero valido!", ephemeral=True)


class ItalianOverseerStatsView(discord.ui.View):
    """Vista statistiche overseer con storico partite paginato."""

    TEAM_EMOJI = {1: "🏘️", 2: "😈", 3: "🔪", 4: "⚖️"}

    def __init__(self, db, stats: dict, history: List[dict], overseer_name: str, avatar_url: str = None, page: int = 0):
        super().__init__(timeout=300)
        self.db = db
        self.stats = stats
        self.history = history
        self.overseer_name = overseer_name
        self.avatar_url = avatar_url
        self.page = page
        self.page_size = 10
        self.max_page = max(0, (len(history) - 1) // self.page_size)

        self.prev_btn = discord.ui.Button(label="◀ Precedente", style=discord.ButtonStyle.secondary, disabled=True)
        self.prev_btn.callback = self.prev_page
        self.add_item(self.prev_btn)

        self.next_btn = discord.ui.Button(label="Successiva ▶", style=discord.ButtonStyle.secondary, disabled=self.max_page == 0)
        self.next_btn.callback = self.next_page
        self.add_item(self.next_btn)

        self.lb_btn = discord.ui.Button(label="🏆 Classifica", style=discord.ButtonStyle.primary, row=1)
        self.lb_btn.callback = self.show_leaderboard
        self.add_item(self.lb_btn)

    async def show_leaderboard(self, interaction: discord.Interaction):
        all_stats = self.db.get_all_overseer_stats()
        if not all_stats:
            await interaction.response.send_message("❌ Nessun dato overseer trovato.", ephemeral=True)
            return
        view = ItalianOverseerLeaderboardView(all_stats)
        await interaction.response.send_message(embed=view.get_embed(), view=view)

    def _compute_faction_stats(self):
        factions = [
            (1, "🏘️", "Village"),
            (2, "😈", "Evil"),
            (3, "🔪", "Random Killer"),
            (4, "⚖️", "Neutral"),
        ]
        results = []
        for tid, emoji, name in factions:
            games = sum(1 for g in self.history if tid in g["team_counts"])
            wins = sum(1 for g in self.history if tid in g["winning_teams"])
            results.append((emoji, name, wins, games))
        return results

    def _compute_overview(self):
        games_os = self.stats["total_games"]
        if not self.history:
            return games_os, 0.0, 0, None

        per_game_totals = [sum(g["team_counts"].values()) for g in self.history]
        avg_players = sum(per_game_totals) / len(per_game_totals)
        largest_game = max(per_game_totals)
        first_game = min(g["game_number"] for g in self.history)
        return games_os, avg_players, largest_game, first_game

    def get_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"📊 Statistiche Overseer • {self.overseer_name}",
            color=EMBED_COLOR,
        )
        if self.avatar_url:
            embed.set_thumbnail(url=self.avatar_url)

        games_os, avg_players, largest_game, first_game = self._compute_overview()
        overview_lines = [
            f"├─ Partite Gestite    {games_os}",
            f"├─ Giocatori Medi     {avg_players:.1f}",
            f"├─ Partita Più Grande {largest_game}",
        ]
        if first_game is not None:
            overview_lines.append(f"└─ Prima Partita      #{first_game}")
        else:
            overview_lines.append("└─ Prima Partita      —")
        embed.add_field(name="📈 Panoramica", value="\n".join(overview_lines), inline=False)

        faction_data = self._compute_faction_stats()
        name_pad = max(len(n) for _, _, n, _, _ in [(e, n, n, w, g) for e, n, w, g in faction_data])
        faction_lines = []
        for emoji, name, wins, games in faction_data:
            padded_name = name.ljust(name_pad)
            if games:
                wr = f"{wins / games * 100:.1f}%"
                faction_lines.append(f"{emoji} {padded_name}  {wins}/{games}   {wr}")
            else:
                faction_lines.append(f"{emoji} {padded_name}  0/0   —")
        embed.add_field(name="🏆 Risultati per Fazione", value="\n".join(faction_lines), inline=False)

        ABBR = {1: "V", 2: "E", 3: "RK", 4: "N"}
        start = self.page * self.page_size
        items = self.history[start:start + self.page_size]

        desc_lines = []
        if items:
            for g in items:
                desc_lines.append(f"#{g['game_number']} {g['game_name']}")
                comp_parts = []
                for tid in (1, 2, 3, 4):
                    if tid in g["team_counts"]:
                        comp_parts.append(f"{g['team_counts'][tid]}{ABBR[tid]}")
                desc_lines.append(" • ".join(comp_parts))
                primary = [t for t in g["winning_teams"] if t != 4]
                if not primary:
                    primary = g["winning_teams"]
                winner_name = TEAMS.get(primary[0], "?") if primary else "—"
                desc_lines.append(f"🏆 {winner_name}" if primary else "—")
                desc_lines.append("")

        total_pages = max(1, (len(self.history) - 1) // self.page_size + 1)
        field_name = f"📜 Partite Recenti • Pagina {self.page + 1}/{total_pages}"
        embed.add_field(
            name=field_name,
            value="\n".join(desc_lines).strip() if desc_lines else "*Nessuna partita trovata.*",
            inline=False,
        )

        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
        return embed

    async def prev_page(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
        await self._update(interaction)

    async def next_page(self, interaction: discord.Interaction):
        if self.page < self.max_page:
            self.page += 1
        await self._update(interaction)

    async def _update(self, interaction: discord.Interaction):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self.max_page
        await interaction.response.edit_message(embed=self.get_embed(), view=self)


class ItalianOverseerLeaderboardView(discord.ui.View):
    """Classifica overseer."""

    def __init__(self, stats, min_games: int = 5, sort_mode: str = "games", page: int = 0):
        super().__init__(timeout=300)
        self.raw_stats = stats
        self.min_games = min_games
        self.sort_mode = sort_mode
        self.page = page
        self.page_size = 10

    def get_embed(self) -> discord.Embed:
        players = self._get_sorted()
        total = len(players)

        embed = discord.Embed(
            title=f"🏆 Classifica Overseer — {self.min_games}+ Partite",
            color=EMBED_COLOR,
        )

        if total == 0:
            embed.description = "Nessun overseer corrisponde a questo filtro."
            return embed

        import math as _math
        max_page = max(0, _math.ceil(total / self.page_size) - 1)
        self.page = min(self.page, max_page)
        start = self.page * self.page_size
        page_players = players[start:start + self.page_size]

        sort_labels = {
            "games": "Partite Overseer", "winrate": "Winrate",
            "village_wr": "Winrate Village", "evil_wr": "Winrate Evil",
            "rk_wr": "Winrate RK", "neutral_wr": "Winrate Neutral",
            "name": "Alfabetico",
        }

        desc = ""
        for idx, p in enumerate(page_players, start=start + 1):
            parts = [f"V {p['village_wins']}W", f"E {p['evil_wins']}W",
                     f"RK {p['rk_wins']}W", f"N {p['neutral_wins']}W"]
            line = (
                f"**#{idx} — {p['sponsor_name']}**\n"
                f"{p['total_games']} partite • {' • '.join(parts)}\n"
            )
            desc += line + "\n"

        embed.description = desc
        embed.set_footer(
            text=f"{EMBED_FOOTER_TEXT} | {self.min_games}+ partite | Ordinato per {sort_labels.get(self.sort_mode, 'Partite')} | Pagina {self.page + 1}/{max_page + 1}",
            icon_url=EMBED_FOOTER_ICON,
        )
        return embed

    def _get_sorted(self):
        players = [p for p in self.raw_stats if p["total_games"] >= self.min_games]
        key_map = {
            "games":       lambda p: (-p["total_games"], -p["winrate"]),
            "winrate":     lambda p: (-p["winrate"], -p["total_games"]),
            "village_wr":  lambda p: (-p["village_wr"], -p["village_wins"], -p["total_games"]),
            "evil_wr":     lambda p: (-p["evil_wr"], -p["evil_wins"], -p["total_games"]),
            "rk_wr":       lambda p: (-p["rk_wr"], -p["rk_wins"], -p["total_games"]),
            "neutral_wr":  lambda p: (-p["neutral_wr"], -p["neutral_wins"], -p["total_games"]),
            "name":        lambda p: p["sponsor_name"].lower(),
        }
        players.sort(key=key_map.get(self.sort_mode, key_map["games"]))
        return players

    @discord.ui.select(
        placeholder="Ordina per...",
        options=[
            discord.SelectOption(label="Partite Overseer", value="games"),
            discord.SelectOption(label="Winrate", value="winrate"),
            discord.SelectOption(label="Alfabetico (A–Z)", value="name"),
            discord.SelectOption(label="Winrate Village", value="village_wr"),
            discord.SelectOption(label="Winrate Evil", value="evil_wr"),
            discord.SelectOption(label="Winrate RK", value="rk_wr"),
            discord.SelectOption(label="Winrate Neutral", value="neutral_wr"),
        ],
        row=0,
    )
    async def sort_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.sort_mode = select.values[0]
        self.page = 0
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="🔢 Imposta Partite Min", style=discord.ButtonStyle.primary, row=1)
    async def set_min_games(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ItalianMinGamesModal(self))

    @discord.ui.button(label="◀ Precedente", style=discord.ButtonStyle.secondary, row=2)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Successiva ▶", style=discord.ButtonStyle.secondary, row=2)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        import math as _math
        max_page = max(0, _math.ceil(len(self._get_sorted()) / self.page_size) - 1)
        if self.page < max_page:
            self.page += 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)


class ItalianMinGamesModal(discord.ui.Modal, title="Imposta Partite Minime"):
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    min_games = discord.ui.TextInput(label="Partite Minime", placeholder="Es: 5", required=True, max_length=5)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.parent_view.min_games = max(1, int(self.min_games.value))
            self.parent_view.page = 0
            await interaction.response.edit_message(embed=self.parent_view.get_embed(), view=self.parent_view)
        except ValueError:
            await interaction.response.send_message("❌ Inserisci un numero valido!", ephemeral=True)


# Helper function for paginated field additions (Italian version)
def add_fields_paginated_it(embed: discord.Embed, name: str, lines: list, max_chars: int = 1024):
    """Suddivide liste lunghe su più embed-field per evitare il limite di 1024 caratteri."""
    chunk, current_len, field_num = [], 0, 0
    for line in lines:
        if current_len + len(line) > max_chars:
            embed.add_field(
                name=name if field_num == 0 else f"{name} (cont.)",
                value="".join(chunk) or "*—*",
                inline=False,
            )
            chunk, current_len, field_num = [], 0, field_num + 1
        chunk.append(line)
        current_len += len(line)
    embed.add_field(
        name=name if field_num == 0 else f"{name} (cont.)",
        value="".join(chunk) or "*—*",
        inline=False,
    )


# =============================================================================
# ADMIN VIEWS — usate esclusivamente da .libitadmin
# =============================================================================

import math as _math  # solo alias locale per non sporcare il namespace globale


def _admin_paginate_fields(embed: discord.Embed, name: str, lines: list, max_chars: int = 1024):
    """Suddivide liste lunghe su più embed-field per evitare il limite di 1024 caratteri."""
    chunk, current_len, field_num = [], 0, 0
    for line in lines:
        if current_len + len(line) > max_chars:
            embed.add_field(
                name=name if field_num == 0 else f"{name} (cont.)",
                value="".join(chunk) or "*—*",
                inline=False,
            )
            chunk, current_len, field_num = [], 0, field_num + 1
        chunk.append(line)
        current_len += len(line)
    embed.add_field(
        name=name if field_num == 0 else f"{name} (cont.)",
        value="".join(chunk) or "*—*",
        inline=False,
    )


# ---------------------------------------------------------------------------
# AdminGameSelectView
# ---------------------------------------------------------------------------

class AdminGameSelectView(discord.ui.View):
    """Versione admin di GameSelectView — identica nell'UI, apre AdminTeamSelectView."""

    def __init__(self, games: List[Tuple[int, str]], db, bot, page: int = 0):
        super().__init__(timeout=300)
        self.games = games
        self.db = db
        self.bot = bot
        self.page = page
        self.max_page = max(0, _math.ceil(len(games) / 10) - 1)

        if self.max_page > 0:
            self.prev_btn = discord.ui.Button(
                label="◀ Previous", style=discord.ButtonStyle.primary, disabled=True
            )
            self.prev_btn.callback = self._prev_page
            self.add_item(self.prev_btn)

            self.next_btn = discord.ui.Button(
                label="Next ▶", style=discord.ButtonStyle.primary
            )
            self.next_btn.callback = self._next_page
            self.add_item(self.next_btn)

    def get_embed(self) -> discord.Embed:
        start = self.page * 10
        end = min(start + 10, len(self.games))
        page_games = self.games[start:end]

        embed = discord.Embed(
            title="📚 [ADMIN] Libreria Partite — Seleziona una Partita",
            description="Usa il pulsante qui sotto per inserire il numero della partita da modificare.",
            color=EMBED_COLOR,
        )

        games_text = ""
        for game_num, game_name in page_games:
            winners = self.db.get_winning_teams(game_num)
            winner_str = f" | 🏆 {', '.join(winners)}" if winners else ""
            games_text += f"**{game_num}** | {game_name.replace('-', ' ').title()}{winner_str}\n"

        embed.add_field(name="Partite Disponibili", value=games_text or "*Nessuna partita*", inline=False)

        footer_extra = f" | Pagina {self.page + 1}/{self.max_page + 1}" if self.max_page > 0 else ""
        embed.set_footer(text=f"{EMBED_FOOTER_TEXT}{footer_extra}", icon_url=EMBED_FOOTER_ICON)
        return embed

    async def _prev_page(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        await self._refresh(interaction)

    async def _next_page(self, interaction: discord.Interaction):
        self.page = min(self.max_page, self.page + 1)
        await self._refresh(interaction)

    async def _refresh(self, interaction: discord.Interaction):
        if self.max_page > 0:
            self.prev_btn.disabled = self.page == 0
            self.next_btn.disabled = self.page == self.max_page
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="🔢 Inserisci Numero Partita", style=discord.ButtonStyle.success, row=1)
    async def open_game_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            AdminGameNumberModal(self.games, self.db, self.bot)
        )


# ---------------------------------------------------------------------------
# AdminGameNumberModal
# ---------------------------------------------------------------------------

class AdminGameNumberModal(discord.ui.Modal, title="Inserisci Numero Partita"):
    def __init__(self, games, db, bot):
        super().__init__()
        self.games = games
        self.db = db
        self.bot = bot

    game_number = discord.ui.TextInput(
        label="Numero Partita",
        placeholder="Es: 42",
        required=True,
        max_length=5,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            game_num = int(self.game_number.value)
        except ValueError:
            await interaction.response.send_message("❌ Inserisci un numero valido!", ephemeral=True)
            return

        game_data = next((g for g in self.games if g[0] == game_num), None)
        if not game_data:
            await interaction.response.send_message("❌ Partita non trovata!", ephemeral=True)
            return

        view = AdminTeamSelectView(game_num, game_data[1], self.db, self.bot)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


# ---------------------------------------------------------------------------
# AdminTeamSelectView
# ---------------------------------------------------------------------------

class AdminTeamSelectView(discord.ui.View):
    """Versione admin di TeamSelectView — identica nell'UI, apre AdminRoleDescriptionView."""

    def __init__(self, game_number: int, game_name: str, db, bot, selected_team: int = 1):
        super().__init__(timeout=300)
        self.game_number = game_number
        self.game_name = game_name
        self.db = db
        self.bot = bot
        self.selected_team = selected_team

    def get_embed(self) -> discord.Embed:
        roles_basic = self.db.get_roles_by_team(self.game_number, self.selected_team)

        embed = discord.Embed(
            title=f"🔧 [ADMIN] {self.game_number} — {self.game_name.replace('-', ' ').title()}",
            description=f"**Team: {TEAMS[self.selected_team]}**\n\nSeleziona un team o inserisci un Role ID.",
            color=EMBED_COLOR,
        )

        if roles_basic:
            lines = []
            for role_id, role_name, player_name, count_flag in roles_basic:
                role_details = self.db.get_role_details(self.game_number, role_id)
                if role_details and role_details.get("count", 1):
                    is_mvp = bool(role_details.get("mvp"))
                    if role_details["win"]:
                        win_emoji = "🏆⭐" if is_mvp else "🏆"
                    else:
                        win_emoji = "❌⭐" if is_mvp else "❌"
                    emoji_part = f" {win_emoji}"
                else:
                    emoji_part = " ⛔"  # excluded from stats
                player_str = f" — {player_name}{emoji_part}" if player_name else emoji_part
                lines.append(f"**{role_id}** — {role_name}{player_str}\n")

            _admin_paginate_fields(embed, f"Ruoli ({len(roles_basic)})", lines)
        else:
            embed.add_field(name="Ruoli", value="*Nessun ruolo trovato per questo team.*", inline=False)

        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=EMBED_FOOTER_ICON)
        return embed

    @discord.ui.select(
        placeholder="Seleziona un team...",
        options=[
            discord.SelectOption(label="Village",       value="1", emoji="🏘️"),
            discord.SelectOption(label="Evil",          value="2", emoji="😈"),
            discord.SelectOption(label="Random Killer", value="3", emoji="🔪"),
            discord.SelectOption(label="Neutral",       value="4", emoji="⚖️"),
            discord.SelectOption(label="Bonus/Extra",   value="5", emoji="⭐"),
        ],
        row=0,
    )
    async def team_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_team = int(select.values[0])
        new_view = AdminTeamSelectView(
            self.game_number, self.game_name, self.db, self.bot, self.selected_team
        )
        await interaction.response.edit_message(embed=new_view.get_embed(), view=new_view)

    @discord.ui.button(label="🔢 Inserisci Role ID", style=discord.ButtonStyle.primary, row=2)
    async def enter_role_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            AdminRoleIDModal(self.game_number, self.game_name, self.db, self.bot)
        )

    @discord.ui.button(label="↩️ Torna alle Partite", style=discord.ButtonStyle.secondary, row=2)
    async def back_to_games(self, interaction: discord.Interaction, button: discord.ui.Button):
        games = self.db.get_all_games()
        view = AdminGameSelectView(games, self.db, self.bot)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


# ---------------------------------------------------------------------------
# AdminRoleIDModal
# ---------------------------------------------------------------------------

class AdminRoleIDModal(discord.ui.Modal, title="Inserisci Role ID"):
    def __init__(self, game_number, game_name, db, bot):
        super().__init__()
        self.game_number = game_number
        self.game_name = game_name
        self.db = db
        self.bot = bot

    role_id = discord.ui.TextInput(
        label="Role ID",
        placeholder="Es: 7",
        required=True,
        max_length=5,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            role_id = int(self.role_id.value)
        except ValueError:
            await interaction.response.send_message("❌ Inserisci un numero valido!", ephemeral=True)
            return

        role_data = self.db.get_role_details(self.game_number, role_id)
        if not role_data:
            await interaction.response.send_message("❌ Ruolo non trovato!", ephemeral=True)
            return

        roles = self.db.get_roles_by_team(self.game_number, role_data["team"])
        try:
            index = next(i for i, r in enumerate(roles) if r[0] == role_id)
        except StopIteration:
            await interaction.response.send_message("❌ Ruolo non trovato nella lista.", ephemeral=True)
            return

        view = AdminRoleDescriptionView(
            self.game_number, self.game_name, roles, index, self.db, self.bot
        )
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


# ---------------------------------------------------------------------------
# AdminRoleDescriptionView  ← la view principale con tutti i campi + edit
# ---------------------------------------------------------------------------

class AdminRoleDescriptionView(discord.ui.View):
    """
    Versione admin di RoleDescriptionView.

    Differenze rispetto all'originale:
    - L'embed mostra TUTTI i campi del database (player_id, sponsor_id, count, mvp…)
    - Select menu su row 3 per scegliere il campo da modificare
    - Il valore viene inserito tramite messaggio in chat (no modal)
    - Solo i librarian possono usare il select menu di modifica
    """

    _EDIT_OPTIONS = [
        discord.SelectOption(
            label="role_name",       value="role_name",
            description="Nome del ruolo",                   emoji="📛"),
        discord.SelectOption(
            label="team",            value="team",
            description="Team (1=Village … 5=Bonus)",       emoji="🎯"),
        discord.SelectOption(
            label="player",          value="player",
            description="Giocatore via @menzione o nome",   emoji="👤"),
        discord.SelectOption(
            label="player_id",       value="player_id",
            description="ID Discord del giocatore (numero)",emoji="🪪"),
        discord.SelectOption(
            label="sponsor",         value="sponsor",
            description="Sponsor via @menzione o nome",     emoji="💼"),
        discord.SelectOption(
            label="sponsor_id",      value="sponsor_id",
            description="ID Discord dello sponsor (numero)",emoji="🪪"),
        discord.SelectOption(
            label="win",             value="win",
            description="Vittoria  — 1=sì  0=no",          emoji="🏆"),
        discord.SelectOption(
            label="count",           value="count",
            description="Conta nelle stat — 1=sì  0=no",   emoji="📊"),
        discord.SelectOption(
            label="mvp",             value="mvp",
            description="MVP — 1=sì  0=no",                emoji="⭐"),
        discord.SelectOption(
            label="description1",    value="description1",
            description="Prima descrizione (o 'none')",     emoji="📜"),
        discord.SelectOption(
            label="description2",    value="description2",
            description="Seconda descrizione (o 'none')",   emoji="📜"),
        discord.SelectOption(
            label="description3",    value="description3",
            description="Terza descrizione (o 'none')",     emoji="📜"),
        discord.SelectOption(
            label="description4",    value="description4",
            description="Quarta descrizione (o 'none')",    emoji="📜"),
    ]

    def __init__(
        self,
        game_number: int,
        game_name: str,
        roles: list,
        current_index: int,
        db,
        bot,
    ):
        super().__init__(timeout=300)
        self.game_number = game_number
        self.game_name = game_name
        self.roles = roles
        self.current_index = current_index
        self.db = db
        self.bot = bot
        self.current_desc = 1
        self._update_available_descs()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_available_descs(self):
        role_data = self.get_role_data()
        self.available_descs = [
            i for i in range(1, 5)
            if role_data.get(f"description{i}") and str(role_data[f"description{i}"]).strip()
        ]
        if not self.available_descs:
            self.available_descs = [1]
        if self.current_desc not in self.available_descs:
            self.current_desc = self.available_descs[0]

    def get_role_data(self) -> dict:
        role_id = self.roles[self.current_index][0]
        return self.db.get_role_details(self.game_number, role_id)

    # ------------------------------------------------------------------
    # Embed
    # ------------------------------------------------------------------

    def get_embed(self) -> discord.Embed:
        role = self.get_role_data()

        description_text = role.get(f"description{self.current_desc}") or "*Nessuna descrizione disponibile.*"
        if not str(description_text).strip():
            description_text = "*Nessuna descrizione disponibile.*"

        embed = discord.Embed(
            title=f"🔧 {role['role_name']}",
            description=description_text,
            color=EMBED_COLOR,
        )

        # ── Tutti i campi del DB ──────────────────────────────────────
        def _fmt(val):
            return f"`{val}`" if val is not None else "`—`"

        db_info = (
            f"**role_id** → {_fmt(role.get('role_id'))}\n"
            f"**role_name** → `{role.get('role_name', '—')}`\n"
            f"**team** → `{role.get('team')}` — {TEAMS.get(role.get('team'), '?')}\n"
            f"**player_name** → `{role.get('player_name') or '—'}`\n"
            f"**player_id** → {_fmt(role.get('player_id'))}\n"
            f"**sponsor_name** → `{role.get('sponsor_name') or '—'}`\n"
            f"**sponsor_id** → {_fmt(role.get('sponsor_id'))}\n"
            f"**win** → {'✅ `1`' if role.get('win') else '❌ `0`'}\n"
            f"**mvp** → {'⭐ `1`' if role.get('mvp') else '— `0`'}\n"
            f"**count** → {'✅ `1`' if role.get('count', 1) else '❌ `0`'}"
        )
        embed.add_field(name="🗃️ Campi Database", value=db_info, inline=False)

        # ── Info contestuali ──────────────────────────────────────────
        game_str = f"{self.game_number} — {self.game_name.replace('-', ' ').title()}"
        embed.add_field(
            name="ℹ️ Contesto",
            value=(
                f"**Partita:** {game_str}\n"
                f"**Ruolo:** {self.current_index + 1}/{len(self.roles)} "
                f"(team {TEAMS.get(role.get('team'), '?')})"
            ),
            inline=False,
        )

        max_desc = max(self.available_descs)
        embed.set_footer(
            text=f"{EMBED_FOOTER_TEXT} | Descrizione {self.current_desc}/{max_desc}",
            icon_url=EMBED_FOOTER_ICON,
        )
        return embed

    # ------------------------------------------------------------------
    # Row 0 — navigazione descrizioni
    # ------------------------------------------------------------------

    @discord.ui.button(label="◀ Desc", style=discord.ButtonStyle.primary, row=0)
    async def prev_desc(self, interaction: discord.Interaction, button: discord.ui.Button):
        idx = self.available_descs.index(self.current_desc)
        if idx > 0:
            self.current_desc = self.available_descs[idx - 1]
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Desc ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_desc(self, interaction: discord.Interaction, button: discord.ui.Button):
        idx = self.available_descs.index(self.current_desc)
        if idx < len(self.available_descs) - 1:
            self.current_desc = self.available_descs[idx + 1]
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    # ------------------------------------------------------------------
    # Row 1 — navigazione ruoli
    # ------------------------------------------------------------------

    @discord.ui.button(label="◀◀ Ruolo", style=discord.ButtonStyle.secondary, row=1)
    async def prev_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index > 0:
            self.current_index -= 1
            self._update_available_descs()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Ruolo ▶▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index < len(self.roles) - 1:
            self.current_index += 1
            self._update_available_descs()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    # ------------------------------------------------------------------
    # Row 2 — pulsante indietro
    # ------------------------------------------------------------------

    @discord.ui.button(label="↩️ Torna ai Ruoli", style=discord.ButtonStyle.secondary, row=2)
    async def back_to_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_role = self.get_role_data()
        view = AdminTeamSelectView(
            self.game_number, self.game_name, self.db, self.bot,
            selected_team=current_role["team"],
        )
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    # ------------------------------------------------------------------
    # Row 3 — select menu modifica campi  (solo librarian)
    # ------------------------------------------------------------------

    @discord.ui.select(
        placeholder="✏️ Modifica un campo del database...",
        options=_EDIT_OPTIONS,
        row=3,
    )
    async def edit_field_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        # ── Controllo permessi ────────────────────────────────────────
        if interaction.user.id not in LIBRARIAN_IDS:
            await interaction.response.send_message(
                "❌ Non hai i permessi per modificare i campi!", ephemeral=True
            )
            return

        field = select.values[0]
        role_id = self.roles[self.current_index][0]

        # ── Messaggio di prompt ───────────────────────────────────────
        team_opts = " · ".join(f"**{k}**={v}" for k, v in TEAMS.items())
        prompts = {
            "role_name":    "Scrivi il **nuovo nome** del ruolo.",
            "team":         f"Scrivi il **numero del team**:\n{team_opts}",
            "player":       (
                "Menziona il giocatore **`@utente`** → salva nome + ID Discord\n"
                "Scrivi solo il **nome** → salva solo il nome (player_id rimane invariato)\n"
                "Scrivi **`none`** → rimuove player_name e player_id"
            ),
            "player_id":    "Scrivi il **Discord ID** numerico del giocatore (o `none` per rimuoverlo).",
            "sponsor":      (
                "Menziona lo sponsor **`@utente`** → salva nome + ID Discord\n"
                "Scrivi solo il **nome** → salva solo il nome (sponsor_id rimane invariato)\n"
                "Scrivi **`none`** → rimuove sponsor_name e sponsor_id"
            ),
            "sponsor_id":   "Scrivi il **Discord ID** numerico dello sponsor (o `none` per rimuoverlo).",
            "win":          "Scrivi **`1`** (vittoria) o **`0`** (sconfitta).",
            "count":        "Scrivi **`1`** (conta nelle stat) o **`0`** (escludi).",
            "mvp":          "Scrivi **`1`** (MVP) o **`0`** (non MVP).",
            "description1": "Scrivi il testo della **description1**, oppure `none` per rimuoverla.",
            "description2": "Scrivi il testo della **description2**, oppure `none` per rimuoverla.",
            "description3": "Scrivi il testo della **description3**, oppure `none` per rimuoverla.",
            "description4": "Scrivi il testo della **description4**, oppure `none` per rimuoverla.",
        }
        prompt_text = prompts.get(field, f"Scrivi il nuovo valore per **{field}**.")

        # Defer l'interazione e invia il prompt nel canale (non ephemeral
        # così l'utente può rispondere nel contesto visibile)
        await interaction.response.defer()
        prompt_msg = await interaction.channel.send(
            f"<@{interaction.user.id}> ✏️ **Campo:** `{field}`\n{prompt_text}\n"
            f"_(Hai 60 secondi. Scrivi il messaggio qui sotto.)_"
        )

        # ── Attende il messaggio dell'utente ──────────────────────────
        def _check(m: discord.Message):
            return (
                m.author.id == interaction.user.id
                and m.channel.id == interaction.channel.id
            )

        try:
            user_msg = await self.bot.wait_for("message", check=_check, timeout=60)
        except asyncio.TimeoutError:
            try:
                await prompt_msg.delete()
            except Exception:
                pass
            await interaction.followup.send(
                "⌛ Tempo scaduto. Nessuna modifica effettuata.", ephemeral=True
            )
            return

        value_str = user_msg.content.strip()
        feedback = ""

        # ── Elaborazione per campo ────────────────────────────────────
        try:
            if field == "player":
                mention_match = re.search(r"<@!?(\d+)>", value_str)
                if mention_match:
                    mid = int(mention_match.group(1))
                    member = await interaction.guild.fetch_member(mid)
                    self.db.update_field(self.game_number, role_id, "player_name", member.display_name)
                    self.db.update_field(self.game_number, role_id, "player_id", member.id)
                    feedback = f"✅ Giocatore → **{member.display_name}** (ID: `{member.id}`)"
                elif value_str.lower() == "none":
                    self.db.update_field(self.game_number, role_id, "player_name", None)
                    self.db.update_field(self.game_number, role_id, "player_id", None)
                    feedback = "✅ Giocatore rimosso (player_name e player_id = NULL)."
                else:
                    self.db.update_field(self.game_number, role_id, "player_name", value_str)
                    feedback = f"✅ player_name → **{value_str}** _(player_id invariato)_"

            elif field == "sponsor":
                mention_match = re.search(r"<@!?(\d+)>", value_str)
                if mention_match:
                    mid = int(mention_match.group(1))
                    member = await interaction.guild.fetch_member(mid)
                    self.db.update_field(self.game_number, role_id, "sponsor_name", member.display_name)
                    self.db.update_field(self.game_number, role_id, "sponsor_id", member.id)
                    feedback = f"✅ Sponsor → **{member.display_name}** (ID: `{member.id}`)"
                elif value_str.lower() == "none":
                    self.db.update_field(self.game_number, role_id, "sponsor_name", None)
                    self.db.update_field(self.game_number, role_id, "sponsor_id", None)
                    feedback = "✅ Sponsor rimosso (sponsor_name e sponsor_id = NULL)."
                else:
                    self.db.update_field(self.game_number, role_id, "sponsor_name", value_str)
                    feedback = f"✅ sponsor_name → **{value_str}** _(sponsor_id invariato)_"

            elif field == "player_id":
                if value_str.lower() == "none":
                    self.db.update_field(self.game_number, role_id, "player_id", None)
                    feedback = "✅ player_id rimosso (NULL)."
                else:
                    val = int(value_str)
                    self.db.update_field(self.game_number, role_id, "player_id", val)
                    feedback = f"✅ player_id → `{val}`"

            elif field == "sponsor_id":
                if value_str.lower() == "none":
                    self.db.update_field(self.game_number, role_id, "sponsor_id", None)
                    feedback = "✅ sponsor_id rimosso (NULL)."
                else:
                    val = int(value_str)
                    self.db.update_field(self.game_number, role_id, "sponsor_id", val)
                    feedback = f"✅ sponsor_id → `{val}`"

            elif field == "team":
                team_val = int(value_str)
                if team_val not in TEAMS:
                    raise ValueError(f"Team `{team_val}` non valido. Usa: {team_opts}")
                self.db.update_field(self.game_number, role_id, "team", team_val)
                # Ricarica la lista ruoli per il nuovo team
                self.roles = self.db.get_roles_by_team(self.game_number, team_val)
                self.current_index = 0
                feedback = f"✅ team → `{team_val}` — **{TEAMS[team_val]}**"

            elif field in ("win", "count", "mvp"):
                val = int(value_str)
                if val not in (0, 1):
                    raise ValueError("Usa `1` (sì) o `0` (no).")
                self.db.update_field(self.game_number, role_id, field, val)
                icons = {"win": "🏆", "count": "📊", "mvp": "⭐"}
                feedback = f"{icons[field]} **{field}** → `{'1 (sì)' if val else '0 (no)'}`"

            elif field.startswith("description"):
                if value_str.lower() == "none":
                    self.db.update_field(self.game_number, role_id, field, None)
                    feedback = f"✅ **{field}** rimosso (NULL)."
                else:
                    self.db.update_field(self.game_number, role_id, field, value_str)
                    preview = value_str[:80] + ("…" if len(value_str) > 80 else "")
                    feedback = f"✅ **{field}** aggiornato: `{preview}`"

            else:  # role_name e altri campi testuali
                self.db.update_field(self.game_number, role_id, field, value_str)
                feedback = f"✅ **{field}** → `{value_str[:100]}`"

        except Exception as exc:
            # Pulizia messaggi e segnalazione errore
            for m in (prompt_msg, user_msg):
                try:
                    await m.delete()
                except Exception:
                    pass
            await interaction.followup.send(f"❌ Errore: `{exc}`", ephemeral=True)
            return

        # ── Pulizia messaggi di servizio ──────────────────────────────
        for m in (prompt_msg, user_msg):
            try:
                await m.delete()
            except Exception:
                pass

        # ── Aggiorna embed con i nuovi valori ─────────────────────────
        self._update_available_descs()
        new_view = AdminRoleDescriptionView(
            self.game_number, self.game_name, self.roles,
            self.current_index, self.db, self.bot,
        )
        await interaction.message.edit(embed=new_view.get_embed(), view=new_view)
        await interaction.followup.send(feedback, ephemeral=True)

async def setup(bot):
    await bot.add_cog(GameLibraryIT(bot))
