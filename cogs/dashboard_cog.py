import discord
from discord.ext import commands
from discord.ui import View, Button, Select, Modal, TextInput
from datetime import datetime, timezone
import json
import os

CONFIG_FILE_PATH = "db/roles_config.json"

# ------------------------------------------------------------------ #
# Gestione JSON (Lettura, Salvataggio e Helpers Status)
# ------------------------------------------------------------------ #

def load_json_data() -> dict:
    if not os.path.exists(CONFIG_FILE_PATH):
        return {}
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] Impossibile caricare {CONFIG_FILE_PATH}: {e}")
        return {}

def save_json_data(data: dict):
    try:
        with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] Impossibile salvare {CONFIG_FILE_PATH}: {e}")

def get_channel_config(channel_id: int) -> dict:
    data = load_json_data()
    return data.get(str(channel_id), {})

def update_channel_config(channel_id: int, channel_data: dict):
    data = load_json_data()
    data[str(channel_id)] = channel_data
    save_json_data(data)

# --- HELPER DEDICATI AGLI STATUS ---

def get_player_status(channel_id: int) -> dict:
    """Restituisce il dizionario degli status per la RoleChat specificata."""
    ch_config = get_channel_config(channel_id)
    default_status = {
        "protected": False,
        "visit_blocked": False,
        "role_blocked": False,
        "wounded": False,
        "custom_status": []
    }
    return ch_config.get("status", default_status)

def update_player_status(channel_id: int, status_key: str, value):
    """Aggiorna uno specifico status per il canale specificato."""
    ch_config = get_channel_config(channel_id)
    if "status" not in ch_config:
        ch_config["status"] = {
            "protected": False,
            "visit_blocked": False,
            "role_blocked": False,
            "wounded": False,
            "custom_status": []
        }
    ch_config["status"][status_key] = value
    update_channel_config(channel_id, ch_config)


# Helpers per stato gilda/server
def load_guild_data(guild_id: int) -> dict:
    if os.path.exists("guild_data.json"):
        with open("guild_data.json", "r", encoding="utf-8") as f:
            return json.load(f).get(str(guild_id), {})
    return {}

def save_guild_data(guild_id: int, g_data: dict):
    all_g = {}
    if os.path.exists("guild_data.json"):
        with open("guild_data.json", "r", encoding="utf-8") as f:
            all_g = json.load(f)
    all_g[str(guild_id)] = g_data
    with open("guild_data.json", "w", encoding="utf-8") as f:
        json.dump(all_g, f, indent=4)

def _rc_categories(guild: discord.Guild, guild_data: dict) -> list:
    cat_names = guild_data.get("rolechat_categories", [])
    if not cat_names and "rc_category_name" in guild_data:
        cat_names = [guild_data["rc_category_name"]]
    return [c for c in guild.categories if c.name in cat_names]

def _is_overseer(ctx_or_interaction, guild_data: dict) -> bool:
    user = getattr(ctx_or_interaction, "user", None) or getattr(ctx_or_interaction, "author", None)
    if not user:
        return False
    if user.guild_permissions.administrator:
        return True
    overseer_role_id = guild_data.get("overseer_role_id")
    if overseer_role_id:
        return any(r.id == overseer_role_id for r in user.roles)
    overseer_role_name = guild_data.get("overseer_role_name")
    if overseer_role_name:
        return any(r.name == overseer_role_name for r in user.roles)
    return False

def _get_current_house_names(guild: discord.Guild, guild_data: dict, rc_channel: discord.TextChannel) -> list:
    houses_cat = discord.utils.get(guild.categories, name=guild_data.get("houses_category_name"))
    if not houses_cat:
        return []
    found_houses = []
    for ch in houses_cat.channels:
        if ch.permissions_for(rc_channel.guild.default_role).read_messages is False:
            found_houses.append(ch.name)
    return found_houses

def insert_action_log(guild_id: int, channel_id: int, player_id: int, message: str, created_at, marked_at, marked_by_id):
    pass


# ------------------------------------------------------------------ #
# Modal per Input Testuali (Arcade Gannon: Peaceful Zone)
# ------------------------------------------------------------------ #

class ArcadePeacefulZoneModal(Modal, title="Peaceful Zone — Accedi a Chat"):
    chat_name = TextInput(
        label="Nome della Chat Privata",
        placeholder="Inserisci il nome esatto della chat...",
        required=True,
        max_length=100
    )

    def __init__(self, cog: "Dashboard", rc_channel: discord.TextChannel, ability: dict):
        super().__init__()
        self.cog = cog
        self.rc_channel = rc_channel
        self.ability = ability

    async def on_submit(self, interaction: discord.Interaction):
        input_name = self.chat_name.value.strip()
        custom_msg = (
            f"🕊️ **[Peaceful Zone]** Richiesta d'accesso inviata per la chat: `{input_name}`.\n"
            f"*Gli Overseer verificheranno l'esistenza della chat e ti aggiungeranno se valida.*"
        )
        await self.cog._commit_ability_usage(interaction, self.rc_channel, self.ability, f"Chat: {input_name}", custom_msg)


# ------------------------------------------------------------------ #
# Dashboard View (Pulsanti Giocatore + Gestione ALT)
# ------------------------------------------------------------------ #

