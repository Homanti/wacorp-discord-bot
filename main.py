import discord
from discord import app_commands
import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.automap import automap_base
from sqlalchemy import select, update

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

APPLICATIONS_CHANNEL_ID = 1096484995587125358

MODERATOR_ROLE_ID = 825063273320939640
ADMIN_ROLE_ID = 825062794356588544

NOVICE_ROLE_ID = 825075676607414282
MEMBER_ROLE_ID = 981634825775640616

Base = automap_base()
engine = create_async_engine(DATABASE_URL, echo=False)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

User = None


async def init_models():
    global User
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.reflect)
        await conn.run_sync(Base.prepare)

    User = Base.classes.users


def has_staff_role(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False

    user_roles = [role.id for role in interaction.user.roles]
    return MODERATOR_ROLE_ID in user_roles or ADMIN_ROLE_ID in user_roles


class ApplicationView(discord.ui.View):
    def __init__(self, user_id: int, discord_id: str, username: str):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.discord_id = discord_id
        self.username = username

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.green, custom_id="approve_app")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_staff_role(interaction):
            await interaction.response.send_message(
                "❌ У вас нет прав для выполнения этого действия.",
                ephemeral=True
            )
            return

        try:
            async with async_session_maker() as session:
                stmt = update(User).where(User.id == self.user_id).values(accepted=True)
                await session.execute(stmt)
                await session.commit()

            # Управление ролями
            guild = interaction.guild
            member = guild.get_member(int(self.discord_id))

            role_changes_text = ""
            if member:
                novice_role = guild.get_role(NOVICE_ROLE_ID)
                member_role = guild.get_role(MEMBER_ROLE_ID)

                try:
                    if novice_role and novice_role in member.roles:
                        await member.remove_roles(novice_role,
                                                  reason=f"Заявка одобрена модератором {interaction.user.name}")
                        role_changes_text += f"🔻 Убрана роль: {novice_role.mention}\n"

                    if member_role:
                        await member.add_roles(member_role,
                                               reason=f"Заявка одобрена модератором {interaction.user.name}")
                        role_changes_text += f"🔺 Выдана роль: {member_role.mention}\n"
                except discord.Forbidden:
                    role_changes_text = "⚠️ Не удалось изменить роли (недостаточно прав)\n"
                except Exception as e:
                    role_changes_text = f"⚠️ Ошибка при изменении ролей: {str(e)}\n"

            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            embed.title = "✅ Заявка одобрена"

            if len(embed.fields) > 5:
                embed.remove_field(-1)

            approval_text = f"**Модератор:** {interaction.user.mention} ({interaction.user.name})\n**Время:** {discord.utils.format_dt(discord.utils.utcnow(), 'F')}"
            if role_changes_text:
                approval_text += f"\n\n{role_changes_text}"

            embed.add_field(
                name="Одобрено",
                value=approval_text,
                inline=False
            )

            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(embed=embed, view=self)

            try:
                user = await interaction.client.fetch_user(int(self.discord_id))
                await user.send(
                    f"🎉 Ваша заявка на верификацию **{self.username}** была одобрена модератором **{interaction.user.name}**!")
            except:
                pass

        except Exception as e:
            print(f"Error approving: {e}")
            await interaction.response.send_message("❌ Не удалось одобрить заявку", ephemeral=True)

    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.red, custom_id="reject_app")
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_staff_role(interaction):
            await interaction.response.send_message(
                "❌ У вас нет прав для выполнения этого действия.",
                ephemeral=True
            )
            return

        try:
            async with async_session_maker() as session:
                stmt = select(User).where(User.id == self.user_id)
                result = await session.execute(stmt)
                user = result.scalar_one_or_none()

                if user:
                    await session.delete(user)
                    await session.commit()

            embed = interaction.message.embeds[0]
            embed.color = discord.Color.red()
            embed.title = "❌ Заявка отклонена"

            if len(embed.fields) > 5:
                embed.remove_field(-1)

            embed.add_field(
                name="Отклонено",
                value=f"**Модератор:** {interaction.user.mention} ({interaction.user.name})\n**Время:** {discord.utils.format_dt(discord.utils.utcnow(), 'F')}",
                inline=False
            )

            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(embed=embed, view=self)

            try:
                user = await interaction.client.fetch_user(int(self.discord_id))
                await user.send(
                    f"❌ Ваша заявка на верификацию **{self.username}** была отклонена модератором **{interaction.user.name}**.")
            except:
                pass

        except Exception as e:
            print(f"Error rejecting: {e}")
            await interaction.response.send_message("❌ Не удалось отклонить заявку", ephemeral=True)


class VerificationBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True  # Необходимо для работы с ролями
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await init_models()
        await self.tree.sync()


client = VerificationBot()


@client.event
async def on_ready():
    print(f'Logged in as {client.user} (ID: {client.user.id})')


@client.tree.command(name="link", description="Привязать Discord аккаунт к WacoRP аккаунту")
@app_commands.describe(user_id="ID пользователя из лаунчера")
async def link(interaction: discord.Interaction, user_id: int):
    try:
        async with async_session_maker() as session:
            stmt = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                await interaction.response.send_message(
                    "❌ Пользователь с таким ID не найден.",
                    ephemeral=True
                )
                return

            if user.discord_id and user.discord_id != str(interaction.user.id):
                await interaction.response.send_message(
                    "❌ Пользователь с таким ID уже привязан к другому аккаунту.",
                    ephemeral=True
                )
                return

            stmt = update(User).where(User.id == user_id).values(
                discord_id=str(interaction.user.id)
            )
            await session.execute(stmt)
            await session.commit()

            username = user.username
            rp_history = user.rp_history or "Не указана"

            skin_url = None
            if user.skin_texture_value:
                import base64, json
                decoded = base64.b64decode(user.skin_texture_value).decode('utf-8')
                texture_data = json.loads(decoded)
                skin_url = texture_data["textures"]["SKIN"]["url"]

            await interaction.response.send_message(
                f"✅ Ваш Discord аккаунт успешно привязан к аккаунту **{username}**! Ожидайте сообщение от бота в ЛС.",
                ephemeral=True
            )

            channel = client.get_channel(APPLICATIONS_CHANNEL_ID)
            if channel:
                embed = discord.Embed(
                    title="Новая заявка на верификацию",
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="Пользователь", value=f"```{username}```", inline=True)
                embed.add_field(name="User ID", value=f"```{user_id}```", inline=True)
                embed.add_field(name="Discord", value=f"{interaction.user.mention} ({interaction.user.id})",
                                inline=False)
                embed.description = f"РП История: ```{rp_history}```"
                embed.add_field(name="Скин",
                                value=f"[Просмотр 3D](https://wacorp-skin-viewer.up.railway.app/?url={skin_url})",
                                inline=False)

                if skin_url:
                    embed.set_thumbnail(url=skin_url)

                embed.set_author(
                    name=interaction.user.display_name,
                    icon_url=interaction.user.display_avatar.url
                )

                embed.set_footer(text="Ожидает рассмотрения")

                view = ApplicationView(
                    user_id=user_id,
                    discord_id=str(interaction.user.id),
                    username=username
                )

                await channel.send(
                    content=f"<@&{MODERATOR_ROLE_ID}> <@&{ADMIN_ROLE_ID}>",
                    embed=embed,
                    view=view
                )

    except Exception as e:
        print(f"Error: {e}")
        await interaction.response.send_message(
            "❌ Не удалось подключиться к базе данных.",
            ephemeral=True
        )


client.run(DISCORD_TOKEN)