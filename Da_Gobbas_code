import disnake
from disnake.ext import commands

intents = disnake.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='/', sync_commands_debug=True, intents=disnake.Intents.all())


@bot.event
async def on_ready():
    print("Бот готов к работе!")

# Команда: pings
@bot.slash_command()
async def pings(inter):
    await inter.response.send_message("Pong!")

# Получите токен бота из переменного окружения
bot_token = ('Токен бота')

# Комманда: server
@bot.slash_command()
async def server(inter):
    await inter.response.send_message(
        f"Имя сервера: {inter.guild.name}\nКоличество участников: {inter.guild.member_count}"
    )

# Комманда: user
@bot.slash_command(name="user", description="Get information about the user")
async def user(inter: disnake.ApplicationCommandInteraction):
    await inter.response.send_message(
        f"Ваш тег: {inter.author}\n"  # Full tag (e.g., "Alice#0001")
        f"Ваш ID: {inter.author.id}\n"  # Unique Discord ID
        f"Ваше имя: {inter.author.name}\n"  # Username
        f"Дискриптор: {inter.author.discriminator}\n"  # Discriminator
        f"Аватар: {inter.author.avatar.url}"  # Avatar URL
    )

bot.load_extension("cogs.ping")
bot.load_extension("cogs.music")


if bot_token:
    bot.run(bot_token)
else:
    print("Токен бота не найден. Пожалуйста проверьте свой .env файл.")
