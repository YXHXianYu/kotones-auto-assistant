"""启动游戏，领取登录奖励，直到首页为止"""
import logging

from kotonebot import task, device, image, cropped, AdaptiveWait, sleep, ocr
from kotonebot.backend.context.task_action import action
from kotonebot.errors import GameUpdateNeededError
from . import R
from .common import Priority, conf
from .actions.loading import loading
from .actions.scenes import at_home, goto_home
from .actions.commu import is_at_commu, handle_unread_commu

logger = logging.getLogger(__name__)

@action('启动游戏公共部分')
def start_game_common():
    # [screenshots/startup/1.png]
    image.wait_for(R.Daily.ButonLinkData, timeout=30)
    sleep(2)
    device.click_center()
    wait = AdaptiveWait(timeout=240, timeout_message='Game startup loading timeout')
    while True:
        while loading():
            wait()
        with device.pinned():
            if image.find(R.Daily.ButtonHomeCurrent):
                break
            # [screenshots/startup/update.png]
            elif image.find(R.Common.TextGameUpdate):
                device.click(image.expect(R.Common.ButtonConfirm))
            # [kotonebot-resource/sprites/jp/daily/screenshot_apk_update.png]
            elif ocr.find('アップデート', rect=R.Daily.BoxApkUpdateDialogTitle):
                raise GameUpdateNeededError()
            # [screenshots/startup/announcement1.png]
            elif image.find(R.Common.ButtonIconClose):
                device.click()
            # [screenshots/startup/birthday.png]
            elif handle_unread_commu():
                pass
            else:
                device.click_center()
            wait()

@task('启动游戏', priority=Priority.START_GAME)
def start_game():
    """
    启动游戏，直到游戏进入首页为止。
    """
    if not conf().start_game.enabled:
        logger.info('"Start game" is disabled.')
        return
    # TODO: 包名放到配置文件里
    if device.current_package() == 'com.bandainamcoent.idolmaster_gakuen':
        logger.info("Game already started")
        if not at_home():
            logger.info("Not at home, going to home")
            goto_home()
        return
    device.launch_app('com.bandainamcoent.idolmaster_gakuen')
    start_game_common()

@task('启动 Kuyo 及游戏', priority=Priority.START_GAME)
def start_kuyo_and_game():
    """
    启动 Kuyo 及游戏，直到游戏进入首页为止。
    """
    if not conf().start_kuyo_and_game.enabled:
        logger.info('"Start kuyo and game" is disabled.')
        return
    # TODO: 包名放到配置文件里
    if device.current_package() == 'org.kuyo.game':
        logger.info("Kuyo already started")
        return
    if device.current_package() == 'com.bandainamcoent.idolmaster_gakuen':
        logger.info("Game already started")
        return
    # 启动kuyo
    device.launch_app('org.kuyo.game')
    device.click(image.expect_wait(R.Kuyo.ButtonTab3Speedup, timeout=10))
    device.click(image.expect_wait(R.Kuyo.ButtonStartGame, timeout=10))
    # 启动游戏
    start_game_common()

if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] [%(name)s] [%(funcName)s] [%(lineno)d] %(message)s')
    logger.setLevel(logging.DEBUG)
    start_game()

