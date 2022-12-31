import asyncio
from base64 import b64encode
from requests import get as rget, utils as rutils
from re import match as re_match, search as re_search, split as re_split
from time import sleep, time
from os import path as ospath, remove as osremove, listdir, walk
from shutil import rmtree
from threading import Thread
from subprocess import run as srun
from pathlib import PurePath
from html import escape
from telegram.ext import CommandHandler
from pyrogram import enums, filters,Client
from pyrogram.types import Message, InlineKeyboardMarkup, CallbackQuery, User
from bot import (
    AUTHORIZED_CHATS,
    SUDO_USERS,
    Interval,
    INDEX_URL,
    BUTTON_FOUR_NAME,
    BUTTON_FOUR_URL,
    BUTTON_FIVE_NAME,
    BUTTON_FIVE_URL,
    BUTTON_SIX_NAME,
    BUTTON_SIX_URL,
    VIEW_LINK,
    dispatcher,
    DOWNLOAD_DIR,
    download_dict,
    download_dict_lock,
    TG_SPLIT_SIZE,
    LOGGER,
    DB_URI,
    INCOMPLETE_TASK_NOTIFIER,
)
from bot.helper.others.bot_utils import (
    is_url,
    is_magnet,
    is_gdtot_link,
    is_unified_link,
    is_udrive_link,
    is_sharer_link,
    is_drivehubs_link,
    is_mega_link,
    is_gdrive_link,
    get_content_type,
)
from bot.helper.others.fs_utils import (
    get_base_name,
    get_path_size,
    split as fs_split,
    clean_download,
)
from bot.helper.others.shortenurl import short_url
from bot.helper.others.exceptions import (
    DirectDownloadLinkException,
    NotSupportedExtractionArchive,
)

from bot.helper.mirror.download.link_generator import direct_link_generator
from bot.helper.mirror.download.gd_downloader import add_gd_download
from bot.helper.mirror.download.telegram_downloader import TelegramDownloadHelper
from bot.helper.mirror.status.extract_status import ExtractStatus
from bot.helper.mirror.status.zip_status import ZipStatus
from bot.helper.mirror.status.split_status import SplitStatus
from bot.helper.mirror.status.upload_status import UploadStatus
from bot.helper.mirror.status.tg_upload_status import TgUploadStatus
from bot.helper.mirror.upload.gdrive_helper import GoogleDriveHelper
from bot.helper.mirror.upload.pyrogramEngine import TgUploader
from bot.helper.tg_helper.list_of_commands import BotCommands
from bot.helper.tg_helper.filters import CustomFilters
from bot.helper.tg_helper.msg_utils import (
    sendMessage,
    sendMarkup,
    delete_all_messages,
    update_all_messages,
)
from bot.helper.tg_helper.make_buttons import ButtonMaker
from bot.helper.others.database_handler import DbManger