class DashboardView(View):
    def __init__(self, cog: "Dashboard", rc_channel: discord.TextChannel, timeout: int = 600):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.rc_channel = rc_channel

    async def _guard(self, interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        guild_data = load_guild_data(guild.id)
        
        allowed_categories = _rc_categories(guild, guild_data)
        if allowed_categories and interaction.channel.category not in allowed_categories:
            await interaction.response.send_message("⛔ Puoi usare la Dashboard solo all'interno delle RoleChat!", ephemeral=True)
            return False

        is_overseer = _is_overseer(interaction, guild_data)
        has_channel_access = interaction.channel.permissions_for(interaction.user).read_messages

        if not (is_overseer or has_channel_access):
            await interaction.response.send_message("⛔ Non hai i permessi per interagire con questa Dashboard.", ephemeral=True)
            return False

        return True

    @discord.ui.button(label="Usa Abilità", style=discord.ButtonStyle.primary, emoji="✨")
    async def ability_button(self, interaction: discord.Interaction, button: Button):
        if not await self._guard(interaction):
            return
        await self.cog.handle_ability_button(interaction, self.rc_channel)

    @discord.ui.button(label="Abilità ALT", style=discord.ButtonStyle.secondary, emoji="👥")
    async def alt_info_button(self, interaction: discord.Interaction, button: Button):
        if not await self._guard(interaction):
            return

        ch_config = get_channel_config(self.rc_channel.id)
        alt_id = ch_config.get("linked_alt_channel_id") or ch_config.get("linked_main_channel_id")

        if not alt_id:
            return await interaction.response.send_message("ℹ️ Nessun ALT collegato a questo canale al momento.", ephemeral=True)

        alt_channel = interaction.guild.get_channel(int(alt_id)) if str(alt_id).isdigit() else None
        alt_config = get_channel_config(alt_id)
        alt_name = alt_config.get("role_name", "ALT")

        embed = discord.Embed(
            title=f"👥 Scheda ALT — {alt_name}",
            description=f"**Canale Dedicato:** {alt_channel.mention if alt_channel else 'Non trovato o impostato via ID'}\n"
                        f"**Team:** `{alt_config.get('team', 'N/D')}`",
            color=discord.Color.purple()
        )

        passives = alt_config.get("passives", [])
        if passives:
            pass_text = "\n".join([f"• **{p['name']}**: {p['desc']}" for p in passives])
            embed.add_field(name="🛡️ Abilità Passive (ALT)", value=pass_text, inline=False)

        abilities = alt_config.get("abilities", [])
        if abilities:
            ab_text = "\n".join([
                f"• **{a.get('name', a['id'])}** `({a.get('category', 'N/D')})` [Usi: {a.get('uses', 0)}]\n  {a.get('desc', '')}"
                for a in abilities
            ])
            embed.add_field(name="⚡ Abilità Attive (ALT)", value=ab_text, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Visita", style=discord.ButtonStyle.primary, emoji="🚪")
    async def visit_button(self, interaction: discord.Interaction, button: Button):
        if not await self._guard(interaction):
            return
        await self.cog.handle_visit_button(interaction, self.rc_channel)

    @discord.ui.button(label="Preset", style=discord.ButtonStyle.success, emoji="🎟️")
    async def preset_button(self, interaction: discord.Interaction, button: Button):
        if not await self._guard(interaction):
            return
        await interaction.response.send_message("🎟️ Funzionalità Preset in arrivo.", ephemeral=True)

    @discord.ui.button(label="Log Azioni", style=discord.ButtonStyle.secondary, emoji="📜")
    async def logging_button(self, interaction: discord.Interaction, button: Button):
        if not await self._guard(interaction):
            return
        await interaction.response.send_message("📜 Registro azioni caricato.", ephemeral=True)


# ------------------------------------------------------------------ #
# Cog Principale: Dashboard
# ------------------------------------------------------------------ #

class Dashboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="dashboard")
    async def dashboard_cmd(self, ctx: commands.Context):
        guild_data = load_guild_data(ctx.guild.id)
        ch_config = get_channel_config(ctx.channel.id)

        if not ch_config:
            return await ctx.send(f"⚠️ Nessuna configurazione JSON trovata per il canale con ID `{ctx.channel.id}`.")

        phase = guild_data.get("current_phase", "PAUSE")
        phase_emoji = {"DAY": "☀️ Diurna", "NIGHT": "🌙 Notturna", "PAUSE": "⏸️ Intermezzo/Pausa"}.get(phase, phase)

        role_name = ch_config.get("role_name", ctx.channel.name)
        lore = ch_config.get("lore", "Nessuna descrizione del ruolo inserita.")

        embed = discord.Embed(
            title=f"🎭 Scheda Ruolo — {role_name}",
            description=f"**Fase Attuale:** `{phase_emoji}`\n\n*{lore}*",
            color=discord.Color.blue()
        )

        passives = ch_config.get("passives", [])
        if passives:
            p_text = "\n".join([f"• **{p.get('name', 'Passiva')}**: {p.get('desc', '')}" for p in passives])
            embed.add_field(name="🛡️ Abilità Passive", value=p_text, inline=False)

        abilities = ch_config.get("abilities", [])
        if abilities:
            for idx, ab in enumerate(abilities, 1):
                uses_left = ab.get("uses", 0)
                cat = ab.get("category", "Generale")
                desc = ab.get("desc", "Nessuna descrizione")
                ab_name = ab.get("name", ab.get("id", f"Abilità {idx}"))
                uses_str = f"♾️ Infiniti" if uses_left < 0 else f"**{uses_left}**"
                
                embed.add_field(
                    name=f"✨ {ab_name} [{cat}] (Utilizzi: {uses_str})",
                    value=desc,
                    inline=False
                )

        visits = ch_config.get("visits", {})
        if visits:
            v_norm = visits.get("normal", 0)
            v_forc = visits.get("forced", 0)
            v_stel = visits.get("stealth", 0)
            v_day = visits.get("day_visits", 0)
            
            v_str = f"Normale: **{v_norm}** | Forzata: **{v_forc}** | Stealth: **{v_stel}**"
            if v_day > 0:
                v_str += f" | Diurna: **{v_day}**"

            embed.add_field(
                name="🚪 Visite Rimanenti",
                value=v_str,
                inline=False
            )

        view = DashboardView(self, ctx.channel)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="statuss")
    async def view_or_edit_status(self, ctx: commands.Context, target_channel: discord.TextChannel = None, key: str = None, value: str = None):
        guild_data = load_guild_data(ctx.guild.id)
        if not _is_overseer(ctx, guild_data):
            return await ctx.send("⛔ Solo gli Overseer possono consultare o modificare gli status segreti.")

        rc = target_channel or ctx.channel
        status_data = get_player_status(rc.id)

        if key and value:
            val_clean = value.lower() in ["true", "1", "si", "yes"] if value.lower() in ["true", "false", "1", "0", "si", "no"] else value
            update_player_status(rc.id, key, val_clean)
            return await ctx.send(f"✅ Status **`{key}`** aggiornato a `{val_clean}` per {rc.mention}.")

        embed = discord.Embed(
            title=f"🕵️ Controllo Status Riservato — {rc.name}",
            color=discord.Color.dark_purple()
        )
        embed.add_field(name="🛡️ Protetto", value=f"`{status_data.get('protected', False)}`", inline=True)
        embed.add_field(name="🚫 Visit Bloccato", value=f"`{status_data.get('visit_blocked', False)}`", inline=True)
        embed.add_field(name="🤐 Role Bloccato", value=f"`{status_data.get('role_blocked', False)}`", inline=True)
        embed.add_field(name="🩸 Ferito", value=f"`{status_data.get('wounded', False)}`", inline=True)
        
        custom_st = status_data.get("custom_status", [])
        embed.add_field(name="✨ Status Custom", value=", ".join(custom_st) if custom_st else "*Nessuno*", inline=False)
        
        embed.set_footer(text="I giocatori non possono vedere questo pannello.")
        await ctx.send(embed=embed)

    @commands.command(name="unlockability")
    async def unlock_ability_cmd(self, ctx: commands.Context, target_channel: discord.TextChannel, ab_id: str, ab_name: str, category: str, uses: int, *, desc: str):
        guild_data = load_guild_data(ctx.guild.id)
        if not _is_overseer(ctx, guild_data):
            return await ctx.send("⛔ Solo gli Overseer possono sbloccare nuove abilità.")

        ch_config = get_channel_config(target_channel.id)
        if not ch_config:
            return await ctx.send("❌ Configurazione per questo canale non trovata.")

        abilities = ch_config.get("abilities", [])
        if len(abilities) >= 5 and ch_config.get("role_name") == "MR. HOUSE":
            return await ctx.send("⚠️ Mr. House ha già raggiunto il limite massimo di 5 abilità sbloccate!")

        new_ability = {
            "id": ab_id,
            "name": ab_name,
            "category": category,
            "uses": uses,
            "desc": desc
        }
        abilities.append(new_ability)
        ch_config["abilities"] = abilities

        if "status" in ch_config and "unlocked_abilities_count" in ch_config["status"]:
            ch_config["status"]["unlocked_abilities_count"] += 1

        update_channel_config(target_channel.id, ch_config)
        await ctx.send(f"✅ Nuova abilità **{ab_name}** (`{ab_id}`) aggiunta con successo a {target_channel.mention}!")


    # ------------------------------------------------------------------ #
    # Gestione Abilità
    # ------------------------------------------------------------------ #

    async def _commit_ability_usage(self, interaction: discord.Interaction, rc_channel: discord.TextChannel, ability: dict, target_info: str, custom_msg: str):
        """Metodo unificato per scalare l'utilizzo solo alla conferma effettiva del target e fornire l'unico feedback finale."""
        guild = interaction.guild
        now_time = datetime.now(timezone.utc)

        # Riduci gli utilizzi se non infiniti
        ch_config = get_channel_config(rc_channel.id)
        for ab in ch_config.get("abilities", []):
            if ab.get("id") == ability.get("id"):
                if ab.get("uses", 0) > 0:
                    ab["uses"] -= 1
                break
        update_channel_config(rc_channel.id, ch_config)

        # Inserisci nel registro
        insert_action_log(
            guild_id=guild.id, channel_id=rc_channel.id, player_id=interaction.user.id,
            message=f"✨ [ABILITÀ] {ability.get('id')} ({target_info})",
            created_at=now_time, marked_at=now_time, marked_by_id=self.bot.user.id
        )

        # Invia l'unico feedback corretto (evita i doppi embed inutili originali)
        if interaction.response.is_done():
            await interaction.followup.send(custom_msg, ephemeral=True)
        else:
            await interaction.response.send_message(custom_msg, ephemeral=True)


    async def handle_ability_button(self, interaction: discord.Interaction, rc_channel: discord.TextChannel):
        guild_data = load_guild_data(interaction.guild.id) or {}

        if guild_data.get("current_phase") == "PAUSE":
            return await interaction.response.send_message("⏸️ **Gioco in Pausa:** Durante l'intermezzo non puoi compiere azioni.", ephemeral=True)

        status = get_player_status(rc_channel.id)
        if status.get("role_blocked", False):
            return await interaction.response.send_message("❌ **Le tue abilità sono attualmente bloccate per questa fase!**", ephemeral=True)

        ch_config = get_channel_config(rc_channel.id)
        abilities = [ab for ab in ch_config.get("abilities", []) if ab.get("uses", 0) != 0]

        if not abilities:
            return await interaction.response.send_message("❌ Non hai abilità attive disponibili o hai esaurito gli utilizzi!", ephemeral=True)

        options = []
        for idx, ab in enumerate(abilities):
            uses = ab.get("uses", 0)
            u_str = "♾️" if uses < 0 else f"{uses} rimasti"
            ab_title = ab.get("name", ab.get("id", f"ab_{idx}"))
            options.append(discord.SelectOption(
                label=f"{ab_title} [{ab.get('category')}]",
                description=f"Usi: {u_str} - {ab.get('desc')[:60]}",
                value=ab.get("id", str(idx))
            ))

        ability_select = Select(placeholder="Scegli l'abilità da eseguire...", options=options)

        async def ability_callback(sel_inter: discord.Interaction):
            chosen_id = ability_select.values[0]
            chosen_ab = next((a for a in abilities if a.get("id") == chosen_id), None)
            if chosen_ab:
                await self._process_ability_usage(sel_inter, rc_channel, chosen_ab)

        ability_select.callback = ability_callback
        view = View(timeout=60)
        view.add_item(ability_select)

        await interaction.response.send_message("🧪 **Seleziona un'abilità:**", view=view, ephemeral=True)

    async def _process_ability_usage(self, interaction: discord.Interaction, rc_channel: discord.TextChannel, ability: dict):
        guild = interaction.guild
        guild_data = load_guild_data(guild.id) or {}
        cat_lower = ability.get("category", "").lower()
        current_phase = guild_data.get("current_phase", "NIGHT")

        is_day_ability = "diurna" in cat_lower or "giorno" in cat_lower
        if current_phase == "DAY" and not is_day_ability:
            return await interaction.response.send_message("☀️ Questa abilità può essere usata solo di **Notte**!", ephemeral=True)
        if current_phase == "NIGHT" and is_day_ability:
            return await interaction.response.send_message("🌙 Questa abilità può essere usata solo di **Giorno**!", ephemeral=True)

        if "fisica" in cat_lower and "remota" not in cat_lower:
            my_houses = _get_current_house_names(guild, guild_data, rc_channel)
            if not my_houses:
                return await interaction.response.send_message("❌ Le abilità fisiche richiedono di essere all'interno di una Casa!", ephemeral=True)
            await self._dispatch_ability_logic(interaction, rc_channel, ability, f"Casa {my_houses[0]}")
        else:
            await self._dispatch_ability_logic(interaction, rc_channel, ability, "Remoto/Ibrido")


    # ------------------------------------------------------------------ #
    # 🎯 DISPATCHER LOGICHE ABILITÀ
    # ------------------------------------------------------------------ #
    async def _dispatch_ability_logic(self, interaction: discord.Interaction, rc_channel: discord.TextChannel, ability: dict, loc_info: str):
        ab_id = ability.get("id")
        guild = interaction.guild
        guild_data = load_guild_data(guild.id) or {}
        
        rc_categories = _rc_categories(guild, guild_data)
        all_rc_channels = []
        if rc_categories:
            for cat in rc_categories:
                all_rc_channels.extend(cat.text_channels)
        else:
            all_rc_channels = [c for c in guild.text_channels if c.id != rc_channel.id]

        # === ABILITÀ BOONE (ROLECHAT 3) ===
        if ab_id == "red_berret":
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select = Select(placeholder="Seleziona il giocatore da marchiare con Red Berret...", options=options)

            async def red_berret_cb(s_inter: discord.Interaction):
                target_id = int(select.values[0])
                target_ch = guild.get_channel(target_id)
                status = get_player_status(rc_channel.id)
                marked = status.get("marked_targets", [])
                if target_id not in marked:
                    marked.append(target_id)
                    update_player_status(rc_channel.id, "marked_targets", marked)

                msg = f"🎯 **[Red Berret]** Hai marchiato {target_ch.mention if target_ch else 'il bersaglio'}!"
                await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else target_id}", msg)

            select.callback = red_berret_cb
            view = View(timeout=60)
            view.add_item(select)
            return await interaction.response.send_message("🔴 **Seleziona il bersaglio da marchiare:**", view=view, ephemeral=True)

        elif ab_id == "best_sniper_in_vegas":
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select = Select(placeholder="Seleziona la vittima dello Sniping...", options=options)

            async def sniper_cb(s_inter: discord.Interaction):
                target_id = int(select.values[0])
                target_ch = guild.get_channel(target_id)
                msg = f"💥 **[Best Sniper in Vegas]** Sparato a {target_ch.mention if target_ch else 'un bersaglio'}!"
                await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else target_id}", msg)

            select.callback = sniper_cb
            view = View(timeout=60)
            view.add_item(select)
            return await interaction.response.send_message("🎯 **Seleziona il bersaglio da eliminare:**", view=view, ephemeral=True)

        elif ab_id == "recon_unit":
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select = Select(placeholder="Seleziona il giocatore da ricognire...", options=options)

            async def recon_cb(s_inter: discord.Interaction):
                target_id = int(select.values[0])
                target_ch = guild.get_channel(target_id)
                msg = f"🔍 **[Recon Unit]** Richiesta inviata per {target_ch.mention if target_ch else 'il giocatore'}."
                await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else target_id}", msg)

            select.callback = recon_cb
            view = View(timeout=60)
            view.add_item(select)
            return await interaction.response.send_message("🕵️ **Seleziona il bersaglio per la ricognizione:**", view=view, ephemeral=True)

        elif ab_id == "i_forgot_to_remember_to_forget":
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select = Select(placeholder="Seleziona il giocatore da tracciare...", options=options)

            async def forget_cb(s_inter: discord.Interaction):
                target_id = int(select.values[0])
                target_ch = guild.get_channel(target_id)
                update_player_status(rc_channel.id, "forget_target", target_id)
                msg = f"👁️ **[I forgot...]** Monitoraggio attivato su {target_ch.mention if target_ch else 'il bersaglio'}."
                await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else target_id}", msg)

            select.callback = forget_cb
            view = View(timeout=60)
            view.add_item(select)
            return await interaction.response.send_message("🧠 **Seleziona il giocatore da monitorare:**", view=view, ephemeral=True)

        # === ABILITÀ DEAN DOMINO (ROLECHAT 4) & OLOGRAMMA (ALT) ===
        elif ab_id == "gruzzolo_segreto":
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select_target = Select(placeholder="Seleziona il destinatario dell'abilità...", options=options)

            buff_options = [
                discord.SelectOption(label="+1 Utilizzo aggiuntivo", value="extra_use"),
                discord.SelectOption(label="Abilità Remota (Nome + Posizione)", value="make_remote"),
                discord.SelectOption(label="Bypassa Status / Manipolazioni / RB", value="bypass_all")
            ]
            select_buff = Select(placeholder="Scegli il potenziamento...", options=buff_options)

            view = View(timeout=90)
            view.add_item(select_target)
            view.add_item(select_buff)

            state = {"target_id": None, "buff": None}

            async def check_and_send(s_inter: discord.Interaction):
                if state["target_id"] and state["buff"]:
                    target_ch = guild.get_channel(int(state["target_id"]))
                    msg = (f"🎁 **[Gruzzolo Segreto]** Abilità inviata a {target_ch.mention if target_ch else 'giocatore'}.\n"
                           f"**Potenziamento applicato:** `{state['buff']}`\n"
                           f"*Comunica agli OS l'abilità del negozio da inviare.*")
                    await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else state['target_id']} Buff: {state['buff']}", msg)
                else:
                    await s_inter.response.defer()

            async def target_cb(i: discord.Interaction):
                state["target_id"] = select_target.values[0]
                await check_and_send(i)
                
            async def buff_cb(i: discord.Interaction):
                state["buff"] = select_buff.values[0]
                await check_and_send(i)

            select_target.callback = target_cb
            select_buff.callback = buff_cb

            return await interaction.response.send_message("💼 **Configura il Gruzzolo Segreto:**", view=view, ephemeral=True)

        elif ab_id in ["istinto_ghoul", "istinto_ghoul_olografico"]:
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select_corpse = Select(placeholder="Seleziona il cadavere...", options=options)

            num_options = [discord.SelectOption(label=f"Abilità #{n}", value=str(n)) for n in range(1, 11)]
            select_num = Select(placeholder="Scegli un numero da 1 a 10...", options=num_options)

            view = View(timeout=90)
            view.add_item(select_corpse)
            view.add_item(select_num)

            state = {"corpse_id": None, "num": None}

            async def process_ghoul(s_inter: discord.Interaction):
                if state["corpse_id"] and state["num"]:
                    c_ch = guild.get_channel(int(state["corpse_id"]))
                    msg = (f"🧟 **[Istinto Ghoul]** Analisi inviata per {c_ch.mention if c_ch else 'il cadavere'}.\n"
                           f"**Numero selezionato:** `{state['num']}`")
                    await self._commit_ability_usage(s_inter, rc_channel, ability, f"Corpse: {c_ch.name if c_ch else state['corpse_id']} Num: {state['num']}", msg)
                else:
                    await s_inter.response.defer()

            async def corpse_cb(i: discord.Interaction):
                state["corpse_id"] = select_corpse.values[0]
                await process_ghoul(i)

            async def num_cb(i: discord.Interaction):
                state["num"] = select_num.values[0]
                await process_ghoul(i)

            select_corpse.callback = corpse_cb
            select_num.callback = num_cb

            return await interaction.response.send_message("🧠 **Seleziona il cadavere e l'indice dell'abilità:**", view=view, ephemeral=True)

        elif ab_id == "rinascita_ghoul":
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select = Select(placeholder="Seleziona il giocatore da marchiare...", options=options)

            async def rinascita_cb(s_inter: discord.Interaction):
                target_id = int(select.values[0])
                target_ch = guild.get_channel(target_id)
                status = get_player_status(rc_channel.id)
                marked = status.get("rinascita_marked", [])
                if target_id not in marked:
                    marked.append(target_id)
                    update_player_status(rc_channel.id, "rinascita_marked", marked)

                msg = f"☣️ **[Rinascita Ghoul]** Marchiato {target_ch.mention if target_ch else 'il bersaglio'}."
                await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else target_id}", msg)

            select.callback = rinascita_cb
            view = View(timeout=60)
            view.add_item(select)
            return await interaction.response.send_message("☣️ **Seleziona il bersaglio da marchiare:**", view=view, ephemeral=True)

        elif ab_id == "saw_her_yesterday":
            options1 = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select1 = Select(placeholder="Primo giocatore da legare...", options=options1)

            options2 = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select2 = Select(placeholder="Secondo giocatore da legare...", options=options2)

            view = View(timeout=90)
            view.add_item(select1)
            view.add_item(select2)

            state = {"p1": None, "p2": None}

            async def process_link(s_inter: discord.Interaction):
                if state["p1"] and state["p2"]:
                    if state["p1"] == state["p2"]:
                        return await s_inter.response.send_message("❌ Non puoi legare un giocatore a se stesso!", ephemeral=True)

                    ch1 = guild.get_channel(int(state["p1"]))
                    ch2 = guild.get_channel(int(state["p2"]))
                    status = get_player_status(rc_channel.id)
                    links = status.get("saw_her_yesterday_links", [])
                    links.append({"p1": state["p1"], "p2": state["p2"]})
                    update_player_status(rc_channel.id, "saw_her_yesterday_links", links)

                    msg = f"🔗 **[Saw Her Yesterday]** Legati {ch1.mention if ch1 else 'P1'} e {ch2.mention if ch2 else 'P2'}!"
                    await self._commit_ability_usage(s_inter, rc_channel, ability, f"Link: {ch1.name if ch1 else state['p1']} & {ch2.name if ch2 else state['p2']}", msg)
                else:
                    await s_inter.response.defer()

            async def p1_cb(i: discord.Interaction):
                state["p1"] = select1.values[0]
                await process_link(i)

            async def p2_cb(i: discord.Interaction):
                state["p2"] = select2.values[0]
                await process_link(i)

            select1.callback = p1_cb
            select2.callback = p2_cb

            return await interaction.response.send_message("🔗 **Seleziona i due giocatori da legare:**", view=view, ephemeral=True)

        elif ab_id == "scannerizzazione":
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select_corpse = Select(placeholder="Seleziona il cadavere da scannerizzare...", options=options)

            async def scan_cb(s_inter: discord.Interaction):
                target_id = int(select_corpse.values[0])
                target_ch = guild.get_channel(target_id)
                status = get_player_status(rc_channel.id)
                scanned = status.get("scanned_corpses", [])

                if target_id in scanned:
                    return await s_inter.response.send_message("❌ Questo cadavere è già stato scannerizzato!", ephemeral=True)

                scanned.append(target_id)
                update_player_status(rc_channel.id, "scanned_corpses", scanned)

                msg = (f"📷 **[Scannerizzazione]** Scannerizzazione inviata per {target_ch.mention if target_ch else 'il cadavere'}.\n"
                       f"*Comunica agli OS le categorie e il prezzo per il negozio della Sierra Madre.*")
                await self._commit_ability_usage(s_inter, rc_channel, ability, f"Corpse: {target_ch.name if target_ch else target_id}", msg)

            select_corpse.callback = scan_cb
            view = View(timeout=60)
            view.add_item(select_corpse)
            return await interaction.response.send_message("📸 **Seleziona il cadavere da scannerizzare:**", view=view, ephemeral=True)

        # === ABILITÀ JULIA FARKAS (ROLECHAT 5) ===
        elif ab_id == "farmaci_scaduti":
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select_target = Select(placeholder="Seleziona il giocatore in casa con te...", options=options)

            action_options = [
                discord.SelectOption(label="Infliggi RoleBlock (RB)", value="inflict_rb"),
                discord.SelectOption(label="Cura RoleBlock (RB)", value="cure_rb"),
                discord.SelectOption(label="Infliggi VisitBlock (VB)", value="inflict_vb"),
                discord.SelectOption(label="Cura VisitBlock (VB)", value="cure_vb")
            ]
            select_action = Select(placeholder="Scegli l'azione...", options=action_options)

            view = View(timeout=90)
            view.add_item(select_target)
            view.add_item(select_action)

            state = {"target_id": None, "action": None}

            async def process_farmaci(s_inter: discord.Interaction):
                if state["target_id"] and state["action"]:
                    target_ch = guild.get_channel(int(state["target_id"]))
                    status = get_player_status(rc_channel.id)
                    history = status.get("julia_target_history", [])
                    if int(state["target_id"]) not in history:
                        history.append(int(state["target_id"]))
                        update_player_status(rc_channel.id, "julia_target_history", history)

                    msg = f"💊 **[Farmaci Scaduti]** Azione `{state['action']}` registrata su {target_ch.mention if target_ch else 'giocatore'}."
                    await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else state['target_id']} Act: {state['action']}", msg)
                else:
                    await s_inter.response.defer()

            async def ft_cb(i: discord.Interaction):
                state["target_id"] = select_target.values[0]
                await process_farmaci(i)

            async def fa_cb(i: discord.Interaction):
                state["action"] = select_action.values[0]
                await process_farmaci(i)

            select_target.callback = ft_cb
            select_action.callback = fa_cb

            return await interaction.response.send_message("🧪 **Seleziona bersaglio e tipo di somministrazione:**", view=view, ephemeral=True)

        elif ab_id == "followers_radio":
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select = Select(placeholder="Seleziona il giocatore da marchiare...", options=options)

            async def radio_cb(s_inter: discord.Interaction):
                target_id = int(select.values[0])
                target_ch = guild.get_channel(target_id)
                
                status = get_player_status(rc_channel.id)
                status["radio_marked_target"] = target_id
                status["radio_teleports_left"] = 2
                
                history = status.get("julia_target_history", [])
                if target_id not in history:
                    history.append(target_id)
                status["julia_target_history"] = history
                update_player_status(rc_channel.id, "status", status)

                msg = f"📻 **[Follower's Radio]** Marchiato {target_ch.mention if target_ch else 'giocatore'}. (Hai 2 trasporti disponibili)"
                await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else target_id}", msg)

            select.callback = radio_cb
            view = View(timeout=60)
            view.add_item(select)
            return await interaction.response.send_message("📻 **Seleziona il bersaglio da marchiare:**", view=view, ephemeral=True)

        elif ab_id == "peaceful_zone":
            my_houses = _get_current_house_names(guild, guild_data, rc_channel)
            if not my_houses:
                return await interaction.response.send_message("❌ Devi essere all'interno di una Casa per attivare Peaceful Zone!", ephemeral=True)

            house_name = my_houses[0]
            houses_cat = discord.utils.get(guild.categories, name=guild_data.get("houses_category_name"))
            house_channel = next((ch for ch in houses_cat.channels if ch.name == house_name), None) if houses_cat else None

            if house_channel:
                await house_channel.edit(name=f"🏰-forte-{house_name}")
                
            msg = (f"🕊️ **[Peaceful Zone]** La casa **{house_name}** è stata rinominata in **Forte**!\n"
                   f"• Protezione da abilità remote attiva.\n"
                   f"• Protezioni personali sospese all'interno.")
            await self._commit_ability_usage(interaction, rc_channel, ability, f"Forte: {house_name}", msg)

        elif ab_id == "new_vegas_medical_clinic":
            status = get_player_status(rc_channel.id)
            history = status.get("julia_target_history", [])

            if not history:
                return await interaction.response.send_message("❌ Non hai ancora utilizzato alcuna abilità su nessun giocatore!", ephemeral=True)

            valid_channels = [guild.get_channel(cid) for cid in history if guild.get_channel(cid) is not None]
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in valid_channels[:25]]
            select = Select(placeholder="Seleziona il giocatore da rianimare...", options=options)

            async def clinic_cb(s_inter: discord.Interaction):
                target_id = int(select.values[0])
                target_ch = guild.get_channel(target_id)
                msg = f"🏥 **[New Vegas Medical Clinic]** Rianimazione inviata agli Overseer per {target_ch.mention if target_ch else 'il giocatore'}."
                await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else target_id}", msg)

            select.callback = clinic_cb
            view = View(timeout=60)
            view.add_item(select)
            return await interaction.response.send_message("💉 **Seleziona il bersaglio da rianimare:**", view=view, ephemeral=True)

        # === ABILITÀ BENNY (ROLECHAT 6) ===
        elif ab_id == "cripple_the_legs":
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select = Select(placeholder="Seleziona il giocatore a cui rimuovere le visite...", options=options)

            async def cripple_cb(s_inter: discord.Interaction):
                target_id = int(select.values[0])
                target_ch = guild.get_channel(target_id)
                msg = f"🦵 **[Cripple the legs]** Azione registrata! {target_ch.mention if target_ch else 'Il bersaglio'} perderà tutte le visite restanti per questa fase."
                await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else target_id}", msg)

            select.callback = cripple_cb
            view = View(timeout=60)
            view.add_item(select)
            return await interaction.response.send_message("🎯 **Seleziona il bersaglio da azzoppare:**", view=view, ephemeral=True)

        elif ab_id == "a_bullet_in_the_head":
            options_target = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select_target = Select(placeholder="Seleziona il giocatore da colpire...", options=options_target)

            num_options = [discord.SelectOption(label=f"Abilità #{n}", value=str(n)) for n in range(1, 11)]
            select_num = Select(placeholder="Seleziona il numero dell'abilità da depotenziare...", options=num_options)

            view = View(timeout=90)
            view.add_item(select_target)
            view.add_item(select_num)

            state = {"target_id": None, "num": None}

            async def process_bullet(s_inter: discord.Interaction):
                if state["target_id"] and state["num"]:
                    target_ch = guild.get_channel(int(state["target_id"]))
                    msg = (f"💥 **[A bullet in the head]** Azione registrata su {target_ch.mention if target_ch else 'giocatore'}.\n"
                           f"**Numero abilità bersaglio:** #{state['num']}\n"
                           f"*Se il giocatore possiede meno abilità di quelle indicate, la rimozione dell'utilizzo sarà casuale.*")
                    await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else state['target_id']} Num: {state['num']}", msg)
                else:
                    await s_inter.response.defer()

            async def bt_cb(i: discord.Interaction):
                state["target_id"] = select_target.values[0]
                await process_bullet(i)

            async def bn_cb(i: discord.Interaction):
                state["num"] = select_num.values[0]
                await process_bullet(i)

            select_target.callback = bt_cb
            select_num.callback = bn_cb

            return await interaction.response.send_message("🔫 **Seleziona bersaglio e numero abilità:**", view=view, ephemeral=True)

        # === ABILITÀ ARCADE GANNON (ROLECHAT 7) ===
        elif ab_id == "chiamata_dell_enclave":
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select = Select(placeholder="Seleziona il bersaglio per la Chiamata dell'Enclave...", options=options)

            async def enclave_cb(s_inter: discord.Interaction):
                target_id = int(select.values[0])
                target_ch = guild.get_channel(target_id)
                msg = (f"🚁 **[Chiamata dell'enclave]** Attacco letale programmato contro {target_ch.mention if target_ch else 'il bersaglio'}.\n"
                       f"*Gli Overseer applicheranno lo stadio effettivo in base al numero di Chat Private attive.*")
                await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else target_id}", msg)

            select.callback = enclave_cb
            view = View(timeout=60)
            view.add_item(select)
            return await interaction.response.send_message("🚁 **Seleziona il bersaglio da eliminare:**", view=view, ephemeral=True)

        elif ab_id == "arcade_followers_radio":
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select = Select(placeholder="Seleziona il compagno per la Chat Privata...", options=options)

            async def radio_cb(s_inter: discord.Interaction):
                target_id = int(select.values[0])
                target_ch = guild.get_channel(target_id)
                msg = (f"📻 **[Follower's Radio]** Creazione della Chat Privata **'Compagni'** richiesta per {target_ch.mention if target_ch else 'il giocatore'}.\n"
                       f"*La chat durerà fino al termine della prossima fase diurna.*")
                await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else target_id}", msg)

            select.callback = radio_cb
            view = View(timeout=60)
            view.add_item(select)
            return await interaction.response.send_message("📻 **Seleziona il compagno da contattare:**", view=view, ephemeral=True)

        elif ab_id == "arcade_peaceful_zone":
            modal = ArcadePeacefulZoneModal(self, rc_channel, ability)
            return await interaction.response.send_modal(modal)

        elif ab_id == "down_with_the_autocrats":
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select = Select(placeholder="Seleziona il bersaglio della manipolazione voti...", options=options)

            async def autocrats_cb(s_inter: discord.Interaction):
                target_id = int(select.values[0])
                target_ch = guild.get_channel(target_id)
                msg = (f"🏛️ **[Down with the Autocrats]** Manipolazione dei voti della fazione registrata contro {target_ch.mention if target_ch else 'il bersaglio'}.\n"
                       f"*L'effetto verrà applicato al primo lynch utile (diurno o notturno).*")
                await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else target_id}", msg)

            select.callback = autocrats_cb
            view = View(timeout=60)
            view.add_item(select)
            return await interaction.response.send_message("🏛️ **Seleziona il bersaglio di un'altra fazione da far votare:**", view=view, ephemeral=True)

        # === ABILITÀ CASSIDY (ROLECHAT 11) & CAROVANA (ALT) ===
        elif ab_id == "free_market_competition":
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select = Select(placeholder="Seleziona la persona da marchiare per la competizione...", options=options)

            async def market_cb(s_inter: discord.Interaction):
                target_id = int(select.values[0])
                target_ch = guild.get_channel(target_id)
                
                status = get_player_status(rc_channel.id)
                marked = status.get("free_market_marked", [])
                if target_id not in marked:
                    marked.append(target_id)
                    update_player_status(rc_channel.id, "free_market_marked", marked)

                msg = (f"💀 **[Free Market Competition]** Marchiato {target_ch.mention if target_ch else 'il bersaglio'}.\n"
                       f"*Se l'ALT Carovana finisce nella stessa casa a fine fase o se il bersaglio poteva acquistare dal negozio dopo Advertising, verrà eliminato.*")
                await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else target_id}", msg)

            select.callback = market_cb
            view = View(timeout=60)
            view.add_item(select)
            return await interaction.response.send_message("💀 **Seleziona il bersaglio per la competizione spietata:**", view=view, ephemeral=True)

        elif ab_id == "pushy_marketing":
            options_target = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select_target = Select(placeholder="Seleziona il giocatore in casa con te...", options=options_target)

            item_options = [
                discord.SelectOption(label="Alcool (100 Caps)", value="alcohol"),
                discord.SelectOption(label="Medicina (350 Caps)", value="medicine"),
                discord.SelectOption(label="Acqua e Cibo (50 Caps)", value="food_water")
            ]
            select_item = Select(placeholder="Seleziona l'oggetto del negozio Carovana...", options=item_options)

            view = View(timeout=90)
            view.add_item(select_target)
            view.add_item(select_item)

            state = {"target_id": None, "item": None}

            async def process_pushy(s_inter: discord.Interaction):
                if state["target_id"] and state["item"]:
                    target_ch = guild.get_channel(int(state["target_id"]))
                    msg = (f"📢 **[Pushy Marketing]** Costretto {target_ch.mention if target_ch else 'il giocatore'} ad acquistare/usare `{state['item']}`!\n"
                           f"*Assicurati che sia tu che l'ALT Carovana siate nella stessa casa col bersaglio.*")
                    await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else state['target_id']} Item: {state['item']}", msg)
                else:
                    await s_inter.response.defer()

            async def pt_cb(i: discord.Interaction):
                state["target_id"] = select_target.values[0]
                await process_pushy(i)

            async def pi_cb(i: discord.Interaction):
                state["item"] = select_item.values[0]
                await process_pushy(i)

            select_target.callback = pt_cb
            select_item.callback = pi_cb

            return await interaction.response.send_message("📢 **Seleziona il bersaglio e l'oggetto da forzare:**", view=view, ephemeral=True)

        elif ab_id == "how_bout_a_beer":
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in all_rc_channels[:25]]
            select_target = Select(placeholder="Seleziona il giocatore...", options=options)

            mode_options = [
                discord.SelectOption(label="Remoto (Posizione) -> Infliggi VB", value="remote_vb"),
                discord.SelectOption(label="Fisico (Stessa Casa) -> +1 Bersaglio Extra", value="physical_extra_target")
            ]
            select_mode = Select(placeholder="Seleziona la modalità d'uso...", options=mode_options)

            view = View(timeout=90)
            view.add_item(select_target)
            view.add_item(select_mode)

            state = {"target_id": None, "mode": None}

            async def process_beer(s_inter: discord.Interaction):
                if state["target_id"] and state["mode"]:
                    target_ch = guild.get_channel(int(state["target_id"]))
                    mode_text = "VB inflitto (Remoto)" if state["mode"] == "remote_vb" else "+1 Bersaglio Extra assegnato (Fisico)"
                    msg = (f"🍺 **[How 'bout a beer?]** Azione usata su {target_ch.mention if target_ch else 'il giocatore'}.\n"
                           f"**Effetto:** `{mode_text}`")
                    await self._commit_ability_usage(s_inter, rc_channel, ability, f"Target: {target_ch.name if target_ch else state['target_id']} Mode: {state['mode']}", msg)
                else:
                    await s_inter.response.defer()

            async def ht_cb(i: discord.Interaction):
                state["target_id"] = select_target.values[0]
                await process_beer(i)

            async def hm_cb(i: discord.Interaction):
                state["mode"] = select_mode.values[0]
                await process_beer(i)

            select_target.callback = ht_cb
            select_mode.callback = hm_cb

            return await interaction.response.send_message("🍺 **Seleziona il bersaglio e la modalità d'attivazione:**", view=view, ephemeral=True)

        elif ab_id == "advertising":
            my_houses = _get_current_house_names(guild, guild_data, rc_channel)
            curr_loc = f"Casa {my_houses[0]}" if my_houses else "Posizione sconosciuta"

            msg = (f"📣 **[Advertising]** Annuncio della Carovana inviato agli Overseer!\n"
                   f"• **Posizione del tuo ALT:** `{curr_loc}`\n"
                   f"• **Incentivo vendita attivo per Free Market Competition.**")
            await self._commit_ability_usage(interaction, rc_channel, ability, f"Loc: {curr_loc}", msg)

        # === FALLBACK PER ABILITÀ DINAMICHE / ACQUISTATE (ES. MR. HOUSE) ===
        else:
            msg = (f"✨ **[{ability.get('name', ab_id)}]** Uso dell'abilità registrato con successo!\n"
                   f"*Notifica inviata agli Overseer per la risoluzione manuale o custom.*")
            await self._commit_ability_usage(interaction, rc_channel, ability, loc_info, msg)


    # --- VISITE ---
    async def handle_visit_button(self, interaction: discord.Interaction, rc_channel: discord.TextChannel):
        guild = interaction.guild
        guild_data = load_guild_data(guild.id) or {}

        if guild_data.get("current_phase") == "PAUSE":
            return await interaction.response.send_message("⏸️ **Gioco in Pausa:** Durante l'intermezzo non puoi effettuare visite.", ephemeral=True)

        status = get_player_status(rc_channel.id)
        if status.get("visit_blocked", False):
            return await interaction.response.send_message("❌ **Le tue visite sono attualmente bloccate!**", ephemeral=True)

        ch_config = get_channel_config(rc_channel.id)
        visits = ch_config.get("visits", {})
        current_phase = guild_data.get("current_phase", "NIGHT")

        visit_options = []
        if current_phase == "NIGHT":
            if visits.get("normal", 0) > 0:
                visit_options.append(discord.SelectOption(label=f"Visita Normale (Bussa) - Restanti: {visits['normal']}", value="normal"))
            if visits.get("forced", 0) > 0:
                visit_options.append(discord.SelectOption(label=f"Visita Forzata (Entra) - Restanti: {visits['forced']}", value="forced"))
            if visits.get("stealth", 0) > 0:
                visit_options.append(discord.SelectOption(label=f"Visita Stealth - Restanti: {visits['stealth']}", value="stealth"))
        elif current_phase == "DAY":
            if visits.get("day_visits", 0) > 0:
                visit_options.append(discord.SelectOption(label=f"Visita Diurna - Restanti: {visits['day_visits']}", value="day_visits"))

        if not visit_options:
            return await interaction.response.send_message("❌ Hai esaurito le visite disponibili per la fase attuale!", ephemeral=True)

        houselist = guild_data.get("houselist") or []
        if not houselist and guild_data.get("houses_category_name"):
            houses_cat = discord.utils.get(guild.categories, name=guild_data.get("houses_category_name"))
            if houses_cat:
                houselist = [ch.name for ch in houses_cat.channels]

        type_select = Select(placeholder="Tipo di visita...", options=visit_options)
        house_select = Select(placeholder="Casa destinazione...", options=[discord.SelectOption(label=h, value=h) for h in houselist[:25]])

        view = View(timeout=120)
        view.add_item(type_select)
        view.add_item(house_select)

        state = {"type": None, "house": None}

        async def check_and_run(sel_inter: discord.Interaction):
            if state["type"] and state["house"]:
                await self._execute_visit(sel_inter, rc_channel, state["type"], state["house"])
            else:
                await sel_inter.response.defer()

        async def vt_cb(i: discord.Interaction):
            state["type"] = type_select.values[0]
            await check_and_run(i)
            
        async def vh_cb(i: discord.Interaction):
            state["house"] = house_select.values[0]
            await check_and_run(i)

        type_select.callback = vt_cb
        house_select.callback = vh_cb

        await interaction.response.send_message("🚪 **Configura la tua Visita:**", view=view, ephemeral=True)

    async def _execute_visit(self, interaction: discord.Interaction, rc_channel: discord.TextChannel, visit_type: str, house_name: str):
        guild = interaction.guild
        guild_data = load_guild_data(guild.id)
        now_time = datetime.now(timezone.utc)

        houses_cat = discord.utils.get(guild.categories, name=guild_data.get("houses_category_name"))
        target_channel = next((ch for ch in houses_cat.channels if ch.name == house_name), None) if houses_cat else None

        if not target_channel:
            if interaction.response.is_done():
                return await interaction.followup.send("❌ Casa non trovata.", ephemeral=True)
            return await interaction.response.send_message("❌ Casa non trovata.", ephemeral=True)

        ch_config = get_channel_config(rc_channel.id)
        if "visits" in ch_config and visit_type in ch_config["visits"]:
            if ch_config["visits"][visit_type] > 0:
                ch_config["visits"][visit_type] -= 1
                update_channel_config(rc_channel.id, ch_config)

        moving_cog = self.bot.get_cog("Moving")
        
        # Facciamo il defer qui: l'onere di rispondere senza bug e col messaggio corretto sarà delegato a process_knock / process_move
        await interaction.response.defer(ephemeral=True)

        if moving_cog:
            ctx = await self.bot.get_context(interaction.message)
            ctx.channel = rc_channel
            ctx.author = interaction.user

            if visit_type == "normal":
                insert_action_log(
                    guild_id=guild.id, channel_id=rc_channel.id, player_id=interaction.user.id,
                    message=f"🚪 [BUSSATA] Ha bussato alla porta di {target_channel.name}",
                    created_at=now_time, marked_at=now_time, marked_by_id=self.bot.user.id
                )
                if hasattr(moving_cog, "process_knock"):
                    await moving_cog.process_knock(ctx, target_channel, guild_data)
                
                # Feedback effimero transitorio (solo per confermare l'invio alla dashboard e chiudere silenziosamente)
                await interaction.followup.send(f"🔔 **Azione di visita inviata per {house_name}.**", ephemeral=True)
            else:
                is_stealth = (visit_type == "stealth")
                if hasattr(moving_cog, "process_move"):
                    await moving_cog.process_move(ctx, target_channel, is_stealth=is_stealth, read_only=False)
                
                insert_action_log(
                    guild_id=guild.id, channel_id=rc_channel.id, player_id=interaction.user.id,
                    message=f"🚪 [INGRESSO DIRECT] Entrato in {target_channel.name} ({visit_type})",
                    created_at=now_time, marked_at=now_time, marked_by_id=self.bot.user.id
                )
                # Feedback effimero transitorio silenzioso (le stampe verranno fatte dal cog Moving)
                await interaction.followup.send(f"✅ **Azione di ingresso inviata per {house_name}.**", ephemeral=True)
        else:
            await interaction.followup.send("❌ Errore: Il sistema di movimento del bot è momentaneamente offline.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Dashboard(bot))