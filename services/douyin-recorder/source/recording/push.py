# -*- encoding: utf-8 -*-

"""直播状态推送处理"""

import threading
import datetime
from typing import Optional


def handle_live_status_push(
    record_name: str,
    record_url: str,
    is_live: bool,
    start_pushed: bool,
    live_status_push: bool,
    over_show_push: bool,
    begin_show_push: bool,
    over_push_message_text: str,
    begin_push_message_text: str,
    push_message_func,
    push_check_seconds: int
) -> bool:
    """
    处理直播状态推送
    
    Args:
        record_name: 录制名称
        record_url: 录制 URL
        is_live: 是否正在直播
        start_pushed: 是否已推送开始
        live_status_push: 是否启用状态推送
        over_show_push: 是否显示结束推送
        begin_show_push: 是否显示开始推送
        over_push_message_text: 自定义结束推送文本
        begin_push_message_text: 自定义开始推送文本
        push_message_func: 推送消息函数
        push_check_seconds: 推送检查间隔
        
    Returns:
        更新后的 start_pushed 状态
    """
    push_at = datetime.datetime.today().strftime('%Y-%m-%d %H:%M:%S')
    
    if not is_live:
        # 直播结束
        if start_pushed and over_show_push:
            push_content = "直播间状态更新：[直播间名称] 直播已结束！时间：[时间]"
            if over_push_message_text:
                push_content = over_push_message_text
            
            push_content = (push_content.replace('[直播间名称]', record_name)
                          .replace('[时间]', push_at))
            
            threading.Thread(
                target=push_message_func,
                args=(record_name, record_url, push_content.replace(r'\n', '\n')),
                daemon=True
            ).start()
        
        return False
    
    else:
        # 正在直播
        if live_status_push and not start_pushed and begin_show_push:
            push_content = "直播间状态更新：[直播间名称] 正在直播中，时间：[时间]"
            if begin_push_message_text:
                push_content = begin_push_message_text
            
            push_content = (push_content.replace('[直播间名称]', record_name)
                          .replace('[时间]', push_at))
            
            threading.Thread(
                target=push_message_func,
                args=(record_name, record_url, push_content.replace(r'\n', '\n')),
                daemon=True
            ).start()
            
            return True
    
    return start_pushed