class MirrorListener:
    def __init__(
        self,
        c:Client,
        m:Message,
        isZip=False,
        extract=False,
        isQbit=False,
        isLeech=False,
        pswd=None,
        tag=None,
    ):
        self.c:Client = c
        self.m:Message = m
        self.uid = self.m.id
        self.extract = extract
        self.isZip = isZip
        self.isQbit = isQbit
        self.isLeech = isLeech
        self.pswd = pswd
        self.tag = tag
        self.isPrivate = self.m.chat.type in ["private", "group"]

    async def clean(self):
        try:
            Interval[0].cancel()
            del Interval[0]
            await delete_all_messages()
        except IndexError:
            pass

    def onDownloadStart(self):
        if not self.isPrivate and INCOMPLETE_TASK_NOTIFIER and DB_URI is not None:
            DbManger().add_incomplete_task(
                self.m.chat.id, self.m.link, self.tag
            )

    async def onDownloadComplete(self):
        with download_dict_lock:
            LOGGER.info(f"Download completed: {download_dict[self.uid].name()}")
            download = download_dict[self.uid]
            name = str(download.name()).replace("/", "")
            gid = download.gid()
            size = download.size_raw()
            if (
                name == "None"
                or self.isQbit
                or not ospath.exists(f"{DOWNLOAD_DIR}{self.uid}/{name}")
            ):
                name = listdir(f"{DOWNLOAD_DIR}{self.uid}")[-1]
            m_path = f"{DOWNLOAD_DIR}{self.uid}/{name}"
        if self.isZip:
            try:
                with download_dict_lock:
                    download_dict[self.uid] = ZipStatus(name, m_path, size)
                path = m_path + ".zip"
                LOGGER.info(f"Zip: orig_path: {m_path}, zip_path: {path}")
                if self.pswd is not None:
                    if self.isLeech and int(size) > TG_SPLIT_SIZE:
                        srun(
                            [
                                "7z",
                                f"-v{TG_SPLIT_SIZE}b",
                                "a",
                                "-mx=0",
                                f"-p{self.pswd}",
                                path,
                                m_path,
                            ]
                        )
                    else:
                        srun(["7z", "a", "-mx=0", f"-p{self.pswd}", path, m_path])
                elif self.isLeech and int(size) > TG_SPLIT_SIZE:
                    srun(["7z", f"-v{TG_SPLIT_SIZE}b", "a", "-mx=0", path, m_path])
                else:
                    srun(["7z", "a", "-mx=0", path, m_path])
            except FileNotFoundError:
                LOGGER.info("File to archive not found!")
                self.onUploadError("Internal error occurred!!")
                return
            if not self.isQbit or self.isLeech:
                try:
                    rmtree(m_path)
                except:
                    osremove(m_path)
        elif self.extract:
            try:
                if ospath.isfile(m_path):
                    path = get_base_name(m_path)
                LOGGER.info(f"Extracting: {name}")
                with download_dict_lock:
                    download_dict[self.uid] = ExtractStatus(name, m_path, size)
                if ospath.isdir(m_path):
                    for dirpath, subdir, files in walk(m_path, topdown=False):
                        for file_ in files:
                            if (
                                file_.endswith(".zip")
                                or re_search(
                                    r"\.part0*1\.rar$|\.7z\.0*1$|\.zip\.0*1$", file_
                                )
                                or (
                                    file_.endswith(".rar")
                                    and not re_search(r"\.part\d+\.rar$", file_)
                                )
                            ):
                                m_path = ospath.join(dirpath, file_)
                                if self.pswd is not None:
                                    result = srun(
                                        [
                                            "7z",
                                            "x",
                                            f"-p{self.pswd}",
                                            m_path,
                                            f"-o{dirpath}",
                                            "-aot",
                                        ]
                                    )
                                else:
                                    result = srun(
                                        ["7z", "x", m_path, f"-o{dirpath}", "-aot"]
                                    )
                                if result.returncode != 0:
                                    LOGGER.error("Unable to extract archive!")
                        for file_ in files:
                            if file_.endswith((".rar", ".zip")) or re_search(
                                r"\.r\d+$|\.7z\.\d+$|\.z\d+$|\.zip\.\d+$", file_
                            ):
                                del_path = ospath.join(dirpath, file_)
                                osremove(del_path)
                    path = f"{DOWNLOAD_DIR}{self.uid}/{name}"
                else:
                    if self.pswd is not None:
                        result = srun(["bash", "pextract", m_path, self.pswd])
                    else:
                        result = srun(["bash", "extract", m_path])
                    if result.returncode == 0:
                        LOGGER.info(f"Extracted Path: {path}")
                        osremove(m_path)
                    else:
                        LOGGER.error("Unable to extract archive! Uploading anyway")
                        path = f"{DOWNLOAD_DIR}{self.uid}/{name}"
            except NotSupportedExtractionArchive:
                LOGGER.info("Not any valid archive, uploading file as it is.")
                path = f"{DOWNLOAD_DIR}{self.uid}/{name}"
        else:
            path = f"{DOWNLOAD_DIR}{self.uid}/{name}"
        up_name = PurePath(path).name
        up_path = f"{DOWNLOAD_DIR}{self.uid}/{up_name}"
        if self.isLeech and not self.isZip:
            checked = False
            for dirpath, subdir, files in walk(
                f"{DOWNLOAD_DIR}{self.uid}", topdown=False
            ):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    f_size = ospath.getsize(f_path)
                    if int(f_size) > TG_SPLIT_SIZE:
                        if not checked:
                            checked = True
                            with download_dict_lock:
                                download_dict[self.uid] = SplitStatus(
                                    up_name, up_path, size
                                )
                            LOGGER.info(f"Splitting: {up_name}")
                        fs_split(f_path, f_size, file_, dirpath, TG_SPLIT_SIZE)
                        osremove(f_path)
        if self.isLeech:
            size = get_path_size(f"{DOWNLOAD_DIR}{self.uid}")
            LOGGER.info(f"Leech Name: {up_name}")
            tg = TgUploader(up_name, self)
            tg_upload_status = TgUploadStatus(tg, size, gid, self)
            with download_dict_lock:
                download_dict[self.uid] = tg_upload_status
            await update_all_messages()
            await tg.upload()
        else:
            size = get_path_size(up_path)
            LOGGER.info(f"Upload Name: {up_name}")
            drive = GoogleDriveHelper(up_name, self)
            upload_status = UploadStatus(drive, size, gid, self)
            with download_dict_lock:
                download_dict[self.uid] = upload_status
            await update_all_messages()
            await drive.upload(up_name)

    async def onDownloadError(self, error):
        error = error.replace("<", " ").replace(">", " ")
        clean_download(f"{DOWNLOAD_DIR}{self.uid}")
        with download_dict_lock:
            try:
                del download_dict[self.uid]
            except Exception as e:
                LOGGER.error(str(e))
            count = len(download_dict)
        msg = f"{self.tag} your download has been stopped due to: {error}"
        await sendMessage(msg, self.c, self.m)
        if count == 0:
            self.clean()
        else:
            await update_all_messages()

        if not self.isPrivate and INCOMPLETE_TASK_NOTIFIER and DB_URI is not None:
            DbManger().rm_complete_task(self.m.link)

    async def onUploadComplete(self, link: str, size, files, folders, typ, name: str):
        if not self.isPrivate and INCOMPLETE_TASK_NOTIFIER and DB_URI is not None:
            DbManger().rm_complete_task(self.m.link)
        msg = f"<b>Name: </b><code>{escape(name)}</code>\n\n<b>Size: </b>{size}"
        if self.isLeech:
            msg += f"\n<b>Total Files: </b>{folders}"
            if typ != 0:
                msg += f"\n<b>Corrupted Files: </b>{typ}"
            msg += f"\n<b>cc: </b>{self.tag}\n\n"
            if not files:
                await sendMessage(msg, self.c, self.m)
            else:
                fmsg = ""
                for index, (name, link) in enumerate(files.items(), start=1):
                    fmsg += f"{index}. <a href='{link}'>{name}</a>\n"
                    if len(fmsg.encode() + msg.encode()) > 4000:
                        await sendMessage(msg + fmsg, self.c, self.m)
                        await asyncio.sleep(1)
                        fmsg = ""
                if fmsg != "":
                    await sendMessage(msg + fmsg, self.c, self.m)
        else:
            msg += f"\n\n<b>Type: </b>{typ}"
            if ospath.isdir(f"{DOWNLOAD_DIR}{self.uid}/{name}"):
                msg += f"\n<b>SubFolders: </b>{folders}"
                msg += f"\n<b>Files: </b>{files}"
            msg += f"\n\n<b>cc: </b>{self.tag}"
            buttons = ButtonMaker()
            link = short_url(link)
            buttons.buildbutton("☁️ Drive Link", link)
            LOGGER.info(f"Done Uploading {name}")
            if INDEX_URL is not None:
                url_path = rutils.quote(f"{name}")
                share_url = f"{INDEX_URL}/{url_path}"
                if ospath.isdir(f"{DOWNLOAD_DIR}/{self.uid}/{name}"):
                    share_url += "/"
                    share_url = short_url(share_url)
                    buttons.buildbutton("⚡ Index Link", share_url)
                else:
                    share_url = short_url(share_url)
                    buttons.buildbutton("⚡ Index Link", share_url)
                    if VIEW_LINK:
                        share_urls = f"{INDEX_URL}/{url_path}?a=view"
                        share_urls = short_url(share_urls)
                        buttons.buildbutton("🌐 View Link", share_urls)
            if BUTTON_FOUR_NAME is not None and BUTTON_FOUR_URL is not None:
                buttons.buildbutton(f"{BUTTON_FOUR_NAME}", f"{BUTTON_FOUR_URL}")
            if BUTTON_FIVE_NAME is not None and BUTTON_FIVE_URL is not None:
                buttons.buildbutton(f"{BUTTON_FIVE_NAME}", f"{BUTTON_FIVE_URL}")
            if BUTTON_SIX_NAME is not None and BUTTON_SIX_URL is not None:
                buttons.buildbutton(f"{BUTTON_SIX_NAME}", f"{BUTTON_SIX_URL}")
            await sendMarkup(
                msg, self.c, self.m, InlineKeyboardMarkup(buttons.build_menu(2))
            )
        clean_download(f"{DOWNLOAD_DIR}{self.uid}")
        with download_dict_lock:
            try:
                del download_dict[self.uid]
            except Exception as e:
                LOGGER.error(str(e))
            count = len(download_dict)
        if count == 0:
            await self.clean()
        else:
            await update_all_messages()

    async def onUploadError(self, error):
        e_str = error.replace("<", "").replace(">", "")
        clean_download(f"{DOWNLOAD_DIR}{self.uid}")
        with download_dict_lock:
            try:
                del download_dict[self.uid]
            except Exception as e:
                LOGGER.error(str(e))
            count = len(download_dict)
        await sendMessage(f"{self.tag} {e_str}", self.c, self.m)
        if count == 0:
            self.clean()
        else:
            await update_all_messages()

        if not self.isPrivate and INCOMPLETE_TASK_NOTIFIER and DB_URI is not None:
            DbManger().rm_complete_task(self.m.link)


