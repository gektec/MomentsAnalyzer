import datetime
import json
import shutil
import threading
import time
from typing import Tuple
import openai  # 导入 OpenAI 库
from openai import OpenAI
import xmltodict

from entity.comment import Comment
from entity.contact import Contact
from exporter.avatar_exporter import AvatarExporter
# from exporter.emoji_exporter import EmojiExporter
from log import LOG
from entity.moment_msg import MomentMsg
from pathlib import Path


class HtmlExporter(threading.Thread):

    def __init__(self, gui: 'Gui', dir_name: str, contacts_map: dict[str, Contact], begin_date: datetime.date,
                 end_date: datetime.date, convert_video: int):
        self.dir_name = dir_name
        if Path(f"output/{self.dir_name}").exists():
            shutil.rmtree(f"output/{self.dir_name}")
        Path(f"output/{self.dir_name}").mkdir(parents=True, exist_ok=True)

        self.gui = gui
        self.avatar_exporter = AvatarExporter(dir_name)
        self.file = None
        self.contacts_map = contacts_map
        self.begin_date = begin_date
        self.end_date = end_date
        self.stop_flag = False
        self.txt_content = ""
        super().__init__()

    def run(self) -> None:
        self.file = open(f"output/{self.dir_name}/output.txt", 'w', encoding='utf-8')

        from app.DataBase import sns_db
        # 加一天
        end_date = self.end_date + datetime.timedelta(days=1)
        begin_time = time.mktime(
            datetime.datetime(self.begin_date.year, self.begin_date.month, self.begin_date.day).timetuple())
        end_time = time.mktime(datetime.datetime(end_date.year, end_date.month, end_date.day).timetuple())

        message_datas = sns_db.get_messages_in_time(begin_time, end_time)
        for index, message_data in enumerate(message_datas):
            if not self.stop_flag:
                if message_data[0] in self.contacts_map:
                    comments_datas = sns_db.get_comment_by_feed_id(message_data[2])
                    comments: list[Comment] = []
                    for c in comments_datas:
                        contact = Comment(c[0], c[1], c[2])
                        comments.append(contact)
                    self.export_msg(message_data[1], comments, self.contacts_map)
                    # 更新进度条
                    progress = round(index / len(message_datas) * 100)
                    self.gui.update_export_progressbar(progress)
                    
        self.process_output_with_openai()
        
        self.gui.update_export_progressbar(100)
        self.finish_file()
        self.gui.export_succeed()


    def stop(self) -> None:
        self.stop_flag = True

    def export_msg(self, message: str, comments: list[Comment], contacts_map: dict[str, Contact]) -> None:
        LOG.info(message)
        # force_list: 强制要求转media为list
        msg_dict = xmltodict.parse(message, force_list={'media'})
        msg_json = json.dumps(msg_dict)
        msg = MomentMsg.from_json(msg_json)

        # 微信ID
        username = msg.timelineObject.username
        contact = contacts_map.get(username)
        # 备注， 或用户名
        remark = contact.remark if contact.remark else contact.nickName

        # 朋友圈内容
        content_desc = msg.timelineObject.contentDesc.replace("\n", "\n    ") if msg.timelineObject.contentDesc else ""
        # content_desc = EmojiExporter.replace_emoji(content_desc)

        # 导出文本
        txt = f"用户: {remark}\n"
        txt += f"内容: {content_desc}\n"
        if msg.timelineObject.location and msg.timelineObject.location.poiName:
            txt += f"位置: {msg.timelineObject.location.poiName}\n"
        txt += f"时间: {msg.timelineObject.create_time}\n"

        txt += "\n" + "=" * 20 + "\n"
        self.file.write(txt)
        self.txt_content += txt

    def finish_file(self):
        self.file.close()

    def process_output_with_openai(self):
        
        with open('config.json', 'r') as config_file:
            config = json.load(config_file)

        # 使用配置文件中的 API Key 和 Base URL
        openai = OpenAI(api_key=config["openai_api_key"], base_url=config["openai_base_url"])

                # 调用 OpenAI API 进行分析
        response = openai.chat.completions.create(
            model=config["model"],  # 选择合适的模型
            messages=[
                {"role": "user", "content": f"请分析以下内容并去除无效信息：\n{self.txt_content}"},
            ],
            stream=False
        )
        
        # test
        print(response)
        
        processed_content = response.choices[0].message.content.strip()
        
        # test
        print("\n",processed_content)
        
        with open(f"output/{self.dir_name}/processed_output.txt", 'w', encoding='utf-8') as file:
            file.write(processed_content)

        LOG.info("AI 处理完成，生成 processed_output.txt 文件。")
