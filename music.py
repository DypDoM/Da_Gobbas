import logging
import disnake
from disnake.ext import commands
import yt_dlp as youtube_dl
import asyncio
from typing import List

logger = logging.getLogger(__name__)

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(disnake.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = disnake.utils.escape_markdown(data.get('title', 'Unknown'))[:100]
        self.url = data.get('url', '')
        self.duration = data.get('duration', 0)

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(
                None, 
                lambda: ytdl.extract_info(url, download=not stream)
            )
        except youtube_dl.DownloadError as e:
            logger.error(f"YTDL download error: {e}")
            raise Exception("Не удалось загрузить видео")

        if not data or ('entries' not in data and 'url' not in data):
            raise Exception("Некорректные данные видео")

        if 'entries' in data:
            data = data['entries'][0] if not stream else data

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(disnake.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue: List[YTDLSource] = []
        self.current = None
        self.queue_lock = asyncio.Lock()
        self.MAX_QUEUE_SIZE = 100

    async def check_voice_channel(self, inter):
        if not inter.author.voice or not inter.author.voice.channel:
            await inter.send("Вы должны быть в голосовом канале!", ephemeral=True)
            return False
        return True

    async def play_next(self, inter):
        async with self.queue_lock:
            if not self.queue:
                await self.idle_timeout(inter)
                return

            self.current = self.queue.pop(0)
        
        vc = inter.guild.voice_client
        if not vc or not vc.is_connected():
            return

        try:
            vc.play(self.current, after=lambda e: self.bot.loop.create_task(
                self.handle_after(e, inter))
            )
            await inter.channel.send(f"Сейчас играет: {self.current.title}")
        except disnake.ClientException as e:
            await inter.channel.send(f"Ошибка воспроизведения: {e}")

    async def handle_after(self, error, inter):
        if error:
            logger.error(f"Playback error: {error}")
            await inter.channel.send(f"Ошибка воспроизведения: {error}")
        await self.play_next(inter)

    async def idle_timeout(self, inter):
        await asyncio.sleep(300)
        vc = inter.guild.voice_client
        if vc and not vc.is_playing() and not self.queue:
            await vc.disconnect()
            await inter.channel.send("Бот отключен из-за бездействия")

    @commands.slash_command(name="play")
    async def play(self, inter: disnake.ApplicationCommandInteraction, query: str):
        """Воспроизводит музыку с YouTube"""
        await inter.response.defer()
        
        if not await self.check_voice_channel(inter):
            return

        if len(self.queue) >= self.MAX_QUEUE_SIZE:
            await inter.followup.send("Очередь переполнена (макс. 100 треков)!")
            return

    @commands.slash_command(name="play", description="Воспроизводит музыку с YouTube по URL или названию")
    async def play(self, inter: disnake.ApplicationCommandInteraction, query: str):
        await inter.response.defer()
        
        if not await self.check_voice_channel(inter):
            await inter.followup.send("Вы должны быть в голосовом канале!", ephemeral=True)
            return

        try:
            if not query.startswith(('http://', 'https://')):
                search_query = f"ytsearch5:{query}"
                data = await self.bot.loop.run_in_executor(None, lambda: ytdl.extract_info(search_query, download=False))
                
                if not data or 'entries' not in data:
                    await inter.followup.send("Ничего не найдено.")
                    return
                
                entries = data['entries'][:5]
                if not entries:
                    await inter.followup.send("Ничего не найдено.")
                    return

                view = disnake.ui.View()
                options = []
                for idx, entry in enumerate(entries, 1):
                    if 'url' not in entry:
                        continue
                    title = entry.get('title', 'Без названия')[:100]
                    uploader = entry.get('uploader', 'Неизвестен')[:100]
                    duration = entry.get('duration', 0)
                    minutes, seconds = divmod(duration, 60)
                    duration_str = f"{minutes}:{seconds:02d}" if duration else "N/A"
                    options.append(disnake.SelectOption(
                        label=f"{idx}. {title}",
                        description=f"{uploader} | {duration_str}",
                        value=entry['url']
                    ))

                if not options:
                    await inter.followup.send("Не удалось загрузить результаты.")
                    return

                select = disnake.ui.Select(options=options, placeholder="Выберите трек")
                view.add_item(select)

                async def select_callback(select_inter: disnake.MessageInteraction):
                    if not await self.check_voice_channel(select_inter):
                        await select_inter.response.send_message("Вы должны быть в голосовом канале!", ephemeral=True)
                        return
                    voice_channel = select_inter.author.voice.channel

                    if not select_inter.guild.voice_client:
                        await voice_channel.connect()
                    elif select_inter.guild.voice_client.channel != voice_channel:
                        await select_inter.response.send_message("Бот уже в другом канале!", ephemeral=True)
                        return

                    selected_url = select_inter.data.values[0]
                    try:
                        player = await YTDLSource.from_url(selected_url, loop=self.bot.loop, stream=True)
                    except Exception as e:
                        await select_inter.response.send_message(f"Ошибка: {str(e)}", ephemeral=True)
                        return

                    self.queue.append(player)
                    if not select_inter.guild.voice_client.is_playing():
                        await self.play_next(select_inter)
                    await select_inter.followup.send(f"Добавлено в очередь ({len(self.queue)}): {player.title}")

                select.callback = select_callback
                await inter.followup.send("Выберите трек:", view=view)
            else:
                voice_channel = inter.author.voice.channel
                if inter.guild.voice_client is None:
                    await voice_channel.connect()
                elif inter.guild.voice_client.channel != voice_channel:
                    await inter.followup.send("Бот уже в другом канале!")
                    return

                player = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True)
                self.queue.append(player)

                if not inter.guild.voice_client.is_playing():
                    await self.play_next(inter)

                await inter.followup.send(f"Добавлено в очередь ({len(self.queue)}): {player.title}")
        
        except Exception as e:
            await inter.followup.send(f"Ошибка: {str(e)}")

    @commands.slash_command(name="skip", description="Пропускает текущий трек")
    async def skip(self, inter: disnake.ApplicationCommandInteraction):
        if inter.guild.voice_client and inter.guild.voice_client.is_playing():
            inter.guild.voice_client.stop()
            await inter.send("Трек пропущен!")
        else:
            await inter.send("Ничего не играет!")

    @commands.slash_command(name="stop", description="Останавливает воспроизведение")
    async def stop(self, inter: disnake.ApplicationCommandInteraction):
        if inter.guild.voice_client:
            self.queue.clear()
            inter.guild.voice_client.stop()
            await inter.guild.voice_client.disconnect()
            await inter.send("Музыка остановлена!")
        else:
            await inter.send("Бот не подключен!")

    @commands.slash_command(name="queue")
    async def show_queue(self, inter: disnake.ApplicationCommandInteraction):
        """Показывает очередь"""
        class QueueView(disnake.ui.View):
            def __init__(self, pages):
                super().__init__(timeout=60)
                self.pages = pages
                self.current_page = 0

            @disnake.ui.button(label="◀️", style=disnake.ButtonStyle.secondary)
            async def previous(self, button: disnake.ui.Button, inter: disnake.Interaction):
                self.current_page = max(self.current_page - 1, 0)
                await inter.response.edit_message(content=self.pages[self.current_page])

            @disnake.ui.button(label="▶️", style=disnake.ButtonStyle.secondary)
            async def next(self, button: disnake.ui.Button, inter: disnake.Interaction):
                self.current_page = min(self.current_page + 1, len(self.pages)-1)
                await inter.response.edit_message(content=self.pages[self.current_page])

        if not self.queue:
            return await inter.send("Очередь пуста!")
        
        entries_per_page = 10
        pages = []
        for i in range(0, len(self.queue), entries_per_page):
            page = "**Очередь:**\n" + "\n".join(
                f"{idx+1}. {track.title} ({track.duration//60}:{track.duration%60:02})"
                for idx, track in enumerate(self.queue[i:i+entries_per_page], start=i)
            )
            pages.append(page)
        
        view = QueueView(pages)
        await inter.send(pages[0], view=view)

    @commands.slash_command(name="pause", description="Пауза")
    async def pause(self, inter: disnake.ApplicationCommandInteraction):
        if inter.guild.voice_client and inter.guild.voice_client.is_playing():
            inter.guild.voice_client.pause()
            await inter.send("Пауза ⏸️")

    @commands.slash_command(name="resume", description="Продолжить")
    async def resume(self, inter: disnake.ApplicationCommandInteraction):
        if inter.guild.voice_client and inter.guild.voice_client.is_paused():
            inter.guild.voice_client.resume()
            await inter.send("Продолжаем ▶️")

    @commands.slash_command(name="volume")
    async def volume(self, inter: disnake.ApplicationCommandInteraction, level: int):
        """Установить громкость (0-100)"""
        if not 0 <= level <= 100:
            return await inter.send("Недопустимое значение!", ephemeral=True)
        
        vc = inter.guild.voice_client
        if not vc or not vc.is_connected():
            return await inter.send("Бот не подключен!", ephemeral=True)
        
        if not isinstance(vc.source, disnake.PCMVolumeTransformer):
            return await inter.send("Громкость нельзя изменить!", ephemeral=True)
        
        vc.source.volume = level / 100
        await inter.send(f"Громкость установлена на {level}%")

    @commands.slash_command(name="search", description="Поиск видео на YouTube")
    async def search(self, inter: disnake.ApplicationCommandInteraction, query: str):
        await inter.response.defer()
    
        try:
            ytdl_search_options = ytdl_format_options.copy()
            ytdl_search_options['extract_flat'] = True
            ytdl_search = youtube_dl.YoutubeDL(ytdl_search_options)
        
            search_results = await self.bot.loop.run_in_executor(
                None, 
                lambda: ytdl_search.extract_info(f"ytsearch5:{query}", download=False)
            )
        
            entries = search_results.get('entries', []) if search_results else []
            entries = [e for e in entries if e and isinstance(e, dict)]
            if not entries:
                await inter.send("Ничего не найдено.")
                return
        
            result_list = "\n".join([
                f"{i+1}. {entry.get('title', 'Без названия')}"
                for i, entry in enumerate(entries)
            ])
            await inter.send(f"**Результаты поиска:**\n{result_list}\n\nВведите номер трека (1-{len(entries)}).")
        
            def check(m):
                return (
                    m.author == inter.author 
                    and m.channel == inter.channel 
                    and m.content.isdigit() 
                    and 1 <= int(m.content) <= len(entries)
                )
        
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=30.0)
                selected = int(msg.content) - 1
            
                try:
                    selected_id = entries[selected]['id']
                except KeyError:
                    await inter.send("Ошибка: не удалось получить ID видео.")
                    return
            
                selected_url = f"https://www.youtube.com/watch?v={selected_id}"
            
                voice_channel = inter.author.voice.channel
        
                # Подключение к каналу
                if not inter.guild.voice_client:
                    await voice_channel.connect()
                elif inter.guild.voice_client.channel != voice_channel:
                    await inter.followup.send("Бот уже в другом канале!")
                    return

                # Непосредственное добавление трека в очередь
                player = await YTDLSource.from_url(selected_url, loop=self.bot.loop, stream=True)
                self.queue.append(player)
        
                if not inter.guild.voice_client.is_playing():
                    await self.play_next(inter)
        
                await inter.followup.send(f"Добавлено в очередь: {player.title}")

            except asyncio.TimeoutError:
                await inter.send("Время выбора истекло.")
    
        except Exception as e:
            await inter.followup.send(f"Ошибка: {str(e)}")

def setup(bot):
    bot.add_cog(Music(bot))