async def _mirror(
    c:Client,
    m:Message,
    isZip=False,
    extract=False,
    isQbit=False,
    isLeech=False,
    pswd=None,
    multi=0,
):
    mesg = m.text.split("\n")
    message_args = mesg[0].split(" ", maxsplit=1)
    name_args = mesg[0].split("|", maxsplit=1)
    qbitsel = False
    is_gdtot = False
    is_unified = False
    is_udrive = False
    is_sharer = False
    is_drivehubs = False
    
    try:
        link = message_args[1]
        if link.startswith("s ") or link == "s":
            qbitsel = True
            message_args = mesg[0].split(" ", maxsplit=2)
            link = message_args[2].strip()
        elif link.isdigit():
            multi = int(link)
            raise IndexError
        if link.startswith(("|", "pswd: ")):
            raise IndexError
    except:
        link = ""
    try:
        name = name_args[1]
        name = name.split(" pswd: ")[0]
        name = name.strip()
    except:
        name = ""
    link = re_split(r"pswd:| \|", link)[0]
    link = link.strip()
    pswdMsg = mesg[0].split(" pswd: ")
    if len(pswdMsg) > 1:
        pswd = pswdMsg[1]

    if m.from_user.username:
        tag = f"@{m.from_user.username}"
    else:
        tag = m.from_user.mention(m.from_user.first_name)

    reply_to = m.reply_to_message
    if reply_to is not None:
        file = None
        media_array = [reply_to.video , reply_to.audio, reply_to.document, reply_to.link ]
        for i in media_array:
            if i is not None:
                file = i
                break

        if not reply_to.from_user.is_bot:
            if reply_to.from_user.username:
                tag = f"@{reply_to.from_user.username}"
            else:
                tag = reply_to.from_user.mention(reply_to.from_user.first_name)

        if not is_url(link) and not is_magnet(link) or len(link) == 0:
            file = reply_to.video
            if file is None:
                reply_text = reply_to.text
                if is_url(reply_text) or is_magnet(reply_text):
                    link = reply_text.strip()
            elif file.mime_type != "application/x-bittorrent" and not isQbit:
                listener = MirrorListener(
                    c, m, isZip, extract, isQbit, isLeech, pswd, tag
                )
                tg_downloader = TelegramDownloadHelper(listener)
                await tg_downloader.add_download(
                    m, f"{DOWNLOAD_DIR}{listener.uid}/", name
                )
                if multi > 1:
                    await asyncio.sleep(3)
                    nextmsg = type(
                        "nextmsg",
                        (object,),
                        {
                            "chat_id": m.chat.id,
                            "message_id": m.reply_to_message.id + 1,
                        },
                    )
                    nextmsg = await sendMessage(message_args[0], c, nextmsg)
                    nextmsg.from_user.id = m.from_user.id
                    multi -= 1
                    await asyncio.sleep(3)
                    await _mirror(c,nextmsg,isZip,extract,isQbit,isLeech,pswd,multi)
                return
            # else:
            #     link = file.get_file().file_path

    if not is_url(link) and not is_magnet(link) and not ospath.exists(link):
        help_msg = "<b>Send link along with command line:</b>"
        help_msg += "\n<code>/command</code> {link} |newname pswd: xx [zip/unzip]"
        help_msg += "\n\n<b>By replying to link or file:</b>"
        help_msg += "\n<code>/command</code> |newname pswd: xx [zip/unzip]"
        help_msg += "\n\n<b>Direct link authorization:</b>"
        help_msg += (
            "\n<code>/command</code> {link} |newname pswd: xx\nusername\npassword"
        )
        help_msg += "\n\n<b>Qbittorrent selection:</b>"
        help_msg += (
            "\n<code>/qbcommand</code> <b>s</b> {link} or by replying to {file/link}"
        )
        help_msg += "\n\n<b>Multi links only by replying to first link or file:</b>"
        help_msg += "\n<code>/command</code> 10(number of links/files)"
        return await sendMessage(help_msg, c, m)

    LOGGER.info(link)
    
    if not is_mega_link(link) and not isQbit and not is_magnet(link) \
        and not is_gdrive_link(link) and not link.endswith('.torrent'):
        content_type = get_content_type(link)
        if content_type is None or re_match(r'text/html|text/plain', content_type):
            try:
                is_gdtot = is_gdtot_link(link)
                is_unified = is_unified_link(link)
                is_udrive = is_udrive_link(link)
                is_sharer = is_sharer_link(link)
                is_drivehubs = is_drivehubs_link(link)
                link = direct_link_generator(link)
                LOGGER.info(f"Generated link: {link}")
            except DirectDownloadLinkException as e:
                LOGGER.info(str(e))
                if str(e).startswith('ERROR:'):
                    return await sendMessage(str(e), c, m)
        

    listener = MirrorListener(c, m, isZip, extract, isQbit, isLeech, pswd, tag)

    if is_gdrive_link(link):
        if not isZip and not extract and not isLeech:
            gmsg = (
                f"Use /{BotCommands.CloneCommand} to clone Google Drive file/folder\n\n"
            )
            gmsg += f"Use /{BotCommands.ZipMirrorCommand} to make zip of Google Drive folder\n\n"
            gmsg += f"Use /{BotCommands.UnzipMirrorCommand} to extracts Google Drive archive file"
            await sendMessage(gmsg, c, m)
        else:
            await add_gd_download(link,listener,is_gdtot, is_unified, is_udrive, is_sharer, is_drivehubs)
            
    if multi > 1:
        await asyncio.sleep(3)
        nextmsg = type(
            "nextmsg",
            (object,),
            {
                "chat_id": m.chat.id,
                "message_id": m.reply_to_message.id + 1,
            },
        )
        msg = message_args[0]
        if len(mesg) > 2:
            msg += "\n" + mesg[1] + "\n" + mesg[2]
        nextmsg = await sendMessage(msg, c, nextmsg)
        nextmsg.from_user.id = m.from_user.id
        multi -= 1
        await asyncio.sleep(3)
        await _mirror(c, nextmsg, isZip, extract, isQbit, isLeech, pswd, multi)


