# -*- encoding: utf-8 -*-

"""录制上下文构建"""

from typing import Dict, Any, Optional


def build_context(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建录制上下文（cookies, credentials 等）
    
    Args:
        config: 配置字典，包含所有 cookie 和凭证
        
    Returns:
        上下文字典
    """
    context = {
        'dy_cookie': config.get('dy_cookie', ''),
        'tiktok_cookie': config.get('tiktok_cookie', ''),
        'ks_cookie': config.get('ks_cookie', ''),
        'hy_cookie': config.get('hy_cookie', ''),
        'douyu_cookie': config.get('douyu_cookie', ''),
        'yy_cookie': config.get('yy_cookie', ''),
        'bili_cookie': config.get('bili_cookie', ''),
        'xhs_cookie': config.get('xhs_cookie', ''),
        'bigo_cookie': config.get('bigo_cookie', ''),
        'blued_cookie': config.get('blued_cookie', ''),
        'sooplive_cookie': config.get('sooplive_cookie', ''),
        'sooplive_username': config.get('sooplive_username', ''),
        'sooplive_password': config.get('sooplive_password', ''),
        'netease_cookie': config.get('netease_cookie', ''),
        'qiandurebo_cookie': config.get('qiandurebo_cookie', ''),
        'pandatv_cookie': config.get('pandatv_cookie', ''),
        'maoerfm_cookie': config.get('maoerfm_cookie', ''),
        'winktv_cookie': config.get('winktv_cookie', ''),
        'flextv_cookie': config.get('flextv_cookie', ''),
        'flextv_username': config.get('flextv_username', ''),
        'flextv_password': config.get('flextv_password', ''),
        'look_cookie': config.get('look_cookie', ''),
        'popkontv_cookie': config.get('popkontv_cookie', ''),
        'popkontv_username': config.get('popkontv_username', ''),
        'popkontv_password': config.get('popkontv_password', ''),
        'popkontv_partner_code': config.get('popkontv_partner_code', ''),
        'twitcasting_cookie': config.get('twitcasting_cookie', ''),
        'twitcasting_account_type': config.get('twitcasting_account_type', ''),
        'twitcasting_username': config.get('twitcasting_username', ''),
        'twitcasting_password': config.get('twitcasting_password', ''),
        'baidu_cookie': config.get('baidu_cookie', ''),
        'weibo_cookie': config.get('weibo_cookie', ''),
        'kugou_cookie': config.get('kugou_cookie', ''),
        'twitch_cookie': config.get('twitch_cookie', ''),
        'liveme_cookie': config.get('liveme_cookie', ''),
        'huajiao_cookie': config.get('huajiao_cookie', ''),
        'liuxing_cookie': config.get('liuxing_cookie', ''),
        'showroom_cookie': config.get('showroom_cookie', ''),
        'acfun_cookie': config.get('acfun_cookie', ''),
        'changliao_cookie': config.get('changliao_cookie', ''),
        'yinbo_cookie': config.get('yinbo_cookie', ''),
        'yingke_cookie': config.get('yingke_cookie', ''),
        'zhihu_cookie': config.get('zhihu_cookie', ''),
        'chzzk_cookie': config.get('chzzk_cookie', ''),
        'haixiu_cookie': config.get('haixiu_cookie', ''),
        'vvxqiu_cookie': config.get('vvxqiu_cookie', ''),
        'yiqilive_cookie': config.get('yiqilive_cookie', ''),
        'langlive_cookie': config.get('langlive_cookie', ''),
        'pplive_cookie': config.get('pplive_cookie', ''),
        'six_room_cookie': config.get('six_room_cookie', ''),
        'shopee_cookie': config.get('shopee_cookie', ''),
        'youtube_cookie': config.get('youtube_cookie', ''),
        'taobao_cookie': config.get('taobao_cookie', ''),
        'jd_cookie': config.get('jd_cookie', ''),
        'faceit_cookie': config.get('faceit_cookie', ''),
        'migu_cookie': config.get('migu_cookie', ''),
        'lianjie_cookie': config.get('lianjie_cookie', ''),
        'laixiu_cookie': config.get('laixiu_cookie', ''),
        'picarto_cookie': config.get('picarto_cookie', ''),
        'global_proxy': config.get('global_proxy', False),
        'config_file': config.get('config_file', ''),
    }
    return context


def resolve_proxy(
    record_url: str,
    proxy_addr: Optional[str],
    proxy_addr_bak: Optional[str],
    enable_proxy_platform_list: list,
    extra_enable_proxy_platform_list: list
) -> Optional[str]:
    """
    解析代理地址
    
    Args:
        record_url: 录制 URL
        proxy_addr: 主代理地址
        proxy_addr_bak: 备用代理地址
        enable_proxy_platform_list: 启用代理的平台列表
        extra_enable_proxy_platform_list: 额外启用代理的平台列表
        
    Returns:
        代理地址或 None
    """
    if not proxy_addr:
        return None
    
    proxy_address = None
    
    # 检查主代理平台列表
    for platform in enable_proxy_platform_list:
        if platform and platform.strip() in record_url:
            proxy_address = proxy_addr
            break
    
    # 检查备用代理平台列表
    if not proxy_address and extra_enable_proxy_platform_list:
        for pt in extra_enable_proxy_platform_list:
            if pt and pt.strip() in record_url:
                proxy_address = proxy_addr_bak or None
                break
    
    return proxy_address
