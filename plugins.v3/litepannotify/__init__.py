import threading
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional

# V3 规范导入
from app.sdk.logging import logger
from app.sdk.events import eventmanager, Event
from app.schemas.types import EventType
from app.utils.http import RequestUtils


class LitePanNotify:
    """
    插件：LitePan 自动联动
    监听 MP 整理完成事件，携带 Bearer 密钥自动触发 LitePan 生成 STRM 与刮削。
    """
    # 插件唯一 ID，必须与类名一致
    plugin_id = "LitePanNotify"
    plugin_name = "LitePan 自动联动"
    plugin_desc = "监听 MP 整理完成事件，携带 Bearer 密钥自动触发 LitePan 生成 STRM 与刮削。"
    plugin_icon = "webhook.png"  # 使用内置图标
    plugin_version = "1.0"
    plugin_author = "Custom"
    author_url = "https://github.com/你的用户名"
    plugin_config_prefix = "litepannotify_"
    plugin_order = 15
    auth_level = 1

    # 私有属性
    _enabled: bool = False
    _onlyonce: bool = False
    _webhook_url: str = ""
    _api_key: str = ""
    _event_name: str = "MP"
    _delay_seconds: int = 10

    # 防抖定时器与待处理队列
    _timer: Optional[threading.Timer] = None
    _lock = threading.Lock()
    _pending_items: List[str] = []

    def init_plugin(self, config: dict = None):
        self.stop_service()
        
        if config:
            self._enabled = bool(config.get("enabled"))
            self._onlyonce = bool(config.get("onlyonce"))
            self._webhook_url = (config.get("webhook_url") or "").strip()
            self._api_key = (config.get("api_key") or "").strip()
            self._event_name = (config.get("event_name") or "MP").strip()
            try:
                self._delay_seconds = int(config.get("delay_seconds") if config.get("delay_seconds") is not None else 10)
            except ValueError:
                self._delay_seconds = 10

        # 处理“立即测试一次”开关
        if self._onlyonce:
            logger.info("[LitePan联动] 正在执行立即测试发送...")
            if self._webhook_url:
                self._send_to_litepan(message=f"{self._event_name}，请执行联动（手动测试触发）")
            else:
                logger.warning("[LitePan联动] 未配置 Webhook 地址，无法测试")
            
            self._onlyonce = False
            self.update_config({
                "enabled": self._enabled,
                "onlyonce": False,
                "webhook_url": self._webhook_url,
                "api_key": self._api_key,
                "event_name": self._event_name,
                "delay_seconds": self._delay_seconds,
            })

    def get_state(self) -> bool:
        return self._enabled

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'enabled', 'label': '启用插件'}
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'onlyonce', 'label': '立即测试一次发送'}
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 8},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'webhook_url',
                                            'label': 'LitePan 接口地址',
                                            'placeholder': 'http://IP:5211/api/open/automation/events'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'api_key',
                                            'label': 'Bearer API 密钥',
                                            'placeholder': 'lpk_api_xxx'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'event_name',
                                            'label': '通知名称 (event)',
                                            'placeholder': 'MP'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'delay_seconds',
                                            'label': '防抖合并延迟（秒，0为立即发送）',
                                            'placeholder': '10',
                                            'type': 'number'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "webhook_url": "",
            "api_key": "",
            "event_name": "MP",
            "delay_seconds": 10
        }

    def get_page(self) -> List[dict]:
        return []

    @eventmanager.register(EventType.TransferComplete)
    def send(self, event: Event):
        if not self._enabled or not self._webhook_url or not event:
            return

        event_data = event.event_data or {}
        transferinfo = event_data.get("transferinfo")
        mediainfo = event_data.get("mediainfo")

        if transferinfo and not getattr(transferinfo, "succeed", True):
            return

        target_path = ""
        if transferinfo:
            if getattr(transferinfo, "target_item", None) and getattr(transferinfo.target_item, "path", None):
                target_path = str(transferinfo.target_item.path)
            elif getattr(transferinfo, "target_diritem", None) and getattr(transferinfo.target_diritem, "path", None):
                target_path = str(transferinfo.target_diritem.path)

        title = getattr(mediainfo, "title", "") if mediainfo else (Path(target_path).name if target_path else "未知媒体")
        item_desc = f"{title} ({target_path})" if target_path else title

        if self._delay_seconds <= 0:
            self._send_to_litepan(message=f"{self._event_name}，请执行联动（已整理：{item_desc}）")
            return

        with self._lock:
            self._pending_items.append(item_desc)
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay_seconds, self._flush_pending)
            self._timer.daemon = True
            self._timer.start()
            logger.info(f"[LitePan联动] 捕获整理完成：{item_desc}，将在 {self._delay_seconds} 秒后合并触发 LitePan")

    def _flush_pending(self):
        with self._lock:
            items = list(self._pending_items)
            self._pending_items.clear()
            self._timer = None

        if not items:
            return

        summary = items[0] if len(items) == 1 else f"{items[0]} 等共 {len(items)} 个文件"
        self._send_to_litepan(message=f"{self._event_name}，请执行联动（已整理：{summary}）")

    def _send_to_litepan(self, message: str):
        if not self._webhook_url:
            return

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if self._api_key:
            token = self._api_key if self._api_key.lower().startswith("bearer ") else f"Bearer {self._api_key}"
            headers["Authorization"] = token

        payload = {
            "event": self._event_name or "MP",
            "message": message
        }

        try:
            # 兼容 V3 的 RequestUtils
            ret = RequestUtils(headers=headers).post_res(self._webhook_url, json=payload)
            if ret and ret.status_code in (200, 201, 202, 204):
                logger.info(f"[LitePan联动] 发送成功：{self._webhook_url} -> {ret.text[:200]}")
            elif ret is not None:
                logger.error(f"[LitePan联动] 发送失败，状态码：{ret.status_code}，返回信息：{ret.text}")
            else:
                logger.error("[LitePan联动] 发送失败，未获取到返回信息")
        except Exception as e:
            logger.error(f"[LitePan联动] 发送请求时发生异常：{e}")

    def stop_service(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending_items.clear()