@Client.on_message(filters.command(BotCommands.MirrorCommand) & (filters.chat(sorted(AUTHORIZED_CHATS)) | filters.user(sorted(SUDO_USERS))))
async def mirror(c:Client, m:Message):
    await _mirror(c, m)

@Client.on_message(filters.command(BotCommands.UnzipMirrorCommand) & (filters.chat(sorted(AUTHORIZED_CHATS)) | filters.user(sorted(SUDO_USERS))))
async def unzip_mirror(c:Client,m:Message):
    await _mirror(c, m, extract=True)

@Client.on_message(filters.command(BotCommands.ZipMirrorCommand) & (filters.chat(sorted(AUTHORIZED_CHATS)) | filters.user(sorted(SUDO_USERS))))
async def zip_mirror(c:Client,m:Message):
    await _mirror(c, m, True)

@Client.on_message(filters.command(BotCommands.LeechCommand) & (filters.chat(sorted(AUTHORIZED_CHATS)) | filters.user(sorted(SUDO_USERS))))
async def leech(c:Client, m:Message):
    await _mirror(c, m, isLeech=True)

@Client.on_message(filters.command(BotCommands.UnzipLeechCommand) & (filters.chat(sorted(AUTHORIZED_CHATS)) | filters.user(sorted(SUDO_USERS))))
async def unzip_leech(c:Client, m:Message):
    await _mirror(c, m, extract=True, isLeech=True)

@Client.on_message(filters.command(BotCommands.ZipLeechCommand) & (filters.chat(sorted(AUTHORIZED_CHATS)) | filters.user(sorted(SUDO_USERS))))
async def zip_leech(c:Client, m:Message):
    await _mirror(c, m, True, isLeech=True)
